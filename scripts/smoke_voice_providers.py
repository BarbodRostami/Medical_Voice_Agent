"""Smoke-check voice provider foundation (prep + optional live TTS).

Usage (from repo root, venv active):

  python scripts/smoke_voice_providers.py
  python scripts/smoke_voice_providers.py --tts
  python scripts/smoke_voice_providers.py --tts --provider openai

Defaults never require a paid key. ``--tts`` exercises ``persian_to_voice``
(which already falls back to edge-tts).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from backend.medical_voice_utils import persian_to_voice, prepare_text_for_tts
from backend.provider_config import provider_status_summary


SAMPLE = (
    "بیمار SpO2 برابر ۹۲ درصد، PEEP برابر 8، ETCO2 برابر ۳۵ "
    "و MAP برابر 70 است."
)
DEFAULT_OUT = str(ROOT / "assets" / "audio" / "scratch" / "smoke_voice_providers.mp3")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test TTS/STT provider foundation")
    parser.add_argument(
        "--tts",
        action="store_true",
        help="Also synthesize MP3 via project pipeline (edge or openai+fallback)",
    )
    parser.add_argument(
        "--provider",
        choices=("edge", "openai"),
        default=None,
        help="Temporarily override TTS_PROVIDER for this run",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help="Output MP3 path when --tts is set (default: assets/audio/scratch/)",
    )
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if args.provider:
        os.environ["TTS_PROVIDER"] = args.provider

    status = provider_status_summary()
    print("=== provider status ===")
    for key, value in status.items():
        print(f"  {key}: {value}")

    prepared = prepare_text_for_tts(SAMPLE)
    print("\n=== speech-prep (dictionary / digits) ===")
    print(f"  in : {SAMPLE}")
    print(f"  out: {prepared}")

    if not args.tts:
        print("\nOK — prep-only. Re-run with --tts to synthesize audio.")
        return 0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    audio = persian_to_voice(SAMPLE)
    out_path.write_bytes(audio)
    print(f"\n=== TTS ===\n  wrote {out_path} ({len(audio)} bytes)")
    print("OK — open the MP3 to listen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
