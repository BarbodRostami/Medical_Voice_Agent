"""Security helpers for the public ``/voice/audio`` proxy.

HakimAI TTS download stays on S3 (unchanged). This module only hardens the
HTTP proxy used for browser / internal ``audio_url`` links.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from urllib.parse import urlencode

from backend.api_auth import configured_api_key

# Allowed public proxy keys (``cases/...`` intentionally excluded).
# Bare ``name.mp3`` maps to ``audio/name.mp3`` in storage (legacy URL shape).
_ALLOWED_AUDIO_KEY = re.compile(
    r"^(?:"
    r"[A-Za-z0-9._-]+\.mp3"
    r"|"
    r"audio/[A-Za-z0-9._-]+\.mp3"
    r"|"
    r"\d{4}-\d{2}-\d{2}/[A-Za-z0-9._-]+\.mp3"
    r")$"
)

# Default signed-link lifetime (2 hours)
_DEFAULT_TTL_SEC = 2 * 60 * 60


def audio_signing_secret() -> str:
    """Secret for HMAC audio URLs (falls back to API_KEY)."""
    return (
        os.getenv("AUDIO_SIGNING_SECRET")
        or configured_api_key()
        or ""
    ).strip()


def audio_signing_enabled() -> bool:
    """When a signing secret exists, proxy URLs are signed and verified."""
    raw = (os.getenv("AUDIO_PROXY_REQUIRE_SIGNATURE") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return bool(audio_signing_secret())
    # Default: require signatures whenever API_KEY / AUDIO_SIGNING_SECRET is set
    return bool(audio_signing_secret())


def is_allowed_audio_proxy_key(key: str) -> bool:
    """Reject path traversal and non-audio object keys (no ``cases/``)."""
    if not key or ".." in key or "\\" in key or key.startswith("/"):
        return False
    if "\x00" in key or key.startswith("cases/"):
        return False
    return bool(_ALLOWED_AUDIO_KEY.match(key))


def _sign_payload(key: str, exp: int) -> str:
    secret = audio_signing_secret().encode("utf-8")
    msg = f"{key}|{exp}".encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def sign_audio_key(key: str, ttl_sec: int = _DEFAULT_TTL_SEC) -> tuple[int, str]:
    """Return ``(exp_unix, signature)`` for ``key``."""
    exp = int(time.time()) + max(60, int(ttl_sec))
    return exp, _sign_payload(key, exp)


def verify_audio_signature(key: str, exp: str | None, sig: str | None) -> bool:
    """Validate HMAC signature and expiry for an audio proxy request."""
    if not exp or not sig:
        return False
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_i < int(time.time()):
        return False
    expected = _sign_payload(key, exp_i)
    return hmac.compare_digest(expected, sig.strip().lower())


def append_audio_signature(url: str, key: str) -> str:
    """Attach ``exp`` + ``sig`` query params when signing is enabled."""
    if not audio_signing_enabled():
        return url
    exp, sig = sign_audio_key(key)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{urlencode({'exp': str(exp), 'sig': sig})}"
