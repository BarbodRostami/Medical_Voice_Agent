"""Speech-to-text helpers: audio normalization (ffmpeg) + Whisper medical transcription."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile

# Bias Whisper toward Persian medical + everyday digits (common in HakimAI tests).
WHISPER_MEDICAL_PROMPT_FA = (
    "گفتار فارسی واضح. اعداد: صفر یک دو سه چهار پنج شش هفت هشت نه ده. "
    "سلام، بیمار، فشار خون، تنفس، نبض، تب. "
    "سوال پزشکی درباره پارامترهای حیاتی و مراقبت‌های ویژه: "
    "اشباع اکسیژن SpO2، دی‌اکسید کربن ETCO2، فشار خون MAP، PEEP، لاکتات، pH، "
    "کاپنوگرافی، ونتیلاتور."
)

# Conservative fixes for frequent short-utterance Whisper FA mistakes.
_TRANSCRIPT_PHRASE_FIXES: tuple[tuple[str, str], ...] = (
    ("ایک دوسر", "یک دو سه"),
    ("ایک دو سر", "یک دو سه"),
    ("یک دوسر", "یک دو سه"),
    ("یک دو سر", "یک دو سه"),
    ("دوسر", "دو سه"),
    ("ایک ", "یک "),
)

_MIME_TO_EXT: dict[str, str] = {
    "audio/webm": ".webm",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
}


def detect_audio_extension(data: bytes, filename: str | None = None, content_type: str | None = None) -> str:
    """Pick the best file extension so decoders receive a valid container."""
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct in _MIME_TO_EXT:
            return _MIME_TO_EXT[ct]
    if filename and "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()
        if ext in {".webm", ".wav", ".mp3", ".ogg", ".m4a", ".mp4"}:
            return ext
    if len(data) >= 4 and data[:4] == b"RIFF":
        return ".wav"
    if len(data) >= 4 and data[:4] == b"\x1aE\xdf\xa3":
        return ".webm"
    if data[:3] == b"ID3" or (len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return ".mp3"
    return ".wav"


def _get_ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None


def normalize_audio_for_stt(src_path: str) -> tuple[str, bool]:
    """Convert input audio to 16 kHz mono PCM WAV. Returns (path, should_delete)."""
    ffmpeg = _get_ffmpeg()
    if not ffmpeg:
        print("Warning: ffmpeg not found — Whisper will decode raw file directly.")
        return src_path, False

    fd, dst = tempfile.mkstemp(suffix=".16k.wav")
    os.close(fd)
    try:
        subprocess.run(
            [
                ffmpeg, "-y", "-i", src_path,
                "-ar", "16000", "-ac", "1",
                "-c:a", "pcm_s16le",
                dst,
            ],
            check=True,
            capture_output=True,
            timeout=90,
        )
        return dst, True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        if os.path.exists(dst):
            os.remove(dst)
        err = getattr(e, "stderr", b"") or b""
        print(f"ffmpeg normalize failed: {err.decode(errors='ignore')[:300]}")
        return src_path, False


def _is_garbled_transcription(text: str) -> bool:
    text = text.strip()
    if len(text) < 4:
        return True
    fa = sum(1 for c in text if "\u0600" <= c <= "\u06ff")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    if fa >= 5:
        return False
    if latin >= 10:
        return False
    return True


def _beam_size() -> int:
    raw = os.getenv("WHISPER_BEAM_SIZE", "8").strip()
    try:
        n = int(raw)
    except ValueError:
        return 8
    return max(1, min(n, 20))


def normalize_transcript_fa(text: str) -> str:
    """Light cleanup + known short-phrase fixes (does not invent medical content)."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return cleaned
    for bad, good in _TRANSCRIPT_PHRASE_FIXES:
        cleaned = cleaned.replace(bad, good)
    return cleaned.strip(" ،,")


def _whisper_transcribe(model, audio_path: str, language: str | None) -> str:
    beam = _beam_size()
    kwargs: dict = dict(
        beam_size=beam,
        best_of=beam,
        patience=1.0,
        temperature=0.0,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400},
        condition_on_previous_text=False,
        initial_prompt=WHISPER_MEDICAL_PROMPT_FA,
        without_timestamps=True,
    )
    if language:
        kwargs["language"] = language
    segments, _info = model.transcribe(audio_path, **kwargs)
    return " ".join(seg.text for seg in segments).strip()


def transcribe_medical_speech(model, audio_path: str) -> str:
    """Normalize audio, transcribe in Persian, retry with auto-detect if garbled."""
    wav_path, cleanup = normalize_audio_for_stt(audio_path)
    try:
        text = _whisper_transcribe(model, wav_path, language="fa")
        if _is_garbled_transcription(text):
            try:
                print(f"STT (fa) garbled: {text[:80]!r} - retrying auto-detect", flush=True)
            except UnicodeEncodeError:
                print("STT (fa) garbled - retrying auto-detect", flush=True)
            text = _whisper_transcribe(model, wav_path, language=None)
        text = normalize_transcript_fa(text)
        try:
            print(f"STT final: {text[:200]}", flush=True)
        except UnicodeEncodeError:
            print(
                "STT final: "
                + text[:200].encode("utf-8", errors="backslashreplace").decode("ascii"),
                flush=True,
            )
        return text
    finally:
        if cleanup and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except OSError:
                pass
