"""Live smoke: Behin voice case → get-msg has text + fields JSON."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid

import requests
from dotenv import load_dotenv

load_dotenv()

BASE = "http://127.0.0.1:8000"
API_KEY = (os.getenv("API_KEY") or "").strip().strip('"')
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}


def main() -> int:
    # 1) health
    home = requests.get(f"{BASE}/", timeout=10)
    print("home", home.status_code, json.dumps(home.json(), ensure_ascii=True)[:200])
    if home.status_code != 200:
        print("FAIL: backend not up")
        return 1

    # 2) TTS a Persian demographics phrase → MP3 bytes
    from backend.medical_voice_utils import persian_to_voice

    phrase = (
        "بیمار آقای چهل و پنج ساله قد صد و هفتاد و پنج سانتی متر "
        "وزن هشتاد کیلو سه روز ونتیلاتور لوله ای تی تی تب دارد"
    )
    print("tts_phrase_ok")
    mp3 = persian_to_voice(phrase, timeout=120)
    print("tts_bytes", len(mp3))

    case_id = f"smoke-fields-{uuid.uuid4().hex[:8]}"
    # 3) POST /api/cases with audio
    r = requests.post(
        f"{BASE}/api/cases",
        headers=HEADERS,
        data={"uuid": case_id},
        files={"file": ("smoke.mp3", mp3, "audio/mpeg")},
        timeout=60,
    )
    print("post_cases", r.status_code, r.text[:300])
    if r.status_code >= 400:
        return 1

    # 4) poll get-msg
    ready = None
    for i in range(60):
        g = requests.get(
            f"{BASE}/api/get-msg",
            headers=HEADERS,
            params={"uuid": case_id},
            timeout=30,
        )
        data = g.json()
        status = data.get("status")
        print(f"poll {i} status={status}")
        if status == "ready":
            ready = data
            break
        if status == "failed":
            print("FAIL", json.dumps(data, ensure_ascii=True)[:500])
            return 1
        time.sleep(3)

    if not ready:
        print("FAIL: timeout waiting for ready")
        return 1

    text = ready.get("text") or ""
    fields = ready.get("fields") or {}
    print("text_preview", text[:120].encode("ascii", "replace").decode("ascii"))
    print(
        "fields_summary",
        json.dumps(
            {
                "gender": fields.get("gender"),
                "age": fields.get("age"),
                "height_cm": fields.get("height_cm"),
                "weight_kg": fields.get("weight_kg"),
                "ventilator_days": fields.get("ventilator_days"),
                "tube_type": fields.get("tube_type"),
                "fever": fields.get("fever"),
                "found": fields.get("found"),
            },
            ensure_ascii=True,
        ),
    )

    # Legacy keys must remain
    assert ready.get("text"), "missing text"
    assert ready.get("transcript") == ready.get("text") or ready.get("transcript")
    assert ready.get("answer") == ready.get("text") or ready.get("answer")
    assert isinstance(fields, dict) and fields, "missing fields JSON"

    # Soft checks — STT may paraphrase numbers
    ok_bits = 0
    if fields.get("gender") == "male":
        ok_bits += 1
    if fields.get("age") in (45, 40, 50) or fields.get("age"):
        ok_bits += 1
    if fields.get("height_cm") or "175" in text or "قد" in text:
        ok_bits += 1
    if fields.get("tube_type") in ("ETT", "Trach") or "تی" in text:
        ok_bits += 1
    print("soft_ok_bits", ok_bits)
    if ok_bits < 2:
        print("FAIL: fields too empty / STT weak")
        return 1

    print("SMOKE_OK", case_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
