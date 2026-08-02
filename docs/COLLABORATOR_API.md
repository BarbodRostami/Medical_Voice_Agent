# Collaborator API — HakimAI ↔ Voice Server

Base URL (example laptop LAN): `http://192.168.1.235:8000`

```http
X-API-Key: <from voice-server .env API_KEY>
```

**Rule:** send **either** text **or** audio — never both.

API responses do **not** include `s3_bucket` / `s3_key`. HakimAI already has S3 credentials.

Browser `audio_url` fields (if used by other clients) may include short-lived `exp`+`sig` query params when the voice server has `API_KEY` set. HakimAI should keep polling S3 — not `/voice/audio`.

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

TTS engine is internal to the voice server. Default is local `edge-tts`. Optional cloud TTS via `TTS_PROVIDER=openai` + API key (`OPENAI_API_KEY` / `GAPGPT_API_KEY`, optional `OPENAI_BASE_URL` for GapGPT); on missing key or any API error the server falls back to edge. STT defaults to local Whisper (`STT_PROVIDER=local`); optional `STT_PROVIDER=openai` uses cloud transcriptions with the same key/base and falls back to local Whisper. Speech-prep (abbreviations + `TTS_DIGIT_MODE`, optional `SPEECH_NORMALIZE_LLM`) runs before every TTS provider. HakimAI contract (JSON + S3 key) does not change.

---

## Mode B — Voice → Text (STT) + structured fields

HakimAI owns medical reasoning. The voice server transcribes speech to Persian text
and **also** returns a structured ``fields`` JSON for patient-tab form fill.

Legacy clients are unchanged: keep reading ``text`` / ``transcript`` / ``answer``.
New clients may additionally read ``fields``.

STT uses Whisper (`WHISPER_MODEL_SIZE`, default `medium`) with a Persian medical + digits prompt and stronger beam search. Prefer clean WAV / 16 kHz mono from the client when possible.

```bash
curl -X POST "http://192.168.1.235:8000/api/cases" \
  -H "X-API-Key: YOUR_KEY" \
  -F "uuid=ext-1002" \
  -F "file=@question.wav"
```

Then poll:

```http
GET /api/get-msg?uuid=ext-1002
```

When `status=ready`:

```json
{
  "uuid": "ext-1002",
  "status": "ready",
  "mode": "audio",
  "text": "بیمار آقای چهل و پنج ساله قد صد و هفتاد و پنج ...",
  "transcript": "...همان متن...",
  "answer": "...همان متن...",
  "fields": {
    "gender": "male",
    "age": 45,
    "height_cm": 175,
    "weight_kg": null,
    "ibw_kg": 70.1,
    "ventilator_days": null,
    "tube_type": null,
    "indication": null,
    "rass": null,
    "covid_status": null,
    "main_diagnosis": null,
    "diagnosis_category": null,
    "sedation_active": null,
    "recent_surgery": null,
    "fever": null,
    "secretion_intensity": null,
    "cxr_summary": null,
    "consultation_goal": null,
    "found": ["gender", "age", "height_cm", "ibw_kg"],
    "missing": ["weight_kg", "ventilator_days"],
    "raw_text": "...",
    "extract_version": "patient-tab-v1",
    "schema_keys": ["gender", "age", "height_cm", "..."]
  }
}
```

- **`text` / `transcript` / `answer`**: full free-text transcript (backward compatible)
- **`fields`**: structured extract for form widgets (`null` = not heard). Use `fields.age`, `fields.gender`, …
- Ignore `null` while `queued` / `processing`

---

## What to share with HakimAI

1. Voice API base URL + `API_KEY`
2. S3 endpoint / bucket / keys (for TTS download only)
3. Poll formula: `{tehran_date}/{uuid}.mp3`
4. For voice: poll `GET /api/get-msg` until `status=ready`, then read `text` (and optionally `fields`)
