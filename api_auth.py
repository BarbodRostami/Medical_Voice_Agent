"""API key authentication helpers for the Medical RAG FastAPI app."""
from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import Request
from fastapi.responses import JSONResponse

# Paths that stay public even when API_KEY is set (health + browser audio playback).
PUBLIC_PATH_PREFIXES = ("/voice/audio/",)
PUBLIC_PATHS = frozenset({"/", "/docs", "/openapi.json", "/redoc", "/favicon.ico"})


def configured_api_key() -> str:
    """Read API_KEY at call time so tests can set/clear the env var."""
    return os.getenv("API_KEY", "").strip()


def api_keys_match(provided: str | None, expected: str) -> bool:
    if not provided:
        return False
    # Hash first so compare_digest never sees unequal lengths.
    a = hashlib.sha256(provided.encode("utf-8")).digest()
    b = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(a, b)


def is_public_path(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES)


async def enforce_api_key(request: Request, call_next):
    """ASGI middleware body: require X-API-Key when API_KEY env is set."""
    expected = configured_api_key()
    if not expected or is_public_path(request.url.path):
        return await call_next(request)

    provided = request.headers.get("X-API-Key")
    if not api_keys_match(provided, expected):
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing API key. Send header X-API-Key."},
        )
    return await call_next(request)
