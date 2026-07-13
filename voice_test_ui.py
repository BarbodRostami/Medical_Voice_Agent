"""
Local voice test UI — record Persian speech, get RAG answer, play MP3.

Run (backend must be on :8000):
    streamlit run voice_test_ui.py
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import requests
import streamlit as st

from medical_voice_utils import persian_to_voice
from stt_utils import detect_audio_extension

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
POLL_SEC = 3
MAX_WAIT = 300


def _poll_job(job_id: str, status_box: st.empty, progress: st.progress) -> dict:
    start = time.time()
    while time.time() - start < MAX_WAIT:
        r = requests.get(f"{API_BASE}/jobs/{job_id}", timeout=15)
        r.raise_for_status()
        data = r.json()
        elapsed = int(time.time() - start)
        status_box.info(f"⏳ [{elapsed}s] {data.get('message', data.get('status'))}")
        if data["status"] == "done":
            progress.progress(100)
            return data
        if data["status"] == "failed":
            st.error(data.get("error") or "خطا در پردازش")
            return data
        progress.progress(min(90, int(elapsed / MAX_WAIT * 90)))
        time.sleep(POLL_SEC)
    return {"status": "timeout"}


def _submit_stt(audio_bytes: bytes, filename: str, content_type: str | None = None) -> str:
    ext = detect_audio_extension(audio_bytes, filename, content_type)
    safe_name = filename if filename and Path(filename).suffix else f"recording{ext}"
    mime = content_type or {
        ".webm": "audio/webm",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
    }.get(ext, "application/octet-stream")

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(audio_bytes)
        path = tmp.name
    try:
        with open(path, "rb") as f:
            r = requests.post(
                f"{API_BASE}/stt/ask",
                files={"file": (safe_name, f, mime)},
                timeout=30,
            )
        r.raise_for_status()
        return r.json()["job_id"]
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _answer_to_mp3(answer_fa: str) -> bytes:
    return persian_to_voice(answer_fa)


st.set_page_config(page_title="تست صوتی", page_icon="🎤", layout="centered")
st.title("🎤 تست صوتی لوکال")
st.caption(f"Backend: `{API_BASE}`")

with st.sidebar:
    st.markdown("### راه‌اندازی")
    st.code("python main_api.py", language="bash")
    st.code("streamlit run voice_test_ui.py", language="bash")
    if st.button("بررسی اتصال"):
        try:
            h = requests.get(f"{API_BASE}/", timeout=5).json()
            st.success(h.get("message", "OK"))
        except Exception as e:
            st.error(str(e))

tab_voice, tab_report, tab_text = st.tabs(
    ["🎙 صدا → جواب صوتی", "📋 گزارش پزشکی", "💬 سوال متنی"]
)

# ─── Tab 1: Voice in → voice out ─────────────────────────────────────────────
with tab_voice:
    st.markdown("سوال را **فارسی** و **واضح** بگویید (حداقل ۵ ثانیه).")
    st.caption("مثال: «محدوده طبیعی اشباع اکسیژن چقدر است؟» یا «ETCO2 نرمال چند است؟»")

    audio_data = None
    audio_name = "recording.wav"
    rec_type: str | None = None

    if hasattr(st, "audio_input"):
        rec = st.audio_input("ضبط از میکروفون")
        if rec is not None:
            audio_data = rec.getvalue() if hasattr(rec, "getvalue") else rec.read()
            audio_name = getattr(rec, "name", None) or "recording.webm"
            rec_type = getattr(rec, "type", None)
            st.audio(audio_data, format=rec_type or "audio/webm")

    st.markdown("**یا** فایل صوتی آپلود کنید:")
    uploaded = st.file_uploader("MP3 / WAV", type=["mp3", "wav", "m4a", "ogg"])
    if uploaded is not None:
        audio_data = uploaded.read()
        audio_name = uploaded.name
        rec_type = uploaded.type
        st.audio(audio_data)

    if st.button("🚀 ارسال و دریافت جواب صوتی", type="primary", disabled=audio_data is None):
        status_box = st.empty()
        progress = st.progress(0)
        try:
            job_id = _submit_stt(audio_data, audio_name, rec_type)
            st.success(f"Job: `{job_id[:8]}...`")
            result = _poll_job(job_id, status_box, progress)
        except requests.RequestException as e:
            st.error(f"خطای API: {e}")
            st.stop()

        if result.get("status") != "done":
            st.error(result.get("message") or "پردازش کامل نشد.")
            if result.get("error"):
                st.caption(f"جزئیات: {result['error']}")
            if result.get("transcription"):
                st.info(f"متن شنیده‌شده: {result['transcription']}")
            st.warning(
                "اگر متن شنیده‌شده اشتباه است: نزدیک میکروفون صحبت کنید، "
                "سروصدا را کم کنید، و یک سوال پزشکی واضح بپرسید."
            )
            st.stop()

        st.markdown("---")
        st.markdown("**متن تشخیص‌داده‌شده:**")
        st.info(result.get("transcription") or "—")
        if result.get("query_en"):
            st.caption(f"سوال (en): {result['query_en']}")

        answer = (result.get("answer") or "").strip()
        answer_en = (result.get("answer_en") or "").strip()
        st.markdown("**پاسخ (فارسی):**")
        if answer:
            st.success(answer)
        elif answer_en:
            st.warning("ترجمه فارسی موجود نیست — پاسخ انگلیسی:")
            st.info(answer_en)
            answer = answer_en
        else:
            st.error("پاسخی دریافت نشد.")
            st.stop()

        if result.get("audio_url"):
            st.markdown("**پخش از storage:**")
            st.audio(result["audio_url"])
        elif answer:
            with st.spinner("ساخت فایل صوتی..."):
                try:
                    mp3 = _answer_to_mp3(answer)
                    st.markdown("**پخش جواب:**")
                    st.audio(mp3, format="audio/mp3")
                except Exception as e:
                    st.error(f"TTS خطا: {e}")

# ─── Tab 2: Medical report ───────────────────────────────────────────────────
with tab_report:
    tafsir = st.text_area("تفسیر بالینی", height=120)
    recom = st.text_area("توصیه‌های درمانی", height=120)
    if st.button("🔊 ساخت صدا از گزارش", type="primary"):
        if not tafsir.strip() and not recom.strip():
            st.warning("حداقل یکی از فیلدها را پر کنید.")
        else:
            payload = {"local-test": {"tafsir": tafsir.strip(), "recom": recom.strip()}}
            try:
                r = requests.post(f"{API_BASE}/jobs/voice-report", json=payload, timeout=15)
                r.raise_for_status()
                job_id = r.json()["job_id"]
                status_box = st.empty()
                progress = st.progress(0)
                result = _poll_job(job_id, status_box, progress)
                if result.get("status") == "done" and result.get("audio_url"):
                    st.audio(result["audio_url"])
                elif result.get("status") == "done":
                    full = f"تفسیر بالینی. {tafsir}  توصیه‌های درمانی. {recom}"
                    st.audio(persian_to_voice(full), format="audio/mp3")
            except requests.RequestException as e:
                st.error(str(e))

# ─── Tab 3: Text question ────────────────────────────────────────────────────
with tab_text:
    query = st.text_input("سوال پزشکی (انگلیسی بهتر است)", placeholder="What is the normal SpO2 range?")
    if st.button("پرسش + جواب صوتی", type="primary") and query.strip():
        try:
            r = requests.post(f"{API_BASE}/jobs/chat", json={"query": query.strip()}, timeout=15)
            r.raise_for_status()
            job_id = r.json()["job_id"]
            status_box = st.empty()
            progress = st.progress(0)
            result = _poll_job(job_id, status_box, progress)
            if result.get("status") == "done":
                st.success(result.get("answer", ""))
                if result.get("audio_url"):
                    st.audio(result["audio_url"])
                elif result.get("answer"):
                    st.audio(persian_to_voice(result["answer"]), format="audio/mp3")
        except requests.RequestException as e:
            st.error(str(e))
