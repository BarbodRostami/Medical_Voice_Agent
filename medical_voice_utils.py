"""
Shared voice/TTS utilities for Medical RAG project.
Used by both main_api.py (FastAPI backend) and app_ui.py (Streamlit UI).
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import os
import re
import uuid as _uuid

import boto3
import edge_tts
from botocore.config import Config as _BotocoreConfig
from botocore.exceptions import BotoCoreError, ClientError
from deep_translator import GoogleTranslator
from dotenv import load_dotenv

load_dotenv()

# ─── Constants ────────────────────────────────────────────────────────────────

TTS_VOICE = "fa-IR-DilaraNeural"
_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_s3_client: boto3.client | None = None

# Medical abbreviations → Persian equivalents
# Sorted by length (longest first) at replacement time to avoid partial matches
MEDICAL_ABBREVIATIONS: dict[str, str] = {
    "ETCO2": "دی‌اکسید کربن بازدمی",
    "EtCO2": "دی‌اکسید کربن بازدمی",
    "PaCO2": "فشار جزئی دی‌اکسید کربن شریانی",
    "PaO2": "فشار جزئی اکسیژن شریانی",
    "SpO2": "اشباع اکسیژن",
    "SaO2": "اشباع اکسیژن شریانی",
    "FiO2": "کسر اکسیژن دمی",
    "HCO3": "بیکربنات",
    "PEEP": "فشار انتهای بازدمی مثبت",
    "ARDS": "سندرم دیسترس تنفسی حاد",
    "COPD": "بیماری انسدادی مزمن ریه",
    "MAP": "فشار خون متوسط شریانی",
    "CVP": "فشار ورید مرکزی",
    "GCS": "مقیاس کمای گلاسکو",
    "ICU": "بخش مراقبت‌های ویژه",
    "CPR": "احیای قلبی ریوی",
    "AED": "دفیبریلاتور خودکار خارجی",
    "ECG": "الکتروکاردیوگرام",
    "EKG": "الکتروکاردیوگرام",
    "MRI": "تصویربرداری رزونانس مغناطیسی",
    "ABG": "گازهای خون شریانی",
    "BUN": "نیتروژن اوره خون",
    "PTT": "زمان ترومبوپلاستین نسبی",
    "INR": "نسبت بین‌المللی نرمال‌شده",
    "CHF": "نارسایی احتقانی قلب",
    "DVT": "ترومبوز ورید عمقی",
    "DKA": "کتواسیدوز دیابتی",
    "TBI": "آسیب مغزی تروماتیک",
    "FRC": "ظرفیت باقیمانده عملکردی",
    "ETT": "لوله داخل تراشه",
    "LMA": "ماسک حنجره‌ای",
    "NPO": "ناشتا",
    "PRN": "در صورت نیاز",
    "mmHg": "میلی‌متر جیوه",
    "mcg": "میکروگرم",
    "mEq": "میلی‌اکی‌والان",
    "bpm": "ضربان در دقیقه",
    "Hgb": "هموگلوبین",
    "Hct": "هماتوکریت",
    "WBC": "گلبول‌های سفید",
    "RBC": "گلبول‌های قرمز",
    "CO2": "دی‌اکسید کربن",
    "MI": "انفارکتوس میوکارد",
    "PE": "آمبولی ریه",
    "BP": "فشار خون",
    "HR": "ضربان قلب",
    "RR": "تعداد تنفس",
    "IV": "داخل وریدی",
    "IM": "داخل عضلانی",
    "SC": "زیر جلدی",
    "CT": "سی‌تی‌اسکن",
    "NG": "نازوگاستریک",
    "BE": "کسری باز",
    "TV": "حجم جاری",
    "O2": "اکسیژن",
    "pH": "پی‌اچ",
    "Hb": "هموگلوبین",
    "Na": "سدیم",
    "Ca": "کلسیم",
    "Mg": "منیزیم",
    "Cl": "کلر",
    "mL": "میلی‌لیتر",
    "ml": "میلی‌لیتر",
    "mg": "میلی‌گرم",
    "kg": "کیلوگرم",
    "K": "پتاسیم",
    "L": "لیتر",
}

# Pre-sorted by length descending (longest abbreviation replaced first)
_SORTED_ABBREVIATIONS = sorted(MEDICAL_ABBREVIATIONS.items(), key=lambda x: -len(x[0]))


# ─── Text Processing ──────────────────────────────────────────────────────────

def replace_abbreviations(text: str) -> str:
    """Replace medical abbreviations with Persian before translation.

    Processes longest abbreviations first to prevent partial matches
    (e.g. ETCO2 before CO2, PaCO2 before CO2).
    """
    for abbr, persian in _SORTED_ABBREVIATIONS:
        text = re.sub(r"\b" + re.escape(abbr) + r"\b", persian, text)
    return text


def clean_persian_for_tts(text: str) -> str:
    """Remove markdown and normalize already-translated Persian text for TTS."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"#{1,6}\s+", "", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    text = re.sub(r"\n\s*[-*•]\s+", "، ", text)
    text = re.sub(r"\n\s*\d+\.\s+", "، ", text)
    text = re.sub(r"\n+", " ", text)
    text = text.translate(_PERSIAN_DIGITS)
    text = re.sub(r"[(){}\[\]<>|\\^~]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ─── Translation ─────────────────────────────────────────────────────────────

def translate_to_english(text: str) -> str:
    """Translate Persian (or any language) medical text to English for RAG lookup."""
    try:
        result = GoogleTranslator(source="auto", target="en").translate(text)
        return result if result else text
    except Exception as e:
        print(f"Translation (→en) error: {e}")
        return text


def translate_to_persian(text: str) -> str:
    """Translate English medical text to Persian.

    Pipeline:
      1. Replace abbreviations with Persian equivalents (before Google Translate sees them)
      2. Translate with Google Translate (chunked for long texts)
    """
    text = replace_abbreviations(text)

    try:
        if len(text) <= 4500:
            result = GoogleTranslator(source="en", target="fa").translate(text)
            return result if result else text

        # Chunked translation for long texts
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks: list[str] = []
        current = ""
        for sent in sentences:
            if len(current) + len(sent) < 4500:
                current += (" " if current else "") + sent
            else:
                if current:
                    chunks.append(current)
                current = sent
        if current:
            chunks.append(current)

        parts = [GoogleTranslator(source="en", target="fa").translate(c) for c in chunks]
        return " ".join(parts)
    except Exception as e:
        print(f"Translation error: {e}")
        return text


# ─── TTS ─────────────────────────────────────────────────────────────────────

async def _tts_async(text: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice=TTS_VOICE, rate="-5%", pitch="+0Hz")
    chunks: list[bytes] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)


def tts_to_mp3(text: str, timeout: int = 60) -> bytes:
    """Convert Persian text to MP3 bytes using edge-tts.

    Runs in an isolated thread to avoid asyncio event-loop conflicts
    (safe to call from FastAPI, Streamlit, or plain scripts).
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _tts_async(text)).result(timeout=timeout)


def english_to_persian_voice(english_text: str, timeout: int = 60) -> bytes:
    """Full pipeline: English text → translate → clean → MP3 bytes."""
    persian = translate_to_persian(english_text)
    clean = clean_persian_for_tts(persian)
    return tts_to_mp3(clean, timeout=timeout)


def persian_to_voice(persian_text: str, timeout: int = 60) -> bytes:
    """Pipeline for already-Persian text: clean → MP3 bytes."""
    clean = clean_persian_for_tts(persian_text)
    return tts_to_mp3(clean, timeout=timeout)


# ─── Object Storage (S3-compatible) ──────────────────────────────────────────

def _get_s3_client() -> _S3Client:
    """Return a cached S3 client (lazy singleton)."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=os.getenv("LIARA_ENDPOINT"),
            aws_access_key_id=os.getenv("LIARA_ACCESS_KEY"),
            aws_secret_access_key=os.getenv("LIARA_SECRET_KEY"),
            region_name="us-east-1",
            config=_BotocoreConfig(
                signature_version="s3v4",
                connect_timeout=10,
                read_timeout=30,
                retries={"max_attempts": 2},
            ),
        )
    return _s3_client


def resolve_storage_key(public_key: str) -> str:
    """Map proxy URL segment to full S3 object key (audio/xxx.mp3)."""
    key = public_key.lstrip("/")
    return key if key.startswith("audio/") else f"audio/{key}"


def build_audio_proxy_url(base_url: str, public_key: str) -> str:
    """Build client-facing URL: .../voice/audio/{uuid}.mp3 (no duplicate audio/ prefix)."""
    base = base_url.rstrip("/") + "/"
    return f"{base}voice/audio/{public_key.lstrip('/')}"


def upload_mp3_to_liara(audio_bytes: bytes, filename: str | None = None) -> str:
    """Upload MP3 bytes to Object Storage and return the public proxy key.

    Args:
        audio_bytes: Raw MP3 data.
        filename: Optional object name (e.g. ``custom.mp3``). Stored under ``audio/``.

    Returns:
        Public key for ``/voice/audio/{key}`` (e.g. ``xxxx.mp3``).

    Raises:
        RuntimeError: If upload fails.
    """
    if filename is None:
        object_name = f"{_uuid.uuid4().hex}.mp3"
    else:
        object_name = filename.rsplit("/", 1)[-1]
    storage_key = resolve_storage_key(object_name)

    bucket = os.getenv("LIARA_BUCKET", "voiceai")

    try:
        s3 = _get_s3_client()
        s3.put_object(
            Bucket=bucket,
            Key=storage_key,
            Body=audio_bytes,
            ContentType="audio/mpeg",
        )
        return object_name
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"Upload failed: {e}") from e


def upload_mp3_with_timeout(audio_bytes: bytes, timeout: float = 45) -> str | None:
    """Upload MP3 with a hard deadline; returns public key or None on failure.

    Uses shutdown(wait=False) so a hung S3 call cannot block the worker after
    ``result(timeout=...)`` raises — the ``with`` form of ThreadPoolExecutor
    would call shutdown(wait=True) on exit and defeat the deadline.
    """
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(upload_mp3_to_liara, audio_bytes).result(timeout=timeout)
    except Exception:
        return None
    finally:
        pool.shutdown(wait=False)


def download_mp3_from_storage(key: str) -> bytes:
    """Download an MP3 object from private storage by public or full key."""
    bucket = os.getenv("LIARA_BUCKET", "voiceai")
    storage_key = resolve_storage_key(key)
    try:
        s3 = _get_s3_client()
        resp = s3.get_object(Bucket=bucket, Key=storage_key)
        return resp["Body"].read()
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"Download failed: {e}") from e


