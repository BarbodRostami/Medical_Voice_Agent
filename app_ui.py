import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import requests
import streamlit as st
from deep_translator import GoogleTranslator

APP_DIR = Path(__file__).resolve().parent
PIPER_MODEL = APP_DIR / "fa_IR-amir-medium.onnx"
translator_to_fa = GoogleTranslator(source="en", target="fa")


def get_piper_executable() -> str | None:
    piper = shutil.which("piper")
    if piper:
        return piper
    venv_piper = APP_DIR / "venv311" / "Scripts" / "piper.exe"
    if venv_piper.exists():
        return str(venv_piper)
    return None


def translate_to_persian(text: str) -> str:
    try:
        return translator_to_fa.translate(text)
    except Exception:
        return text


def speak_farsi_to_wav(text: str) -> bytes | None:
    piper_exe = get_piper_executable()
    if not piper_exe or not PIPER_MODEL.exists():
        return None

    clean_text = text.replace('"', "").replace("'", "").replace("\n", " ").strip()
    if not clean_text:
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        txt_path = Path(tmpdir) / "input.txt"
        wav_path = Path(tmpdir) / "output.wav"
        txt_path.write_text(clean_text, encoding="utf-8")

        result = subprocess.run(
            [
                piper_exe,
                "--model",
                str(PIPER_MODEL),
                "--input_file",
                str(txt_path),
                "--output_file",
                str(wav_path),
                "--length_scale",
                "1.1",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not wav_path.exists():
            return None
        return wav_path.read_bytes()


def render_voice_output(answer: str) -> tuple[str | None, bytes | None]:
    persian_answer = translate_to_persian(answer)
    audio_bytes = speak_farsi_to_wav(persian_answer)
    return persian_answer, audio_bytes


# تنظیمات ظاهری صفحه
st.set_page_config(
    page_title="Medical RAG Assistant",
    page_icon="🩺",
    layout="centered",
)

# هدر برنامه
st.markdown(
    "<h1 style='text-align: center; color: #008080;'>🩺 Medical RAG AI Assistant</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p style='text-align: center;'>Ask clinical or medical questions based on your loaded knowledge base.</p>",
    unsafe_allow_html=True,
)
st.write("---")

# آدرس API بک‌اند (اگر در داکر کامپوز باشد از نام سرویس و در غیر این صورت از localhost استفاده می‌کند)
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000/chat")
enable_voice = st.sidebar.toggle("🔊 خروجی صوتی فارسی", value=True)

# مقداردهی اولیه به تاریخچه چت در Session State
if "messages" not in st.session_state:
    st.session_state.messages = []

# نمایش پیام‌های قبلی چت
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            if persian_text := message.get("persian_answer"):
                with st.expander("🇮🇷 متن فارسی"):
                    st.markdown(persian_text)
            if audio_bytes := message.get("audio"):
                st.audio(audio_bytes, format="audio/wav")
        if "sources" in message and message["sources"] > 0:
            st.caption(f"📚 Calculated using {message['sources']} source documents.")

# دریافت سوال جدید از کاربر
if prompt := st.chat_input("How can I help you with your clinical query?"):
    with st.chat_message("user"):
        st.markdown(prompt)

    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        with st.spinner("Analyzing medical documents and generating response..."):
            try:
                response = requests.post(BACKEND_URL, json={"query": prompt}, timeout=400)

                if response.status_code == 200:
                    data = response.json()
                    answer = data.get("answer", "No response generated.")
                    sources_count = data.get("source_documents_count", 0)

                    st.markdown(answer)

                    persian_answer = None
                    audio_bytes = None
                    if enable_voice:
                        with st.spinner("در حال تولید صدای فارسی..."):
                            persian_answer, audio_bytes = render_voice_output(answer)
                        if persian_answer:
                            with st.expander("🇮🇷 متن فارسی"):
                                st.markdown(persian_answer)
                        if audio_bytes:
                            st.audio(audio_bytes, format="audio/wav")
                        elif enable_voice:
                            st.caption("🔇 خروجی صوتی در دسترس نیست. Piper یا مدل فارسی را بررسی کنید.")

                    if sources_count > 0:
                        with st.expander("📚 Reference Information"):
                            st.write(
                                f"This response was cross-referenced with **{sources_count}** "
                                "medical documents extracted from your vector database."
                            )

                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": answer,
                            "sources": sources_count,
                            "persian_answer": persian_answer,
                            "audio": audio_bytes,
                        }
                    )
                else:
                    st.error("⚠️ Error: Backend API returned an unsuccessful status code.")
            except Exception as e:
                st.error(f"⚠️ Connection Error: Could not connect to the medical backend. Details: {e}")
