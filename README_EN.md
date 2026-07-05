# 🩺 Medical RAG Assistant

A Retrieval-Augmented Generation (RAG) system for medical Q&A, built with **BioMistral** (via Ollama), **ChromaDB**, and a **Streamlit** interface — with Farsi voice output and a Django-based admin panel for chat history.

## Architecture

```
Streamlit UI  ──▶  FastAPI Backend (RAG)  ──▶  Django Admin (chat history)
  (:8501)              (:8000)                       (:8001)
                          │
                ┌─────────┴─────────┐
             ChromaDB            Ollama
          (vector store)      (BioMistral LLM)
```

**Flow:** user query → semantic search in ChromaDB → relevant chunks + query sent to BioMistral → answer cleaned and returned → query/answer logged to Django.

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI, Uvicorn |
| RAG | LangChain (community, chroma, huggingface, ollama) |
| Vector DB | ChromaDB |
| Embeddings | `ncbi/MedCPT-Query/Article-Encoder`, `all-mpnet-base-v2` |
| LLM | BioMistral via Ollama |
| Frontend | Streamlit |
| TTS / Translation | Piper TTS (Farsi), deep-translator |
| Admin Panel | Django + DRF |
| Infra | Docker Compose |

## Project Structure

```
main_api.py         # FastAPI RAG endpoint
app_ui.py            # Streamlit chat UI
ingestion.py          # Builds Chroma vector DB from PDF
chat.py / voice_chat.py  # CLI clients (text / voice)
docker-compose.yml      # backend, frontend, django-admin services
config/, api/            # Django project + chat-history app
```

## Prerequisites

- Docker & Docker Compose
- [Ollama](https://ollama.com/) running on the host with the model pulled:
  ```bash
  ollama pull biomistral
  ```
- A source PDF (e.g. `Critical_Care_Notes.pdf`) in the project root
- *(Optional)* Piper Farsi voice model files (`fa_IR-amir-medium.onnx*`)

## Setup

```bash
# 1. Build the vector database
pip install -r requirements.txt
python ingestion.py

# 2. Start Ollama
ollama serve

# 3. Launch all services
docker-compose up --build

# 4. Run Django migrations (first time only)
docker-compose exec django-admin python manage.py migrate
docker-compose exec django-admin python manage.py createsuperuser
```

| Service | URL |
|---|---|
| Streamlit UI | http://localhost:8501 |
| FastAPI backend | http://localhost:8000 |
| Django admin | http://localhost:8001/admin |

## API Reference

**`POST /chat`**
```json
// Request
{ "query": "What are the signs of sepsis?" }

// Response
{ "query": "...", "answer": "...", "source_documents_count": 3 }
```

**`GET /`** — health check + loaded model info
**`POST /save_chat/`** — internal, persists Q&A to Django (called automatically)

## Known Issues / Notes

- **Embedding mismatch**: `ingestion.py`, `chat.py`, and `main_api.py` use different embedding models (`MedCPT-Article-Encoder`, `MedCPT-Query-Encoder`, `all-mpnet-base-v2`). The ingestion and query-time embedding model **must match** for retrieval to work correctly.
- **Secrets**: keep API keys (e.g. `OPENROUTER_API_KEY`) in `.env`, never commit them.
- **Ollama host access**: backend uses `host.docker.internal` to reach Ollama on the host; works out of the box on Docker Desktop, requires `extra_hosts` on Linux (already configured in `docker-compose.yml`).
- **Django settings**: `DEBUG=True` and `ALLOWED_HOSTS=['*']` are dev-only — harden before any production deployment.

## Roadmap

- Add re-ranking to improve retrieval quality
- Unify embedding model across all scripts
- Add auth to the API and admin panel
- Support PDF upload from the UI

---

*Built for research/educational purposes. Validate clinically before any real-world medical use.*
