"""
EXPERIMENT — Voice → fill patient demographics form (gender / age / height).

Isolated from production UI. Does **not** change HakimAI or main RAG flows.

Prerequisites:
  1. Backend running (for STT via /api/cases):
       uvicorn backend.main_api:app --host 0.0.0.0 --port 8000
  2. From project root:
       streamlit run backend/experiments/voice_form_ui.py

You can also paste transcript text only (no mic) to test extraction.
"""
from __future__ import annotations

import os
import tempfile
import time
import uuid
from pathlib import Path

import requests
import streamlit as st

from backend.api_auth import request_headers
from backend.experiments.form_extract import (
    extract_patient_demographics,
    gender_label_fa,
)
from backend.stt_utils import detect_audio_extension

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
POLL_SEC = 2
MAX_WAIT = 180

GENDER_OPTIONS = ["", "مرد", "زن"]
GENDER_TO_VALUE = {"": None, "مرد": "male", "زن": "female"}
VALUE_TO_GENDER = {None: "", "male": "مرد", "female": "زن"}


def _transcribe_via_cases(audio_bytes: bytes, filename: str, content_type: str | None) -> str:
    """Use existing collaborator STT path (no RAG)."""
    ext = detect_audio_extension(audio_bytes, filename, content_type)
    safe_name = filename if filename and Path(filename).suffix else f"recording{ext}"
    mime = content_type or {
        ".webm": "audio/webm",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
    }.get(ext, "application/octet-stream")

    case_id = f"form-exp-{uuid.uuid4().hex[:12]}"
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(audio_bytes)
        path = tmp.name
    try:
        with open(path, "rb") as f:
            r = requests.post(
                f"{API_BASE}/api/cases",
                files={"file": (safe_name, f, mime)},
                data={"uuid": case_id},
                headers=request_headers(),
                timeout=60,
            )
        r.raise_for_status()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    start = time.time()
    while time.time() - start < MAX_WAIT:
        s = requests.get(
            f"{API_BASE}/api/get-msg",
            params={"uuid": case_id},
            headers=request_headers(),
            timeout=15,
        )
        s.raise_for_status()
        data = s.json()
        status = data.get("status")
        if status == "ready":
            return (data.get("text") or data.get("transcript") or "").strip()
        if status == "failed":
            raise RuntimeError(data.get("error") or "STT failed")
        time.sleep(POLL_SEC)
    raise TimeoutError("STT timed out")


def _apply_to_session(parsed: dict) -> None:
    st.session_state["form_gender"] = VALUE_TO_GENDER.get(parsed.get("gender"), "")
    st.session_state["form_age"] = (
        int(parsed["age"]) if parsed.get("age") is not None else None
    )
    st.session_state["form_height"] = (
        int(parsed["height_cm"]) if parsed.get("height_cm") is not None else None
    )
    st.session_state["form_transcript"] = parsed.get("raw_text") or ""
    st.session_state["form_missing"] = parsed.get("missing") or []


st.set_page_config(page_title="آزمایش فرم از ویس", page_icon="🧪", layout="centered")
st.title("🧪 آزمایش: پر کردن فرم از ویس")
st.caption(
    "برنچ آزمایشی — روی قرارداد HakimAI اثری ندارد. "
    f"Backend: `{API_BASE}`"
)

with st.sidebar:
    st.markdown("### راه‌اندازی")
    st.code("uvicorn backend.main_api:app --host 0.0.0.0 --port 8000")
    st.code("streamlit run backend/experiments/voice_form_ui.py")
    st.info("فیلدها: جنس · سن · قد (cm)")

# Defaults once
for key, default in (
    ("form_gender", ""),
    ("form_age", None),
    ("form_height", None),
    ("form_transcript", ""),
    ("form_missing", []),
):
    if key not in st.session_state:
        st.session_state[key] = default

st.subheader("۱) ورودی")
mode = st.radio("روش", ["ضبط / آپلود ویس", "فقط متن (بدون STT)"], horizontal=True)

transcript_in = ""
if mode == "فقط متن (بدون STT)":
    transcript_in = st.text_area(
        "متن شنیده‌شده (یا فرضی)",
        value="بیمار آقای ۴۵ ساله با قد ۱۷۵ سانتی‌متر",
        height=100,
    )
    if st.button("استخراج و پر کردن فرم", type="primary"):
        _apply_to_session(extract_patient_demographics(transcript_in))
        st.success("فرم به‌روز شد.")
else:
    st.markdown(
        "مثال بگویید: «بیمار خانم ۳۲ ساله، قد ۱۶۰ سانتی‌متر»"
    )
    audio_data = None
    audio_name = "recording.wav"
    rec_type: str | None = None

    if hasattr(st, "audio_input"):
        rec = st.audio_input("ضبط از میکروفون")
        if rec is not None:
            audio_data = rec.getvalue() if hasattr(rec, "getvalue") else rec.read()
            audio_name = getattr(rec, "name", None) or "recording.webm"
            rec_type = getattr(rec, "type", None)

    uploaded = st.file_uploader("یا فایل صوتی", type=["mp3", "wav", "m4a", "ogg", "webm"])
    if uploaded is not None:
        audio_data = uploaded.read()
        audio_name = uploaded.name
        rec_type = uploaded.type

    if st.button("🎤 ویس → فرم", type="primary", disabled=audio_data is None):
        with st.spinner("در حال تشخیص گفتار..."):
            try:
                text = _transcribe_via_cases(audio_data, audio_name, rec_type)
            except Exception as e:
                st.error(f"خطای STT: {e}")
                st.stop()
        if not text:
            st.warning("متنی تشخیص داده نشد.")
            st.stop()
        parsed = extract_patient_demographics(text)
        _apply_to_session(parsed)
        st.success("فرم از روی ویس پر شد.")

st.subheader("۲) متن تشخیص‌داده‌شده")
st.info(st.session_state["form_transcript"] or "— هنوز چیزی نیست —")
if st.session_state["form_missing"]:
    st.caption("یافت‌نشده: " + ", ".join(st.session_state["form_missing"]))

st.subheader("۳) اطلاعات بیمار")
with st.form("patient_demo_form"):
    gender_label = st.selectbox(
        "جنس *",
        options=GENDER_OPTIONS,
        index=GENDER_OPTIONS.index(st.session_state["form_gender"])
        if st.session_state["form_gender"] in GENDER_OPTIONS
        else 0,
        format_func=lambda x: "انتخاب کنید" if x == "" else x,
    )
    age_val = st.number_input(
        "سن * (سال)",
        min_value=0,
        max_value=130,
        value=int(st.session_state["form_age"] or 0),
        step=1,
    )
    height_val = st.number_input(
        "قد (cm)",
        min_value=0,
        max_value=250,
        value=int(st.session_state["form_height"] or 0),
        step=1,
    )
    submitted = st.form_submit_button("ثبت / نمایش")

if submitted:
    st.session_state["form_gender"] = gender_label
    st.session_state["form_age"] = age_val or None
    st.session_state["form_height"] = height_val or None
    st.json(
        {
            "gender": GENDER_TO_VALUE.get(gender_label),
            "gender_fa": gender_label or None,
            "age": age_val or None,
            "height_cm": height_val or None,
            "transcript": st.session_state["form_transcript"],
        }
    )

st.divider()
st.caption(f"استخراج نمونه: {gender_label_fa('male')} / سن / قد — فقط آزمایش")
