"""Storage key mapping and public audio proxy URL builder (no heavy deps)."""
from __future__ import annotations

import re

from backend.audio_security import append_audio_signature, is_allowed_audio_proxy_key


def resolve_storage_key(public_key: str) -> str:
    """Map proxy URL segment to full S3 object key.

    - ``audio/...`` legacy clips
    - ``cases/...`` internal case metadata (not served by public audio proxy)
    - ``YYYY-MM-DD/{uuid}.mp3`` HakimAI TTS poll keys
    """
    key = public_key.lstrip("/")
    if ".." in key or "\\" in key or "\x00" in key:
        raise ValueError("Invalid storage key")
    if key.startswith(("audio/", "cases/")):
        return key
    if re.match(r"^\d{4}-\d{2}-\d{2}/", key):
        return key
    return f"audio/{key}"


def build_audio_proxy_url(base_url: str, public_key: str) -> str:
    """Build client-facing URL: .../voice/audio/{key} (supports dated keys).

    When ``API_KEY`` / ``AUDIO_SIGNING_SECRET`` is set, appends a short-lived
    HMAC signature so the public proxy cannot be scraped by key guessing.
    HakimAI S3 polling is unaffected (does not use this proxy).
    """
    key = public_key.lstrip("/")
    if not is_allowed_audio_proxy_key(key):
        raise ValueError(f"Refusing to build proxy URL for key: {key!r}")
    base = base_url.rstrip("/") + "/"
    url = f"{base}voice/audio/{key}"
    return append_audio_signature(url, key)
