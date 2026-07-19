# Collaborator API (External Server ↔ Voice Server)

Use this when the company **external server** talks to the **voice server**.
Cases are keyed by **your** `uuid`. Audio lands in Parmin S3; you usually poll our API and download via `audio_url`.

Base URL (example): `http://192.168.1.15:8000`

Auth: send header on every call except health and audio playback:

```http
X-API-Key: <value from voice-server .env API_KEY>
```

---

## Rules

1. Send **either** text **or** audio — never both (server capacity).
2. Creating a case is async: you get `queued` immediately.
3. Poll until `status` is `ready` or `failed`.
4. Download MP3 from `audio_url` (public proxy; no API key required for GET audio).

S3 layout (Parmin bucket, managed by voice server):

```text
cases/{uuid}/meta.json
cases/{uuid}/input/text.json          # text mode
cases/{uuid}/input/audio.<ext>        # audio mode
cases/{uuid}/output/reply.mp3         # final file
```

You do **not** need S3 credentials; use the HTTP API + `audio_url`.

---

## 1) Text → voice

`POST /api/cases` or alias `POST /api/ask`

```http
POST /api/ask
Content-Type: application/json
X-API-Key: ...

{"uuid": "ext-1001", "text": "تفسیر بالینی بیمار پایدار است."}
```

Response:

```json
{
  "uuid": "ext-1001",
  "status": "queued",
  "mode": "text",
  "message": "..."
}
```

Pipeline: TTS only → upload `cases/{uuid}/output/reply.mp3`.

---

## 2) Voice only (empty text)

`POST /api/cases` as `multipart/form-data`:

| field | value |
|-------|--------|
| `uuid` | your case id |
| `file` | audio (wav/mp3/ogg/m4a) |
| `text` | omit or empty |

```bash
curl -X POST "http://192.168.1.15:8000/api/cases" \
  -H "X-API-Key: YOUR_KEY" \
  -F "uuid=ext-1002" \
  -F "file=@question.wav"
```

Pipeline: STT → RAG → TTS → same output key (heavier; keep traffic modest).

---

## 3) Get result by uuid

```http
GET /api/cases/ext-1001
X-API-Key: ...
```

Alias:

```http
GET /api/get-msg?uuid=ext-1001
X-API-Key: ...
```

When ready:

```json
{
  "uuid": "ext-1001",
  "status": "ready",
  "mode": "text",
  "audio_url": "http://192.168.1.15:8000/voice/audio/cases/ext-1001/output/reply.mp3",
  "transcript": null,
  "answer": null,
  "error": null
}
```

Statuses: `queued` | `processing` | `ready` | `failed`

---

## What to give the external-server team

1. Base URL: `PUBLIC_API_URL` (e.g. `http://192.168.1.15:8000`)
2. Shared `API_KEY` (rotate if leaked)
3. This document
4. OpenAPI: `http://192.168.1.15:8000/docs` (also requires API key when enabled)

They should **not** need `LIARA_*` / S3 keys for normal integration.
