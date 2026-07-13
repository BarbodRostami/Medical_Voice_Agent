"""
Quick demo for the async job queue endpoints.
Run after server is up: python test_jobs.py
"""
from __future__ import annotations

import time
import requests

BASE = "http://localhost:8000"


def wait_for_job(job_id: str, max_wait: int = 300) -> dict:
    """Poll GET /jobs/{job_id} until done or failed."""
    start = time.time()
    while time.time() - start < max_wait:
        r = requests.get(f"{BASE}/jobs/{job_id}", timeout=10)
        data = r.json()
        status = data["status"]
        print(f"  [{int(time.time()-start):>3}s] status={status:12} | {data['message']}")
        if status in ("done", "failed"):
            return data
        time.sleep(3)
    return {"status": "timeout"}


def test_chat_job():
    print("\n══════════════════════════════════════════")
    print("TEST 1: POST /jobs/chat  (RAG → TTS → S3)")
    print("══════════════════════════════════════════")
    payload = {"query": "What is the normal ETCO2 range in capnography?"}
    r = requests.post(f"{BASE}/jobs/chat", json=payload, timeout=10)
    print(f"Immediate response ({r.status_code}): {r.json()}")
    job_id = r.json()["job_id"]
    result = wait_for_job(job_id)
    print("\nFinal result:")
    for k, v in result.items():
        if k not in ("answer",):
            print(f"  {k}: {v}")
    if result.get("answer"):
        print(f"  answer (first 120 chars): {result['answer'][:120]}...")


def test_voice_report_job():
    print("\n══════════════════════════════════════════")
    print("TEST 2: POST /jobs/voice-report  (Persian TTS → S3)")
    print("══════════════════════════════════════════")
    payload = {
        "d0be342f-527f-45d8-9603-1165583a9d38": {
            "tafsir": "بیمار با فشار خون پایین و لاکتات بالا مشخص می‌شود.",
            "recom": "ادامه رژیم ضد میکروبی و نظارت دقیق بر عملکرد کلیوی.",
        }
    }
    r = requests.post(f"{BASE}/jobs/voice-report", json=payload, timeout=10)
    print(f"Immediate response ({r.status_code}): {r.json()}")
    job_id = r.json()["job_id"]
    result = wait_for_job(job_id)
    print(f"\nFinal result: status={result['status']}, audio_url={result.get('audio_url')}")


if __name__ == "__main__":
    # Check server is alive
    try:
        r = requests.get(f"{BASE}/", timeout=5)
        print(f"Server OK: {r.json()['message']}")
    except Exception as e:
        print(f"Server not ready: {e}")
        exit(1)

    test_chat_job()
    test_voice_report_job()

    print("\n══════════════════════════════════════════")
    print("TEST 3: GET /jobs  (list all jobs)")
    print("══════════════════════════════════════════")
    r = requests.get(f"{BASE}/jobs", timeout=5)
    all_jobs = r.json()
    print(f"Total jobs in memory: {all_jobs['total']}")
    for jid, jdata in all_jobs["jobs"].items():
        print(f"  {jid[:8]}...  status={jdata['status']}")
