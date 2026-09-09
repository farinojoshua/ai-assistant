"""Cinema ticket booking over WhatsApp, driven by the SAMS Studios API.

A guided text conversation (city -> cinema -> date -> showtime -> seats),
then a Kirim/Batal confirm and a Bayar/Batal payment step via reply buttons
— the same draft-and-confirm shape as the reimbursement flow, since a
cinema seat map doesn't fit WhatsApp's native list-message UI (seat counts
routinely exceed its item caps) and money is involved, so nothing here
auto-submits without an explicit tap.

State lives in memory per phone, same tradeoff as the reimbursement draft
and the message-dedupe ring: a backend restart mid-flow loses it, the user
just starts over. Acceptable for a first pass.

PAYMENT NOTE: "Bayar" debits the merchant's own SAMS wallet (see
app/sams/client.py) — it does not collect any money from whoever is
chatting. That's intentionally out of scope for this pass.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db.app_db import get_sessionmaker
from app.db.models import TicketBooking, User
from app.sams import client as sams
from app.sams.client import MutationsDisabledError, SamsApiError
from app.whatsapp.seatmap import render_seat_map
from app.whatsapp.send import send_buttons, send_image, send_text

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jakarta")
# Phrases, not single words — a bare "bioskop"/"nonton"/"tiket" also shows up
# in plain questions like "film apa yang tayang di bioskop?", which should
# reach the chat agent (film_bioskop tool), not hijack into this flow.
_TRIGGER_PHRASES = (
    "pesan tiket", "pesen tiket", "beli tiket", "booking tiket", "order tiket",
    "mau nonton", "pengen nonton", "ingin nonton", "mau ke bioskop",
)
_CANCEL_WORDS = ("batal", "cancel", "gajadi", "ga jadi", "gak jadi", "tidak jadi", "nggak jadi", "stop")
# Desire language for the "named a real, just-shown movie title" trigger —
# the LLM kept mishandling this itself (e.g. "mau dong baby udon" got
# answered as if about food), so it's caught here deterministically instead
# of relying on prompt instructions alone. See film_bioskop.recent_titles().
_DESIRE_WORDS = ("mau", "pesan", "pesen", "pengen", "ingin", "dong", "boleh")

_pending: dict[str, dict[str, Any]] = {}

# Flat city+cinema list, cached — a user often names the specific branch
# ("Cibadak") rather than the city it's in ("Sukabumi"), and there's no way
# to know which city a cinema belongs to without having fetched all of
# them at least once. Cinema rosters don't change minute to minute, so a
# TTL cache beats a fresh multi-city fetch on every unmatched reply.
_cinema_cache: dict[str, Any] = {"data": None, "expires_at": 0.0}
_CINEMA_CACHE_TTL_S = 1800


def _normalize_phone(raw: str) -> str:
    return "".join(ch for ch in raw if ch.isdigit())


def _rp(n: float) -> str:
    return f"Rp{n:,.0f}".replace(",", ".")


async def _all_cinemas() -> list[dict]:
    now = time.monotonic()
    if _cinema_cache["data"] is not None and now < _cinema_cache["expires_at"]:
        return _cinema_cache["data"]

    cities = await sams.list_cities()
    flat: list[dict] = []
    for city in cities:
        if not city.get("is_active"):
            continue
        try:
            cinemas = await sams.list_cinemas(city["city_id"])
        except SamsApiError:
            continue
        for cinema in cinemas:
            flat.append({**cinema, "city_id": city["city_id"], "city_name": city["city_name"]})

    _cinema_cache["data"] = flat
    _cinema_cache["expires_at"] = now + _CINEMA_CACHE_TTL_S
    return flat


def _normalize(s: str) -> str:
    """Lowercase, punctuation dropped, whitespace collapsed — a typed reply
    naturally omits a title's punctuation ("Munafik: Melawan Iblis" ->
    "munafik melawan iblis"), so compare on this instead of the raw string.
    Collapsing whitespace matters: swapping ":" for " " next to the space
    that already followed it would otherwise leave a double space that
    fails to match normally single-spaced typed text."""
    s = re.sub(r"[^\w\s]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def should_start(text: str) -> bool:
    t = text.strip().lower()
    if any(p in t for p in _TRIGGER_PHRASES):
        return True
    # "mau dong baby udon" after film_bioskop just listed "Baby Udon" —
    # named a real, recently-shown title + desire language, no trigger
    # phrase needed.
    if any(w in t for w in _DESIRE_WORDS):
        from app.tools.film_bioskop import recent_titles

        norm_t = _normalize(t)
        return any(_normalize(title) in norm_t for title in recent_titles())
    return False


def is_active(phone: str) -> bool:
    return phone in _pending


def _is_cancel(text: str) -> bool:
    t = text.strip().lower()
    return any(w in t for w in _CANCEL_WORDS)


async def _fail(phone: str, e: SamsApiError, context: str) -> None:
    logger.warning("sams api error during %s: %s", context, e)
    await send_text(
        f"Maaf, layanan tiket lagi bermasalah ({context}): {e.message}. Coba lagi nanti atau ketik 'batal'.",
        to=phone,
    )


async def _mutations_disabled_reply(phone: str, context: str) -> None:
    """confirm_booking/confirm_payment/void_booking are hard-disabled
    (SAMS_ALLOW_MUTATIONS=false, e.g. while pointed at production
    read-only) — say so instead of leaving the user on read with no
    reply at all, which is what an uncaught MutationsDisabledError does."""
    logger.warning("ticket_flow: mutation blocked during %s for %s", context, phone)
    await send_text(
        "Maaf, pemesanan tiket lagi belum bisa diselesaikan sampai ke booking/bayar "
        "(sedang mode uji coba read-only). Kamu masih bisa cek film & jadwal, "
        "tapi belum bisa checkout dulu. Ketik 'batal' untuk keluar.",
        to=phone,
    )


async def start(phone: str, text: str, *, user: User) -> None:
    try:
        cities = await sams.list_cities()
    except SamsApiError as e:
        await _fail(phone, e, "daftar kota")
        return

    active = [c for c in cities if c.get("is_active")]
    options = active[:15]
    state = {
        "step": "city",
        "user_id": str(user.id),
        "tenant_id": str(user.tenant_id),
        "cities": options,
        # remembered so later steps don't re-ask something already said
        # up front, e.g. "mau nonton hari ini" — see _remember_date_hint
        "seed_text": text,
    }
    _remember_date_hint(state, text)
    _pending[phone] = state

    # named the city up front too ("mau nonton di Sukabumi hari ini")? skip
    # straight past the city question.
    seed_city = _find_in_text(text, options, "city_name")
    if seed_city is not None:
        await _proceed_after_city(phone, state, seed_city)
        return

    # or named the specific branch directly ("mau nonton di Cibadak") —
    # search nationally, same as the city step's fallback.
    seed_cinema = _find_in_text(text, await _all_cinemas(), "cinema_name")
    if seed_cinema is not None:
        await _jump_to_cinema(phone, state, seed_cinema)
        return

    lines = [f"{i+1}. {c['city_name']}" for i, c in enumerate(options)]
    await send_text(
        "🎬 Mau nonton di kota mana? Ketik nomor atau nama kotanya:\n" + "\n".join(lines),
        to=phone,
    )


def _remember_date_hint(state: dict, text: str) -> None:
    """If a date was already mentioned (e.g. "mau nonton hari ini"), stash it
    so the date step is skipped later instead of asking again."""
    if "date" in state:
        return
    d = _parse_date_anywhere(text)
    if d is not None:
        state["date"] = d.isoformat()


def _match(text: str, options: list[dict], name_key: str) -> dict | None:
    """A direct reply to a "pick one" prompt — a number, the option's name
    (possibly a fragment of it, e.g. "suka" -> "Sukabumi"), or the name
    wrapped in a fuller sentence (e.g. "di sukabumi" -> "Sukabumi")."""
    t = text.strip().lower()
    # leading number, not "the whole message is only digits" — "1 😎" or
    # "2 tiket ya" should still pick option 1/2, not fail past this check
    # entirely just because of what follows the digit.
    m = re.match(r"^(\d+)\b", t)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(options):
            return options[idx]
    for o in options:
        if t == o[name_key].strip().lower():
            return o
    whole = [
        o
        for o in options
        if t in o[name_key].strip().lower() or o[name_key].strip().lower() in t
    ]
    if len(whole) == 1:
        return whole[0]
    # "cibadak boleh" doesn't contain the full "sams cibadak" as a
    # substring either direction — fall back to word overlap so a
    # distinctive word from the name (skip short/common ones like "sams")
    # matching a word in the reply is enough.
    t_words = set(re.findall(r"\w+", t))
    word_matches = [
        o
        for o in options
        if {w for w in re.findall(r"\w+", o[name_key].strip().lower()) if len(w) >= 4}
        & t_words
    ]
    return word_matches[0] if len(word_matches) == 1 else None


def _find_in_text(text: str, options: list[dict], name_key: str) -> dict | None:
    """The reverse: scan free text for a mention of one option's name — for
    picking up "mau nonton di Sukabumi hari ini" from the message that
    kicked the flow off, not a direct one-word reply to a prompt."""
    t = text.strip().lower()
    matches = [o for o in options if o[name_key].strip().lower() in t]
    if len(matches) == 1:
        return matches[0]
    # punctuation-insensitive fallback — "Munafik: Melawan Iblis" typed
    # without the colon.
    norm_t = _normalize(t)
    matches = [o for o in options if _normalize(o[name_key]) in norm_t]
    return matches[0] if len(matches) == 1 else None


async def _cancel(phone: str) -> None:
    _pending.pop(phone, None)
    await send_text("Oke, pemesanan tiket dibatalkan.", to=phone)


_CONFIRM_WORDS = ("kirim", "lanjut", "gas", "setuju")
_PAY_WORDS = ("bayar", "lanjut", "gas")


async def handle_text(phone: str, text: str, *, user: User) -> None:
    state = _pending.get(phone)
    if state is None:
        return
    step = state["step"]
    if _is_cancel(text):
        # a real hold exists once we're at the payment step (confirm_booking
        # already ran) — dropping local state without telling SAMS would
        # orphan it instead of actually releasing the seat.
        if step == "payment":
            await _void(phone, state)
        else:
            await _cancel(phone)
        return

    if step == "city":
        await _step_city(phone, text, state)
    elif step == "cinema":
        await _step_cinema(phone, text, state)
    elif step == "date":
        await _step_date(phone, text, state)
    elif step == "movie":
        await _step_movie(phone, text, state)
    elif step == "showtime":
        await _step_showtime(phone, text, state)
    elif step == "seats":
        await _step_seats(phone, text, state)
    else:
        # confirm/payment are button-driven, but plenty of people type
        # "kirim"/"bayar" instead of actually tapping — accept that too
        # rather than just repeating the nudge every time.
        t = text.strip().lower()
        if step == "confirm" and any(w in t for w in _CONFIRM_WORDS):
            await _confirm_booking(phone, state)
            return
        if step == "payment" and any(w in t for w in _PAY_WORDS):
            await _confirm_payment(phone, state)
            return
        await send_text(
            "Tekan salah satu tombol di atas ya, atau ketik 'batal' untuk membatalkan.",
            to=phone,
        )


async def _step_city(phone: str, text: str, state: dict) -> None:
    city = _match(text, state["cities"], "city_name")
    if city is not None:
        await _proceed_after_city(phone, state, city)
        return

    # not a city name — maybe they named the specific branch instead
    # ("Cibadak" is a cinema, the city is "Sukabumi"). Search nationally.
    cinema = _match(text, await _all_cinemas(), "cinema_name")
    if cinema is not None:
        await _jump_to_cinema(phone, state, cinema)
        return

    await send_text("Kota tidak ditemukan. Coba ketik ulang nama/nomor kotanya, atau 'batal'.", to=phone)


async def _jump_to_cinema(phone: str, state: dict, cinema: dict) -> None:
    """cinema came from the national _all_cinemas() search, so both the
    city and the exact branch are already known — skip straight past both
    questions to whatever comes after (date, or showtimes if the date was
    also given up front)."""
    all_cinemas = await _all_cinemas()
    state["city_id"] = cinema["city_id"]
    state["city_name"] = cinema["city_name"]
    state["cinemas"] = [c for c in all_cinemas if c["city_id"] == cinema["city_id"]]
    state["cinema_id"] = cinema["cinema_id"]
    state["cinema_name"] = cinema["cinema_name"]
    await _proceed_after_cinema(phone, state)


async def _proceed_after_city(phone: str, state: dict, city: dict) -> None:
    try:
        cinemas = await sams.list_cinemas(city["city_id"])
    except SamsApiError as e:
        await _fail(phone, e, "daftar bioskop")
        return
    if not cinemas:
        await send_text(f"Belum ada bioskop terdaftar di {city['city_name']}. Ketik kota lain atau 'batal'.", to=phone)
        state["step"] = "city"
        return

    state["city_id"] = city["city_id"]
    state["city_name"] = city["city_name"]
    state["cinemas"] = cinemas

    # already named the cinema in the original message ("mau nonton di SAMS
    # Cibadak")? skip the cinema question too, not just the date one.
    seed_cinema = _find_in_text(state.get("seed_text", ""), cinemas, "cinema_name")
    if seed_cinema is not None:
        state["cinema_id"] = seed_cinema["cinema_id"]
        state["cinema_name"] = seed_cinema["cinema_name"]
        await _proceed_after_cinema(phone, state)
        return

    state["step"] = "cinema"
    lines = [f"{i+1}. {c['cinema_name']} — {c.get('cinema_address', '-')}" for i, c in enumerate(cinemas)]
    await send_text("Pilih bioskopnya:\n" + "\n".join(lines), to=phone)


async def _step_cinema(phone: str, text: str, state: dict) -> None:
    cinema = _match(text, state["cinemas"], "cinema_name")
    if cinema is None:
        await send_text("Bioskop tidak ditemukan. Coba ketik ulang, atau 'batal'.", to=phone)
        return
    state["cinema_id"] = cinema["cinema_id"]
    state["cinema_name"] = cinema["cinema_name"]
    await _proceed_after_cinema(phone, state)


async def _proceed_after_cinema(phone: str, state: dict) -> None:
    """Cinema is known — go straight to showtimes if a date was already
    mentioned up front, otherwise ask for one."""
    if "date" in state:
        await _fetch_and_show_showtimes(phone, state, date.fromisoformat(state["date"]))
        return
    state["step"] = "date"
    await send_text(
        "Mau nonton tanggal berapa? Ketik 'hari ini', 'besok', atau format YYYY-MM-DD.",
        to=phone,
    )


_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")


def _parse_date_anywhere(text: str) -> date | None:
    """A date phrase anywhere in free text — "mau nonton hari ini" from the
    seed message, but also a direct reply like "hari ini deh boleh" (same
    filler-word problem as the movie/showtime/seat steps, fixed the same
    way: don't require the whole message to be exactly the phrase)."""
    t = text.strip().lower()
    today = datetime.now(_TZ).date()
    if "hari ini" in t or "sekarang" in t:
        return today
    if "besok" in t:
        return today + timedelta(days=1)
    if "lusa" in t:
        return today + timedelta(days=2)
    m = _DATE_RE.search(t)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            return None
    return None


async def _step_date(phone: str, text: str, state: dict) -> None:
    d = _parse_date_anywhere(text)
    if d is None:
        await send_text("Format tanggal gak dikenali. Contoh: 'besok' atau '2026-09-10'.", to=phone)
        return
    await _fetch_and_show_showtimes(phone, state, d)


async def _fetch_and_show_showtimes(phone: str, state: dict, d: date) -> None:
    try:
        showtimes = await sams.list_showtimes(state["cinema_id"], d.isoformat())
    except SamsApiError as e:
        if e.code.startswith("404"):
            await send_text(
                f"Gak ada jadwal tayang di {state['cinema_name']} tanggal {d.isoformat()}. "
                "Coba tanggal lain atau ketik 'batal'.",
                to=phone,
            )
            state["step"] = "date"
            state.pop("date", None)
            return
        await _fail(phone, e, "daftar jadwal")
        return

    state["date"] = d.isoformat()
    state["showtimes"] = showtimes

    # group into distinct movies first — a flat list of every single
    # timeslot (same title repeated per showing) is hard to scan once a
    # cinema has 10+ showings a day.
    movies: list[dict] = []
    seen = set()
    for s in showtimes:
        if s["movie_name"] in seen:
            continue
        seen.add(s["movie_name"])
        movies.append(s)
    state["movies_today"] = movies

    if len(movies) == 1:
        _select_movie(state, movies[0]["movie_name"])
        await _show_showtime_choices(phone, state)
        return

    # named the movie up front too ("mau dong Baby Udon")? skip the movie
    # question if it's actually showing here today.
    seed_movie = _find_in_text(state.get("seed_text", ""), movies, "movie_name")
    if seed_movie is not None:
        _select_movie(state, seed_movie["movie_name"])
        await _show_showtime_choices(phone, state)
        return

    state["step"] = "movie"
    lines = [
        f"{i+1}. {m['movie_name']} (rating {m.get('rating_name', '-')})"
        for i, m in enumerate(movies)
    ]
    await send_text("Film apa saja hari ini:\n" + "\n".join(lines) + "\n\nPilih nomor filmnya:", to=phone)


def _select_movie(state: dict, movie_name: str) -> None:
    state["selected_movie"] = movie_name
    state["showtimes_for_movie"] = [
        s for s in state["showtimes"] if s["movie_name"] == movie_name
    ]


async def _show_showtime_choices(phone: str, state: dict) -> None:
    state["step"] = "showtime"
    lines = []
    for i, s in enumerate(state["showtimes_for_movie"]):
        jam = (s.get("showtime_start") or "")[-8:-3]
        lines.append(f"{i+1}. {jam} — {s.get('studio_name', '-')} — {_rp(s['showtime_price'])}")
    await send_text(
        f"Jadwal *{state['selected_movie']}*:\n" + "\n".join(lines) + "\n\nPilih nomor jamnya:",
        to=phone,
    )


async def _step_movie(phone: str, text: str, state: dict) -> None:
    movie = _match(text, state["movies_today"], "movie_name")
    if movie is None:
        await send_text("Film tidak ditemukan. Coba ketik ulang nama/nomor filmnya, atau 'batal'.", to=phone)
        return
    _select_movie(state, movie["movie_name"])
    await _show_showtime_choices(phone, state)


_TIME_RE = re.compile(r"\b([01]?\d|2[0-3])[.:]([0-5]\d)\b")


def _parse_time(text: str) -> str | None:
    m = _TIME_RE.search(text)
    if not m:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


async def _step_showtime(phone: str, text: str, state: dict) -> None:
    t = text.strip().lower()
    showtime = None
    m = re.match(r"^(\d+)\b", t)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(state["showtimes_for_movie"]):
            showtime = state["showtimes_for_movie"][idx]
    if showtime is None:
        # "jam 15.50 boleh deh" — answered with the time shown, not its
        # list number.
        wanted = _parse_time(t)
        if wanted:
            matches = [
                s
                for s in state["showtimes_for_movie"]
                if (s.get("showtime_start") or "")[-8:-3] == wanted
            ]
            if len(matches) == 1:
                showtime = matches[0]
    if showtime is None:
        await send_text("Nomor jadwal gak ditemukan. Coba ketik ulang, atau 'batal'.", to=phone)
        return

    try:
        seat_payload = await sams.list_seats(showtime["showtime_id"])
    except SamsApiError as e:
        await _fail(phone, e, "peta kursi")
        return

    seat_map: dict[str, str] = {}
    rows_text = []
    for row in seat_payload.get("show_time_seat", []):
        available = [s["seat_name"] for s in row.get("seat_data", []) if s.get("seat_flag") == "AVAILABLE"]
        for s in row.get("seat_data", []):
            if s.get("seat_flag") == "AVAILABLE":
                seat_map[s["seat_name"].upper()] = s["studio_seat_id"]
        if available:
            rows_text.append(f"{row['row_name']}: {' '.join(available)}")

    if not seat_map:
        await send_text("Maaf, kursi untuk jadwal ini sudah penuh. Pilih jadwal lain atau ketik 'batal'.", to=phone)
        return

    state["showtime_id"] = showtime["showtime_id"]
    state["movie_name"] = showtime["movie_name"]
    state["showtime_start"] = showtime["showtime_start"]
    state["showtime_price"] = showtime["showtime_price"]
    state["seat_map"] = seat_map
    state["step"] = "seats"

    jam = (showtime.get("showtime_start") or "")[-8:-3]
    try:
        image_bytes = render_seat_map(
            seat_payload.get("show_time_seat", []),
            title=showtime["movie_name"],
            subtitle=f"{state['cinema_name']} — {jam}",
        )
        await send_image(image_bytes, "Hijau = tersedia, merah = terisi", to=phone)
    except Exception:  # noqa: BLE001 - the text list below still works without it
        logger.exception("ticket_flow: gagal render/kirim gambar peta kursi")

    await send_text(
        "Kursi tersedia (kode kursi per baris):\n" + "\n".join(rows_text) +
        "\n\nKetik kode kursi yang mau dipesan, pisahkan dengan koma. Contoh: G14,G15",
        to=phone,
    )


async def _step_seats(phone: str, text: str, state: dict) -> None:
    seat_map: dict[str, str] = state["seat_map"]
    # "A3 deh boleh" — extract seat-code-shaped tokens rather than assuming
    # the whole comma-separated chunk is exactly a code; restricted to the
    # row letters that actually exist here so it can't false-match unrelated
    # text.
    row_letters = "".join(sorted({code[0] for code in seat_map}))
    pattern = re.compile(rf"\b([{row_letters}])\s*-?\s*(\d{{1,2}})\b", re.IGNORECASE)
    seen: set[str] = set()
    codes: list[str] = []
    for letter, num in pattern.findall(text):
        code = f"{letter.upper()}{num}"
        if code not in seen:
            seen.add(code)
            codes.append(code)
    if not codes:
        await send_text("Ketik kode kursinya, contoh: G14,G15", to=phone)
        return
    invalid = [c for c in codes if c not in seat_map]
    if invalid:
        await send_text(
            f"Kursi tidak tersedia/tidak dikenal: {', '.join(invalid)}. Coba ketik ulang.",
            to=phone,
        )
        return

    state["selected_seat_names"] = codes
    state["selected_seat_ids"] = [seat_map[c] for c in codes]
    state["amount"] = state["showtime_price"] * len(codes)
    state["partner_reference_number"] = sams.new_partner_reference()
    state["step"] = "confirm"

    jam = (state["showtime_start"] or "")[-8:-3]
    recap = (
        f"🎬 *{state['movie_name']}*\n"
        f"{state['cinema_name']}, {jam}\n"
        f"Kursi: {', '.join(codes)}\n"
        f"Total: {_rp(state['amount'])}\n\n"
        "Kirim untuk booking kursinya (belum bayar), atau Batal."
    )
    await send_buttons(recap, [("ticket_confirm", "Kirim"), ("ticket_cancel", "Batal")], to=phone)


async def handle_button(phone: str, button_id: str) -> None:
    phone = _normalize_phone(phone)
    state = _pending.get(phone)
    if state is None:
        await send_text("Gak ada pemesanan tiket yang aktif. Ketik 'pesan tiket' untuk mulai.", to=phone)
        return

    if button_id == "ticket_cancel":
        await _cancel(phone)
        return

    if button_id == "ticket_confirm" and state["step"] == "confirm":
        await _confirm_booking(phone, state)
        return

    if button_id == "ticket_pay" and state["step"] == "payment":
        await _confirm_payment(phone, state)
        return

    if button_id == "ticket_pay_cancel" and state["step"] == "payment":
        await _void(phone, state)
        return

    logger.info("ticket_flow: button %r ignored at step %r", button_id, state.get("step"))


async def _confirm_booking(phone: str, state: dict) -> None:
    customer_id = sams.customer_id_for(uuid.UUID(state["user_id"]))
    try:
        booking = await sams.confirm_booking(
            showtime_id=state["showtime_id"],
            studio_seat_id=state["selected_seat_ids"],
            partner_reference_number=state["partner_reference_number"],
            customer_id=customer_id,
        )
    except MutationsDisabledError:
        await _mutations_disabled_reply(phone, "confirm_booking")
        return
    except SamsApiError as e:
        if e.code == "4090001":  # Some Seat Already Booked
            await send_text(
                "Yah, ada kursi yang barusan dibooking orang lain. Ketik ulang kode kursi lain, atau 'batal'.",
                to=phone,
            )
            state["step"] = "seats"
            return
        await _fail(phone, e, "konfirmasi booking")
        return

    state["sams_booking_id"] = booking["booking_id"]
    state["sams_customer_id"] = customer_id
    state["step"] = "payment"

    async with get_sessionmaker()() as session:
        session.add(
            TicketBooking(
                tenant_id=uuid.UUID(state["tenant_id"]),
                user_id=uuid.UUID(state["user_id"]),
                phone=phone,
                partner_reference_number=state["partner_reference_number"],
                sams_customer_id=customer_id,
                sams_booking_id=booking["booking_id"],
                showtime_id=state["showtime_id"],
                cinema_name=state["cinema_name"],
                movie_name=state["movie_name"],
                showtime_start=state["showtime_start"],
                seat_names=", ".join(state["selected_seat_names"]),
                amount=state["amount"],
                status="booked",
            )
        )
        await session.commit()

    await send_buttons(
        f"Kursi berhasil di-hold: {', '.join(state['selected_seat_names'])} — {_rp(state['amount'])}.\n"
        "Tekan Bayar untuk menyelesaikan pemesanan.",
        [("ticket_pay", "Bayar"), ("ticket_pay_cancel", "Batal")],
        to=phone,
    )


async def _confirm_payment(phone: str, state: dict) -> None:
    try:
        payment = await sams.confirm_payment(
            booking_id=state["sams_booking_id"],
            partner_reference_number=state["partner_reference_number"],
            customer_id=state["sams_customer_id"],
        )
    except MutationsDisabledError:
        await _mutations_disabled_reply(phone, "confirm_payment")
        return
    except SamsApiError as e:
        await _fail(phone, e, "pembayaran")
        return

    async with get_sessionmaker()() as session:
        row = (
            await session.execute(
                select(TicketBooking).where(
                    TicketBooking.partner_reference_number == state["partner_reference_number"]
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            row.status = "paid"
            row.payment_reference_number = payment.get("payment_reference_number")
            await session.commit()

    jam = (state["showtime_start"] or "")[-8:-3]
    await send_text(
        f"✅ Tiket berhasil dipesan!\n\n"
        f"🎬 *{state['movie_name']}*\n"
        f"{state['cinema_name']}, {jam}\n"
        f"Kursi: {', '.join(state['selected_seat_names'])}\n"
        f"Total dibayar: {_rp(state['amount'])}\n"
        f"Kode referensi: {state['partner_reference_number']}",
        to=phone,
    )
    _pending.pop(phone, None)


async def _void(phone: str, state: dict) -> None:
    try:
        await sams.void_booking(
            booking_id=state["sams_booking_id"],
            partner_reference_number=state["partner_reference_number"],
            customer_id=state["sams_customer_id"],
        )
    except MutationsDisabledError:
        await _mutations_disabled_reply(phone, "void_booking")
        return
    except SamsApiError as e:
        await _fail(phone, e, "pembatalan booking")
        return

    async with get_sessionmaker()() as session:
        row = (
            await session.execute(
                select(TicketBooking).where(
                    TicketBooking.partner_reference_number == state["partner_reference_number"]
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            row.status = "voided"
            await session.commit()

    await send_text("Booking dibatalkan, kursi sudah dilepas.", to=phone)
    _pending.pop(phone, None)
