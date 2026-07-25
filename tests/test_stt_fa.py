"""Test Persian voice input: user speaks Farsi → gets Farsi answer"""
import asyncio
import time

import edge_tts
import requests

from backend.api_auth import request_headers

BASE = "http://localhost:8000"

# Step 1: generate a Persian question as test audio
async def make_persian_audio():
    comm = edge_tts.Communicate(
        "محدوده طبیعی دی اکسید کربن بازدمی در کاپنوگرافی چقدر است؟",
        voice="fa-IR-DilaraNeural",
    )
    await comm.save("test_persian_input.mp3")

print("ساخت فایل صوتی فارسی...")
asyncio.run(make_persian_audio())
print("test_persian_input.mp3 ساخته شد.")

# Step 2: submit
print("\nارسال به POST /stt/ask ...")
with open("test_persian_input.mp3", "rb") as f:
    r = requests.post(
        f"{BASE}/stt/ask",
        files={"file": ("persian.mp3", f, "audio/mpeg")},
        headers=request_headers(),
        timeout=15,
    )

print(f"پاسخ فوری ({r.status_code}):", r.json())
job_id = r.json()["job_id"]
print(f"Job ID: {job_id[:8]}...")

# Step 3: poll
print("\nبررسی وضعیت...")
for i in range(80):
    time.sleep(5)
    s = requests.get(f"{BASE}/jobs/{job_id}", headers=request_headers(), timeout=5).json()
    status = s["status"]
    msg = s["message"]
    print(f"[{(i+1)*5:>3}s] {status:12} | {msg}")
    if status in ("done", "failed"):
        print("\n══════════ نتیجه نهایی ══════════")
        print("متن تشخیص داده شده (فارسی):", s.get("transcription"))
        if s.get("answer"):
            print("پاسخ (فارسی):", s["answer"][:300])
        print("audio_url:", s.get("audio_url"))
        if s.get("error"):
            print("خطا:", s["error"])
        break
