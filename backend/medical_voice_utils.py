"""
Shared voice/TTS utilities for Medical RAG project.
Used by both backend.main_api (FastAPI) and backend.app_ui (Streamlit UI).
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import os
import re
import uuid as _uuid

import boto3
import edge_tts
import requests
from botocore.config import Config as _BotocoreConfig
from botocore.exceptions import BotoCoreError, ClientError
from deep_translator import GoogleTranslator
from dotenv import load_dotenv

from backend.provider_config import (
    openai_compatible_config,
    openai_speech_llm_model,
    openai_tts_model,
    openai_tts_voice,
    speech_normalize_llm_enabled,
    tts_digit_mode,
    tts_provider,
)

load_dotenv()

# ─── Constants ────────────────────────────────────────────────────────────────

TTS_VOICE = "fa-IR-DilaraNeural"
_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
# Eastern + Arabic-Indic digits → ASCII (OpenAI-compatible TTS often skips Persian digits)
_TO_ASCII_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)
_s3_client: boto3.client | None = None

# Small integers → spoken Persian (optional TTS_DIGIT_MODE=words)
_ONES_FA = (
    "صفر",
    "یک",
    "دو",
    "سه",
    "چهار",
    "پنج",
    "شش",
    "هفت",
    "هشت",
    "نه",
)
_TEENS_FA = (
    "ده",
    "یازده",
    "دوازده",
    "سیزده",
    "چهارده",
    "پانزده",
    "شانزده",
    "هفده",
    "هجده",
    "نوزده",
)
_TENS_FA = (
    "",
    "",
    "بیست",
    "سی",
    "چهل",
    "پنجاه",
    "شصت",
    "هفتاد",
    "هشتاد",
    "نود",
)
_HUNDREDS_FA = (
    "",
    "صد",
    "دویست",
    "سیصد",
    "چهارصد",
    "پانصد",
    "ششصد",
    "هفتصد",
    "هشتصد",
    "نهصد",
)

# Medical abbreviations → speakable Persian (longest match first at runtime)
MEDICAL_ABBREVIATIONS: dict[str, str] = {
    "ETCO2": "دی‌اکسید کربن بازدمی",
    "EtCO2": "دی‌اکسید کربن بازدمی",
    "PaCO2": "فشار جزئی دی‌اکسید کربن شریانی",
    "PaO2": "فشار جزئی اکسیژن شریانی",
    "SpO2": "اشباع اکسیژن",
    "SaO2": "اشباع اکسیژن شریانی",
    "FiO2": "کسر اکسیژن دمی",
    "HCO3": "بیکربنات",
    "PEEP": "فشار مثبت انتهای بازدمی",
    "BiPAP": "بای‌پپ",
    "CPAP": "سی‌پپ",
    "NIV": "تهویه غیرتهاجمی",
    "ARDS": "سندرم دیسترس تنفسی حاد",
    "COPD": "بیماری انسدادی مزمن ریه",
    "COVID": "کووید",
    "COVID-19": "کووید نوزده",
    "SOFA": "نمره سوفا",
    "APACHE": "آپاچی",
    "MAP": "فشار خون متوسط شریانی",
    "CVP": "فشار ورید مرکزی",
    "GCS": "مقیاس کمای گلاسکو",
    "ICU": "آی‌سی‌یو",
    "CCU": "سی‌سی‌یو",
    "OR": "اتاق عمل",
    "ER": "اورژانس",
    "CPR": "احیای قلبی ریوی",
    "AED": "دفیبریلاتور خودکار خارجی",
    "ECG": "نوار قلب",
    "EKG": "نوار قلب",
    "MRI": "ام‌آر‌آی",
    "ABG": "گازهای خون شریانی",
    "BUN": "نیتروژن اوره خون",
    "PTT": "زمان ترومبوپلاستین نسبی",
    "INR": "آی‌ان‌آر",
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
    "cmH2O": "سانتی‌متر آب",
    "mcg": "میکروگرم",
    "mEq": "میلی‌اکی‌والان",
    "bpm": "ضربان در دقیقه",
    "Hgb": "هموگلوبین",
    "Hct": "هماتوکریت",
    "WBC": "گلبول‌های سفید",
    "RBC": "گلبول‌های قرمز",
    "PLT": "پلاکت",
    "CO2": "دی‌اکسید کربن",
    "MI": "انفارکتوس میوکارد",
    "PE": "آمبولی ریه",
    "BP": "فشار خون",
    "HR": "ضربان قلب",
    "RR": "تعداد تنفس",
    "IV": "داخل وریدی",
    "IM": "داخل عضلانی",
    "SC": "زیر جلدی",
    "PO": "خوراکی",
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

# Letter/digit spelling for leftover Latin tokens (e.g. rare acronyms)
_LATIN_CHAR_FA: dict[str, str] = {
    "A": "ای",
    "B": "بی",
    "C": "سی",
    "D": "دی",
    "E": "ای",
    "F": "اف",
    "G": "جی",
    "H": "اچ",
    "I": "آی",
    "J": "جی",
    "K": "کی",
    "L": "ال",
    "M": "ام",
    "N": "ان",
    "O": "او",
    "P": "پی",
    "Q": "کیو",
    "R": "آر",
    "S": "اس",
    "T": "تی",
    "U": "یو",
    "V": "وی",
    "W": "دبلیو",
    "X": "ایکس",
    "Y": "وای",
    "Z": "زد",
    "0": "صفر",
    "1": "یک",
    "2": "دو",
    "3": "سه",
    "4": "چهار",
    "5": "پنج",
    "6": "شش",
    "7": "هفت",
    "8": "هشت",
    "9": "نه",
}

# Pre-sorted by length descending (longest abbreviation replaced first)
_SORTED_ABBREVIATIONS = sorted(MEDICAL_ABBREVIATIONS.items(), key=lambda x: -len(x[0]))


# ─── Text Processing ──────────────────────────────────────────────────────────

def replace_abbreviations(text: str) -> str:
    """Replace medical abbreviations with Persian (longest match first).

    Short tokens (len <= 2) stay case-sensitive to avoid false positives
    (e.g. ``OR`` must not replace English ``or``).
    Longer tokens are matched case-insensitively (``spo2`` → اشباع اکسیژن).
    """
    for abbr, persian in _SORTED_ABBREVIATIONS:
        pattern = r"\b" + re.escape(abbr) + r"\b"
        if len(abbr) <= 2:
            text = re.sub(pattern, persian, text)
        else:
            text = re.sub(pattern, persian, text, flags=re.IGNORECASE)
    return text


def _spell_latin_token(token: str) -> str:
    """Spell leftover Latin/digit tokens so TTS does not invent English words."""
    if not token:
        return token
    # Keep pure numbers; persian digit map runs later.
    if token.isdigit():
        return token
    chars = [_LATIN_CHAR_FA.get(ch.upper(), ch) for ch in token if ch.isalnum()]
    return "‌".join(chars) if chars else token


def _should_spell_latin_token(token: str) -> bool:
    """Only spell acronym-like leftovers; leave normal lowercase words alone."""
    letters = [c for c in token if c.isalpha()]
    if len(token) < 2 or not letters:
        return False
    if any(c.isdigit() for c in token):
        return True
    upper = sum(1 for c in letters if c.isupper())
    # All-caps or mostly-caps short tokens (SpO2-style already handled earlier)
    if upper == len(letters):
        return True
    if len(token) <= 5 and upper >= max(1, len(letters) // 2):
        return True
    return False


def expand_remaining_latin_for_speech(text: str) -> str:
    """Spell remaining Latin acronym-like tokens in Persian letters."""

    def _repl(match: re.Match[str]) -> str:
        token = match.group(0)
        if not _should_spell_latin_token(token):
            return token
        return _spell_latin_token(token)

    return re.sub(r"[A-Za-z][A-Za-z0-9\-]*", _repl, text)


def _int_to_persian_words(n: int) -> str:
    """Convert 0..9999 to spoken Persian words (medical vitals / doses)."""
    if n < 0 or n > 9999:
        return str(n)
    if n < 10:
        return _ONES_FA[n]
    if n < 20:
        return _TEENS_FA[n - 10]
    if n < 100:
        tens, ones = divmod(n, 10)
        if ones == 0:
            return _TENS_FA[tens]
        return f"{_TENS_FA[tens]} و {_ONES_FA[ones]}"
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        if rest == 0:
            return _HUNDREDS_FA[hundreds]
        return f"{_HUNDREDS_FA[hundreds]} و {_int_to_persian_words(rest)}"
    thousands, rest = divmod(n, 1000)
    head = "هزار" if thousands == 1 else f"{_int_to_persian_words(thousands)} هزار"
    if rest == 0:
        return head
    return f"{head} و {_int_to_persian_words(rest)}"


def _number_token_to_speech(token: str, mode: str) -> str:
    """Normalize one numeric token (optional decimal) for speech."""
    if mode == "persian":
        return token.translate(_PERSIAN_DIGITS)
    if mode != "words":
        return token  # ascii
    if "." in token:
        left, _, right = token.partition(".")
        if left.isdigit() and right.isdigit() and len(left) <= 4 and len(right) <= 4:
            left_w = _int_to_persian_words(int(left))
            # Spell decimal digits one-by-one (e.g. 3.5 → سه ممیز پنج)
            right_w = " ".join(_ONES_FA[int(d)] for d in right)
            return f"{left_w} ممیز {right_w}"
        return token
    if token.isdigit() and len(token) <= 4:
        return _int_to_persian_words(int(token))
    return token


def normalize_digits_for_speech(text: str) -> str:
    """Normalize digits for any TTS provider.

    ``TTS_DIGIT_MODE``:
      - ``ascii`` (default): Persian/Arabic digits → 0-9. Safe for GapGPT / OpenAI TTS.
      - ``words``: small integers → spoken Persian (بهتر برای شنیدن اعداد پزشکی).
      - ``persian``: ASCII → Persian digits (legacy preference for some edge voices).
    """
    text = text.translate(_TO_ASCII_DIGITS)
    mode = tts_digit_mode()

    def _repl(match: re.Match[str]) -> str:
        return _number_token_to_speech(match.group(0), mode)

    # Integers or simple decimals (35, 3.5, 92) — not list markers already flattened
    return re.sub(r"\d+(?:\.\d+)?", _repl, text)


_SPEECH_LLM_SYSTEM = (
    "تو ویرایشگر متن برای تبدیل گفتار فارسی پزشکی هستی.\n"
    "قوانین سخت:\n"
    "1) فقط یک پاراگراف گفتاری روان برگردان؛ بدون توضیح، بدون بولت، بدون نقل‌قول.\n"
    "2) معنا و اعداد را عوض نکن؛ اختصارات را به فارسی گفتاری باز کن.\n"
    "3) ترتیب طبیعی فارسی: «اشباع اکسیژن بیمار برابر 92 درصد» نه «بیمار اشباع اکسیژن برابر».\n"
    "4) بین پارامترها ویرگول بگذار و جمله را با «است» تمام کن.\n"
    "5) اعداد را با رقم انگلیسی (0-9) نگه دار مگر اینکه در ورودی واژه باشند.\n"
    "مثال ورودی: بیمار SpO2 برابر 92 درصد، PEEP برابر 8 و ETCO2 برابر 35 است.\n"
    "مثال خروجی: اشباع اکسیژن بیمار برابر 92 درصد، فشار مثبت انتهای بازدمی برابر 8، "
    "و دی‌اکسید کربن بازدمی برابر 35 است."
)


def _llm_speech_normalize(text: str, timeout: int = 45) -> str:
    """Optional OpenAI-compatible chat rewrite for speech. Raises on failure."""
    cfg = openai_compatible_config()
    if not cfg.configured:
        raise RuntimeError("OPENAI_API_KEY not set for SPEECH_NORMALIZE_LLM")

    model = openai_speech_llm_model()
    response = requests.post(
        f"{cfg.base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": 0.15,
            "messages": [
                {"role": "system", "content": _SPEECH_LLM_SYSTEM},
                {"role": "user", "content": text[:6000]},
            ],
        },
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Speech LLM HTTP {response.status_code}: {response.text[:300]}"
        )
    data = response.json()
    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    out = (content or "").strip()
    # Strip accidental quotes / markdown fences from some chat models
    out = re.sub(r"^```(?:\w+)?\s*", "", out)
    out = re.sub(r"\s*```$", "", out)
    out = out.strip().strip("\"'«»")
    if not out:
        raise RuntimeError("Speech LLM returned empty content")
    return out


# Unique Persian vital phrases (longest first) for spoken word-order polish
_SPOKEN_VITAL_PHRASES: tuple[str, ...] = tuple(
    sorted({p for p in MEDICAL_ABBREVIATIONS.values() if len(p) >= 3}, key=len, reverse=True)
)


def polish_spoken_phrasing(text: str) -> str:
    """Cheap rule-based polish so TTS sounds less like raw abbreviation expansion.

    Example: «بیمار اشباع اکسیژن برابر 92» → «اشباع اکسیژن بیمار برابر 92»
    """
    if not text:
        return text
    out = text
    for vital in _SPOKEN_VITAL_PHRASES:
        out = re.sub(
            rf"(?<!\S)بیمار\s+{re.escape(vital)}\s+برابر",
            f"{vital} بیمار برابر",
            out,
        )
    # Comma before «و <next vital>» — avoid touching «نود و دو»
    out = re.sub(
        r"(?<![،,])\s+و\s+(?=(?:فشار|اشباع|دی‌اکسید|دی اکسید|کسر|نمره|بای|سی‌پپ))",
        "، و ",
        out,
    )
    out = re.sub(r"\s+", " ", out).strip()
    out = out.replace("،، و ", "، و ")
    return out


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
    text = normalize_digits_for_speech(text)
    text = re.sub(r"[(){}\[\]<>|\\^~]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def prepare_text_for_tts(text: str, *, use_llm: bool | None = None) -> str:
    """Full speech-prep pipeline used before any TTS provider.

    1) Expand known medical abbreviations to Persian
    2) Spell leftover Latin tokens
    3) Clean markdown / digits / punctuation for speech
    4) Rule-based spoken phrasing polish
    5) Optional LLM polish when ``SPEECH_NORMALIZE_LLM=1`` (or ``use_llm=True``);
       falls back to dictionary + phrasing on any failure

    Provider-agnostic: same prep feeds edge-tts or OpenAI-compatible cloud TTS.
    """
    prepared = replace_abbreviations(text or "")
    prepared = expand_remaining_latin_for_speech(prepared)
    prepared = clean_persian_for_tts(prepared)
    prepared = polish_spoken_phrasing(prepared)

    want_llm = speech_normalize_llm_enabled() if use_llm is None else use_llm
    if want_llm and prepared:
        try:
            polished = _llm_speech_normalize(prepared)
            # Re-run digit/abbrev/phrasing safety on LLM output
            polished = replace_abbreviations(polished)
            polished = clean_persian_for_tts(polished)
            polished = polish_spoken_phrasing(polished)
            if polished:
                print(f"Speech normalize LLM ok (model={openai_speech_llm_model()})")
                return polished
        except Exception as e:
            print(f"Speech normalize LLM failed ({e}); using dictionary prep")
    return prepared


# ─── Translation ─────────────────────────────────────────────────────────────

def translate_to_english(text: str) -> str:
    """Translate Persian (or any language) medical text to English for RAG lookup."""
    try:
        result = GoogleTranslator(source="auto", target="en").translate(text)
        return result if result else text
    except Exception as e:
        print(f"Translation (to en) error: {e}")
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

async def _edge_tts_async(text: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice=TTS_VOICE, rate="-5%", pitch="+0Hz")
    chunks: list[bytes] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)


def _edge_tts_mp3(text: str, timeout: int = 60) -> bytes:
    """Convert Persian text to MP3 bytes using edge-tts (default / fallback)."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _edge_tts_async(text)).result(timeout=timeout)


def _openai_tts_mp3(text: str, timeout: int = 60) -> bytes:
    """OpenAI-compatible Audio Speech API → MP3 bytes (no local GPU)."""
    cfg = openai_compatible_config()
    if not cfg.configured:
        raise RuntimeError("OPENAI_API_KEY (or GAPGPT_API_KEY) is not set")

    model = openai_tts_model()
    voice = openai_tts_voice()

    response = requests.post(
        f"{cfg.base_url}/audio/speech",
        headers={
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "input": text[:4096],
            "voice": voice,
            "response_format": "mp3",
        },
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"OpenAI TTS HTTP {response.status_code}: {response.text[:300]}"
        )
    audio = response.content
    if not audio:
        raise RuntimeError("OpenAI TTS returned empty audio")
    return audio


def tts_to_mp3(text: str, timeout: int = 60) -> bytes:
    """Convert speech-ready text to MP3.

    Provider from ``TTS_PROVIDER``:
      - ``edge`` (default): Microsoft edge-tts, no API key — always the local fallback
      - ``openai``: OpenAI-compatible ``/audio/speech`` (OpenAI, GapGPT, …).
        If key missing or any error → edge-tts (project never hard-depends on paid TTS)

    Safe to call from FastAPI, Streamlit, or plain scripts.
    """
    provider = tts_provider()
    if provider == "openai":
        cfg = openai_compatible_config()
        if not cfg.configured:
            print("TTS_PROVIDER=openai but no API key; using edge-tts")
            return _edge_tts_mp3(text, timeout=timeout)
        try:
            print(
                f"TTS provider=openai base={cfg.base_url} "
                f"model={openai_tts_model()} voice={openai_tts_voice()}"
            )
            return _openai_tts_mp3(text, timeout=timeout)
        except Exception as e:
            print(f"OpenAI-compatible TTS failed ({e}); falling back to edge-tts")
            return _edge_tts_mp3(text, timeout=timeout)
    if provider not in ("", "edge"):
        print(f"Unknown TTS_PROVIDER={provider!r}; using edge-tts")
    return _edge_tts_mp3(text, timeout=timeout)


def english_to_persian_voice(english_text: str, timeout: int = 60) -> bytes:
    """Full pipeline: English text → translate → speech-prep → MP3 bytes."""
    persian = translate_to_persian(english_text)
    clean = prepare_text_for_tts(persian)
    return tts_to_mp3(clean, timeout=timeout)


def persian_to_voice(persian_text: str, timeout: int = 60) -> bytes:
    """Pipeline for already-Persian text: speech-prep → MP3 bytes."""
    clean = prepare_text_for_tts(persian_text)
    return tts_to_mp3(clean, timeout=timeout)


# ─── Object Storage (S3-compatible) ──────────────────────────────────────────

def _get_s3_client() -> boto3.client:
    """Return a cached S3 client (lazy singleton).

    Parmin must be reached **directly from this machine** — never via HTTP(S) proxy
    (proxy causes SSL/read timeouts to ``sas.amin.parminstorage.ir``).
    """
    global _s3_client
    if _s3_client is None:
        # Ensure env proxy vars cannot redirect Parmin traffic for this process.
        endpoint = (os.getenv("LIARA_ENDPOINT") or "").strip()
        host = ""
        if endpoint:
            from urllib.parse import urlparse

            host = urlparse(endpoint).hostname or ""
        existing = os.getenv("NO_PROXY") or os.getenv("no_proxy") or ""
        bypass = {
            "localhost",
            "127.0.0.1",
            "sas.amin.parminstorage.ir",
            "parminstorage.ir",
        }
        if host:
            bypass.add(host)
        merged = ",".join(sorted({*existing.split(","), *bypass} - {""}))
        os.environ["NO_PROXY"] = merged
        os.environ["no_proxy"] = merged

        _s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint or None,
            aws_access_key_id=os.getenv("LIARA_ACCESS_KEY"),
            aws_secret_access_key=os.getenv("LIARA_SECRET_KEY"),
            region_name="us-east-1",
            config=_BotocoreConfig(
                signature_version="s3v4",
                connect_timeout=20,
                read_timeout=90,
                retries={"max_attempts": 4, "mode": "standard"},
                # Explicit empty dict = do not use system/env HTTP(S)_PROXY.
                proxies={},
            ),
        )
    return _s3_client


def resolve_storage_key(public_key: str) -> str:
    """Map proxy URL segment to full S3 object key.

    - ``audio/...`` legacy clips
    - ``cases/...`` internal case metadata
    - ``YYYY-MM-DD/{uuid}.mp3`` HakimAI TTS poll keys
    """
    key = public_key.lstrip("/")
    if key.startswith(("audio/", "cases/")):
        return key
    if re.match(r"^\d{4}-\d{2}-\d{2}/", key):
        return key
    return f"audio/{key}"


def build_audio_proxy_url(base_url: str, public_key: str) -> str:
    """Build client-facing URL: .../voice/audio/{key} (supports dated keys)."""
    base = base_url.rstrip("/") + "/"
    return f"{base}voice/audio/{public_key.lstrip('/')}"


def _bucket_name() -> str:
    return os.getenv("LIARA_BUCKET", "voiceai")


def put_storage_object(key: str, body: bytes, content_type: str) -> str:
    """Upload bytes to a full storage key."""
    storage_key = resolve_storage_key(key)
    try:
        s3 = _get_s3_client()
        s3.put_object(
            Bucket=_bucket_name(),
            Key=storage_key,
            Body=body,
            ContentType=content_type,
        )
        return storage_key
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"Upload failed: {e}") from e


def get_storage_object(key: str) -> bytes:
    """Download an object by public or full storage key."""
    storage_key = resolve_storage_key(key)
    try:
        s3 = _get_s3_client()
        resp = s3.get_object(Bucket=_bucket_name(), Key=storage_key)
        return resp["Body"].read()
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"Download failed: {e}") from e


def storage_object_exists(key: str) -> bool:
    """Return True if the object exists in the configured bucket."""
    storage_key = resolve_storage_key(key)
    try:
        s3 = _get_s3_client()
        s3.head_object(Bucket=_bucket_name(), Key=storage_key)
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise RuntimeError(f"Head object failed: {e}") from e
    except BotoCoreError as e:
        raise RuntimeError(f"Head object failed: {e}") from e


def put_json_to_storage(key: str, payload: dict) -> str:
    """Serialize ``payload`` as UTF-8 JSON and upload it."""
    import json

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return put_storage_object(key, body, "application/json")


def get_json_from_storage(key: str) -> dict:
    """Download a JSON object and parse it."""
    import json

    raw = get_storage_object(key)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("Stored JSON is not an object.")
    return data


def upload_mp3_to_liara(audio_bytes: bytes, filename: str | None = None) -> str:
    """Upload MP3 bytes to Object Storage and return the public proxy key.

    Args:
        audio_bytes: Raw MP3 data.
        filename: Optional object name. May be ``audio/...``, ``cases/...``,
            or dated ``YYYY-MM-DD/{uuid}.mp3``.

    Returns:
        Public key for ``/voice/audio/{key}``.

    Raises:
        RuntimeError: If upload fails.
    """
    if filename is None:
        object_name = f"{_uuid.uuid4().hex}.mp3"
        storage_key = resolve_storage_key(object_name)
        public_key = object_name
    elif filename.startswith(("audio/", "cases/")) or re.match(
        r"^\d{4}-\d{2}-\d{2}/", filename
    ):
        storage_key = resolve_storage_key(filename)
        public_key = storage_key
    else:
        object_name = filename.rsplit("/", 1)[-1]
        storage_key = resolve_storage_key(object_name)
        public_key = object_name

    put_storage_object(storage_key, audio_bytes, "audio/mpeg")
    return public_key


def upload_mp3_with_timeout(audio_bytes: bytes, timeout: float = 90) -> str | None:
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


def upload_mp3_to_key_with_timeout(
    audio_bytes: bytes,
    storage_key: str,
    timeout: float = 90,
) -> str | None:
    """Upload MP3 to an explicit storage key with a hard deadline."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(upload_mp3_to_liara, audio_bytes, storage_key).result(
            timeout=timeout
        )
    except Exception:
        return None
    finally:
        pool.shutdown(wait=False)


def download_mp3_from_storage(key: str) -> bytes:
    """Download an MP3 object from private storage by public or full key."""
    return get_storage_object(key)


