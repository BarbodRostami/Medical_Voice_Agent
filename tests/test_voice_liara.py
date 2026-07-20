"""Test /voice endpoint with Liara upload."""
import json
import requests

payload = {
    "d0be342f-527f-45d8-9603-1165583a9d38": {
        "tafsir": "بیمار با شوک سپتیک ارائه می‌شود. فشار خون متوسط شریانی ۵۹ میلی‌متر جیوه و لاکتات ۴.۱ است.",
        "recom": "۱. ادامه رژیم ضد میکروبی فعلی. ۲. بهینه‌سازی تنظیمات فشار انتهای بازدمی مثبت."
    }
}

resp = requests.post("http://localhost:8000/voice", json=payload, timeout=120)
print("Status:", resp.status_code)
try:
    data = resp.json()
    print("Response:", json.dumps(data, ensure_ascii=False, indent=2))
except Exception:
    print("Binary response (MP3), size:", len(resp.content), "bytes")
