# Voice Form Fill — ICU Persian Voice Agent (Experiment)

> A production-quality voice-to-structured-form system for Persian-speaking ICU clinicians.  
> Speaks → Transcribes → Extracts → Fills structured medical form automatically.

---

## Demo

<!-- Place a screenshot at assets/demo_lab.png to display it here -->
<!-- ![ICU Voice Form Fill Demo](../../assets/demo_lab.png) -->

> **Result:** All 20 lab fields (Hb, Hct, WBC, Platelets, Na, K, Ca, Mg, Phosphate, BUN,  
> Creatinine, Albumin, AST, ALT, Bilirubin, CRP, Procalcitonin, Glucose, ESR, Lactate)  
> extracted from a single Persian voice recording — no manual typing required.

---

## What it does

1. **Record / upload** Persian speech (microphone or `.ogg/.wav/.mp3`)
2. **STT** via Whisper (`POST /experiments/voice-form/stt`) with ICU-domain prompt
3. **Extract** patient fields using a hybrid regex + LLM pipeline (`form_extract.py`)
4. **Display** filled form card with:
   - Filled fields only (empty fields hidden)
   - Missing-field hints
   - Manual edit support
   - Append another voice (merge into existing result)
   - Confirmation TTS readback
   - Copy JSON (for HakimAI handoff)

---

## Supported Form Sections

| Section | Fields |
|---------|--------|
| **Demographics** | Name, Age, Sex, Height, Weight, Diagnosis |
| **Hemodynamics** | SBP, DBP, MAP (auto-computed), HR, Temp, Urine output, I&O balance, Vasopressor |
| **ABG** | pH, PaCO2, PaO2, SaO2, HCO3, Base Excess, P/F ratio (auto-computed) |
| **Ventilator Settings** | Mode, Pi/PS, PEEP, FiO2, VT set, RR set, Rise time, Ti max |
| **Ventilator Measurements** | RR total, RR spontaneous, VTe, Peak pressure, Plateau, PEEP measured, Auto-PEEP, Mean pressure, Driving pressure (auto), I:E, MV, Compliance static/dynamic, RSBI, Leak, WOB, RC exp |
| **Lab** | Hb, Hct, WBC, Platelets, Na, K, Ca, Mg, Phosphate, BUN, Creatinine, Albumin, AST, ALT, Bilirubin, CRP, Procalcitonin, Glucose, ESR, Lactate |

---

## Architecture

```
Persian speech
     │
     ▼
Whisper STT  ──── ICU-domain initial_prompt (terminology priming)
     │
     ▼
normalize_persian_text()  ──── digit/ZWNJ/common-garble fixes
     │
     ▼
Regex extractors  ──── per-field patterns with allow_decimal support
     │
     ▼
LLM (GapGPT / gpt-4o-mini)  ──── primary for hemo/ABG, fallback for vent/lab
     │
     ▼
Structured JSON  ──── merged, validated, range-checked
     │
     ▼
Streamlit UI  ──── editable form card + TTS confirmation
```

---

## Key Files

| File | Role |
|------|------|
| `form_extract.py` | Field extractors, LLM integration, merge logic |
| `voice_form_ui.py` | Streamlit UI |
| `../../backend/stt_utils.py` | Whisper wrapper, STT garble fixes, domain prompt |
| `../../tests/test_form_extract.py` | Unit tests for extractors |

---

## Run (Windows)

```powershell
cd D:\Python_envs\rag_project

# Terminal 1 — FastAPI backend (loads Whisper model, ~2 min startup)
.\venv\Scripts\python.exe -m uvicorn backend.main_api:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Streamlit UI
.\venv\Scripts\streamlit.exe run backend\experiments\voice_form_ui.py --server.port 8501
```

Open **http://localhost:8501**

### Optional: Enable LLM extraction

```powershell
# In .env or shell:
$env:FORM_EXTRACT_LLM = "1"
$env:FORM_EXTRACT_LLM_MODEL = "gpt-4o-mini"   # or your GapGPT model
$env:OPENAI_API_KEY = "sk-..."
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FORM_EXTRACT_LLM` | `0` | Enable LLM extraction (`1` = on) |
| `FORM_EXTRACT_LLM_MODEL` | `gpt-4o-mini` | LLM model name |
| `OPENAI_BASE_URL` | OpenAI | Custom base URL (e.g. GapGPT) |

> `.env` is git-ignored — never commit API keys.

---

## Tests

```powershell
cd D:\Python_envs\rag_project
.\venv\Scripts\python.exe -m pytest tests/test_form_extract.py -v
```

---

## Version

Current extractor version: `hemo-slot-v12`

> Each version increment reflects a breaking change to extraction logic.
> Store this version alongside saved JSON to detect schema drift.
