"""Pre-deploy smoke test — run all critical endpoints and report pass/fail."""
from __future__ import annotations

import asyncio
import sys
import time

import edge_tts
import requests

from backend.api_auth import request_headers

BASE = "http://localhost:8000"
POLL_INTERVAL = 5
MAX_WAIT = 300
VENV_PYTHON = sys.executable


def poll_job(job_id: str) -> dict:
    start = time.time()
    while time.time() - start < MAX_WAIT:
        r = requests.get(f"{BASE}/jobs/{job_id}", headers=request_headers(), timeout=10)
        r.raise_for_status()
        data = r.json()
        if data["status"] in ("done", "failed"):
            return data
        time.sleep(POLL_INTERVAL)
    return {"status": "timeout", "job_id": job_id}


def ok(label: str, passed: bool, detail: str = "") -> bool:
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    return passed


def main() -> int:
    results: list[bool] = []
    print("=" * 50)
    print("PRE-DEPLOY SMOKE TEST")
    print("=" * 50)

    # 1. Health
    print("\n[1] Health check")
    try:
        r = requests.get(f"{BASE}/", timeout=10)
        data = r.json()
        results.append(ok("GET / returns 200", r.status_code == 200))
        results.append(ok("db_loaded=true", data.get("db_loaded") is True, str(data.get("db_loaded"))))
    except Exception as e:
        results.append(ok("GET /", False, str(e)))

    # 2. Routes
    print("\n[2] API routes")
    required = {"/jobs/chat", "/jobs/voice-report", "/stt/ask", "/jobs/{job_id}"}
    try:
        paths = set(requests.get(f"{BASE}/openapi.json", timeout=10).json()["paths"].keys())
        for route in ["/jobs/chat", "/jobs/voice-report", "/stt/ask", "/jobs/{job_id}"]:
            results.append(ok(f"Route {route}", route in paths))
    except Exception as e:
        results.append(ok("OpenAPI routes", False, str(e)))

    # 3. voice-report job
    print("\n[3] POST /jobs/voice-report")
    try:
        payload = {
            "test-uuid": {
                "tafsir": "بیمار با فشار خون پایین مشخص می‌شود.",
                "recom": "ادامه مانیتورینگ.",
            }
        }
        r = requests.post(
            f"{BASE}/jobs/voice-report",
            json=payload,
            headers=request_headers(),
            timeout=15,
        )
        data = r.json()
        results.append(ok("Submit returns 200", r.status_code == 200))
        results.append(ok("Returns job_id", "job_id" in data))
        if "job_id" in data:
            print(f"      polling {data['job_id'][:8]}...")
            final = poll_job(data["job_id"])
            results.append(ok("Job reaches done", final.get("status") == "done", final.get("status", "")))
            if final.get("status") == "failed":
                results.append(ok("No error", False, final.get("error", "")))
    except Exception as e:
        results.append(ok("voice-report", False, str(e)))

    # 4. chat job
    print("\n[4] POST /jobs/chat")
    try:
        r = requests.post(
            f"{BASE}/jobs/chat",
            json={"query": "What is the normal SpO2 range?"},
            headers=request_headers(),
            timeout=15,
        )
        data = r.json()
        results.append(ok("Submit returns 200", r.status_code == 200))
        if "job_id" in data:
            print(f"      polling {data['job_id'][:8]}...")
            final = poll_job(data["job_id"])
            results.append(ok("Job reaches done", final.get("status") == "done", final.get("status", "")))
            answer = final.get("answer") or ""
            has_persian = any("\u0600" <= c <= "\u06ff" for c in answer)
            results.append(ok("answer is Persian", has_persian, answer[:80] if answer else "empty"))
            results.append(ok("answer_en present", bool(final.get("answer_en")), ""))
    except Exception as e:
        results.append(ok("jobs/chat", False, str(e)))

    # 5. STT Persian
    print("\n[5] POST /stt/ask (Persian audio)")
    try:
        async def make_audio() -> None:
            comm = edge_tts.Communicate(
                "محدوده طبیعی اشباع اکسیژن چقدر است؟",
                voice="fa-IR-DilaraNeural",
            )
            await comm.save("_predeploy_stt.mp3")

        asyncio.run(make_audio())
        with open("_predeploy_stt.mp3", "rb") as f:
            r = requests.post(
                f"{BASE}/stt/ask",
                files={"file": ("q.mp3", f, "audio/mpeg")},
                headers=request_headers(),
                timeout=15,
            )
        data = r.json()
        results.append(ok("Submit returns 200", r.status_code == 200))
        if "job_id" in data:
            print(f"      polling {data['job_id'][:8]}... (may take 2-3 min)")
            final = poll_job(data["job_id"])
            results.append(ok("Job reaches done", final.get("status") == "done", final.get("status", "")))
            trans = final.get("transcription") or ""
            answer = final.get("answer") or ""
            results.append(ok("transcription present", len(trans) > 5, trans[:60]))
            results.append(ok("answer is Persian", any("\u0600" <= c <= "\u06ff" for c in answer), answer[:80]))
    except Exception as e:
        results.append(ok("stt/ask", False, str(e)))

    # Summary
    passed = sum(results)
    total = len(results)
    print("\n" + "=" * 50)
    print(f"RESULT: {passed}/{total} checks passed")
    print("=" * 50)
    if passed == total:
        print("All tests passed — ready for company server deploy.")
        return 0
    print("Some tests failed — fix before deploy.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
