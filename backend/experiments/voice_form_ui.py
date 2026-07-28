"""
EXPERIMENT — Minimal voice → patient form UI.

Flow:
  1. Nearly empty page; plays greeting TTS once
  2. Mic capture + optional audio upload
  3. After successful extract → show filled fields only

Run (backend on :8000):
  streamlit run backend/experiments/voice_form_ui.py --server.port 8502
"""
from __future__ import annotations

import base64
import hashlib
import os
import tempfile
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")

import importlib

from backend.experiments import form_extract as _form_extract

importlib.reload(_form_extract)
from backend.experiments.form_extract import (  # noqa: E402
    FIELD_LABELS_FA,
    extract_patient_demographics,
    format_field_value,
)
from backend.api_auth import request_headers
from backend.medical_voice_utils import persian_to_voice
from backend.stt_utils import detect_audio_extension

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
MAX_WAIT = 180
GREETING = "سلام، چطوری می‌تونم کمکتون کنم؟"

VALUE_TO_GENDER = {None: "", "male": "مرد", "female": "زن"}

_HIDE_CHROME = """
<style>
  header, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
  [data-testid="stStatusWidget"], #MainMenu { visibility: hidden; height: 0; }
  .block-container { padding-top: 3rem !important; max-width: 520px; }
  [data-testid="stAudioInput"] label { display: none !important; }
  div[data-testid="stVerticalBlock"] > div:has([data-testid="stAudioInput"]) {
    display: flex; justify-content: center;
  }
  .result-card {
    margin-top: 1.5rem;
    padding: 1.25rem 1.5rem;
    border: 1px solid rgba(128,128,128,0.35);
    border-radius: 12px;
    direction: rtl;
    text-align: right;
  }
  .result-card h3 {
    margin: 0 0 0.85rem 0;
    font-size: 1.05rem;
    opacity: 0.85;
  }
  .result-card .row { margin: 0.45rem 0; font-size: 1.02rem; }
  .result-card .label { opacity: 0.6; margin-left: 0.45rem; }
  .result-card .section {
    margin-top: 0.9rem;
    padding-top: 0.65rem;
    border-top: 1px solid rgba(128,128,128,0.25);
    font-size: 0.85rem;
    opacity: 0.7;
  }
  .listening-hint {
    text-align: center; opacity: 0.45; font-size: 0.9rem; margin-top: 1rem;
    direction: rtl;
  }
</style>
"""


def _transcribe_via_form_stt(
    audio_bytes: bytes,
    filename: str,
    content_type: str | None,
) -> str:
    load_dotenv(_PROJECT_ROOT / ".env", override=False)
    ext = detect_audio_extension(audio_bytes, filename, content_type)
    safe_name = filename if filename and Path(filename).suffix else f"recording{ext}"
    mime = content_type or {
        ".webm": "audio/webm",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
    }.get(ext, "application/octet-stream")

    headers = request_headers()
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(audio_bytes)
        path = tmp.name
    try:
        with open(path, "rb") as f:
            r = requests.post(
                f"{API_BASE}/experiments/voice-form/stt",
                files={"file": (safe_name, f, mime)},
                headers=headers,
                timeout=MAX_WAIT,
            )
        if r.status_code == 401:
            raise RuntimeError(
                "کلید API قبول نشد. مطمئن شو فایل .env برای Streamlit و backend یکی است."
            )
        if r.status_code == 404:
            raise RuntimeError("Backend را ری‌استارت کنید (endpoint آزمایشی موجود نیست).")
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail") or r.text[:200]
            except Exception:
                detail = r.text[:200]
            raise RuntimeError(f"خطای سرور ({r.status_code}): {detail}")
        return (r.json().get("transcript") or "").strip()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _play_mp3_with_gesture(mp3: bytes) -> None:
    b64 = base64.b64encode(mp3).decode("ascii")
    st.components.v1.html(
        f"""
        <div id="tap" style="position:fixed;inset:0;z-index:9999;cursor:pointer;"></div>
        <audio id="greet" preload="auto">
          <source src="data:audio/mpeg;base64,{b64}" type="audio/mpeg" />
        </audio>
        <script>
          const a = document.getElementById("greet");
          const tap = document.getElementById("tap");
          const tryPlay = () => a.play().then(() => tap.remove()).catch(() => {{}});
          tryPlay();
          tap.addEventListener("click", () => {{ tryPlay(); }}, {{ once: true }});
          window.addEventListener("pointerdown", () => {{ tryPlay(); }}, {{ once: true }});
        </script>
        """,
        height=0,
    )


def _ensure_greeting() -> None:
    if st.session_state.get("greeting_ready"):
        return
    try:
        st.session_state["greeting_mp3"] = persian_to_voice(GREETING, timeout=90)
    except Exception as e:
        st.session_state["greeting_mp3"] = None
        st.session_state["greeting_error"] = str(e)
    st.session_state["greeting_ready"] = True


def _process_audio(audio_bytes: bytes, audio_name: str, rec_type: str | None) -> None:
    digest = hashlib.sha256(audio_bytes).hexdigest()
    if digest == st.session_state["last_audio_hash"] or len(audio_bytes) <= 200:
        return
    st.session_state["last_audio_hash"] = digest
    st.session_state["phase"] = "processing"
    st.session_state["error"] = ""
    try:
        text = _transcribe_via_form_stt(audio_bytes, audio_name, rec_type)
        if not text:
            st.session_state["error"] = (
                "چیزی شنیده نشد. بلندتر و کامل‌تر بگویید "
                "(مثلاً بیمار خانم سی و دو ساله قد صد و شصت)."
            )
            st.session_state["phase"] = "listen"
        else:
            parsed = extract_patient_demographics(text)
            if parsed.get("found"):
                st.session_state["result"] = parsed
                st.session_state["phase"] = "result"
            else:
                st.session_state["error"] = (
                    f"شنیدم «{text}» ولی فیلدی استخراج نشد. دوباره بگویید."
                )
                st.session_state["phase"] = "listen"
    except Exception as e:
        st.session_state["error"] = str(e)
        st.session_state["phase"] = "listen"
    st.rerun()


st.set_page_config(page_title=" ", layout="centered", initial_sidebar_state="collapsed")
st.markdown(_HIDE_CHROME, unsafe_allow_html=True)

for key, default in (
    ("phase", "listen"),
    ("greeting_ready", False),
    ("greeting_mp3", None),
    ("greeting_played", False),
    ("last_audio_hash", ""),
    ("result", None),
    ("error", ""),
):
    if key not in st.session_state:
        st.session_state[key] = default

_ensure_greeting()

if not st.session_state["greeting_played"]:
    mp3 = st.session_state.get("greeting_mp3")
    if mp3:
        _play_mp3_with_gesture(mp3)
    st.session_state["greeting_played"] = True

phase = st.session_state["phase"]

if phase == "result" and st.session_state.get("result"):
    r = st.session_state["result"]
    rows: list[str] = []
    for key, label in FIELD_LABELS_FA.items():
        if key not in (r.get("found") or []):
            continue
        val = format_field_value(key, r.get(key))
        rows.append(
            f'<div class="row"><span class="label">{label}</span>'
            f"<strong>{val}</strong></div>"
        )
    transcript = (r.get("raw_text") or "").strip()
    transcript_html = (
        f'<div class="section">متن: {transcript}</div>' if transcript else ""
    )
    st.markdown(
        f"""
        <div class="result-card" dir="rtl">
          <h3>اطلاعات استخراج‌شده</h3>
          {"".join(rows) if rows else "<div class='row'>—</div>"}
          {transcript_html}
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)
    if st.button("دوباره", use_container_width=True):
        st.session_state["phase"] = "listen"
        st.session_state["result"] = None
        st.session_state["last_audio_hash"] = ""
        st.session_state["error"] = ""
        st.session_state["greeting_played"] = False
        st.rerun()

elif phase == "processing":
    st.markdown('<p class="listening-hint">...</p>', unsafe_allow_html=True)

else:
    if hasattr(st, "audio_input"):
        rec = st.audio_input(" ", label_visibility="collapsed", key="mic")
        if rec is not None:
            audio_bytes = rec.getvalue() if hasattr(rec, "getvalue") else rec.read()
            _process_audio(
                audio_bytes,
                getattr(rec, "name", None) or "recording.webm",
                getattr(rec, "type", None),
            )

    uploaded = st.file_uploader(
        "آپلود ویس",
        type=["wav", "mp3", "m4a", "ogg", "webm"],
        label_visibility="collapsed",
        key="upload_audio",
    )
    st.markdown(
        '<p class="listening-hint">ضبط یا آپلود فایل صوتی</p>',
        unsafe_allow_html=True,
    )
    if uploaded is not None:
        _process_audio(uploaded.read(), uploaded.name, uploaded.type)

    if st.session_state.get("error"):
        st.caption(st.session_state["error"])
