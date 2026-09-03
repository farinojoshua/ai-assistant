"""Download inbound media (photos) from the WhatsApp Cloud API.

Meta's webhook only gives a media id — the actual bytes live behind a
short-lived URL that must be resolved (and re-fetched with the same bearer
token) separately.
"""
from __future__ import annotations

import httpx

from app.config import get_settings


class MediaError(Exception):
    pass


async def download_media(media_id: str) -> tuple[bytes, str]:
    """Resolve a WhatsApp media id to (bytes, mime_type)."""
    s = get_settings()
    if not s.whatsapp_token:
        raise MediaError("WHATSAPP_TOKEN belum diset")
    headers = {"Authorization": f"Bearer {s.whatsapp_token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        meta = await client.get(
            f"https://graph.facebook.com/{s.whatsapp_api_version}/{media_id}",
            headers=headers,
        )
        if meta.status_code >= 400:
            raise MediaError(f"gagal resolve media (HTTP {meta.status_code})")
        info = meta.json()
        url = info.get("url")
        mime_type = info.get("mime_type", "image/jpeg")
        if not url:
            raise MediaError("respons media tidak berisi url")

        resp = await client.get(url, headers=headers)
        if resp.status_code >= 400:
            raise MediaError(f"gagal download media (HTTP {resp.status_code})")
        return resp.content, mime_type
