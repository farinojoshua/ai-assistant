"""Thin client for the SAMS Studios Open API Ticket (B2B, cinema booking).

Reference: Sams Studios Open API Document Specification v1.1.0 + the
"Open Api Ticket" Postman collection. Every call after auth is RSA-signed
(see signature.py); the access token is cached and refreshed with a safety
margin before it expires.

IMPORTANT — payment model: `wallet_id` is the MERCHANT's own prepaid balance
with SAMS Studios, not the end customer's payment method. Confirming payment
here debits *our* wallet; collecting money from whoever is booking the
ticket (if that's ever needed) is a separate concern this client knows
nothing about. See app/whatsapp/ticket_flow.py.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

import httpx

from app.config import get_settings
from app.sams.signature import iso_timestamp, sign


class SamsApiError(Exception):
    def __init__(self, code: str, message: str, payload: Any = None):
        self.code = code
        self.message = message
        self.payload = payload
        super().__init__(f"{code}: {message}")


_token_cache: dict[str, Any] = {"token": None, "expires_at": 0.0}


def _dumps(body: dict | None) -> str:
    if not body:
        return "{}"
    return json.dumps(body, separators=(",", ":"))


async def _request(
    method: str, path: str, body: dict | None = None, *, with_auth: bool = True
) -> dict:
    settings = get_settings()
    raw_body = _dumps(body)
    timestamp = iso_timestamp()
    signature = sign(method, path, raw_body, timestamp)

    headers = {
        "Content-Type": "application/json",
        "X-Signature": signature,
        "X-Timestamp": timestamp,
    }
    if with_auth:
        headers["Authorization"] = f"Bearer {await _get_access_token()}"

    url = f"{settings.sams_base_url}{path}"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.request(method, url, content=raw_body, headers=headers)

    try:
        data = resp.json()
    except ValueError as e:
        raise SamsApiError("HTTP_" + str(resp.status_code), resp.text) from e

    # The sandbox has been observed sending "is_success": true on a 400
    # (e.g. validation errors, payload = ["client_id minimal 36 karakter"])
    # despite the spec's own documented samples showing false there — so
    # HTTP status is the primary signal, is_success only a secondary one.
    if resp.status_code >= 400 or not data.get("is_success"):
        message = data.get("response_message") or "unknown error"
        payload = data.get("payload")
        if isinstance(payload, list) and payload:
            message = f"{message}: {'; '.join(str(p) for p in payload)}"
        raise SamsApiError(
            data.get("response_code") or f"HTTP_{resp.status_code}", message, payload
        )
    return data.get("payload")


async def _get_access_token() -> str:
    now = time.monotonic()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]

    settings = get_settings()
    payload = await _request(
        "POST",
        "/oauth/access-token/b2b",
        {"client_id": settings.sams_client_id, "client_secret": settings.sams_client_secret},
        with_auth=False,
    )
    # The PDF spec sample uses "accessToken"/"expiresIn"; the sandbox's own
    # Postman collection test script reads "access_token" instead — accept
    # either since the two disagree.
    token = payload.get("accessToken") or payload["access_token"]
    ttl = int(payload.get("expiresIn") or payload.get("expires_in") or 900)
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + max(ttl - 60, 30)  # refresh 60s early
    return token


def new_partner_reference() -> str:
    settings = get_settings()
    return f"{settings.sams_partner_prefix}-{uuid.uuid4().hex[:14]}"


def customer_id_for(user_id: uuid.UUID) -> str:
    """Stable per-user SAMS customer_id — deterministic, no extra DB column."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(user_id)))


async def list_cities() -> list[dict]:
    return await _request("GET", "/public/list/city")


async def list_movies() -> list[dict]:
    return await _request("GET", "/public/list/movie")


async def get_movie(movie_id: str) -> dict:
    return await _request("POST", "/public/get/movie", {"movie_id": movie_id})


async def list_now_playing() -> list[dict]:
    return await _request("GET", "/public/list/now-playing")


async def list_upcoming() -> list[dict]:
    return await _request("GET", "/public/list/up-coming")


async def list_disclaimer() -> list[dict]:
    return await _request("GET", "/public/list/disclaimer")


async def list_cinemas(city_id: str) -> list[dict]:
    return await _request("POST", "/public/list/cinema", {"city_id": city_id})


async def list_showtimes(cinema_id: str, showtime_date: str) -> list[dict]:
    return await _request(
        "POST",
        "/public/list/showtime",
        {"cinema_id": cinema_id, "showtime_date": showtime_date},
    )


async def list_seats(showtime_id: str) -> dict:
    return await _request("POST", "/public/list/seat", {"showtime_id": showtime_id})


async def confirm_booking(
    *, showtime_id: str, studio_seat_id: list[str], partner_reference_number: str, customer_id: str
) -> dict:
    return await _request(
        "POST",
        "/ticket/booking/confirm",
        {
            "showtime_id": showtime_id,
            "studio_seat_id": studio_seat_id,
            "partner_reference_number": partner_reference_number,
            "customer_id": customer_id,
        },
    )


async def booking_status(*, showtime_id: str, partner_reference_number: str) -> dict:
    return await _request(
        "POST",
        "/ticket/booking/status",
        {"showtime_id": showtime_id, "partner_reference_number": partner_reference_number},
    )


async def void_booking(
    *, booking_id: str, partner_reference_number: str, customer_id: str, wallet_id: str | None = None
) -> dict:
    settings = get_settings()
    return await _request(
        "POST",
        "/ticket/booking/void",
        {
            "booking_id": booking_id,
            "wallet_id": wallet_id or settings.sams_wallet_id,
            "partner_reference_number": partner_reference_number,
            "customer_id": customer_id,
        },
    )


async def confirm_payment(
    *, booking_id: str, partner_reference_number: str, customer_id: str, wallet_id: str | None = None
) -> dict:
    settings = get_settings()
    return await _request(
        "POST",
        "/ticket/payment/confirm",
        {
            "booking_id": booking_id,
            "wallet_id": wallet_id or settings.sams_wallet_id,
            "partner_reference_number": partner_reference_number,
            "customer_id": customer_id,
        },
    )


async def payment_history(customer_id: str) -> list[dict]:
    # PDF spec says "/payment/history"; the corrected Postman collection
    # (and live sandbox) actually uses "/ticket/payment/history".
    return await _request("POST", "/ticket/payment/history", {"customer_id": customer_id})
