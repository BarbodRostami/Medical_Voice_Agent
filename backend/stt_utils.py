"""Speech-to-text helpers: audio normalization (ffmpeg) + Whisper medical transcription.

Default STT is local faster-whisper. Optional ``STT_PROVIDER=openai`` uses an
OpenAI-compatible ``/audio/transcriptions`` API (GapGPT / OpenAI) and falls
back to local Whisper on any failure.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from typing import Any

import requests

from backend.provider_config import (
    openai_compatible_config,
    openai_stt_model,
    stt_provider,
)
# Bias Whisper toward Persian medical + everyday digits (common in HakimAI tests).
WHISPER_MEDICAL_PROMPT_FA = (
    "گفتار فارسی واضح. اعداد: صفر یک دو سه چهار پنج شش هفت هشت نه ده. "
    "سلام، بیمار، فشار خون، تنفس، نبض، تب. "
    "سوال پزشکی درباره پارامترهای حیاتی و مراقبت‌های ویژه: "
    "اشباع اکسیژن SpO2، دی‌اکسید کربن ETCO2، فشار خون MAP، PEEP، لاکتات، pH، "
    "کاپنوگرافی، ونتیلاتور."
)

# Experiment: voice → HakimAI-like patient tab. Does not affect HakimAI API.
WHISPER_FORM_PROMPT_FA = (
    "فرم بیمار ICU، تنظیمات و اندازه‌گیری ونتیلاتور، ABG و همودینامیک به فارسی. "
    "جنس مرد یا زن، سن ساله، قد سانتی‌متر، وزن کیلوگرم. "
    "مود ونتیلاتور: VCV PCV SIMV-V SIMV-P PSV CPAP APRV PRVC. "
    "PEEP set، FiO2، VT set، RR set، Pi، PS. "
    "اندازه‌گیری: RR total، RR spontaneous، VTe، Peak pressure، Plateau، "
    "PEEP measured، Auto-PEEP، Mean pressure، Driving pressure، I:E، "
    "Minute ventilation، Compliance، RSBI، Leak. "
    "ABG: pH، PaCO2، PaO2، SaO2، HCO3، Base Excess، P/F ratio. "
    "همودینامیک: SBP، DBP، MAP، HR، دما، Urine output، I&O balance، Vasopressor. "
    "مثال تنظیمات: مود VCV، PEEP پنج، FiO2 چهل، VT پانصد. "
    "مثال اندازه‌گیری: آر آر توتال بیست، وی تی ای چهارصد و پنجاه، "
    "پیک پرشر بیست و هشت، پلاتو بیست و دو، پیپ اندازه‌گیری پنج، لیک دو. "
    "مثال ABG: پی اچ هفت و سی و پنج، پی ای او دو هشتاد، فی او دو چهل. "
    "مثال همودینامیک: فشار خون صد و بیست روی هشتاد، اچ آر نود، دما سی و هفت."
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

# Extra STT cleanup for demographics form (cases + experiment).
_FORM_TRANSCRIPT_FIXES: tuple[tuple[str, str], ...] = (
    ("سیودو", "سی و دو"),
    ("سیو دو", "سی و دو"),
    ("سی ودو", "سی و دو"),
    ("چهل‌وپنج", "چهل و پنج"),
    ("چهل وپنج", "چهل و پنج"),
    ("چهل‌و پنج", "چهل و پنج"),
    ("بیست‌و", "بیست و"),
    ("خانوم", "خانم"),
    ("سانتیمتر", "سانتی متر"),
    ("سانتی‌متر", "سانتی متر"),
    # Common Whisper/GapGPT garbling on height/age phrases
    ("سنتی میت", "سانتی متر"),
    ("سنتی‌میت", "سانتی متر"),
    ("سنتی متر", "سانتی متر"),
    ("سانتی میتر", "سانتی متر"),
    ("سانتی میت", "سانتی متر"),
    ("حفتاد", "هفتاد"),
    ("حضتاد", "هفتاد"),
    ("هفتادو", "هفتاد و"),
    ("سد و", "صد و"),
    (" سد ", " صد "),
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


def normalize_transcript_fa(
    text: str,
    extra_fixes: tuple[tuple[str, str], ...] = (),
) -> str:
    """Light cleanup + known short-phrase fixes (does not invent medical content)."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return cleaned
    for bad, good in _TRANSCRIPT_PHRASE_FIXES + tuple(extra_fixes):
        cleaned = cleaned.replace(bad, good)
    return cleaned.strip(" ،,")


def _whisper_transcribe(
    model: Any,
    audio_path: str,
    language: str | None,
    initial_prompt: str | None = None,
    vad_filter: bool = True,
) -> str:
    beam = _beam_size()
    kwargs: dict = dict(
        beam_size=beam,
        best_of=beam,
        patience=1.0,
        temperature=0.0,
        vad_filter=vad_filter,
        vad_parameters={"min_silence_duration_ms": 400},
        condition_on_previous_text=False,
        initial_prompt=initial_prompt or WHISPER_MEDICAL_PROMPT_FA,
        without_timestamps=True,
    )
    if language:
        kwargs["language"] = language
    segments, _info = model.transcribe(audio_path, **kwargs)
    return " ".join(seg.text for seg in segments).strip()


def transcribe_medical_speech(model: Any, audio_path: str) -> str:
    """Normalize audio, transcribe in Persian with local Whisper, retry if garbled."""
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


def transcribe_form_demographics_speech(model: Any, audio_path: str) -> str:
    """STT biased for patient form fields (gender / age / height)."""
    wav_path, cleanup = normalize_audio_for_stt(audio_path)
    try:
        # Soft VAD: short form utterances are often clipped by aggressive VAD.
        text = _whisper_transcribe(
            model,
            wav_path,
            language="fa",
            initial_prompt=WHISPER_FORM_PROMPT_FA,
            vad_filter=False,
        )
        if _is_garbled_transcription(text) or not text.strip():
            text = _whisper_transcribe(
                model,
                wav_path,
                language="fa",
                initial_prompt=WHISPER_FORM_PROMPT_FA,
                vad_filter=True,
            )
        if _is_garbled_transcription(text):
            text = _whisper_transcribe(
                model,
                wav_path,
                language=None,
                initial_prompt=WHISPER_FORM_PROMPT_FA,
                vad_filter=False,
            )
        return normalize_transcript_fa(text, extra_fixes=_FORM_TRANSCRIPT_FIXES)
    finally:
        if cleanup and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except OSError:
                pass


def _openai_transcribe_file(
    audio_path: str,
    timeout: int = 120,
    prompt: str | None = None,
    extra_fixes: tuple[tuple[str, str], ...] = (),
) -> str:
    """OpenAI-compatible ``/audio/transcriptions`` → Persian text."""
    cfg = openai_compatible_config()
    if not cfg.configured:
        raise RuntimeError("OPENAI_API_KEY (or GAPGPT_API_KEY) is not set")

    model = openai_stt_model()
    with open(audio_path, "rb") as fh:
        response = requests.post(
            f"{cfg.base_url}/audio/transcriptions",
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            files={"file": (os.path.basename(audio_path), fh)},
            data={
                "model": model,
                "language": "fa",
                "prompt": (prompt or WHISPER_MEDICAL_PROMPT_FA)[:800],
            },
            timeout=timeout,
        )
    if response.status_code >= 400:
        raise RuntimeError(
            f"OpenAI STT HTTP {response.status_code}: {response.text[:300]}"
        )
    # JSON ``{text: ...}`` or plain text depending on provider
    ctype = (response.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        data = response.json()
        text = (data.get("text") or "").strip()
    else:
        text = response.text.strip()
    if not text:
        raise RuntimeError("OpenAI STT returned empty transcript")
    return normalize_transcript_fa(text, extra_fixes=extra_fixes)


def transcribe_medical_audio(
    audio_path: str,
    local_model_getter: Callable[[], Any],
) -> str:
    """STT entrypoint with provider switch + local fallback.

    ``STT_PROVIDER``:
      - ``local`` (default): faster-whisper via ``local_model_getter``
      - ``openai``: cloud transcriptions; on missing key / error → local
    """
    provider = stt_provider()
    if provider == "openai":
        cfg = openai_compatible_config()
        if not cfg.configured:
            print("STT_PROVIDER=openai but no API key; using local Whisper")
        else:
            try:
                # Prefer normalized WAV when possible for more stable upstream decode
                wav_path, cleanup = normalize_audio_for_stt(audio_path)
                try:
                    print(
                        f"STT provider=openai base={cfg.base_url} "
                        f"model={openai_stt_model()}"
                    )
                    text = _openai_transcribe_file(wav_path)
                    try:
                        print(f"STT cloud final: {text[:200]}", flush=True)
                    except UnicodeEncodeError:
                        print("STT cloud final: <persian>", flush=True)
                    return text
                finally:
                    if cleanup and os.path.exists(wav_path):
                        try:
                            os.remove(wav_path)
                        except OSError:
                            pass
            except Exception as e:
                print(f"OpenAI-compatible STT failed ({e}); falling back to local Whisper")
    elif provider not in ("", "local"):
        print(f"Unknown STT_PROVIDER={provider!r}; using local Whisper")

    model = local_model_getter()
    return transcribe_medical_speech(model, audio_path)
def transcribe_form_demographics_audio(
    audio_path: str,
    local_model_getter: Callable[[], Any],
) -> str:
    """Form-fill STT (used by /api/cases voice path + voice-form experiment)."""
    provider = stt_provider()
    if provider == "openai":
        cfg = openai_compatible_config()
        if cfg.configured:
            try:
                wav_path, cleanup = normalize_audio_for_stt(audio_path)
                try:
                    return _openai_transcribe_file(
                        wav_path,
                        prompt=WHISPER_FORM_PROMPT_FA,
                        extra_fixes=_FORM_TRANSCRIPT_FIXES,
                    )
                finally:
                    if cleanup and os.path.exists(wav_path):
                        try:
                            os.remove(wav_path)
                        except OSError:
                            pass
            except Exception as e:
                print(f"Form STT cloud failed ({e}); falling back to local Whisper")
    model = local_model_getter()
    return transcribe_form_demographics_speech(model, audio_path)
