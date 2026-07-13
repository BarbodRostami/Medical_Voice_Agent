from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Literal
from urllib.parse import urlparse

import tempfile

import requests
import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from langchain_chroma import Chroma
from langchain_community.llms import Ollama as OllamaLLM
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from pydantic import BaseModel

from medical_voice_utils import (
    download_mp3_from_storage,
    english_to_persian_voice,
    persian_to_voice,
    translate_to_english,
    translate_to_persian,
    upload_mp3_to_liara,
)

app = FastAPI(title="Medical RAG API")

PERSIST_DIRECTORY = "db"
# Must match the model used in ingestion.py (MedCPT — a medical-domain encoder)
EMBEDDING_MODEL = "ncbi/MedCPT-Article-Encoder"
LLM_MODEL = "biomistral:latest"
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

_cache: OrderedDict[str, dict] = OrderedDict()

# ─── Job Manager ──────────────────────────────────────────────────────────────
# In-memory store: job_id → job state. Resets on server restart.
# For production use Redis instead.

JobStatus = Literal["queued", "processing", "done", "failed"]

_jobs: dict[str, dict] = {}
_job_executor = ThreadPoolExecutor(max_workers=5)

# Whisper model — loaded once on first STT request (lazy, ~150MB for "tiny")
_whisper_model = None
_WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small")  # tiny / small / medium


def _get_whisper() -> "WhisperModel":
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        print(f"Loading Whisper model '{_WHISPER_MODEL_SIZE}'...")
        _whisper_model = WhisperModel(_WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
        print("Whisper ready.")
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


db = None
llm = None
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

    llm = OllamaLLM(
        model=LLM_MODEL,
        base_url=OLLAMA_HOST,
        temperature=0.1,
        stop=["<|im_start|>", "<|im_end|>", "user:", "assistant:"],
    )
    print("Models loaded successfully!")
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

def _build_rag_prompt(query: str, context: str) -> str:
    return (
        "<|im_start|>system\n"
        "You are an expert medical assistant specialized in critical care and clinical medicine.\n"
        "Answer the user's question using ONLY the provided context.\n\n"
        "Answer format rules:\n"
        "1. Always state exact normal ranges or values when relevant (include units).\n"
        "2. If the question asks about pediatric vs adult differences, mention both.\n"
        "3. Write in clear, concise prose. No markdown headers or bullet dashes.\n"
        "4. Use numbered lists only when listing 3+ distinct items.\n"
        "5. If the context does not contain enough information, say exactly: "
        "'The provided documents do not contain enough information to answer this question.'\n\n"
        f"Context:\n{context}<|im_end|>\n"
        "<|im_start|>user\n"
        f"{query}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def _clean_llm_output(raw: str, query: str) -> str:
    text = raw.replace("<|im_start|>", "").replace("<|im_end|>", "")
    for role in ("assistant", "user", "system"):
        text = text.replace(role, "")
    for phrase in [
        "You are an expert medical assistant",
        "Answer the user's question",
        "Context:",
        query[:50],
    ]:
        if phrase in text:
            text = text.split(phrase)[-1]
    text = text.strip().lstrip(":").strip()
    if text.lower().startswith("answer:"):
        text = text[7:].strip()
    return text if len(text) >= 5 else raw.strip()


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
    return {
        "message": "Medical RAG API is running!",
        "model": LLM_MODEL,
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
        docs = _retrieve(query)
        context = "\n\n---\n\n".join([doc.page_content for doc in docs])
        prompt = _build_rag_prompt(query, context)
        raw = llm.invoke(prompt)
        answer = _clean_llm_output(raw, query)

        _set_cache(key, answer, len(docs))
        _save_to_django(query, answer)

        return {
            "query": query,
            "answer": answer,
            "source_documents_count": len(docs),
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
    prompt = _build_rag_prompt(query, context)
    source_count = len(docs)

    def _stream_ollama():
        full_text = ""
        try:
            resp = requests.post(
                f"{OLLAMA_HOST}/api/generate",
                json={
                    "model": LLM_MODEL,
                    "prompt": prompt,
                    "stream": True,
                    "options": {
                        "temperature": 0.1,
                        "stop": ["<|im_start|>", "<|im_end|>", "user:", "assistant:"],
                    },
                },
                stream=True,
                timeout=180,
            )
            for line in resp.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                token = data.get("response", "")
                if token:
                    full_text += token
                    yield token
                if data.get("done"):
                    break
        except Exception as e:
            yield f"\n[Error: {e}]"
            return

        clean = _clean_llm_output(full_text, query)
        _set_cache(key, clean, source_count)
        _save_to_django(query, clean)

    return StreamingResponse(_stream_ollama(), media_type="text/plain; charset=utf-8")


@app.post("/translate")
async def translate_text(request: QuestionRequest):
    """Translate English medical text to Persian (unused by UI, kept for completeness)."""
    if llm is None:
        raise HTTPException(status_code=500, detail="LLM not initialized.")
    try:
        prompt = (
            "<|im_start|>system\n"
            "You are a professional medical translator (English to Persian/Farsi). "
            "Return ONLY the Persian translation, nothing else.<|im_end|>\n"
            "<|im_start|>user\n"
            f"Translate to Persian:\n{request.query}<|im_end|>\n"
            "<|im_start|>assistant\n"
        )
        translation = llm.invoke(prompt).strip().lstrip(":").strip()
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
        audio_url = str(request.base_url) + f"voice/audio/{file_key}"
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
async def chat_voice(request: QuestionRequest):
    """
    One-shot endpoint: runs RAG retrieval + LLM answer + Persian TTS.
    Send a question, receive an MP3 file directly.
    """
    if db is None or llm is None or bm25_retriever is None:
        raise HTTPException(status_code=500, detail="System not initialized.")

    query = request.query
    key = _cache_key(query)
    cached = _get_cache(key)

    if cached:
        answer = cached["answer"]
        print(f"Cache hit (voice): {query[:60]}")
    else:
        try:
            print(f"Chat/Voice question: {query}")
            docs = _retrieve(query)
            context = "\n\n---\n\n".join([doc.page_content for doc in docs])
            prompt = _build_rag_prompt(query, context)
            raw = llm.invoke(prompt)
            answer = _clean_llm_output(raw, query)
            _set_cache(key, answer, len(docs))
            _save_to_django(query, answer)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"RAG failed: {e}")

    # Full pipeline: English answer → translate → TTS → upload to Liara
    try:
        audio_bytes = english_to_persian_voice(answer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS failed: {e}")

    try:
        file_key = upload_mp3_to_liara(audio_bytes)
        audio_url = str(request.base_url) + f"voice/audio/{file_key}"
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
    persian = translate_to_persian(answer_en)
    audio_bytes = persian_to_voice(persian)
    return persian, audio_bytes


def _worker_chat_voice(job_id: str, query: str, base_url: str) -> None:
    """Background worker: RAG → TTS → S3 upload. Updates job state throughout."""
    try:
        _update_job(job_id, status="processing", message="در حال جستجو در پایگاه دانش...")

        # Step 1: RAG
        key = _cache_key(query)
        cached = _get_cache(key)
        if cached:
            answer = cached["answer"]
        else:
            docs = _retrieve(query)
            context = "\n\n---\n\n".join([doc.page_content for doc in docs])
            prompt = _build_rag_prompt(query, context)
            _update_job(job_id, message="در حال تولید پاسخ با هوش مصنوعی...")
            raw = llm.invoke(prompt)
            answer = _clean_llm_output(raw, query)
            _set_cache(key, answer, len(docs))
            _save_to_django(query, answer)

        # Step 2: TTS (Persian answer for API + audio)
        _update_job(job_id, message="در حال تبدیل متن به صدا...")
        persian_answer, audio_bytes = _answer_to_persian_voice(answer)

        # Step 3: Upload (hard 45s deadline — executor.shutdown(wait=False) avoids blocking)
        _update_job(job_id, message="در حال آپلود فایل صوتی...")
        try:
            _up = ThreadPoolExecutor(max_workers=1)
            fut = _up.submit(upload_mp3_to_liara, audio_bytes)
            _up.shutdown(wait=False)
            file_key = fut.result(timeout=45)
            audio_url = base_url + f"voice/audio/{file_key}"
        except Exception:
            audio_url = None

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
        # Step 1: Speech-to-Text (force Persian; falls back to auto-detect if empty)
        _update_job(job_id, status="processing", message="در حال تبدیل صدا به متن...")
        whisper = _get_whisper()
        segments, info = whisper.transcribe(audio_path, beam_size=5, language="fa")
        persian_query = " ".join(seg.text for seg in segments).strip()
        print(f"STT (fa): {persian_query[:80]}")

        if not persian_query:
            _update_job(job_id, status="failed", message="صدایی شناسایی نشد.", error="Empty transcription")
            return

        # Step 2: Translate Persian question → English for RAG
        _update_job(job_id, message="در حال ترجمه سوال...")
        query = translate_to_english(persian_query)
        print(f"Translated query (en): {query[:80]}")

        # Step 3: RAG
        _update_job(job_id, message="در حال جستجو در پایگاه دانش...", answer=None)
        key = _cache_key(query)
        cached = _get_cache(key)
        if cached:
            answer = cached["answer"]
        else:
            docs = _retrieve(query)
            context = "\n\n---\n\n".join([doc.page_content for doc in docs])
            prompt = _build_rag_prompt(query, context)
            _update_job(job_id, message="در حال تولید پاسخ با هوش مصنوعی...")
            raw = llm.invoke(prompt)
            answer = _clean_llm_output(raw, query)
            _set_cache(key, answer, len(docs))
            _save_to_django(query, answer)

        # Step 4: TTS (Persian answer + audio)
        _update_job(job_id, message="در حال تبدیل متن به صدا...")
        persian_answer, audio_bytes = _answer_to_persian_voice(answer)

        # Step 5: Upload
        _update_job(job_id, message="در حال آپلود فایل صوتی...")
        try:
            _up = ThreadPoolExecutor(max_workers=1)
            fut = _up.submit(upload_mp3_to_liara, audio_bytes)
            _up.shutdown(wait=False)
            file_key = fut.result(timeout=45)
            audio_url = base_url + f"voice/audio/{file_key}"
        except Exception:
            audio_url = None

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
        try:
            _up = ThreadPoolExecutor(max_workers=1)
            fut = _up.submit(upload_mp3_to_liara, audio_bytes)
            _up.shutdown(wait=False)
            file_key = fut.result(timeout=45)
            audio_url = base_url + f"voice/audio/{file_key}"
        except Exception:
            audio_url = None

        _update_job(job_id, status="done", message="تکمیل شد.", audio_url=audio_url)

    except Exception as e:
        _update_job(job_id, status="failed", message="خطا در پردازش.", error=str(e))


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
    base_url = str(req.base_url)
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
    base_url = str(req.base_url)
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

    # Save upload to a temp file (worker reads from disk)
    suffix = "." + (file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "wav")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    job_id = _new_job()
    base_url = str(req.base_url)
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


@app.get(
    "/voice/audio/{key:path}",
    responses={200: {"content": {"audio/mpeg": {}}}, 404: {"description": "Not found"}},
    summary="Stream a stored MP3 audio file (private proxy)",
)
async def stream_audio(key: str):
    """Proxy endpoint: fetches the private MP3 from object storage and streams it."""
    filename = key.rsplit("/", 1)[-1]
    try:
        audio_bytes = download_mp3_from_storage(key)
    except RuntimeError:
        raise HTTPException(status_code=404, detail="Audio file not found.")
    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
