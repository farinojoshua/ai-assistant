"""Reverse geocoding via OpenStreetMap Nominatim.

Free, no API key. Usage policy asks for a descriptive User-Agent and a low
request rate — fine here since this fires once per shared location, not a
bulk job.
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_USER_AGENT = "ai-assistant-gbijonggolraya/1.0 (internal WA location log)"


async def reverse_geocode(latitude: float, longitude: float) -> str | None:
    """Best-effort: coordinate -> human-readable address, or None."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={
                    "lat": latitude,
                    "lon": longitude,
                    "format": "jsonv2",
                    "zoom": 18,
                },
                headers={"User-Agent": _USER_AGENT},
            )
        if resp.status_code >= 400:
            logger.warning(
                "reverse_geocode failed %s: %s", resp.status_code, resp.text
            )
            return None
        return resp.json().get("display_name")
    except Exception:  # noqa: BLE001 - best-effort, never block saving the location
        logger.exception("reverse_geocode error")
        return None
