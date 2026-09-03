"""RSA-SHA256 request signing for the SAMS Studios Open API.

Pattern (SAMS Studios Open API Document Specification v1.1.0, section 6):
    string_to_sign = f"{METHOD}:{PATH}:{sha256_hex(body).lower()}:{TIMESTAMP}"
signed with the merchant's RSA private key (SHA256withRSA / PKCS1v15),
base64-encoded into the X-Signature header.

PATH is the route below the API version prefix, e.g. "/public/list/showtime"
— not the full "/sandbox/merchant/v1.0/public/list/showtime". An empty body
signs as the literal string "{}".
"""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from functools import lru_cache

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.config import get_settings


@lru_cache
def _load_private_key():
    settings = get_settings()
    with open(settings.sams_private_key_path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def iso_timestamp() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def sign(method: str, path: str, body: str, timestamp: str) -> str:
    body_hash = hashlib.sha256(body.encode()).hexdigest().lower()
    string_to_sign = f"{method}:{path}:{body_hash}:{timestamp}"
    private_key = _load_private_key()
    signature = private_key.sign(
        string_to_sign.encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    return base64.b64encode(signature).decode()
