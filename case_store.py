"""Collaborator case layout on S3-compatible storage.

HakimAI / external server owns the case ``uuid``. Voice server writes::

    cases/{uuid}/meta.json
    cases/{uuid}/input/text.json          # text (TTS) mode
    cases/{uuid}/input/audio.<ext>        # audio (STT) mode
    cases/{uuid}/output/reply.mp3         # TTS output (HakimAI polls this)
    audio/{uuid}.mp3                      # same MP3 — legacy voice_storage-style key

TTS: HakimAI polls S3 for the MP3 (does not pull bytes from the voice API).
STT: HakimAI reads text via GET /api/get-msg (no MP3 required).
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Literal

from medical_voice_utils import (
    get_json_from_storage,
    put_json_to_storage,
    put_storage_object,
    storage_object_exists,
)

CaseStatus = Literal["queued", "processing", "ready", "failed"]

_CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_case_id(raw: str) -> str:
    """Reject empty / path-traversal / odd ids from the external server."""
    case_id = (raw or "").strip()
    if not case_id or ".." in case_id or "/" in case_id or "\\" in case_id:
        raise ValueError("Invalid uuid: empty or contains path separators.")
    if not _CASE_ID_RE.match(case_id):
        raise ValueError(
            "Invalid uuid: use letters, digits, dot, underscore, or hyphen (max 128)."
        )
    return case_id


def meta_key(case_id: str) -> str:
    return f"cases/{case_id}/meta.json"


def input_text_key(case_id: str) -> str:
    return f"cases/{case_id}/input/text.json"


def input_audio_key(case_id: str, extension: str) -> str:
    ext = extension if extension.startswith(".") else f".{extension}"
    return f"cases/{case_id}/input/audio{ext}"


def output_audio_key(case_id: str) -> str:
    """Canonical object key HakimAI should poll after TTS."""
    return f"cases/{case_id}/output/reply.mp3"


def legacy_audio_key(case_id: str) -> str:
    """Compatibility key for existing voice_storage-style pollers: audio/{uuid}.mp3."""
    return f"audio/{case_id}.mp3"


def s3_bucket() -> str:
    return os.getenv("LIARA_BUCKET", "voiceai")


def s3_endpoint() -> str:
    return (os.getenv("LIARA_ENDPOINT") or "").rstrip("/")


def s3_locator(case_id: str) -> dict[str, str]:
    """Fields HakimAI needs to poll/download TTS audio without hitting the voice API."""
    return {
        "s3_endpoint": s3_endpoint(),
        "s3_bucket": s3_bucket(),
        "s3_key": output_audio_key(case_id),
        "s3_key_legacy": legacy_audio_key(case_id),
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_meta(
    case_id: str,
    *,
    mode: Literal["text", "audio"],
    status: CaseStatus = "queued",
    message: str = "در صف انتظار...",
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "uuid": case_id,
        "mode": mode,
        "status": status,
        "message": message,
        "audio_url": None,
        "output_key": output_audio_key(case_id),
        "transcript": None,
        "answer": None,
        "text": None,
        "error": None,
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }
    meta.update(s3_locator(case_id))
    return meta


def save_meta(meta: dict[str, Any]) -> None:
    meta = dict(meta)
    meta["updated_at"] = utc_now_iso()
    put_json_to_storage(meta_key(meta["uuid"]), meta)


def load_meta(case_id: str) -> dict[str, Any] | None:
    key = meta_key(case_id)
    if not storage_object_exists(key):
        return None
    return get_json_from_storage(key)


def save_input_text(case_id: str, text: str) -> None:
    put_json_to_storage(input_text_key(case_id), {"uuid": case_id, "text": text})


def save_input_audio(case_id: str, audio_bytes: bytes, extension: str) -> str:
    key = input_audio_key(case_id, extension)
    put_storage_object(key, audio_bytes, "application/octet-stream")
    return key


def save_output_text(case_id: str, *, transcript: str | None, answer: str | None) -> None:
    """Persist STT/RAG text so HakimAI can rely on S3 meta even after API restart."""
    put_json_to_storage(
        f"cases/{case_id}/output/text.json",
        {
            "uuid": case_id,
            "transcript": transcript,
            "answer": answer,
            "text": answer or transcript,
        },
    )
