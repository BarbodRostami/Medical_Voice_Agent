# Voice → form fill (experiment)

Isolated demo on branch `experiment/voice-form-fill`.  
Does **not** change HakimAI, `/api/ask`, or production RAG paths.

## What it does

1. Greeting TTS → record / upload Persian speech  
2. STT via `POST /experiments/voice-form/stt`  
3. Extract patient-tab fields (`form_extract.py`)  
4. Result card with:
   - filled fields only
   - **missing-field hints**
   - **manual edit**
   - **append another voice** (merge into existing result)
   - **confirmation TTS**
   - **copy JSON** (for future HakimAI handoff tests)

## Run (Windows)

```powershell
cd D:\Python_envs\rag_project
.\venv\Scripts\python.exe -m uvicorn backend.main_api:app --host 0.0.0.0 --port 8000
.\venv\Scripts\python.exe -m streamlit run backend/experiments/voice_form_ui.py --server.port 8502
```

Open **http://localhost:8502**

## Files

| File | Role |
|------|------|
| `form_extract.py` | Parse + merge + confirmation speech helpers |
| `voice_form_ui.py` | Streamlit experiment UI |
| `README.md` | This note |

Unit tests: `tests/test_form_extract.py`
