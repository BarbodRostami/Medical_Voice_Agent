from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Literal
from urllib.parse import urlparse

import tempfile

# Windows consoles (cp1252) crash on Persian/emoji in print — break STT/case workers.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests
import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from pydantic import BaseModel, Field

from backend.api_auth import configured_api_key, enforce_api_key
from backend.audio_security import (
    audio_signing_enabled,
    is_allowed_audio_proxy_key,
    verify_audio_signature,
)
from backend.case_store import (
    load_meta,
    new_meta,
    output_audio_key,
    output_json_key,
    save_collaborator_stt_json,
    save_input_audio,
    save_input_text,
    save_meta,
    save_output_text,
    validate_case_id,
)
from backend.llm_output import clean_llm_output
from backend.llm_provider import (
    AnswerLLM,
    build_rag_messages,
    create_answer_llm,
)
from backend.provider_config import llm_provider
from backend.medical_voice_utils import (
    build_audio_proxy_url,
    download_mp3_from_storage,
    english_to_persian_voice,
    persian_to_voice,
    translate_to_english,
    translate_to_persian,
    upload_mp3_to_key_with_timeout,
    upload_mp3_to_liara,
    upload_mp3_with_timeout,
)
from backend.stt_utils import detect_audio_extension, transcribe_medical_audio, transcribe_form_demographics_audio
from backend.experiments.form_extract import (
    FIELD_LABELS_FA,
    extract_patient_demographics,
    export_fields_payload,
)


def _collaborator_fields_from_transcript(transcript: str) -> dict:
    """Flat form JSON for HakimAI + found/missing (keeps free-text separate)."""
    payload = export_fields_payload(extract_patient_demographics(transcript))
    flat = dict(payload.get("fields") or {})
    flat["found"] = list(payload.get("found") or [])
    flat["missing"] = list(payload.get("missing") or [])
    flat["raw_text"] = payload.get("raw_text") or transcript
    flat["extract_version"] = payload.get("extract_version") or "patient-tab-v1"
    # Help clients iterate known form keys without hard-coding
    flat["schema_keys"] = list(FIELD_LABELS_FA.keys())
    return flat


def _api_docs_enabled() -> bool:
    """Hide OpenAPI UI in production when API_KEY is set (opt-in with EXPOSE_API_DOCS=1)."""
    if os.getenv("DISABLE_API_DOCS", "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    if configured_api_key() and os.getenv("EXPOSE_API_DOCS", "").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return False
    return True


_docs_on = _api_docs_enabled()
app = FastAPI(
    title="Medical RAG API",
    docs_url="/docs" if _docs_on else None,
    redoc_url="/redoc" if _docs_on else None,
    openapi_url="/openapi.json" if _docs_on else None,
)
app.middleware("http")(enforce_api_key)

PERSIST_DIRECTORY = "db"  
# Must match the model used in ingestion.py (MedCPT — a medical-domain encoder)
EMBEDDING_MODEL = "ncbi/MedCPT-Article-Encoder"
RETRIEVE_K = 5       # final number of chunks returned
FETCH_K = 20         # candidates for MMR to diversify from


def _normalize_ollama_host(raw: str | None) -> str:
    if not raw:
        return "http://localhost:11434"
    raw = raw.strip().replace("0.0.0.0", "127.0.0.1")
    if not raw.startswith(("http://", "https://")):
        raw = "http://" + raw
    if not urlparse(raw).port:
        raw = raw.rstrip("/") + ":11434"
    return raw.rstrip("/")


OLLAMA_HOST = _normalize_ollama_host(os.getenv("OLLAMA_HOST"))
MAX_CACHE_SIZE = 100


def _public_base_url(req: Request) -> str:
    """External URL for audio_url — use PUBLIC_API_URL on server if set."""
    override = os.getenv("PUBLIC_API_URL", "").strip()
    if override:
        return override if override.endswith("/") else override + "/"
    return str(req.base_url)


_cache: OrderedDict[str, dict] = OrderedDict()

# ─── Job Manager ──────────────────────────────────────────────────────────────
# In-memory store: job_id → job state. Resets on server restart.
# For production use Redis instead.

JobStatus = Literal["queued", "processing", "done", "failed"]

_jobs: dict[str, dict] = {}
_job_executor = ThreadPoolExecutor(max_workers=5)

# Collaborator cases keyed by external uuid (also persisted as cases/{uuid}/meta.json).
_cases: dict[str, dict] = {}
_cases_lock = threading.Lock()

# Whisper model — loaded once on first STT request (lazy, ~150MB for "tiny")
_whisper_model = None
_whisper_lock = threading.Lock()
# medium is slower on CPU but markedly better for Persian short utterances.
_WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "medium")  # tiny / small / medium / large-v3


def _whisper_load_candidates() -> list[tuple[str, str]]:
    """Build (device, compute_type) attempts. Explicit env wins; else CUDA then CPU fallback."""
    device = (os.getenv("WHISPER_DEVICE") or "").strip().lower()
    compute = (os.getenv("WHISPER_COMPUTE_TYPE") or "").strip().lower()

    if device and compute:
        # Still append safe fallbacks so a bad pair (e.g. cuda+float16) does not kill the case.
        extras: list[tuple[str, str]] = []
        if (device, compute) != ("cpu", "int8"):
            extras.append(("cpu", "int8"))
        if device == "cuda" and compute == "float16":
            extras = [("cuda", "int8"), ("cuda", "float32"), ("cpu", "int8")]
        return [(device, compute), *[e for e in extras if e != (device, compute)]]

    if device == "cpu":
        return [(device, compute or "int8")]

    if device == "cuda":
        comps = [compute] if compute else ["float16", "int8", "float32"]
        out = [(device, c) for c in comps]
        out.append(("cpu", "int8"))
        return out

    # Auto-detect: try CUDA variants, always end with CPU int8.
    candidates: list[tuple[str, str]] = []
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            candidates.extend(
                [("cuda", "float16"), ("cuda", "int8"), ("cuda", "float32")]
            )
    except Exception:
        pass
    candidates.append(("cpu", "int8"))
    return candidates


def _get_whisper() -> "WhisperModel":
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    with _whisper_lock:
        if _whisper_model is None:
            from faster_whisper import WhisperModel

            last_error: Exception | None = None
            for device, compute in _whisper_load_candidates():
                try:
                    print(
                        f"Loading Whisper model '{_WHISPER_MODEL_SIZE}' "
                        f"(device={device}, compute_type={compute})..."
                    )
                    _whisper_model = WhisperModel(
                        _WHISPER_MODEL_SIZE,
                        device=device,
                        compute_type=compute,
                    )
                    print(
                        f"Whisper ready (device={device}, compute_type={compute})."
                    )
                    break
                except Exception as e:
                    last_error = e
                    print(
                        f"Whisper load failed on {device}/{compute}: {e} — trying next..."
                    )
            if _whisper_model is None:
                raise RuntimeError(
                    f"Could not load Whisper model '{_WHISPER_MODEL_SIZE}'. "
                    f"Last error: {last_error}"
                )
    return _whisper_model


def _new_job() -> str:
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "queued",
        "message": "در صف انتظار...",
        "audio_url": None,
        "answer": None,
        "error": None,
    }
    return job_id


def _update_job(job_id: str, **kwargs) -> None:
    if job_id in _jobs:
        _jobs[job_id].update(kwargs)


def _set_case(meta: dict) -> None:
    with _cases_lock:
        _cases[meta["uuid"]] = meta
    # Persist meta in background so enqueue / status updates stay fast.
    _job_executor.submit(_persist_case_meta_safe, dict(meta))


def _persist_case_meta_safe(meta: dict) -> None:
    try:
        save_meta(meta)
    except Exception as e:
        print(f"Warning: could not persist case meta to S3: {e}")


def _patch_case(case_id: str, **kwargs) -> None:
    with _cases_lock:
        current = dict(_cases.get(case_id) or {})
        if not current:
            return
        current.update(kwargs)
        _cases[case_id] = current
        snapshot = dict(current)
    _job_executor.submit(_persist_case_meta_safe, snapshot)


def _get_case(case_id: str) -> dict | None:
    with _cases_lock:
        cached = _cases.get(case_id)
        if cached is not None:
            return dict(cached)
    try:
        meta = load_meta(case_id)
    except Exception as e:
        print(f"Warning: could not load case meta from S3: {e}")
        return None
    if meta is None:
        return None
    with _cases_lock:
        _cases[case_id] = meta
    return dict(meta)


class CaseTextRequest(BaseModel):
    """JSON body for text-only collaborator cases (aliases: /api/cases, /api/ask)."""

    uuid: str = Field(..., description="External server case id")
    text: str = Field(..., min_length=1, description="Persian (or TTS-ready) text")


db = None
llm: AnswerLLM | None = None
bm25_retriever = None
vector_retriever = None


# ─── Initialization ───────────────────────────────────────────────────────────

print("Loading Vector Database and Models...")
try:
    # Use MedCPT — a medical-domain encoder that matches how the DB was indexed
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    
    if not os.path.exists(PERSIST_DIRECTORY):
        print(f"Warning: Folder '{PERSIST_DIRECTORY}' not found!")

    db = Chroma(persist_directory=PERSIST_DIRECTORY, embedding_function=embeddings)
    
    # ── Build Hybrid Retriever ──────────────────────────────────────────────
    # 1. Load all documents from ChromaDB for BM25 keyword index
    raw = db._collection.get(include=["documents", "metadatas"])
    all_docs: list[Document] = [
        Document(page_content=doc, metadata=meta or {})
        for doc, meta in zip(raw["documents"], raw["metadatas"])
    ]
    print(f"Loaded {len(all_docs)} documents for BM25 index.")

    # 2. BM25 retriever — keyword/exact-match (great for medical terms like ETCO2)
    bm25_retriever = BM25Retriever.from_documents(all_docs)
    bm25_retriever.k = FETCH_K  # fetch more, RRF will rank and trim

    # 3. Vector retriever with MMR — semantic similarity + diversity
    vector_retriever = db.as_retriever(
        search_type="mmr",
        search_kwargs={"k": FETCH_K, "fetch_k": FETCH_K * 2, "lambda_mult": 0.7},
    )

    print("Hybrid retriever (BM25 + MMR) ready.")

    llm = create_answer_llm(ollama_host=OLLAMA_HOST)
    print("Models loaded successfully!")
    if configured_api_key():
        print("API key auth ENABLED (header X-API-Key required except / and /voice/audio/*).")
    else:
        print("WARNING: API_KEY is not set — API endpoints are open on the network.")
except Exception as e:
    print(f"Error during initialization: {e}")


# ─── Cache ────────────────────────────────────────────────────────────────────

def _cache_key(query: str) -> str:
    return hashlib.md5(query.strip().lower().encode()).hexdigest()


def _get_cache(key: str) -> dict | None:
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    return None


def _set_cache(key: str, answer: str, sources: int) -> None:
    if len(_cache) >= MAX_CACHE_SIZE:
        _cache.popitem(last=False)
    _cache[key] = {"answer": answer, "sources": sources}


# ─── Retrieval ────────────────────────────────────────────────────────────────

def _rrf_merge(
    lists: list[list[Document]], k_rrf: int = 60
) -> list[Document]:
    """Reciprocal Rank Fusion — combines ranked lists without needing scores."""
    scores: dict[str, float] = {}
    doc_map: dict[str, Document] = {}
    for ranked_list in lists:
        for rank, doc in enumerate(ranked_list):
            key = doc.page_content[:120]
            scores[key] = scores.get(key, 0.0) + 1.0 / (k_rrf + rank + 1)
            doc_map[key] = doc
    sorted_keys = sorted(scores, key=lambda k: scores[k], reverse=True)
    return [doc_map[k] for k in sorted_keys]


def _retrieve(query: str) -> list[Document]:
    """Hybrid retrieval: BM25 keyword + MMR vector, merged via RRF."""
    bm25_docs = bm25_retriever.invoke(query)
    vector_docs = vector_retriever.invoke(query)
    merged = _rrf_merge([vector_docs, bm25_docs])  # vector weighted first
    return merged[:RETRIEVE_K]


# ─── Prompt ───────────────────────────────────────────────────────────────────

def _clean_llm_output(raw: str, query: str) -> str:
    """Backward-compatible wrapper around clean_llm_output."""
    return clean_llm_output(raw, query)


def _rag_answer(query: str) -> tuple[str, int]:
    """Shared RAG path for /chat, /chat/voice, and job workers.

    Retrieval: hybrid BM25 + MMR → RRF. Generation: ``LLM_PROVIDER``
    (``openai`` = GapGPT/OpenAI-compatible chat, else Ollama BioMistral).

    Returns ``(answer_text, source_documents_count)``. Uses the in-memory LRU
    cache when present so callers do not re-implement retrieve → prompt → LLM.
    """
    if llm is None:
        raise RuntimeError("LLM not initialized")
    key = _cache_key(query)
    cached = _get_cache(key)
    if cached:
        return cached["answer"], int(cached["sources"])

    docs = _retrieve(query)
    context = "\n\n---\n\n".join([doc.page_content for doc in docs])
    messages = build_rag_messages(query, context)
    raw = llm.invoke_messages(messages)
    answer = _clean_llm_output(raw, query)
    source_count = len(docs)
    _set_cache(key, answer, source_count)
    _save_to_django(query, answer)
    return answer, source_count


def _upload_audio_url(audio_bytes: bytes, base_url: str, timeout: int = 90) -> tuple[str | None, str | None]:
    """Upload MP3 with timeout and build the public proxy URL (shared upload pattern)."""
    file_key = upload_mp3_with_timeout(audio_bytes, timeout=timeout)
    audio_url = build_audio_proxy_url(base_url, file_key) if file_key else None
    return file_key, audio_url


def _save_to_django(question: str, answer: str) -> None:
    try:
        django_url = os.getenv("DJANGO_URL", "http://django-admin:8000/save_chat/")
        requests.post(django_url, json={"question": question, "answer": answer}, timeout=5)
    except Exception as e:
        print(f"Django save failed: {e}")


# ─── Models ───────────────────────────────────────────────────────────────────

class QuestionRequest(BaseModel):
    query: str


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/")
def home():
    model_name = llm.active_model if llm is not None else None
    return {
        "message": "Medical RAG API is running!",
        "llm_provider": llm_provider() if llm is not None else None,
        "model": model_name,
        "embedding_model": EMBEDDING_MODEL,
        "retriever": "Hybrid BM25 + MMR",
        "db_loaded": db is not None,
    }


@app.post("/chat")
async def chat(request: QuestionRequest):
    """Standard (non-streaming) chat with LRU cache."""
    if db is None or llm is None or bm25_retriever is None:
        raise HTTPException(status_code=500, detail="System not initialized.")

    query = request.query
    key = _cache_key(query)
    cached = _get_cache(key)
    if cached:
        print(f"Cache hit: {query[:60]}")
        return {
            "query": query,
            "answer": cached["answer"],
            "source_documents_count": cached["sources"],
            "cached": True,
        }

    try:
        print(f"Question: {query}")
        answer, source_count = _rag_answer(query)
        return {
            "query": query,
            "answer": answer,
            "source_documents_count": source_count,
            "cached": False,
        }
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/stream")
async def chat_stream(request: QuestionRequest):
    """Streaming chat — yields tokens as plain text."""
    if db is None or llm is None or bm25_retriever is None:
        raise HTTPException(status_code=500, detail="System not initialized.")

    query = request.query
    key = _cache_key(query)
    cached = _get_cache(key)

    if cached:
        async def _yield_cached():
            yield cached["answer"]
        return StreamingResponse(_yield_cached(), media_type="text/plain; charset=utf-8")

    docs = _retrieve(query)
    context = "\n\n---\n\n".join([doc.page_content for doc in docs])
    messages = build_rag_messages(query, context)
    source_count = len(docs)

    def _stream_tokens():
        full_text = ""
        assert llm is not None
        for token in llm.stream_messages(messages):
            full_text += token
            yield token
        if full_text.startswith("\n[Error:"):
            return
        clean = _clean_llm_output(full_text, query)
        _set_cache(key, clean, source_count)
        _save_to_django(query, clean)

    return StreamingResponse(_stream_tokens(), media_type="text/plain; charset=utf-8")


@app.post("/translate")
async def translate_text(request: QuestionRequest):
    """Translate English medical text to Persian (unused by UI, kept for completeness)."""
    if llm is None:
        raise HTTPException(status_code=500, detail="LLM not initialized.")
    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a professional medical translator (English to Persian/Farsi). "
                    "Return ONLY the Persian translation, nothing else."
                ),
            },
            {
                "role": "user",
                "content": f"Translate to Persian:\n{request.query}",
            },
        ]
        translation = llm.invoke_messages(messages).strip().lstrip(":").strip()
        for tag in ("<|im_start|>", "<|im_end|>", "assistant", "user"):
            translation = translation.replace(tag, "").strip()
        return {"translation": translation, "original": request.query}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Voice Endpoints ─────────────────────────────────────────────────────────

@app.post(
    "/voice",
    responses={
        200: {"description": "JSON with audio_url (Liara) or MP3 bytes as fallback"},
        400: {"description": "Invalid request body"},
        500: {"description": "TTS generation failed"},
    },
    summary="Convert Persian medical report to voice (MP3)",
)
async def generate_voice(request: Request):
    """
    Accepts: { "<uuid>": { "tafsir": "...", "recom": "..." } }
    Returns: MP3 audio of the Persian text read aloud.
    """
    try:
        body: dict = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    if not body:
        raise HTTPException(status_code=400, detail="Empty request body.")

    first_value = next(iter(body.values()))
    data = first_value if isinstance(first_value, dict) else body

    tafsir: str = data.get("tafsir", "").strip()
    recom: str = data.get("recom", "").strip()

    if not tafsir and not recom:
        raise HTTPException(status_code=400, detail="Provide at least 'tafsir' or 'recom'.")

    parts: list[str] = []
    if tafsir:
        parts.append(f"تفسیر بالینی. {tafsir}")
    if recom:
        parts.append(f"توصیه‌های درمانی. {recom}")
    full_text = "  ".join(parts)

    try:
        audio_bytes = persian_to_voice(full_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS failed: {e}")

    try:
        file_key = upload_mp3_to_liara(audio_bytes)
        audio_url = build_audio_proxy_url(_public_base_url(request), file_key)
        return {"audio_url": audio_url, "status": "uploaded"}
    except Exception:
        return Response(
            content=audio_bytes,
            media_type="audio/mp3",
            headers={"Content-Disposition": "inline; filename=report.mp3"},
        )


@app.post(
    "/chat/voice",
    responses={
        200: {"description": "JSON with query and audio_url (Liara) or MP3 bytes as fallback"},
        500: {"description": "RAG or TTS failed"},
    },
    summary="Ask a medical question and get an MP3 voice answer",
)
async def chat_voice(body: QuestionRequest, req: Request):
    """
    One-shot endpoint: runs RAG retrieval + LLM answer + Persian TTS.
    Send a question, receive an MP3 file directly.
    """
    if db is None or llm is None or bm25_retriever is None:
        raise HTTPException(status_code=500, detail="System not initialized.")

    query = body.query
    key = _cache_key(query)
    cached = _get_cache(key)

    if cached:
        answer = cached["answer"]
        print(f"Cache hit (voice): {query[:60]}")
    else:
        try:
            print(f"Chat/Voice question: {query}")
            answer, _source_count = _rag_answer(query)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"RAG failed: {e}")

    # Full pipeline: English answer → translate → TTS → upload to Liara
    try:
        audio_bytes = english_to_persian_voice(answer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS failed: {e}")

    try:
        file_key = upload_mp3_to_liara(audio_bytes)
        audio_url = build_audio_proxy_url(_public_base_url(req), file_key)
        return {"query": query, "audio_url": audio_url, "status": "uploaded"}
    except Exception:
        return Response(
            content=audio_bytes,
            media_type="audio/mp3",
            headers={"Content-Disposition": "inline; filename=answer.mp3"},
        )


# ─── Job Workers (run in background thread) ───────────────────────────────────

def _answer_to_persian_voice(answer_en: str) -> tuple[str, bytes]:
    """Translate English RAG answer to Persian and generate MP3."""
    if not answer_en or len(answer_en.strip()) < 3:
        raise ValueError("پاسخ خالی است")
    persian = translate_to_persian(answer_en)
    if not persian or len(persian.strip()) < 3:
        raise ValueError("ترجمه فارسی ناموفق بود")
    audio_bytes = persian_to_voice(persian)
    return persian, audio_bytes


def _worker_chat_voice(job_id: str, query: str, base_url: str) -> None:
    """Background worker: RAG → TTS → S3 upload. Updates job state throughout."""
    try:
        _update_job(job_id, status="processing", message="در حال جستجو در پایگاه دانش...")

        # Step 1: RAG (shared helper — issue #12)
        _update_job(job_id, message="در حال تولید پاسخ با هوش مصنوعی...")
        answer, _source_count = _rag_answer(query)

        # Step 2: TTS (Persian answer for API + audio)
        _update_job(job_id, message="در حال تبدیل متن به صدا...")
        persian_answer, audio_bytes = _answer_to_persian_voice(answer)

        # Step 3: Upload (shared helper — issue #12)
        _update_job(job_id, message="در حال آپلود فایل صوتی...")
        _file_key, audio_url = _upload_audio_url(audio_bytes, base_url)

        _update_job(
            job_id,
            status="done",
            message="تکمیل شد.",
            answer=persian_answer,
            answer_en=answer,
            audio_url=audio_url,
        )

    except Exception as e:
        _update_job(job_id, status="failed", message="خطا در پردازش.", error=str(e))


def _worker_voice_input(job_id: str, audio_path: str, base_url: str) -> None:
    """Background worker: audio file → Whisper STT → RAG → TTS → S3."""
    try:
        # Step 1: Speech-to-Text (ffmpeg normalize + Whisper with medical prompt)
        _update_job(job_id, status="processing", message="در حال تبدیل صدا به متن...")
        persian_query = transcribe_medical_audio(audio_path, local_model_getter=_get_whisper)

        if not persian_query:
            _update_job(job_id, status="failed", message="صدایی شناسایی نشد.", error="Empty transcription")
            return

        # Step 2: Translate Persian question → English for RAG
        _update_job(job_id, message="در حال ترجمه سوال...")
        query = translate_to_english(persian_query)
        print(f"Translated query (en): {query[:80]}")

        # Step 3: RAG (shared helper)
        _update_job(job_id, message="در حال جستجو در پایگاه دانش...", answer=None)
        _update_job(job_id, message="در حال تولید پاسخ با هوش مصنوعی...")
        answer, _source_count = _rag_answer(query)

        if not answer or len(answer.strip()) < 5:
            _update_job(
                job_id,
                status="failed",
                message="پاسخی تولید نشد — سوال را واضح‌تر و به فارسی بپرسید.",
                transcription=persian_query,
                query_en=query,
                error="LLM returned empty or too-short answer",
            )
            return

        # Step 4: TTS (Persian answer + audio)
        _update_job(job_id, message="در حال تبدیل متن به صدا...")
        persian_answer, audio_bytes = _answer_to_persian_voice(answer)

        # Step 5: Upload
        _update_job(job_id, message="در حال آپلود فایل صوتی...")
        _file_key, audio_url = _upload_audio_url(audio_bytes, base_url)

        _update_job(
            job_id,
            status="done",
            message="تکمیل شد.",
            transcription=persian_query,
            query_en=query,
            answer=persian_answer,
            answer_en=answer,
            audio_url=audio_url,
        )

    except Exception as e:
        _update_job(job_id, status="failed", message="خطا در پردازش.", error=str(e))
    finally:
        # Clean up temp file
        try:
            import os as _os
            _os.remove(audio_path)
        except Exception:
            pass


def _worker_voice(job_id: str, full_text: str, base_url: str) -> None:
    """Background worker for /jobs/voice-report: TTS only → S3 upload."""
    try:
        _update_job(job_id, status="processing", message="در حال تبدیل متن به صدا...")
        audio_bytes = persian_to_voice(full_text)

        _update_job(job_id, message="در حال آپلود فایل صوتی...")
        _file_key, audio_url = _upload_audio_url(audio_bytes, base_url)

        _update_job(job_id, status="done", message="تکمیل شد.", audio_url=audio_url)

    except Exception as e:
        _update_job(job_id, status="failed", message="خطا در پردازش.", error=str(e))


def _worker_case_text(case_id: str, text: str, base_url: str) -> None:
    """Text/TTS case: MP3 → S3 as ``{YYYY-MM-DD}/{uuid}.mp3`` for HakimAI poll."""
    try:
        _patch_case(case_id, status="processing", message="در حال تبدیل متن به صدا...")
        audio_bytes = persian_to_voice(text)
        with _cases_lock:
            day = (_cases.get(case_id) or {}).get("day")
        out_key = output_audio_key(case_id, day)
        _patch_case(
            case_id,
            message="در حال آپلود فایل صوتی روی S3...",
            output_key=out_key,
        )
        print(f"[case {case_id}] uploading MP3 -> {out_key} ({len(audio_bytes)} bytes)")
        file_key = upload_mp3_to_key_with_timeout(audio_bytes, out_key, timeout=90)
        if not file_key:
            raise RuntimeError(f"S3 upload failed or timed out for key={out_key}")
        print(f"[case {case_id}] S3 upload OK: {file_key}")
        audio_url = build_audio_proxy_url(base_url, file_key)
        _patch_case(
            case_id,
            status="ready",
            message="تکمیل شد — فایل روی S3 آماده است.",
            audio_url=audio_url,
            output_key=file_key,
            error=None,
        )
    except Exception as e:
        print(f"[case {case_id}] FAILED: {e}")
        _patch_case(case_id, status="failed", message="خطا در پردازش.", error=str(e))


def _safe_log(msg: str) -> None:
    """Print without crashing Windows cp1252 consoles on Persian text."""
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("utf-8", errors="backslashreplace").decode("ascii", errors="replace"), flush=True)


def _worker_case_audio(case_id: str, audio_path: str, base_url: str) -> None:
    """HakimAI voice case: STT → Persian text + fields JSON on S3.

    Same collaboration pattern as TTS MP3:
    upload result to ``{YYYY-MM-DD}/{uuid}.json`` for HakimAI to poll on S3.

    Also keeps legacy ``text`` / ``transcript`` / ``answer`` / ``fields`` on
    GET /api/get-msg for status and older clients. No RAG/LLM on this path.
    """
    del base_url  # reserved for future audio_url links; unused in STT mode
    try:
        _patch_case(case_id, status="processing", message="در حال تبدیل صدا به متن...")
        _safe_log(f"[case {case_id}] STT started")
        transcript = transcribe_medical_audio(audio_path, local_model_getter=_get_whisper)
        if not transcript:
            _safe_log(f"[case {case_id}] FAILED: empty transcription")
            _patch_case(
                case_id,
                status="failed",
                message="صدایی شناسایی نشد.",
                error="Empty transcription",
            )
            return

        # Structured extract for form fill — does not replace free-text fields.
        try:
            fields_payload = _collaborator_fields_from_transcript(transcript)
        except Exception as e:
            _safe_log(f"[case {case_id}] Warning: form extract failed: {e}")
            fields_payload = None

        with _cases_lock:
            day = (_cases.get(case_id) or {}).get("day")
        json_key = output_json_key(case_id, day)
        s3_payload = {
            "uuid": case_id,
            "status": "ready",
            "mode": "audio",
            "text": transcript,
            "transcript": transcript,
            "answer": transcript,
            "fields": fields_payload,
        }

        try:
            save_output_text(
                case_id,
                transcript=transcript,
                answer=transcript,
                fields=fields_payload,
            )
        except Exception as e:
            _safe_log(f"[case {case_id}] Warning: could not store internal output text: {e}")

        _patch_case(
            case_id,
            message="در حال آپلود JSON روی S3...",
            output_json_key=json_key,
        )
        try:
            written = save_collaborator_stt_json(case_id, s3_payload, day=day)
            _safe_log(f"[case {case_id}] S3 JSON OK: {written}")
        except Exception as e:
            _safe_log(f"[case {case_id}] FAILED S3 JSON upload: {e}")
            _patch_case(
                case_id,
                status="failed",
                message="خطا در آپلود JSON روی S3.",
                error=str(e),
                text=transcript,
                transcript=transcript,
                answer=transcript,
                fields=fields_payload,
            )
            return

        _patch_case(
            case_id,
            status="ready",
            message=(
                "تکمیل شد — JSON روی S3 آماده است "
                f"(کلید {{YYYY-MM-DD}}/{case_id}.json)."
            ),
            transcript=transcript,
            answer=transcript,
            text=transcript,
            fields=fields_payload,
            output_json_key=json_key,
            audio_url=None,
            error=None,
        )
        _safe_log(
            f"[case {case_id}] READY for S3 poll: "
            f"{json.dumps(s3_payload, ensure_ascii=False)}"
        )
    except Exception as e:
        _safe_log(f"[case {case_id}] FAILED: {e}")
        _patch_case(case_id, status="failed", message="خطا در پردازش.", error=str(e))
    finally:
        try:
            os.remove(audio_path)
        except Exception:
            pass


def _enqueue_case_text(case_id: str, text: str, base_url: str) -> dict:
    cleaned = text.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="text must not be empty.")
    _job_executor.submit(_save_input_text_safe, case_id, cleaned)
    meta = new_meta(case_id, mode="text")
    _set_case(meta)
    _job_executor.submit(_worker_case_text, case_id, cleaned, base_url)
    return {
        "uuid": case_id,
        "status": "queued",
        "mode": "text",
        "message": (
            "پذیرفته شد — بعد از ready فایل را از S3 با کلید "
            f"{{YYYY-MM-DD}}/{case_id}.mp3 بگیرید (تاریخ تهران)."
        ),
    }


def _save_input_text_safe(case_id: str, text: str) -> None:
    try:
        save_input_text(case_id, text)
    except Exception as e:
        print(f"Warning: could not store case input text: {e}")


def _enqueue_case_audio(
    case_id: str,
    raw: bytes,
    filename: str | None,
    content_type: str | None,
    base_url: str,
) -> dict:
    # Collaborator audio path is STT-only — does not need Chroma / Ollama.
    if not raw:
        raise HTTPException(status_code=400, detail="Empty audio upload.")
    suffix = detect_audio_extension(raw, filename, content_type)
    _job_executor.submit(_save_input_audio_safe, case_id, raw, suffix)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    meta = new_meta(case_id, mode="audio")
    _set_case(meta)
    _job_executor.submit(_worker_case_audio, case_id, tmp_path, base_url)
    return {
        "uuid": case_id,
        "status": "queued",
        "mode": "audio",
        "message": (
            "فایل صوتی دریافت شد — بعد از ready JSON را از S3 با کلید "
            f"{{YYYY-MM-DD}}/{case_id}.json بگیرید (تاریخ تهران). "
            "وضعیت اختیاری: GET /api/get-msg?uuid=..."
        ),
    }


def _save_input_audio_safe(case_id: str, raw: bytes, suffix: str) -> None:
    try:
        save_input_audio(case_id, raw, suffix)
    except Exception as e:
        print(f"Warning: could not store case input audio: {e}")


def _case_public_view(meta: dict) -> dict:
    """Public JSON for HakimAI — no s3_bucket / s3_key fields.

    Legacy clients keep using ``text`` / ``transcript`` / ``answer``.
    Newer clients may also read ``fields`` (structured patient-tab JSON).
    """
    text = meta.get("text") or meta.get("answer") or meta.get("transcript")
    return {
        "uuid": meta.get("uuid"),
        "status": meta.get("status"),
        "mode": meta.get("mode"),
        "message": meta.get("message"),
        "text": text,
        "transcript": meta.get("transcript"),
        "answer": meta.get("answer"),
        "fields": meta.get("fields"),
        "audio_url": meta.get("audio_url"),
        "error": meta.get("error"),
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
    }


# ─── Job Endpoints ────────────────────────────────────────────────────────────

@app.post(
    "/jobs/chat",
    summary="Async chat → voice job",
    response_description="Returns job_id immediately; poll /jobs/{job_id} for status",
)
async def job_chat_voice(request: QuestionRequest, req: Request):
    """
    Submit a medical question. Processing (RAG + TTS + upload) runs in background.
    Returns a job_id to poll with GET /jobs/{job_id}.
    """
    if db is None or llm is None:
        raise HTTPException(status_code=500, detail="System not initialized.")
    job_id = _new_job()
    base_url = _public_base_url(req)
    _job_executor.submit(_worker_chat_voice, job_id, request.query, base_url)
    return {
        "job_id": job_id,
        "status": "queued",
        "message": "در صف انتظار — برای بررسی وضعیت از GET /jobs/{job_id} استفاده کنید.",
    }


@app.post(
    "/jobs/voice-report",
    summary="Async Persian medical report → voice job",
    response_description="Returns job_id immediately",
)
async def job_voice_report(req: Request):
    """
    Submit a Persian medical report dict { uuid: {tafsir, recom} }.
    TTS + upload runs in background. Poll /jobs/{job_id} for audio_url.
    """
    try:
        body: dict = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    if not body:
        raise HTTPException(status_code=400, detail="Empty request body.")

    first_value = next(iter(body.values()))
    data = first_value if isinstance(first_value, dict) else body
    tafsir = data.get("tafsir", "").strip()
    recom = data.get("recom", "").strip()
    if not tafsir and not recom:
        raise HTTPException(status_code=400, detail="Provide at least 'tafsir' or 'recom'.")

    parts = []
    if tafsir:
        parts.append(f"تفسیر بالینی. {tafsir}")
    if recom:
        parts.append(f"توصیه‌های درمانی. {recom}")
    full_text = "  ".join(parts)

    job_id = _new_job()
    base_url = _public_base_url(req)
    _job_executor.submit(_worker_voice, job_id, full_text, base_url)
    return {
        "job_id": job_id,
        "status": "queued",
        "message": "در صف انتظار — برای بررسی وضعیت از GET /jobs/{job_id} استفاده کنید.",
    }


@app.post(
    "/stt/ask",
    summary="Async voice input → RAG answer → MP3",
    response_description="Returns job_id immediately; poll /jobs/{job_id} for status + audio_url",
)
async def job_voice_input(req: Request, file: UploadFile = File(...)):
    """
    Upload an audio file (MP3/WAV/OGG/M4A). Whisper transcribes it locally,
    then the text goes through RAG + TTS. Poll /jobs/{job_id} for the result.
    """
    if db is None or llm is None:
        raise HTTPException(status_code=500, detail="System not initialized.")

    raw = await file.read()
    suffix = detect_audio_extension(raw, file.filename, file.content_type)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    job_id = _new_job()
    base_url = _public_base_url(req)
    _job_executor.submit(_worker_voice_input, job_id, tmp_path, base_url)
    return {
        "job_id": job_id,
        "status": "queued",
        "message": "فایل صوتی دریافت شد — برای بررسی وضعیت از GET /jobs/{job_id} استفاده کنید.",
    }


@app.get(
    "/jobs/{job_id}",
    summary="Check job status",
)
async def get_job_status(job_id: str):
    """
    Poll this endpoint to check if your voice job is ready.
    status: queued | processing | done | failed
    """
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"job_id": job_id, **job}


@app.get("/jobs", summary="List all jobs (debug)")
async def list_jobs():
    return {"total": len(_jobs), "jobs": _jobs}


# ─── Collaborator Cases (external server ↔ voice server via S3) ───────────────

@app.post(
    "/api/cases",
    summary="Create case (text XOR audio) keyed by external uuid",
    response_description="Accepted immediately; poll GET /api/cases/{uuid}",
)
async def create_case(req: Request):
    """
    External-server / HakimAI contract (exactly one input mode — not both):

    - **TTS (text):** JSON ``{\"uuid\",\"text\"}`` → we upload MP3 to
      ``{YYYY-MM-DD}/{uuid}.mp3`` (Tehran date). HakimAI polls that key on S3.
      API responses do not expose s3_bucket / s3_key.
    - **STT (audio):** multipart ``uuid`` + ``file`` → Whisper STT + form fields;
      we upload JSON to ``{YYYY-MM-DD}/{uuid}.json`` for HakimAI to poll on S3
      (same pattern as MP3). Optional status via ``GET /api/get-msg?uuid=``.
      No RAG/LLM — HakimAI owns medical reasoning.
    """
    content_type = (req.headers.get("content-type") or "").lower()
    base_url = _public_base_url(req)

    if "application/json" in content_type:
        try:
            body = await req.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body.")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="JSON body must be an object.")
        try:
            case_id = validate_case_id(str(body.get("uuid", "")))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        text = str(body.get("text") or "").strip()
        if not text:
            raise HTTPException(
                status_code=400,
                detail="JSON mode requires non-empty text. For audio use multipart.",
            )
        if body.get("audio") not in (None, "", False):
            raise HTTPException(
                status_code=400,
                detail="Send text OR audio — not both. Use multipart for audio-only.",
            )
        return _enqueue_case_text(case_id, text, base_url)

    try:
        form = await req.form()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Expected application/json or multipart/form-data.",
        ) from None

    try:
        case_id = validate_case_id(str(form.get("uuid") or ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    text = str(form.get("text") or "").strip()
    upload = form.get("file")
    raw = b""
    filename: str | None = None
    file_content_type: str | None = None
    if upload is not None and hasattr(upload, "read"):
        raw = await upload.read()
        filename = getattr(upload, "filename", None)
        file_content_type = getattr(upload, "content_type", None)
    has_file = bool(raw)

    if text and has_file:
        raise HTTPException(
            status_code=400,
            detail="Send text OR audio file — not both (server capacity).",
        )
    if text:
        return _enqueue_case_text(case_id, text, base_url)
    if has_file:
        return _enqueue_case_audio(
            case_id,
            raw,
            filename,
            file_content_type,
            base_url,
        )
    raise HTTPException(
        status_code=400,
        detail="Provide non-empty text, or an audio file (not both, not neither).",
    )


@app.post(
    "/api/ask",
    summary="Alias of POST /api/cases for text JSON {uuid, text}",
)
async def api_ask(body: CaseTextRequest, req: Request):
    try:
        case_id = validate_case_id(body.uuid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _enqueue_case_text(case_id, body.text, _public_base_url(req))


@app.get(
    "/api/cases/{case_id}",
    summary="Get case status / audio_url by external uuid",
)
async def get_case(case_id: str):
    try:
        case_id = validate_case_id(case_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    meta = _get_case(case_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    return _case_public_view(meta)


@app.get(
    "/api/get-msg",
    summary="Alias of GET /api/cases/{uuid} (?uuid=)",
)
async def get_msg(uuid: str):
    try:
        case_id = validate_case_id(uuid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    meta = _get_case(case_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    return _case_public_view(meta)


@app.post(
    "/experiments/voice-form/stt",
    summary="EXPERIMENT: voice → demographics transcript + form fields",
)
async def experiment_voice_form_stt(file: UploadFile = File(...)):
    """Isolated form-fill STT (does not change HakimAI /api/cases).

    Uses a demographics-biased Whisper prompt, then extracts gender/age/height.
    """
    from backend.experiments.form_extract import extract_patient_demographics

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty audio upload.")
    suffix = detect_audio_extension(raw, file.filename, file.content_type)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    try:
        transcript = transcribe_form_demographics_audio(
            tmp_path,
            local_model_getter=_get_whisper,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"STT failed: {e}") from e
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    # Soft empty: UI asks user to speak again (avoid scary 422 in the browser).
    fields = extract_patient_demographics(transcript or "")
    return {
        "transcript": transcript or "",
        "fields": fields,
        "experiment": True,
        "ok": bool(transcript),
    }


@app.get(
    "/voice/audio/{key:path}",
    responses={
        200: {"content": {"audio/mpeg": {}}},
        403: {"description": "Invalid or expired signed link"},
        404: {"description": "Not found"},
    },
    summary="Stream a stored MP3 audio file (private proxy)",
)
async def stream_audio(key: str, request: Request):
    """Proxy endpoint: fetches the private MP3 from object storage and streams it.

    Keys are allowlisted (no ``cases/``, no ``..``). When API_KEY is set, URLs
    from ``build_audio_proxy_url`` include ``exp``+``sig`` and are verified here.
    HakimAI downloads TTS from S3 directly and does not use this endpoint.
    """
    if not is_allowed_audio_proxy_key(key):
        raise HTTPException(status_code=404, detail="Audio file not found.")
    if audio_signing_enabled() and not verify_audio_signature(
        key,
        request.query_params.get("exp"),
        request.query_params.get("sig"),
    ):
        raise HTTPException(status_code=403, detail="Invalid or expired audio link.")
    filename = key.rsplit("/", 1)[-1]
    try:
        audio_bytes = download_mp3_from_storage(key)
    except (RuntimeError, ValueError):
        raise HTTPException(status_code=404, detail="Audio file not found.")
    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
