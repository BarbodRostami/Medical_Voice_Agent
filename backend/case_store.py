"""Collaborator case layout on S3-compatible storage.

HakimAI / external server owns the case ``uuid``.

TTS output key (HakimAI polls this)::

    {YYYY-MM-DD}/{uuid}.mp3

STT / form-fields output key (HakimAI polls this)::

    {YYYY-MM-DD}/{uuid}.json

Date is Asia/Tehran calendar day when the job is created.

Internal metadata (optional, voice-server only)::

    cases/{uuid}/meta.json
    cases/{uuid}/input/...
    cases/{uuid}/output/text.json   # STT text backup

TTS: HakimAI polls S3 for ``{date}/{uuid}.mp3`` — do not expose bucket/key in API JSON.
STT: Whisper + structured fields; HakimAI polls ``{date}/{uuid}.json`` on S3
(and may still use GET /api/get-msg for status / legacy text).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from backend.medical_voice_utils import (
    get_json_from_storage,
    put_json_to_storage,
    put_storage_object,
    storage_object_exists,
)

CaseStatus = Literal["queued", "processing", "ready", "failed"]

_TEHRAN = ZoneInfo("Asia/Tehran")
_CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}/")


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


def tehran_date_str(when: datetime | None = None) -> str:
    """Return YYYY-MM-DD in Asia/Tehran."""
    dt = when or datetime.now(_TEHRAN)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TEHRAN)
    else:
        dt = dt.astimezone(_TEHRAN)
    return dt.strftime("%Y-%m-%d")


def meta_key(case_id: str) -> str:
    return f"cases/{case_id}/meta.json"


def input_text_key(case_id: str) -> str:
    return f"cases/{case_id}/input/text.json"


def input_audio_key(case_id: str, extension: str) -> str:
    ext = extension if extension.startswith(".") else f".{extension}"
    return f"cases/{case_id}/input/audio{ext}"


def output_audio_key(case_id: str, day: str | None = None) -> str:
    """Canonical MP3 key HakimAI polls: ``{YYYY-MM-DD}/{uuid}.mp3``."""
    date_part = day or tehran_date_str()
    return f"{date_part}/{case_id}.mp3"


def output_json_key(case_id: str, day: str | None = None) -> str:
    """Canonical STT/fields JSON key HakimAI polls: ``{YYYY-MM-DD}/{uuid}.json``."""
    date_part = day or tehran_date_str()
    return f"{date_part}/{case_id}.json"


def utc_now_iso() -> str:
    return datetime.now(_TEHRAN).astimezone().replace(microsecond=0).isoformat()


def new_meta(
    case_id: str,
    *,
    mode: Literal["text", "audio"],
    status: CaseStatus = "queued",
    message: str = "در صف انتظار...",
) -> dict[str, Any]:
    day = tehran_date_str()
    return {
        "uuid": case_id,
        "mode": mode,
        "status": status,
        "message": message,
        "audio_url": None,
        "output_key": output_audio_key(case_id, day),
        "output_json_key": output_json_key(case_id, day),
        "day": day,
        "transcript": None,
        "answer": None,
        "text": None,
        "fields": None,
        "error": None,
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }


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


def save_output_text(
    case_id: str,
    *,
    transcript: str | None,
    answer: str | None,
    fields: dict[str, Any] | None = None,
) -> None:
    """Persist STT/RAG text backup under cases/ (internal)."""
    payload: dict[str, Any] = {
        "uuid": case_id,
        "transcript": transcript,
        "answer": answer,
        "text": answer or transcript,
    }
    if fields is not None:
        payload["fields"] = fields
    put_json_to_storage(f"cases/{case_id}/output/text.json", payload)


def save_collaborator_stt_json(
    case_id: str,
    payload: dict[str, Any],
    *,
    day: str | None = None,
) -> str:
    """Write pollable STT result for HakimAI: ``{YYYY-MM-DD}/{uuid}.json``."""
    key = output_json_key(case_id, day)
    put_json_to_storage(key, payload)
    return key
