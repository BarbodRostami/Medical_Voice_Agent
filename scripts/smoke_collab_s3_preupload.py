"""Collaborator E2E: upload audio to S3 ourselves, POST uuid only, poll get-text + S3 JSON."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

BASE = "http://127.0.0.1:8000"
API_KEY = (os.getenv("API_KEY") or "").strip().strip('"')
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}


def main() -> int:
    from backend.case_store import input_audio_key, output_json_key, tehran_date_str
    from backend.medical_voice_utils import (
        get_json_from_storage,
        persian_to_voice,
        put_storage_object,
        storage_object_exists,
    )

    home = requests.get(f"{BASE}/", timeout=10)
    print("home", home.status_code)
    if home.status_code != 200:
        print("FAIL backend down — start: python -m backend.main_api")
        return 1

    phrase = (
        "بیمار آقای چهل و پنج ساله قد صد و هفتاد و پنج سانتی متر "
        "وزن هشتاد کیلو سه روز ونتیلاتور لوله ای تی تی تب دارد"
    )
    print("making_tts...")
    mp3 = persian_to_voice(phrase, timeout=120)
    print("tts_bytes", len(mp3))

    case_id = f"collab-pre-{uuid.uuid4().hex[:8]}"
    day = tehran_date_str()
    input_key = input_audio_key(case_id, ".mp3")
    print("case_id", case_id)
    print("uploading_input", input_key)

    put_storage_object(input_key, mp3, "audio/mpeg")
    if not storage_object_exists(input_key):
        print("FAIL: input audio not visible on S3 after put")
        return 1
    print("s3_input_ok")

    # Collaborator contract: uuid only (no file)
    r = requests.post(
        f"{BASE}/api/cases",
        headers=HEADERS,
        data={"uuid": case_id},
        timeout=60,
    )
    print("POST /api/cases (uuid-only)", r.status_code, r.text[:300])
    if r.status_code >= 400:
        return 1

    json_key = output_json_key(case_id, day)
    print("polling get-text + S3", json_key)

    found = None
    last_status = "?"
    for i in range(90):
        try:
            g = requests.get(
                f"{BASE}/api/get-text",
                headers=HEADERS,
                params={"uuid": case_id},
                timeout=20,
            )
            body = g.json()
            last_status = body.get("status")
        except Exception as e:
            body = {}
            last_status = f"err:{e}"

        exists = storage_object_exists(json_key)
        print(f"poll {i} get-text={last_status} s3_exists={exists}")
        if last_status == "ready" and body.get("text"):
            print(
                "GET_MSG_READY",
                json.dumps(
                    {
                        "text_preview": (body.get("text") or "")[:80],
                        "age": (body.get("fields") or {}).get("age"),
                        "gender": (body.get("fields") or {}).get("gender"),
                    },
                    ensure_ascii=True,
                ),
            )
        if exists:
            found = get_json_from_storage(json_key)
            break
        if last_status == "failed":
            print("FAIL get-text failed", json.dumps(body, ensure_ascii=True)[:400])
            return 1
        time.sleep(3)

    if not found:
        print("FAIL: S3 JSON never appeared:", json_key)
        return 1

    print(
        "S3_JSON",
        json.dumps(
            {
                "uuid": found.get("uuid"),
                "status": found.get("status"),
                "text_preview": (found.get("text") or "")[:100],
                "gender": (found.get("fields") or {}).get("gender"),
                "age": (found.get("fields") or {}).get("age"),
                "height_cm": (found.get("fields") or {}).get("height_cm"),
                "weight_kg": (found.get("fields") or {}).get("weight_kg"),
                "found": (found.get("fields") or {}).get("found"),
            },
            ensure_ascii=True,
        ),
    )

    assert found.get("uuid") == case_id
    assert found.get("text"), "missing text"
    assert isinstance(found.get("fields"), dict)
    fields = found["fields"]
    ok = sum(
        [
            fields.get("gender") == "male",
            bool(fields.get("age")),
            bool(fields.get("height_cm")),
            fields.get("tube_type") == "ETT" or fields.get("fever") is True,
        ]
    )
    print("ok_bits", ok)
    if ok < 2:
        print("FAIL weak extract")
        return 1

    print("COLLAB_S3_PREUPLOAD_OK", json_key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
