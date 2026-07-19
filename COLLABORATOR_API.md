# Collaborator API — HakimAI ↔ Voice Server

Base URL (example laptop LAN): `http://192.168.1.235:8000`

```http
X-API-Key: <from voice-server .env API_KEY>
```

**Rule:** send **either** text **or** audio — never both.

API responses do **not** include `s3_bucket` / `s3_key`. HakimAI already has S3 credentials.

---

## Mode A — Text → Voice (TTS)

### 1) Start job

```http
POST /api/ask
Content-Type: application/json
X-API-Key: ...

{"uuid": "d8f364c9-96da-4d92-a7f2-842389c02093", "text": "متن فارسی اینجا"}
```

Immediate response (no S3 secrets):

```json
{"uuid": "...", "status": "queued", "mode": "text"}
```

### 2) HakimAI polls S3

Voice server uploads MP3 to:

```text
{YYYY-MM-DD}/{uuid}.mp3
```

- Date = **Asia/Tehran** calendar day when the job was accepted  
- Example: `2026-07-19/d8f364c9-96da-4d92-a7f2-842389c02093.mp3`

Poll with `HeadObject` / `GetObject` until the object exists, then download.

Optional status check (not required for S3 poll):

```http
GET /api/get-msg?uuid=...
```

`status`: `queued` | `processing` | `ready` | `failed`

---

## Mode B — Voice → Text (STT)

```bash
curl -X POST "http://192.168.1.235:8000/api/cases" \
  -H "X-API-Key: YOUR_KEY" \
  -F "uuid=ext-1002" \
  -F "file=@question.wav"
```

Then:

```http
GET /api/get-msg?uuid=ext-1002
```

When `status=ready`, use `text` / `answer` / `transcript`.

---

## What to share with HakimAI

1. Voice API base URL + `API_KEY`
2. S3 endpoint / bucket / keys (for TTS download only)
3. Poll formula: `{tehran_date}/{uuid}.mp3`
