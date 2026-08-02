"""Live smoke: new get-text has fields; legacy get-msg stays text-only."""
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
    home = requests.get(f"{BASE}/", timeout=10)
    print("home", home.status_code, json.dumps(home.json(), ensure_ascii=True)[:200])
    if home.status_code != 200:
        print("FAIL: backend not up")
        return 1

    from backend.medical_voice_utils import persian_to_voice

    phrase = (
        "بیمار آقای چهل و پنج ساله قد صد و هفتاد و پنج سانتی متر "
        "وزن هشتاد کیلو سه روز ونتیلاتور لوله ای تی تی تب دارد"
    )
    print("tts_phrase_ok")
    mp3 = persian_to_voice(phrase, timeout=120)
    print("tts_bytes", len(mp3))

    case_id = f"smoke-fields-{uuid.uuid4().hex[:8]}"
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

    ready = None
    for i in range(60):
        g = requests.get(
            f"{BASE}/api/get-text",
            headers=HEADERS,
            params={"uuid": case_id},
            timeout=30,
        )
        data = g.json()
        status = data.get("status")
        print(f"poll {i} get-text status={status}")
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
                "found": fields.get("found"),
            },
            ensure_ascii=True,
        ),
    )
    if not text:
        print("FAIL: missing text on get-text")
        return 1
    if not isinstance(fields, dict) or not fields.get("age"):
        print("FAIL: missing fields on get-text")
        return 1

    legacy = requests.get(
        f"{BASE}/api/get-msg",
        headers=HEADERS,
        params={"uuid": case_id},
        timeout=30,
    ).json()
    if "fields" in legacy:
        print("FAIL: get-msg must stay legacy (no fields)", list(legacy.keys()))
        return 1
    if not legacy.get("text"):
        print("FAIL: get-msg missing text")
        return 1
    print("legacy_get_msg_ok keys=", sorted(legacy.keys()))
    print("SMOKE_GET_TEXT_OK", case_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
