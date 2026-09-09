"""Render a cinema seat map as a PNG for WhatsApp — a visual companion to
the text seat list ticket_flow already sends (the text stays the source of
truth for typing seat codes; this is just so a customer can *see* the layout
before typing).

Colors are the reference dataviz palette's status pair (good/critical) —
status color always paired with a label (the seat code itself, plus a
legend), never color alone, per the skill's accessibility rule.
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

_CELL = 40
_GAP = 6
_ROW_LABEL_W = 36
_MARGIN = 20
_HEADER_H = 70
_LEGEND_H = 44

_COLOR_SURFACE = (252, 252, 251)
_COLOR_INK = (11, 11, 11)
_COLOR_MUTED = (137, 135, 129)
_COLOR_AVAILABLE = (12, 163, 12)   # status "good"
_COLOR_TAKEN = (208, 59, 59)       # status "critical"
_COLOR_SCREEN = (200, 200, 195)


def _font(size: int) -> ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def render_seat_map(rows: list[dict], *, title: str, subtitle: str) -> bytes:
    """rows: SAMS's show_time_seat shape — [{"row_name": "G", "seat_data": [
    {"seat_name": "G14", "seat_flag": "AVAILABLE"|other}, ...]}, ...]."""
    # SAMS lists seats back-to-front (row A closest to screen last); flip so
    # the screen bar at top visually matches row order below it.
    ordered_rows = list(reversed(rows))
    max_seats = max((len(r["seat_data"]) for r in ordered_rows), default=0)

    width = _MARGIN * 2 + _ROW_LABEL_W + max_seats * (_CELL + _GAP)
    height = (
        _MARGIN * 2
        + _HEADER_H
        + len(ordered_rows) * (_CELL + _GAP)
        + _LEGEND_H
    )
    img = Image.new("RGB", (width, height), _COLOR_SURFACE)
    draw = ImageDraw.Draw(img)

    title_font = _font(20)
    subtitle_font = _font(14)
    seat_font = _font(12)
    legend_font = _font(13)

    draw.text((_MARGIN, _MARGIN), title, fill=_COLOR_INK, font=title_font)
    draw.text((_MARGIN, _MARGIN + 26), subtitle, fill=_COLOR_MUTED, font=subtitle_font)

    screen_y = _MARGIN + _HEADER_H
    screen_w = max_seats * (_CELL + _GAP) - _GAP
    screen_x = _MARGIN + _ROW_LABEL_W
    draw.rounded_rectangle(
        [screen_x, screen_y, screen_x + screen_w, screen_y + 10],
        radius=4,
        fill=_COLOR_SCREEN,
    )
    draw.text(
        (screen_x + screen_w / 2, screen_y + 20),
        "LAYAR",
        fill=_COLOR_MUTED,
        font=subtitle_font,
        anchor="mm",
    )

    y = screen_y + 36
    for row in ordered_rows:
        draw.text(
            (_MARGIN, y + _CELL / 2),
            row["row_name"],
            fill=_COLOR_INK,
            font=seat_font,
            anchor="lm",
        )
        x = _MARGIN + _ROW_LABEL_W
        seats_in_order = sorted(row["seat_data"], key=lambda s: s.get("seat_index", 0))
        for seat in seats_in_order:
            available = seat.get("seat_flag") == "AVAILABLE"
            color = _COLOR_AVAILABLE if available else _COLOR_TAKEN
            draw.rounded_rectangle([x, y, x + _CELL, y + _CELL], radius=4, fill=color)
            label = seat["seat_name"].lstrip("ABCDEFGHIJ")  # just the seat number
            draw.text(
                (x + _CELL / 2, y + _CELL / 2),
                label,
                fill=(255, 255, 255),
                font=seat_font,
                anchor="mm",
            )
            x += _CELL + _GAP
        y += _CELL + _GAP

    legend_y = y + 10
    lx = _MARGIN
    for color, label in ((_COLOR_AVAILABLE, "Tersedia"), (_COLOR_TAKEN, "Terisi")):
        draw.rounded_rectangle([lx, legend_y, lx + 18, legend_y + 18], radius=3, fill=color)
        draw.text((lx + 24, legend_y + 9), label, fill=_COLOR_INK, font=legend_font, anchor="lm")
        lx += 120

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
