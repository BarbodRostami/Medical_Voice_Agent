import os
from pathlib import Path

import requests
import streamlit as st
from medical_voice_utils import (
    clean_persian_for_tts,
    tts_to_mp3,
    translate_to_persian,
)

# ─── Config ──────────────────────────────────────────────────────────────────

APP_DIR = Path(__file__).resolve().parent
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000/chat")
BACKEND_STREAM_URL = os.getenv("BACKEND_STREAM_URL", "http://localhost:8000/chat/stream")


@st.cache_data(ttl=3600, show_spinner=False)
def cached_translate(text: str) -> str:
    return translate_to_persian(text)


@st.cache_data(ttl=3600, show_spinner=False)
def generate_audio(persian_text: str) -> bytes | None:
    """Generate MP3 from Persian text, cached per unique text."""
    clean = clean_persian_for_tts(persian_text)
    if not clean:
        return None
    try:
        return tts_to_mp3(clean, timeout=30)
    except Exception as e:
        print(f"TTS error: {e}")
        return None


# ─── Streaming ────────────────────────────────────────────────────────────────

def stream_from_backend(query: str):
    """Generator that yields text tokens from the streaming backend endpoint."""
    try:
        with requests.post(
            BACKEND_STREAM_URL,
            json={"query": query},
            stream=True,
            timeout=180,
        ) as resp:
            if resp.status_code != 200:
                yield f"Error {resp.status_code}: Could not get a response from the backend."
                return
            for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
                if chunk:
                    yield chunk
    except Exception as e:
        yield f"\nConnection error: {e}"


def get_source_count(query: str) -> int:
    """Fetch source document count (cache hit — instant after streaming)."""
    try:
        resp = requests.post(BACKEND_URL, json={"query": query}, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("source_documents_count", 0)
    except Exception:
        pass
    return 0


# ─── Page Layout ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Medical RAG Assistant",
    page_icon="🩺",
    layout="centered",
)

st.markdown(
    "<h1 style='text-align:center;color:#008080;'>🩺 Medical RAG AI Assistant</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p style='text-align:center;color:#555;'>"
    "Ask clinical or medical questions based on your loaded knowledge base."
    "</p>",
    unsafe_allow_html=True,
)
st.write("---")

# ─── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("تنظیمات")
    enable_voice = st.toggle("🔊 خروجی صوتی فارسی", value=True)
    st.caption("صدا: fa-IR-DilaraNeural")
    st.caption("ترجمه: Google Translate")

# ─── Chat History ─────────────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            if persian_text := message.get("persian_answer"):
                with st.expander("🇮🇷 متن فارسی"):
                    st.markdown(persian_text)
            if audio_bytes := message.get("audio"):
                st.audio(audio_bytes, format="audio/mp3")
            if sources := message.get("sources", 0):
                st.caption(f"📚 Based on {sources} source document(s).")

# ─── New Message ──────────────────────────────────────────────────────────────

if prompt := st.chat_input("How can I help you with your clinical query?"):
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        # Phase 1: Stream the answer token by token
        full_answer: str = st.write_stream(stream_from_backend(prompt))

        # Phase 2: Fetch source count (cache hit — instant)
        sources_count = get_source_count(prompt)

        persian_answer: str | None = None
        audio_bytes: bytes | None = None

        # Phase 3: Translate + TTS (runs after streaming so user already has text)
        if enable_voice and full_answer:
            with st.spinner("در حال ترجمه و تولید صدای فارسی..."):
                # translate_to_persian already handles abbreviation replacement internally
                persian_answer = cached_translate(full_answer)
                audio_bytes = generate_audio(persian_answer)

            if persian_answer:
                with st.expander("🇮🇷 متن فارسی"):
                    st.markdown(persian_answer)

            if audio_bytes:
                st.audio(audio_bytes, format="audio/mp3")
            else:
                st.caption("🔇 خروجی صوتی در دسترس نیست (edge-tts را بررسی کنید).")

        if sources_count > 0:
            with st.expander("📚 Reference Information"):
                st.write(
                    f"This response was cross-referenced with **{sources_count}** "
                    "medical document(s) from your vector database."
                )

        # Save to session history
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": full_answer,
                "sources": sources_count,
                "persian_answer": persian_answer,
                "audio": audio_bytes,
            }
        )
