# Voice → form fill (experiment)

Isolated demo on branch `experiment/voice-form-fill`.  
Does **not** change HakimAI, `/api/ask`, or production RAG paths.

## What it does

1. Record / upload Persian speech **or** paste text  
2. STT via existing `POST /api/cases` (transcript only)  
3. Extract **جنس / سن / قد** with rules in `form_extract.py`  
4. Fill a small patient form in Streamlit

## Run (Windows)

```powershell
cd D:\Python_envs\rag_project
.\venv\Scripts\python.exe -m uvicorn backend.main_api:app --host 0.0.0.0 --port 8000
.\venv\Scripts\python.exe -m streamlit run backend/experiments/voice_form_ui.py --server.port 8502
```

Open **http://localhost:8502**

Minimal UX: greeting TTS → mic only → show gender/age/height after extract.

## Files (this folder only)

| File | Role |
|------|------|
| `form_extract.py` | Parse gender / age / height from text |
| `voice_form_ui.py` | Streamlit form demo |
| `README.md` | This note |

Unit tests: `tests/test_form_extract.py`
