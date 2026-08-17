"""Save voice-form experiment samples for later regression / Whisper fine-tune.

Audio + a small JSON sidecar are written under ``assets/audio/dataset/``.
Disabled with ``VOICE_FORM_SAVE_SAMPLES=0``. Failures never break STT.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = _PROJECT_ROOT / "assets" / "audio" / "dataset"
_MAX_SAMPLES = 500
_MAX_AUDIO_BYTES = 8 * 1024 * 1024  # 8 MB


def _enabled() -> bool:
    flag = os.getenv("VOICE_FORM_SAVE_SAMPLES", "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


def _prune_oldest(directory: Path) -> None:
    audio_files = sorted(
        [p for p in directory.iterdir() if p.suffix.lower() in {".ogg", ".webm", ".wav", ".mp3", ".m4a"}],
        key=lambda p: p.stat().st_mtime,
    )
    while len(audio_files) > _MAX_SAMPLES:
        old = audio_files.pop(0)
        old.unlink(missing_ok=True)
        old.with_suffix(".json").unlink(missing_ok=True)


def save_voice_form_sample(
    audio_bytes: bytes,
    suffix: str,
    transcript: str,
    fields: dict[str, Any],
) -> Path | None:
    """Persist one STT sample (audio + extracted fields). Returns JSON path or None."""
    if not _enabled() or not audio_bytes or len(audio_bytes) > _MAX_AUDIO_BYTES:
        return None
    try:
        DATASET_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        ext = suffix if suffix.startswith(".") else f".{suffix}"
        audio_path = DATASET_DIR / f"{stamp}{ext}"
        json_path = DATASET_DIR / f"{stamp}.json"
        audio_path.write_bytes(audio_bytes)
        extracted = {
            k: v
            for k, v in fields.items()
            if k not in ("raw_text", "found", "missing") and v is not None
        }
        payload = {
            "saved_at_utc": datetime.now(timezone.utc).isoformat(),
            "extract_version": fields.get("extract_version"),
            "transcript": transcript or "",
            "extracted": extracted,
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _prune_oldest(DATASET_DIR)
        return json_path
    except OSError:
        return None
