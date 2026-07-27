# Voice → form fill (experiment)

Isolated demo on branch `experiment/voice-form-fill`.  
Does **not** change HakimAI, `/api/ask`, or production RAG paths.

## What it does

1. Record / upload Persian speech **or** paste text  
2. STT via existing `POST /api/cases` (transcript only)  
3. Extract **جنس / سن / قد** with rules in `form_extract.py`  
4. Fill a small patient form in Streamlit

## Run

```bash
# terminal 1 — unchanged production backend
uvicorn backend.main_api:app --host 0.0.0.0 --port 8000

# terminal 2 — experiment UI only
streamlit run backend/experiments/voice_form_ui.py
```

Set `API_KEY` / `API_BASE_URL` if your backend requires them (same as other UIs).

## Files (this folder only)

| File | Role |
|------|------|
| `form_extract.py` | Parse gender / age / height from text |
| `voice_form_ui.py` | Streamlit form demo |
| `README.md` | This note |

Unit tests: `tests/test_form_extract.py`
