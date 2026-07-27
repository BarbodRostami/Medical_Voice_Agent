"""EXPERIMENT ONLY — extract HakimAI-like patient-tab fields from Persian speech.

Isolated from production HakimAI contract. Used by ``voice_form_ui.py``.
"""
from __future__ import annotations

import re
from typing import Any, Literal

Gender = Literal["male", "female"]

EXTRACT_VERSION = "patient-tab-v1"

# Persian labels for UI (order matters for display)
FIELD_LABELS_FA: dict[str, str] = {
    "gender": "جنس",
    "age": "سن (سال)",
    "height_cm": "قد (cm)",
    "weight_kg": "وزن واقعی (kg)",
    "ibw_kg": "IBW (محاسباتی)",
    "ventilator_days": "مدت روی ونتیلاتور (روز)",
    "tube_type": "نوع لوله",
    "indication": "اندیکاسیون",
    "rass": "RASS",
    "covid_status": "وضعیت COVID-19",
    "main_diagnosis": "تشخیص اصلی",
    "diagnosis_category": "دسته تشخیص",
    "sedation_active": "sedation فعال",
    "recent_surgery": "جراحی اخیر",
    "fever": "تب",
    "secretion_intensity": "شدت ترشحات",
    "cxr_summary": "خلاصه CXR",
    "consultation_goal": "سوال / هدف مشاوره",
}

DIAGNOSIS_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ARDS", ("ards", "آردز", "ای آر دی اس")),
    ("COPD", ("copd", "سی او پی دی", "انسدادی مزمن")),
    ("Pneumonia", ("پنومونی", "ذات الریه", "ذات‌الریه", "pneumonia")),
    ("Neuromuscular", ("عصبی عضلانی", "عصبی-عضلانی", "neuromuscular")),
    ("Heart Failure", ("نارسایی قلب", "heart failure", "hf")),
    ("Sepsis", ("سپسیس", "sepsis", "عفونت خون")),
    ("Post-surgery", ("پس از جراحی", "بعد از جراحی", "post-surgery", "post surgery")),
)

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

_MALE = re.compile(
    r"(?:مرد|آقا(?:ی|یی)?|پسر|آقاه?|male|man|mr\.?)",
    re.IGNORECASE,
)
_FEMALE = re.compile(
    r"(?:زن|خانم|خانوم|بانو|دختر|female|woman|mrs?\.?|miss)",
    re.IGNORECASE,
)

_UNITS: dict[str, int] = {
    "صفر": 0,
    "یک": 1,
    "دو": 2,
    "سه": 3,
    "چهار": 4,
    "پنج": 5,
    "شش": 6,
    "هفت": 7,
    "هشت": 8,
    "نه": 9,
}
_TEENS: dict[str, int] = {
    "ده": 10,
    "یازده": 11,
    "دوازده": 12,
    "سیزده": 13,
    "چهارده": 14,
    "پانزده": 15,
    "شانزده": 16,
    "هفده": 17,
    "هجده": 18,
    "نوزده": 19,
}
_TENS: dict[str, int] = {
    "بیست": 20,
    "سی": 30,
    "چهل": 40,
    "پنجاه": 50,
    "شصت": 60,
    "هفتاد": 70,
    "هشتاد": 80,
    "نود": 90,
}
_ALL_WORDS = {**_UNITS, **_TEENS, **_TENS, "صد": 100, "یکصد": 100}

_AGE_DIGITS = re.compile(
    r"(?:"
    r"سن(?:\s*(?:بیمار|او|ایشان))?\s*(?:حدود|تقریباً|تقریبا)?\s*[:\-]?\s*(\d{1,3})"
    r"|"
    r"(\d{1,3})\s*(?:ساله|سالگی|(?<![آ-ی])سال(?![آ-ی]))"
    r")"
)

_HEIGHT_DIGITS = re.compile(
    r"(?:"
    r"قد(?:\s*(?:بیمار|او|ایشان))?\s*(?:حدود|تقریباً|تقریبا)?\s*[:\-]?\s*(\d{2,3})"
    r"(?:\s*(?:سانتی[\s\-]?متر|سانت(?:ی)?|cm|سم))?"
    r"|"
    r"(\d{2,3})\s*(?:سانتی[\s\-]?متر|سانت(?:ی)?|cm)"
    r")",
    re.IGNORECASE,
)


def normalize_persian_digits(text: str) -> str:
    return text.translate(_PERSIAN_DIGITS)


def normalize_persian_text(text: str) -> str:
    t = normalize_persian_digits(text or "")
    t = t.replace("\u064a", "\u06cc")
    t = t.replace("\u0649", "\u06cc")
    t = t.replace("\u0643", "\u06a9")
    t = t.replace("\u200c", " ")
    t = t.replace("\u200f", "").replace("\u200e", "")
    t = t.replace("،", " ").replace(",", " ").replace(";", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def persian_spoken_number(phrase: str) -> int | None:
    raw = normalize_persian_text(phrase)
    raw = re.sub(r"[.\-]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return int(float(raw))
    parts = [p for p in re.split(r"\s+و\s+|\s+", raw) if p]
    if not parts:
        return None
    total = 0
    for p in parts:
        if p not in _ALL_WORDS:
            return None
        total += _ALL_WORDS[p]
    return total if total > 0 else None


def _trailing_number_phrase(left: str) -> str | None:
    tokens = left.split()
    chunk: list[str] = []
    for tok in reversed(tokens):
        if tok == "و" or tok.replace(".", "", 1).isdigit() or tok in _ALL_WORDS:
            chunk.append(tok)
            continue
        break
    chunk.reverse()
    while chunk and chunk[0] == "و":
        chunk.pop(0)
    return " ".join(chunk) if chunk else None


def compute_ibw_kg(gender: Gender | None, height_cm: int | None) -> float | None:
    """Devine IBW (kg) from gender + height."""
    if gender is None or height_cm is None or height_cm < 100:
        return None
    inches = height_cm / 2.54
    if gender == "male":
        ibw = 50.0 + 2.3 * (inches - 60.0)
    else:
        ibw = 45.5 + 2.3 * (inches - 60.0)
    return round(max(ibw, 0.0), 1)


def _extract_gender(text: str) -> Gender | None:
    if _MALE.search(text) and not _FEMALE.search(text):
        return "male"
    if _FEMALE.search(text) and not _MALE.search(text):
        return "female"
    if _MALE.search(text) and _FEMALE.search(text):
        m_pos = _MALE.search(text)
        f_pos = _FEMALE.search(text)
        assert m_pos and f_pos
        return "male" if m_pos.start() < f_pos.start() else "female"
    return None


def _extract_age(text: str) -> int | None:
    for m in re.finditer(r"([^\n]{0,40}?)\s*(?:ساله|سالگی)\b", text):
        phrase = _trailing_number_phrase(m.group(1).strip())
        if not phrase:
            continue
        val = persian_spoken_number(phrase)
        if val is not None and 0 < val < 130:
            return val
    age_m = _AGE_DIGITS.search(text)
    if age_m:
        digits = next(g for g in age_m.groups() if g)
        val = int(digits)
        if 0 < val < 130:
            return val
    return None


def _extract_height(text: str) -> int | None:
    for m in re.finditer(
        r"([^\n]{0,50}?)\s*(?:سانتی[\s\-]?متر|سانت(?:ی)?|cm|سم)\b",
        text,
        flags=re.IGNORECASE,
    ):
        phrase = _trailing_number_phrase(m.group(1).strip())
        if not phrase:
            continue
        val = persian_spoken_number(phrase)
        if val is not None and 40 <= val <= 250:
            return val
    m = re.search(
        r"قد(?:\s*(?:بیمار|او|ایشان))?\s*(?:حدود|تقریباً|تقریبا)?\s*[:\-]?\s*"
        r"((?:[^\s]+(?:\s+و\s+[^\s]+){0,4}|\d{2,3}))",
        text,
    )
    if m:
        val = persian_spoken_number(m.group(1))
        if val is not None and 40 <= val <= 250:
            return val
    h_m = _HEIGHT_DIGITS.search(text)
    if h_m:
        digits = next(g for g in h_m.groups() if g)
        val = int(digits)
        if 40 <= val <= 250:
            return val
    return None


def _extract_weight(text: str) -> float | None:
    m = re.search(
        r"وزن(?:\s*(?:واقعی|بدن|بیمار))?\s*(?:حدود|تقریباً|تقریبا)?\s*[:\-]?\s*"
        r"(\d{2,3}(?:\.\d+)?)",
        text,
    )
    if m:
        val = float(m.group(1))
        if 20 <= val <= 300:
            return val
    m = re.search(r"(\d{2,3}(?:\.\d+)?)\s*(?:کیلو(?:گرم)?|kg)\b", text, re.I)
    if m:
        val = float(m.group(1))
        if 20 <= val <= 300:
            return val
    # spoken: وزن هفتاد کیلو
    m = re.search(
        r"وزن(?:\s*(?:واقعی|بدن|بیمار))?\s*(?:حدود|تقریباً|تقریبا)?\s*[:\-]?\s*"
        r"((?:[^\s]+(?:\s+و\s+[^\s]+){0,3}))\s*(?:کیلو(?:گرم)?|kg)?",
        text,
    )
    if m:
        val = persian_spoken_number(m.group(1))
        if val is not None and 20 <= val <= 300:
            return float(val)
    return None


def _extract_ventilator_days(text: str) -> float | None:
    m = re.search(
        r"(?:مدت\s*)?(?:روی\s*)?ونتیلاتور\s*(?:حدود|تقریباً|تقریبا)?\s*[:\-]?\s*"
        r"(\d{1,3}(?:\.\d+)?)\s*(?:روز|day)?",
        text,
        re.I,
    )
    if m:
        return float(m.group(1))
    m = re.search(r"(\d{1,3}(?:\.\d+)?)\s*روز\s*(?:ونتیلاتور|ventilator)", text, re.I)
    if m:
        return float(m.group(1))
    m = re.search(
        r"((?:[^\s]+(?:\s+و\s+[^\s]+){0,2}))\s*روز\s*(?:ونتیلاتور|ventilator)",
        text,
        re.I,
    )
    if m:
        val = persian_spoken_number(m.group(1))
        if val is not None and 0 < val < 365:
            return float(val)
    return None


def _extract_tube_type(text: str) -> str | None:
    t = text.lower()
    if re.search(r"تراک(?:ئوستومی)?|trach|tracheostom", t, re.I):
        return "Trach"
    if re.search(r"\bett\b|لوله\s*(?:دهان|تراشه)|اندوتراک|endotrach", t, re.I):
        return "ETT"
    return None


def _extract_indication(text: str) -> str | None:
    if re.search(r"اورژانس|اضطراری|emergency", text, re.I):
        return "emergency"
    if re.search(r"الکتیو|انتخابی|elective", text, re.I):
        return "elective"
    return None


def _extract_bool_flag(text: str, patterns: tuple[str, ...]) -> bool | None:
    """Detect yes/no for a clinical flag.

    Prefer explicit polarity next to the keyword so unrelated «ندارد»
    (e.g. «جراحی اخیر ندارد sedation فعال») does not flip another flag.
    """
    joined = "|".join(patterns)
    if re.search(
        rf"(?:{joined})\s*(?:دارد|فعال|مثبت|هست|بله|yes)",
        text,
        re.I,
    ):
        return True
    if re.search(
        rf"(?:{joined})\s*(?:ندارد|منفی|نیست|نه|غیرفعال|no)",
        text,
        re.I,
    ):
        return False
    if re.search(rf"(?:بدون|فاقد)\s*(?:{joined})", text, re.I):
        return False
    # «ندارد X» only when X starts immediately after ندارد (same clause)
    if re.search(rf"ندارد\s+(?:{joined})", text, re.I):
        return False
    if re.search(joined, text, re.I):
        return True
    return None


def _extract_rass(text: str) -> int | None:
    m = re.search(r"(?:rass|راس)\s*[:\-]?\s*([+\-]\d{1,2})", text, re.I)
    if m:
        val = int(m.group(1))
        if -5 <= val <= 4:
            return val
    m = re.search(
        r"(?:rass|راس)\s*[:\-]?\s*منفی\s*(یک|دو|سه|چهار|پنج|\d)",
        text,
        re.I,
    )
    if m:
        raw = m.group(1)
        val = persian_spoken_number(raw) if not raw.isdigit() else int(raw)
        if val is not None and 1 <= val <= 5:
            return -val
    m = re.search(r"(?:rass|راس)\s*[:\-]?\s*(\d{1,2})", text, re.I)
    if m:
        val = int(m.group(1))
        if -5 <= val <= 4:
            return val
    return None


def _extract_covid(text: str) -> str | None:
    if not re.search(r"covid|کووید|کرونا", text, re.I):
        return None
    if re.search(r"شدید|severe", text, re.I):
        return "severe"
    if re.search(r"متوسط|moderate", text, re.I):
        return "moderate"
    if re.search(r"خفیف|mild", text, re.I):
        return "mild"
    if re.search(r"بدون|منفی|ندارد|none", text, re.I):
        return "none"
    return None


def _extract_diagnosis_category(text: str) -> str | None:
    low = text.lower()
    for label, keys in DIAGNOSIS_CATEGORIES:
        for k in keys:
            if k.lower() in low:
                return label
    return None


def _extract_secretion(text: str) -> str | None:
    if re.search(r"ترشح(?:ات)?\s*(?:خیلی\s*)?زیاد|ترشح\s*شدید|profuse", text, re.I):
        return "زیاد"
    if re.search(r"ترشح(?:ات)?\s*متوسط|moderate\s*secret", text, re.I):
        return "متوسط"
    if re.search(r"ترشح(?:ات)?\s*(?:کم|خفیف)|minimal\s*secret", text, re.I):
        return "کم"
    if re.search(r"بدون\s*ترشح|ترشح\s*ندارد", text, re.I):
        return "ندارد"
    return None


def _extract_after_keyword(text: str, keywords: tuple[str, ...], max_len: int = 120) -> str | None:
    for kw in keywords:
        m = re.search(
            rf"{kw}\s*[:\-]?\s*(.+?)(?=(?:تشخیص|دسته|cxr|رادیو|جنس|سن|قد|وزن|ونتیلاتور|rass|تب|جراحی|$))",
            text,
            re.I | re.S,
        )
        if m:
            val = m.group(1).strip(" .،-")
            val = re.sub(r"\s+", " ", val)
            if 2 <= len(val) <= max_len:
                return val
    return None


def format_field_value(key: str, value: Any) -> str:
    """Human-readable Persian value for UI."""
    if value is None:
        return "—"
    if key == "gender":
        return "مرد" if value == "male" else "زن" if value == "female" else str(value)
    if key in ("sedation_active", "recent_surgery", "fever"):
        return "بله" if value else "خیر"
    if key == "tube_type":
        return "ETT (دهان)" if value == "ETT" else "Trach (تراکئوستومی)" if value == "Trach" else str(value)
    if key == "indication":
        return "اورژانس" if value == "emergency" else "الکتیو" if value == "elective" else str(value)
    if key == "covid_status":
        return {
            "none": "بدون",
            "mild": "خفیف",
            "moderate": "متوسط",
            "severe": "شدید",
        }.get(str(value), str(value))
    if key == "height_cm":
        return f"{value} cm"
    if key == "weight_kg":
        return f"{value} kg"
    if key == "ibw_kg":
        return f"{value} kg"
    if key == "ventilator_days":
        return f"{value} روز"
    return str(value)


def extract_patient_demographics(transcript: str) -> dict[str, Any]:
    """Parse patient-tab fields from free Persian (or mixed) text.

    Backward-compatible name; returns flat keys + found/missing lists.
    """
    raw = (transcript or "").strip()
    text = normalize_persian_text(raw)

    gender = _extract_gender(text)
    age = _extract_age(text)
    height_cm = _extract_height(text)
    weight_kg = _extract_weight(text)
    ibw_kg = compute_ibw_kg(gender, height_cm)
    ventilator_days = _extract_ventilator_days(text)
    tube_type = _extract_tube_type(text)
    indication = _extract_indication(text)
    rass = _extract_rass(text)
    covid_status = _extract_covid(text)
    diagnosis_category = _extract_diagnosis_category(text)
    main_diagnosis = _extract_after_keyword(
        text,
        ("تشخیص اصلی", "تشخیص", "diagnosis"),
        max_len=160,
    )
    # If category found but no free diagnosis, use category as soft hint only in found list
    sedation_active = _extract_bool_flag(
        text,
        ("sedation فعال", "سدیشن فعال", "تحت sedation", "sedation", "سدیشن"),
    )
    recent_surgery = _extract_bool_flag(
        text,
        ("جراحی اخیر", "عمل اخیر", "اخیرا عمل", "اخیراً جراحی"),
    )
    fever = _extract_bool_flag(text, (r"تب\b", "fever"))
    secretion_intensity = _extract_secretion(text)
    cxr_summary = _extract_after_keyword(
        text,
        ("خلاصه cxr", "cxr", "رادیوگرافی قفسه", "عکس ریه", "chest x.?ray"),
        max_len=220,
    )
    consultation_goal = _extract_after_keyword(
        text,
        ("هدف مشاوره", "سوال مشاوره", "سوال", "هدف"),
        max_len=200,
    )

    fields: dict[str, Any] = {
        "gender": gender,
        "age": age,
        "height_cm": height_cm,
        "weight_kg": weight_kg,
        "ibw_kg": ibw_kg,
        "ventilator_days": ventilator_days,
        "tube_type": tube_type,
        "indication": indication,
        "rass": rass,
        "covid_status": covid_status,
        "main_diagnosis": main_diagnosis,
        "diagnosis_category": diagnosis_category,
        "sedation_active": sedation_active,
        "recent_surgery": recent_surgery,
        "fever": fever,
        "secretion_intensity": secretion_intensity,
        "cxr_summary": cxr_summary,
        "consultation_goal": consultation_goal,
    }
    found = [k for k, v in fields.items() if v is not None]
    # IBW alone shouldn't count as "heard" — only when gender+height present
    if "ibw_kg" in found and (gender is None or height_cm is None):
        found = [k for k in found if k != "ibw_kg"]
        fields["ibw_kg"] = None
    missing = [k for k in FIELD_LABELS_FA if fields.get(k) is None]
    return {
        **fields,
        "raw_text": raw,
        "found": found,
        "missing": missing,
        "extract_version": EXTRACT_VERSION,
    }


def gender_label_fa(gender: Gender | None) -> str:
    if gender == "male":
        return "مرد"
    if gender == "female":
        return "زن"
    return ""
