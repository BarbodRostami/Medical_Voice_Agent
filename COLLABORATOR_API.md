# Collaborator API — HakimAI ↔ Voice Server

Base URL (example): `http://192.168.1.15:8000`

```http
X-API-Key: <from voice-server .env API_KEY>
```

(If `API_KEY` is unset on the voice server, the header is optional.)

**Rule:** send **either** text **or** audio — never both.

---

## Mode A — Text → Voice (TTS)

HakimAI triggers TTS; **downloads the MP3 from S3 itself** (not from the voice API).

### 1) Start job

```http
POST /api/ask
Content-Type: application/json
X-API-Key: ...

{"uuid": "ext-1001", "text": "متن فارسی اینجا"}
```

Immediate response:

```json
{
  "uuid": "ext-1001",
  "status": "queued",
  "mode": "text",
  "s3_endpoint": "https://sas.amin.parminstorage.ir",
  "s3_bucket": "voiceai",
  "s3_key": "cases/ext-1001/output/reply.mp3",
  "s3_key_legacy": "audio/ext-1001.mp3"
}
```

### 2) HakimAI polls S3 (like `voice_storage.py`)

Voice server uploads **MP3** to both keys when ready:

| Key | Purpose |
|-----|---------|
| `cases/{uuid}/output/reply.mp3` | canonical (`s3_key`) |
| `audio/{uuid}.mp3` | legacy / voice_storage-style (`s3_key_legacy`) |

HakimAI: `HeadObject` / `GetObject` on that key until the file exists, then download.  
Do **not** pull audio bytes through the voice API for this mode.

S3 credentials for HakimAI: same Parmin bucket (`LIARA_*` / `S3_*` equivalent) — separate from `X-API-Key`.

---

## Mode B — Voice → Text (STT)

### 1) Upload audio to voice server

```bash
curl -X POST "http://192.168.1.15:8000/api/cases" \
  -H "X-API-Key: YOUR_KEY" \
  -F "uuid=ext-1002" \
  -F "file=@question.wav"
```

Immediate: `{"uuid","status":"queued","mode":"audio"}`

Pipeline on voice server: STT → RAG → Persian text (**no TTS** — lighter load).

### 2) HakimAI gets text via API

```http
GET /api/get-msg?uuid=ext-1002
X-API-Key: ...
```

(or `GET /api/cases/ext-1002`)

When ready:

```json
{
  "uuid": "ext-1002",
  "status": "ready",
  "mode": "audio",
  "text": "پاسخ فارسی برای نمایش",
  "transcript": "متن تشخیص‌داده‌شده از ویس کاربر",
  "answer": "پاسخ فارسی برای نمایش",
  "error": null
}
```

HakimAI stores/displays `text` (or `answer`). Poll until `status` is `ready` or `failed`.

---

## Status values

`queued` | `processing` | `ready` | `failed`

---

## What to share with HakimAI

1. Voice API base URL + `API_KEY`
2. S3 endpoint / bucket / access+secret (for TTS poll/download only)
3. This document — keys: `cases/{uuid}/output/reply.mp3` and `audio/{uuid}.mp3`
