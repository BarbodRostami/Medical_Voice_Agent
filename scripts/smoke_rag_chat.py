"""Live RAG chat smoke against local API (uses GapGPT when LLM_PROVIDER=openai)."""
from __future__ import annotations

import json
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

base = os.getenv("PUBLIC_API_URL", "http://127.0.0.1:8000").rstrip("/")
# Prefer loopback for local smoke
base = "http://127.0.0.1:8000"
api_key = (os.getenv("API_KEY") or "").strip().strip('"')
headers = {"Content-Type": "application/json"}
if api_key:
    headers["X-API-Key"] = api_key

home = requests.get(f"{base}/", timeout=10)
print("home", home.status_code, json.dumps(home.json(), ensure_ascii=True))

r = requests.post(
    f"{base}/chat",
    headers=headers,
    json={"query": "What is the normal SpO2 range for adults?"},
    timeout=180,
)
print("chat_status", r.status_code)
try:
    data = r.json()
except Exception:
    print(r.text[:500])
    sys.exit(1)

answer = (data.get("answer") or "")[:500]
print("cached", data.get("cached"))
print("sources", data.get("source_documents_count"))
print("answer_preview", answer.encode("ascii", "replace").decode("ascii"))
sys.exit(0 if r.status_code == 200 and answer else 1)
