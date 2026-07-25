"""Build A/B voice demos for industrial presentation (dict / LLM / edge / GapGPT).

Usage (from repo root, venv active):

  python scripts/demo_voice_ab.py
  python scripts/demo_voice_ab.py --skip-openai
  python scripts/demo_voice_ab.py --with-llm

Writes MP3s + manifest under ``assets/audio/demo/``.
Does not change production defaults; temporary env overrides only for this process.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from backend.medical_voice_utils import prepare_text_for_tts, tts_to_mp3
from backend.provider_config import openai_compatible_config, provider_status_summary


DEMO_CASES: list[dict[str, str]] = [
    {
        "id": "vitals_spo2",
        "label": "vitals_spo2_peep_etco2_map",
        "text": (
            "بیمار SpO2 برابر ۹۲ درصد، PEEP برابر 8، ETCO2 برابر ۳۵ "
            "و MAP برابر 70 است."
        ),
    },
    {
        "id": "ventilator_short",
        "label": "ventilator_short",
        "text": "بیمار روی FiO2 چهل درصد و PEEP هشت است. RR برابر 18 و TV مناسب است.",
    },
    {
        "id": "natural_reference",
        "label": "natural_reference_style",
        "text": (
            "اشباع اکسیژن بیمار برابر 92 درصد، فشار مثبت انتهای بازدمی برابر 8، "
            "دی اکسید کربن بازدمی برابر 35، و فشار خون متوسط شریانی برابر 70 است."
        ),
    },
]


def _write_mp3(path: Path, audio: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)


def _safe_print(*args: object) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    print(*args)


def main() -> int:
    parser = argparse.ArgumentParser(description="A/B medical voice demo pack")
    parser.add_argument(
        "--out-dir",
        default=str(ROOT / "assets" / "audio" / "demo"),
        help="Directory for MP3 + manifest",
    )
    parser.add_argument(
        "--skip-openai",
        action="store_true",
        help="Only generate edge-tts samples",
    )
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="Also generate GapGPT TTS after SPEECH_NORMALIZE_LLM polish",
    )
    parser.add_argument(
        "--cases",
        default="all",
        help="Comma-separated case ids, or 'all'",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    case_filter = None if args.cases == "all" else {c.strip() for c in args.cases.split(",")}
    cases = [c for c in DEMO_CASES if case_filter is None or c["id"] in case_filter]

    status = provider_status_summary()
    _safe_print("=== provider status ===")
    for k, v in status.items():
        _safe_print(f"  {k}: {v}")

    cfg = openai_compatible_config()
    do_openai = (not args.skip_openai) and cfg.configured
    if not args.skip_openai and not cfg.configured:
        _safe_print("WARN: no API key — skipping openai samples (edge only)")

    manifest: list[dict[str, object]] = []

    for case in cases:
        raw = case["text"]
        label = case["label"]
        dict_text = prepare_text_for_tts(raw, use_llm=False)
        _safe_print(f"\n--- case {label} ---")
        _safe_print(f"raw : {raw}")
        _safe_print(f"dict: {dict_text}")

        # 1) dictionary + edge
        os.environ["TTS_PROVIDER"] = "edge"
        edge_path = out_dir / f"{label}__01_dict_edge.mp3"
        audio = tts_to_mp3(dict_text)
        _write_mp3(edge_path, audio)
        manifest.append(
            {
                "case": label,
                "variant": "01_dict_edge",
                "path": str(edge_path),
                "bytes": len(audio),
                "speech_text": dict_text,
            }
        )
        _safe_print(f"wrote {edge_path.name} ({len(audio)} bytes)")

        if do_openai:
            # 2) dictionary + GapGPT/OpenAI TTS
            os.environ["TTS_PROVIDER"] = "openai"
            oai_path = out_dir / f"{label}__02_dict_openai.mp3"
            audio = tts_to_mp3(dict_text)
            _write_mp3(oai_path, audio)
            manifest.append(
                {
                    "case": label,
                    "variant": "02_dict_openai",
                    "path": str(oai_path),
                    "bytes": len(audio),
                    "speech_text": dict_text,
                }
            )
            _safe_print(f"wrote {oai_path.name} ({len(audio)} bytes)")

            if args.with_llm:
                llm_text = prepare_text_for_tts(raw, use_llm=True)
                _safe_print(f"llm : {llm_text}")
                llm_path = out_dir / f"{label}__03_llm_openai.mp3"
                audio = tts_to_mp3(llm_text)
                _write_mp3(llm_path, audio)
                manifest.append(
                    {
                        "case": label,
                        "variant": "03_llm_openai",
                        "path": str(llm_path),
                        "bytes": len(audio),
                        "speech_text": llm_text,
                    }
                )
                _safe_print(f"wrote {llm_path.name} ({len(audio)} bytes)")

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {"provider_status": status, "samples": manifest},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    readme = out_dir / "LISTEN.txt"
    readme.write_text(
        "\n".join(
            [
                "Voice A/B demo pack",
                "===================",
                "01_dict_edge     = local edge-tts + dictionary/phrasing prep",
                "02_dict_openai   = GapGPT/OpenAI TTS + dictionary/phrasing prep",
                "03_llm_openai    = GapGPT/OpenAI TTS + dictionary + LLM speech polish",
                "",
                "Play on Windows:",
                f'  Invoke-Item "{out_dir}\\*.mp3"',
                "Or open folder and compare 01 → 02 → 03 for the same case label.",
                "",
                "See docs/VOICE_DEMO_CHECKLIST.md for presentation checklist.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _safe_print(f"\nOK — manifest: {manifest_path}")
    _safe_print(f"Open folder: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
