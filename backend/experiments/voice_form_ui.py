"""
EXPERIMENT — Minimal voice → patient form UI.

Flow:
  1. Greeting TTS once
  2. Mic / upload → STT + extract
  3. Result: review, edit, missing hints, append voice, confirm TTS, copy JSON

Does not change HakimAI /api/cases. Run (backend on :8000):
  streamlit run backend/experiments/voice_form_ui.py --server.port 8502
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

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
    confirmation_speech_fa,
    export_fields_payload,
    extract_patient_demographics,
    finalize_patient_fields,
    format_field_value,
    merge_patient_extractions,
)
from backend.api_auth import request_headers
from backend.medical_voice_utils import persian_to_voice
from backend.stt_utils import detect_audio_extension

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
MAX_WAIT = 180
GREETING = "سلام، چطوری می‌تونم کمکتون کنم؟"

_BOOL_KEYS = ("sedation_active", "recent_surgery", "fever")
_INT_KEYS = ("age", "height_cm", "rass")
_FLOAT_KEYS = ("weight_kg", "ventilator_days")

_HIDE_CHROME = """
<style>
  header, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
  [data-testid="stStatusWidget"], #MainMenu { visibility: hidden; height: 0; }
  .block-container { padding-top: 2.5rem !important; max-width: 560px; }
  [data-testid="stAudioInput"] label { display: none !important; }
  div[data-testid="stVerticalBlock"] > div:has([data-testid="stAudioInput"]) {
    display: flex; justify-content: center;
  }
  .result-card {
    margin-top: 0.75rem;
    padding: 1.15rem 1.35rem;
    border: 1px solid rgba(128,128,128,0.35);
    border-radius: 12px;
    direction: rtl;
    text-align: right;
  }
  .result-card h3 {
    margin: 0 0 0.75rem 0;
    font-size: 1.05rem;
    opacity: 0.85;
  }
  .result-card .row { margin: 0.4rem 0; font-size: 1.02rem; }
  .result-card .label { opacity: 0.6; margin-left: 0.45rem; }
  .result-card .section {
    margin-top: 0.85rem;
    padding-top: 0.55rem;
    border-top: 1px solid rgba(128,128,128,0.25);
    font-size: 0.85rem;
    opacity: 0.75;
  }
  .missing-box {
    margin-top: 0.85rem;
    padding: 0.75rem 1rem;
    border-radius: 10px;
    background: rgba(180,120,40,0.12);
    direction: rtl;
    text-align: right;
    font-size: 0.92rem;
  }
  .listening-hint {
    text-align: center; opacity: 0.45; font-size: 0.9rem; margin-top: 1rem;
    direction: rtl;
  }
</style>
"""


def _stt_extract(
    audio_bytes: bytes,
    filename: str,
    content_type: str | None,
) -> dict[str, Any]:
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
        data = r.json()
        transcript = (data.get("transcript") or "").strip()
        fields = data.get("fields")
        if isinstance(fields, dict) and ("found" in fields or "missing" in fields):
            return fields
        return extract_patient_demographics(transcript)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _play_mp3_with_gesture(mp3: bytes, *, dom_id: str = "greet") -> None:
    b64 = base64.b64encode(mp3).decode("ascii")
    st.components.v1.html(
        f"""
        <div id="tap_{dom_id}" style="position:fixed;inset:0;z-index:9999;cursor:pointer;"></div>
        <audio id="{dom_id}" preload="auto">
          <source src="data:audio/mpeg;base64,{b64}" type="audio/mpeg" />
        </audio>
        <script>
          const a = document.getElementById("{dom_id}");
          const tap = document.getElementById("tap_{dom_id}");
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


def _reset_session(*, keep_greeting: bool = False) -> None:
    st.session_state["phase"] = "listen"
    st.session_state["result"] = None
    st.session_state["last_audio_hash"] = ""
    st.session_state["error"] = ""
    st.session_state["confirm_played"] = False
    if not keep_greeting:
        st.session_state["greeting_played"] = False


def _process_audio(
    audio_bytes: bytes,
    audio_name: str,
    rec_type: str | None,
    *,
    append: bool,
) -> None:
    digest = hashlib.sha256(audio_bytes).hexdigest()
    if digest == st.session_state["last_audio_hash"] or len(audio_bytes) <= 200:
        return
    st.session_state["last_audio_hash"] = digest
    st.session_state["phase"] = "processing"
    st.session_state["error"] = ""
    try:
        parsed = _stt_extract(audio_bytes, audio_name, rec_type)
        text = (parsed.get("raw_text") or "").strip()
        if not text and not parsed.get("found"):
            st.session_state["error"] = (
                "چیزی شنیده نشد. بلندتر و کامل‌تر بگویید "
                "(مثلاً بیمار خانم سی و دو ساله قد صد و شصت)."
            )
            st.session_state["phase"] = "append" if append else "listen"
        else:
            if append and st.session_state.get("result"):
                merged = merge_patient_extractions(st.session_state["result"], parsed)
            else:
                merged = parsed
            if merged.get("found"):
                st.session_state["result"] = merged
                st.session_state["phase"] = "result"
                st.session_state["confirm_played"] = False
            else:
                st.session_state["error"] = (
                    f"شنیدم «{text}» ولی فیلدی استخراج نشد. دوباره بگویید."
                )
                st.session_state["phase"] = "append" if append else "listen"
    except Exception as e:
        st.session_state["error"] = str(e)
        st.session_state["phase"] = "append" if append else "listen"
    st.rerun()


def _clipboard_button(payload: str, *, label: str = "کپی JSON") -> None:
    # URI-encode so Persian JSON survives the HTML bridge
    from urllib.parse import quote

    encoded = quote(payload, safe="")
    st.components.v1.html(
        f"""
        <div style="direction:rtl;text-align:right;margin:0.35rem 0;">
          <button id="copyBtn" style="
            width:100%;padding:0.55rem 0.75rem;border-radius:8px;
            border:1px solid rgba(128,128,128,0.4);background:transparent;
            cursor:pointer;font-size:0.95rem;">
            {label}
          </button>
          <div id="copyMsg" style="opacity:0.55;font-size:0.8rem;margin-top:0.35rem;"></div>
        </div>
        <script>
          const decoded = decodeURIComponent("{encoded}");
          document.getElementById("copyBtn").onclick = async () => {{
            try {{
              await navigator.clipboard.writeText(decoded);
              document.getElementById("copyMsg").textContent = "کپی شد";
            }} catch (e) {{
              document.getElementById("copyMsg").textContent = "کپی نشد — از باکس JSON استفاده کنید";
            }}
          }};
        </script>
        """,
        height=72,
    )


def _render_mic_upload(*, append: bool, key_suffix: str) -> None:
    if hasattr(st, "audio_input"):
        rec = st.audio_input(
            " ",
            label_visibility="collapsed",
            key=f"mic_{key_suffix}",
        )
        if rec is not None:
            audio_bytes = rec.getvalue() if hasattr(rec, "getvalue") else rec.read()
            _process_audio(
                audio_bytes,
                getattr(rec, "name", None) or "recording.webm",
                getattr(rec, "type", None),
                append=append,
            )

    uploaded = st.file_uploader(
        "آپلود ویس",
        type=["wav", "mp3", "m4a", "ogg", "webm"],
        label_visibility="collapsed",
        key=f"upload_{key_suffix}",
    )
    hint = (
        "فیلدهای جاافتاده را بگویید یا آپلود کنید"
        if append
        else "ضبط یا آپلود فایل صوتی"
    )
    st.markdown(f'<p class="listening-hint">{hint}</p>', unsafe_allow_html=True)
    if uploaded is not None:
        _process_audio(uploaded.read(), uploaded.name, uploaded.type, append=append)


def _apply_edits_from_widgets() -> dict[str, Any]:
    current = dict(st.session_state.get("result") or {})
    edited: dict[str, Any] = {k: current.get(k) for k in FIELD_LABELS_FA}

    gender_label = st.session_state.get("edit_gender", "—")
    edited["gender"] = {"مرد": "male", "زن": "female"}.get(gender_label)

    for key in _INT_KEYS:
        raw = st.session_state.get(f"edit_{key}")
        if raw is None or raw == "" or raw == "—":
            edited[key] = None
        else:
            try:
                edited[key] = int(raw)
            except (TypeError, ValueError):
                edited[key] = current.get(key)

    for key in _FLOAT_KEYS:
        raw = st.session_state.get(f"edit_{key}")
        if raw is None or raw == "" or raw == "—":
            edited[key] = None
        else:
            try:
                edited[key] = float(raw)
            except (TypeError, ValueError):
                edited[key] = current.get(key)

    tube = st.session_state.get("edit_tube_type", "—")
    edited["tube_type"] = {"ETT": "ETT", "Trach": "Trach"}.get(tube)

    ind = st.session_state.get("edit_indication", "—")
    edited["indication"] = {"اورژانس": "emergency", "الکتیو": "elective"}.get(ind)

    covid = st.session_state.get("edit_covid_status", "—")
    edited["covid_status"] = {
        "بدون": "none",
        "خفیف": "mild",
        "متوسط": "moderate",
        "شدید": "severe",
    }.get(covid)

    for key in _BOOL_KEYS:
        label = st.session_state.get(f"edit_{key}", "—")
        edited[key] = {"بله": True, "خیر": False}.get(label)

    for key in (
        "main_diagnosis",
        "diagnosis_category",
        "secretion_intensity",
        "cxr_summary",
        "consultation_goal",
    ):
        raw = (st.session_state.get(f"edit_{key}") or "").strip()
        edited[key] = raw or None

    return finalize_patient_fields(
        edited,
        raw_text=current.get("raw_text") or "",
    )


def _render_edit_form(r: dict[str, Any]) -> None:
    st.markdown("#### ویرایش دستی")
    g_opts = ["—", "مرد", "زن"]
    g_cur = {"male": "مرد", "female": "زن"}.get(r.get("gender"), "—")
    st.selectbox("جنس", g_opts, index=g_opts.index(g_cur), key="edit_gender")

    c1, c2 = st.columns(2)
    with c1:
        st.number_input(
            "سن",
            min_value=0,
            max_value=130,
            value=int(r["age"]) if r.get("age") is not None else 0,
            key="edit_age",
        )
        st.number_input(
            "قد (cm)",
            min_value=0,
            max_value=250,
            value=int(r["height_cm"]) if r.get("height_cm") is not None else 0,
            key="edit_height_cm",
        )
        st.number_input(
            "وزن (kg)",
            min_value=0.0,
            max_value=400.0,
            value=float(r["weight_kg"]) if r.get("weight_kg") is not None else 0.0,
            step=0.5,
            key="edit_weight_kg",
        )
        st.number_input(
            "ونتیلاتور (روز)",
            min_value=0.0,
            max_value=365.0,
            value=float(r["ventilator_days"]) if r.get("ventilator_days") is not None else 0.0,
            step=0.5,
            key="edit_ventilator_days",
        )
    with c2:
        tube_opts = ["—", "ETT", "Trach"]
        tube_cur = r.get("tube_type") if r.get("tube_type") in ("ETT", "Trach") else "—"
        st.selectbox("نوع لوله", tube_opts, index=tube_opts.index(tube_cur), key="edit_tube_type")
        ind_opts = ["—", "اورژانس", "الکتیو"]
        ind_map = {"emergency": "اورژانس", "elective": "الکتیو"}
        ind_cur = ind_map.get(r.get("indication"), "—")
        st.selectbox("اندیکاسیون", ind_opts, index=ind_opts.index(ind_cur), key="edit_indication")
        st.number_input(
            "RASS",
            min_value=-5,
            max_value=4,
            value=int(r["rass"]) if r.get("rass") is not None else 0,
            key="edit_rass",
        )
        covid_opts = ["—", "بدون", "خفیف", "متوسط", "شدید"]
        covid_map = {
            "none": "بدون",
            "mild": "خفیف",
            "moderate": "متوسط",
            "severe": "شدید",
        }
        covid_cur = covid_map.get(r.get("covid_status"), "—")
        st.selectbox(
            "COVID-19",
            covid_opts,
            index=covid_opts.index(covid_cur),
            key="edit_covid_status",
        )

    bool_opts = ["—", "بله", "خیر"]
    for key, label in (
        ("sedation_active", "sedation فعال"),
        ("recent_surgery", "جراحی اخیر"),
        ("fever", "تب"),
    ):
        cur = {True: "بله", False: "خیر"}.get(r.get(key), "—")  # type: ignore[arg-type]
        st.selectbox(label, bool_opts, index=bool_opts.index(cur), key=f"edit_{key}")

    st.text_input(
        "تشخیص اصلی",
        value=r.get("main_diagnosis") or "",
        key="edit_main_diagnosis",
    )
    st.text_input(
        "دسته تشخیص",
        value=r.get("diagnosis_category") or "",
        key="edit_diagnosis_category",
    )
    st.text_input(
        "شدت ترشحات",
        value=r.get("secretion_intensity") or "",
        key="edit_secretion_intensity",
    )
    st.text_area(
        "خلاصه CXR",
        value=r.get("cxr_summary") or "",
        key="edit_cxr_summary",
        height=80,
    )
    st.text_area(
        "هدف مشاوره",
        value=r.get("consultation_goal") or "",
        key="edit_consultation_goal",
        height=80,
    )

    # number_input cannot be empty — treat 0 as empty when original was None
    # (handled in apply by re-reading; for age/height 0 is invalid clinically)
    if st.button("اعمال ویرایش", use_container_width=True, type="primary"):
        applied = _apply_edits_from_widgets()
        # Clear zero placeholders when original field was empty and user left 0
        for key in ("age", "height_cm"):
            widget_val = st.session_state.get(f"edit_{key}")
            if widget_val == 0 and r.get(key) is None:
                applied[key] = None
        for key in ("weight_kg", "ventilator_days"):
            widget_val = st.session_state.get(f"edit_{key}")
            if widget_val == 0.0 and r.get(key) is None:
                applied[key] = None
        if st.session_state.get("edit_rass") == 0 and r.get("rass") is None:
            # Ambiguous: RASS 0 is valid. Keep 0 if user touched; if never set keep None
            applied["rass"] = 0
        applied = finalize_patient_fields(applied, raw_text=r.get("raw_text") or "")
        st.session_state["result"] = applied
        st.session_state["confirm_played"] = False
        st.success("ویرایش اعمال شد.")
        st.rerun()


def _render_result(r: dict[str, Any]) -> None:
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

    missing = [k for k in (r.get("missing") or []) if k != "ibw_kg"]
    if missing:
        labels = "، ".join(FIELD_LABELS_FA[k] for k in missing[:10])
        more = " …" if len(missing) > 10 else ""
        st.markdown(
            f'<div class="missing-box">هنوز نگفتید: {labels}{more}</div>',
            unsafe_allow_html=True,
        )

    payload = json.dumps(
        export_fields_payload(r),
        ensure_ascii=False,
        indent=2,
    )
    _clipboard_button(payload)

    with st.expander("مشاهده JSON", expanded=False):
        st.code(payload, language="json")

    with st.expander("ویرایش دستی", expanded=False):
        _render_edit_form(r)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("ادامه ویس", use_container_width=True):
            st.session_state["phase"] = "append"
            st.session_state["last_audio_hash"] = ""
            st.session_state["error"] = ""
            st.rerun()
    with c2:
        if st.button("تأیید صوتی", use_container_width=True):
            try:
                phrase = confirmation_speech_fa(r)
                mp3 = persian_to_voice(phrase, timeout=90)
                _play_mp3_with_gesture(mp3, dom_id="confirm")
                st.session_state["confirm_played"] = True
                st.caption(phrase)
            except Exception as e:
                st.error(f"TTS تأیید ناموفق: {e}")

    if st.button("از نو", use_container_width=True):
        _reset_session()
        st.rerun()


# ─── Page ────────────────────────────────────────────────────────────────────

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
    ("confirm_played", False),
):
    if key not in st.session_state:
        st.session_state[key] = default

_ensure_greeting()

if not st.session_state["greeting_played"]:
    mp3 = st.session_state.get("greeting_mp3")
    if mp3:
        _play_mp3_with_gesture(mp3, dom_id="greet")
    st.session_state["greeting_played"] = True

phase = st.session_state["phase"]

if phase == "result" and st.session_state.get("result"):
    _render_result(st.session_state["result"])

elif phase == "processing":
    st.markdown('<p class="listening-hint">...</p>', unsafe_allow_html=True)

elif phase == "append":
    st.markdown(
        '<p class="listening-hint">ادامه بدهید — فیلدهای قبلی نگه داشته می‌شوند</p>',
        unsafe_allow_html=True,
    )
    _render_mic_upload(append=True, key_suffix="append")
    if st.button("بازگشت به نتیجه", use_container_width=True):
        st.session_state["phase"] = "result"
        st.rerun()
    if st.session_state.get("error"):
        st.caption(st.session_state["error"])

else:
    _render_mic_upload(append=False, key_suffix="main")
    if st.session_state.get("error"):
        st.caption(st.session_state["error"])
