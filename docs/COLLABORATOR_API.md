# Collaborator API — HakimAI ↔ Voice Server

Base URL (example laptop LAN): `http://192.168.1.235:8000`

```http
X-API-Key: <from voice-server .env API_KEY>
```

**Rule:** send **either** text **or** audio — never both.

For audio, HakimAI may either upload the file in the POST, **or** pre-upload to shared S3 and POST **uuid only**.

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

## Mode B — Voice → JSON on S3 (STT + structured fields)

Same S3 collaboration pattern as Mode A (TTS MP3), but the pollable object is JSON.

HakimAI owns medical reasoning / form UI. The voice server:

1. Accepts audio via ``POST /api/cases`` (multipart file **or** uuid-only after S3 pre-upload)
2. Runs Whisper STT
3. Extracts patient-tab fields
4. Uploads result to S3 for HakimAI to poll

### 1a) Start job — multipart file

```bash
curl -X POST "http://192.168.1.235:8000/api/cases" \
  -H "X-API-Key: YOUR_KEY" \
  -F "uuid=ext-1002" \
  -F "file=@question.wav"
```

### 1b) Start job — S3 pre-upload + uuid only (HakimAI preferred)

1. HakimAI uploads audio to the shared bucket at:

```text
cases/{uuid}/input/audio.webm
```

(also accepted: `.wav`, `.mp3`, `.m4a`, `.ogg`, …)

2. Then notify the voice server (no file in the body):

```bash
curl -X POST "http://192.168.1.235:8000/api/cases" \
  -H "X-API-Key: YOUR_KEY" \
  -F "uuid=ext-1002"
```

If the object is missing → `404`.

Immediate response (both 1a and 1b):

```json
{"uuid": "ext-1002", "status": "queued", "mode": "audio"}
```

### 2) HakimAI polls S3

Voice server uploads JSON to:

```text
{YYYY-MM-DD}/{uuid}.json
```

- Date = **Asia/Tehran** calendar day when the job was accepted  
- Example: `2026-08-02/ext-1002.json`

Poll with `HeadObject` / `GetObject` until the object exists, then download.

JSON body example:

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

- **`text` / `transcript` / `answer`**: full free-text transcript (legacy-compatible)
- **`fields`**: structured extract for form widgets (`null` = not heard)
  - Patient tab keys (unchanged): `gender`, `age`, `height_cm`, `weight_kg`, …
  - Settings tab (ventilator) additive keys: `ventilator_mode`, `peep_cmh2o`, `fio2_pct`,
    `vt_set_ml`, `rr_set_bpm`, `pi_cmh2o`, `ps_cmh2o`, `p_hi_cmh2o`, `p_lo_cmh2o`,
    `t_hi_sec`, `t_lo_sec`, `ti_max_sec`, `cycle_criteria_pct`, `rise_time_sec`,
    `trigger_sensitivity_lpm`
  - Measurement tab additive keys: `rr_total_bpm`, `rr_spontaneous_bpm`, `vte_ml`,
    `peak_pressure_cmh2o`, `plateau_pressure_cmh2o`, `peep_measured_cmh2o`,
    `auto_peep_cmh2o`, `mean_pressure_cmh2o`, `driving_pressure_cmh2o`, `ie_ratio`,
    `minute_ventilation_lpm`, `compliance_static`, `compliance_dynamic`, `rsbi`,
    `leak_pct`, …
  - ABG tab additive keys: `ph`, `paco2_mmhg`, `pao2_mmhg`, `sao2_pct`,
    `hco3_meq_l`, `base_excess_meq_l`, `pf_ratio` (computed = PaO2 / FiO2 fraction)
  - Computed helpers (same idea as `ibw_kg`): `vt_ibw_ml_kg` from VTe+IBW;
    `pf_ratio` from PaO2 + `fio2_pct`
  - `ventilator_mode` values match HakimAI dropdown:
    `VCV` | `PCV` | `SIMV-V` | `SIMV-P` | `PSV/CPAP` | `APRV` | `PRVC`
  - Full key list is always in `fields.schema_keys`

### Status poll (choose the right endpoint)

| Endpoint | Use |
|----------|-----|
| `GET /api/get-msg?uuid=...` | **Legacy Behin** — text / transcript / answer / status only (**no `fields`**) |
| `GET /api/get-text?uuid=...` | **New form-fill** — same text + **`fields`** (+ `output_json_key` when ready) |

```http
GET /api/get-text?uuid=ext-1002
X-API-Key: ...
```

When `status=ready`, read `fields` for the form. Not required if you only poll S3 JSON.

STT uses Whisper (`WHISPER_MODEL_SIZE`, default `medium`) with a Persian medical + digits prompt.

---

## What to share with HakimAI

1. Voice API base URL + `API_KEY` (current laptop LAN example: `http://192.168.1.239:8000`)
2. S3 endpoint / bucket / keys
3. TTS poll: `{tehran_date}/{uuid}.mp3`
4. STT poll: `{tehran_date}/{uuid}.json` (contains `text` + `fields`)
5. Legacy status: `GET /api/get-msg?uuid=...` (text only)
6. New form status: `GET /api/get-text?uuid=...` (text + `fields`)

If the laptop IP changes or collaborator cannot reach you while your proxy is ON, on the voice-server PC run:

```powershell
.\scripts\ensure_lan_collaborator_access.ps1 -RestartApi
```

That opens firewall TCP 8000 on all profiles, adds LAN to proxy bypass (proxy stays ON for GapGPT), and refreshes `PUBLIC_API_URL`.
