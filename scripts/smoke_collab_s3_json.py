"""Collaborator-style E2E: POST voice → poll S3 {date}/{uuid}.json (like HakimAI)."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

BASE = "http://127.0.0.1:8000"
API_KEY = (os.getenv("API_KEY") or "").strip().strip('"')
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}
TEHRAN = ZoneInfo("Asia/Tehran")


def main() -> int:
    from backend.case_store import output_json_key, tehran_date_str
    from backend.medical_voice_utils import (
        get_json_from_storage,
        persian_to_voice,
        storage_object_exists,
    )

    home = requests.get(f"{BASE}/", timeout=10)
    print("home", home.status_code)
    if home.status_code != 200:
        print("FAIL backend down")
        return 1

    phrase = (
        "بیمار آقای چهل و پنج ساله قد صد و هفتاد و پنج سانتی متر "
        "وزن هشتاد کیلو سه روز ونتیلاتور لوله ای تی تی تب دارد"
    )
    print("making_tts...")
    mp3 = persian_to_voice(phrase, timeout=120)
    print("tts_bytes", len(mp3))

    # Day must match what server assigns at enqueue time (Tehran)
    day_guess = tehran_date_str()
    case_id = f"collab-s3-{uuid.uuid4().hex[:8]}"
    print("case_id", case_id, "day_guess", day_guess)

    r = requests.post(
        f"{BASE}/api/cases",
        headers=HEADERS,
        data={"uuid": case_id},
        files={"file": ("collab.mp3", mp3, "audio/mpeg")},
        timeout=60,
    )
    print("POST /api/cases", r.status_code, r.text[:250])
    if r.status_code >= 400:
        return 1

    # Prefer day from get-msg meta if available; else Tehran today
    json_key = output_json_key(case_id, day_guess)
    print("polling S3 key", json_key)

    found = None
    for i in range(90):
        # Optional status (collaborator may skip this)
        try:
            g = requests.get(
                f"{BASE}/api/get-text",
                headers=HEADERS,
                params={"uuid": case_id},
                timeout=20,
            )
            st = g.json().get("status")
            # If server stored output_json_key with a day, sync key
            # (not exposed in public view currently — use day_guess)
        except Exception:
            st = "?"

        exists = storage_object_exists(json_key)
        print(f"poll {i} get-text={st} s3_exists={exists}")
        if exists:
            found = get_json_from_storage(json_key)
            break
        if st == "failed":
            print("FAIL get-text failed", g.text[:400])
            return 1
        time.sleep(3)

    if not found:
        print("FAIL: S3 JSON never appeared:", json_key)
        return 1

    print("S3_JSON", json.dumps({
        "uuid": found.get("uuid"),
        "status": found.get("status"),
        "text_preview": (found.get("text") or "")[:80],
        "gender": (found.get("fields") or {}).get("gender"),
        "age": (found.get("fields") or {}).get("age"),
        "height_cm": (found.get("fields") or {}).get("height_cm"),
        "weight_kg": (found.get("fields") or {}).get("weight_kg"),
        "ventilator_days": (found.get("fields") or {}).get("ventilator_days"),
        "tube_type": (found.get("fields") or {}).get("tube_type"),
        "fever": (found.get("fields") or {}).get("fever"),
        "found": (found.get("fields") or {}).get("found"),
    }, ensure_ascii=True))

    assert found.get("uuid") == case_id
    assert found.get("text"), "missing text in S3 JSON"
    assert isinstance(found.get("fields"), dict), "missing fields in S3 JSON"
    fields = found["fields"]
    ok = 0
    if fields.get("gender") == "male":
        ok += 1
    if fields.get("age"):
        ok += 1
    if fields.get("height_cm"):
        ok += 1
    if fields.get("tube_type") == "ETT" or fields.get("fever") is True:
        ok += 1
    print("ok_bits", ok)
    if ok < 2:
        print("FAIL weak extract")
        return 1

    print("COLLAB_S3_OK", json_key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
