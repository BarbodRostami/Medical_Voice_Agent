"""Extract HakimAI form fields from Persian speech (patient + settings + measurement).

Used by voice-form experiment UI and collaborator ``/api/cases`` → ``fields``.
Patient and Settings keys stay stable; Measurement-tab keys are additive.
"""
from __future__ import annotations

import re
from typing import Any, Literal

Gender = Literal["male", "female"]

EXTRACT_VERSION = "patient-tab-v1"

# Persian labels for UI (order matters for display)
FIELD_LABELS_FA: dict[str, str] = {
    # --- Patient tab ---
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
    # --- Ventilator settings tab (additive; does not remove patient keys) ---
    "ventilator_mode": "مود ونتیلاتور",
    "vt_set_ml": "VT set (ml)",
    "pi_cmh2o": "Pi فشار دمی (cmH2O)",
    "p_hi_cmh2o": "P Hi (cmH2O)",
    "p_lo_cmh2o": "P Lo (cmH2O)",
    "t_hi_sec": "T Hi (sec)",
    "t_lo_sec": "T Lo (sec)",
    "rr_set_bpm": "RR set (bpm)",
    "ti_max_sec": "Ti max (sec)",
    "ps_cmh2o": "PS حمایت تنفسی (cmH2O)",
    "cycle_criteria_pct": "Cycle criteria (%)",
    "rise_time_sec": "Rise time (sec)",
    "trigger_sensitivity_lpm": "Trigger sensitivity (L/min)",
    "peep_cmh2o": "PEEP set (cmH2O)",
    "fio2_pct": "FiO2 (%)",
    # --- Measurement tab (additive) ---
    "rr_total_bpm": "RR total (bpm)",
    "rr_spontaneous_bpm": "RR spontaneous (bpm)",
    "vte_ml": "VTe (mL)",
    "vt_ibw_ml_kg": "VT/IBW (mL/kg)",
    "minute_ventilation_lpm": "Minute ventilation (L/min)",
    "spontaneous_mv_lpm": "Spontaneous MV (L/min)",
    "peak_pressure_cmh2o": "Peak pressure (cmH2O)",
    "plateau_pressure_cmh2o": "Plateau pressure (cmH2O)",
    "peep_measured_cmh2o": "PEEP measured (cmH2O)",
    "auto_peep_cmh2o": "Auto-PEEP (cmH2O)",
    "mean_pressure_cmh2o": "Mean pressure (cmH2O)",
    "driving_pressure_cmh2o": "Driving Pressure (cmH2O)",
    "ie_ratio": "I:E",
    "peak_flow_insp_lpm": "Peak flow inspiratory (L/min)",
    "peak_flow_exp_lpm": "Peak flow expiratory (L/min)",
    "r_inspiratory": "R inspiratory (cmH2O/L/s)",
    "rcexp_sec": "RCexp (sec)",
    "compliance_static": "Compliance static (mL/cmH2O)",
    "compliance_dynamic": "Compliance dynamic (mL/cmH2O)",
    "wob_jl": "WOB (J/L)",
    "rsbi": "RSBI",
    "leak_pct": "Leak (%)",
}

# HakimAI Settings-tab mode dropdown values (exact strings for UI mapping)
VentilatorMode = Literal[
    "VCV",
    "PCV",
    "SIMV-V",
    "SIMV-P",
    "PSV/CPAP",
    "APRV",
    "PRVC",
]

# Longer / more specific patterns first
_VENT_MODE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("PRVC", r"\bprvc\b|پی\s*آر\s*وی\s*سی|حجم\s*تنظیم\s*شده\s*با\s*فشار"),
    ("APRV", r"\baprv\b|ای\s*پی\s*آر\s*وی|اِی\s*پی\s*آر\s*وی"),
    ("SIMV-V", r"simv[\s\-]?v\b|سیم\s*وی[\s\-]?وی|سیموی\s*حجمی|simv\s*حجمی"),
    ("SIMV-P", r"simv[\s\-]?p\b|سیم\s*وی[\s\-]?پی|سیموی\s*فشاری|simv\s*فشاری"),
    ("PSV/CPAP", r"psv\s*/\s*cpap|\bpsv\b|\bcpap\b|پی\s*اس\s*وی|سی\s*پپ|سیپپ|مود\s*حمایتی"),
    ("VCV", r"\bvcv\b|وی\s*سی\s*وی|مود\s*حجمی|volume\s*control|کنترل\s*حجمی"),
    ("PCV", r"\bpcv\b|پی\s*سی\s*وی|مود\s*فشاری|pressure\s*control|کنترل\s*فشاری"),
)

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
    # Avoid matching «زن» inside «وزن»
    r"(?:(?<!و)زن|خانم|خانوم|بانو|دختر|female|woman|mrs?\.?|miss)",
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
_ALL_WORDS = {
    **_UNITS,
    **_TEENS,
    **_TENS,
    "صد": 100,
    "یکصد": 100,
    "دویست": 200,
    "سیصد": 300,
    "چهارصد": 400,
    "پانصد": 500,
    "ششصد": 600,
    "هفتصد": 700,
    "هشتصد": 800,
    "نهصد": 900,
}

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
    # Frequent STT garbling on demographics phrases (collaborator TTS→STT)
    for bad, good in (
        ("سنتی میت", "سانتی متر"),
        ("سنتی متر", "سانتی متر"),
        ("سانتی میتر", "سانتی متر"),
        ("سانتی میت", "سانتی متر"),
        ("سانتیمتر", "سانتی متر"),
        ("حفتاد", "هفتاد"),
        ("حضتاد", "هفتاد"),
        ("سد و", "صد و"),
    ):
        t = t.replace(bad, good)
    t = re.sub(r"(^|\s)سد(\s|$)", r"\1صد\2", t)
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
    # سن بیمار چهل و پنج سال است / سن ۴۵ سال
    m = re.search(
        r"سن(?:\s*(?:بیمار|او|ایشان))?\s*(?:حدود|تقریباً|تقریبا)?\s*[:\-]?\s*"
        r"((?:[^\s]+(?:\s+و\s+[^\s]+){0,3}|\d{1,3}))\s*سال\b",
        text,
    )
    if m:
        val = persian_spoken_number(m.group(1))
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
    if re.search(
        r"تراک(?:ئوستومی)?|\btrach\b|tracheostom|لوله\s*تراک",
        t,
        re.I,
    ):
        return "Trach"
    # Spoken Persian spellings of ETT + Latin forms
    if re.search(
        r"\bett\b|ای\s*تی\s*تی|آی\s*تی\s*تی|e\s*t\s*t|"
        r"لوله\s*(?:دهان|تراشه)|اندوتراک|endotrach",
        t,
        re.I,
    ):
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
    m = re.search(r"(?:rass|راس|رَس)\s*[:\-]?\s*([+\-]\d{1,2})", text, re.I)
    if m:
        val = int(m.group(1))
        if -5 <= val <= 4:
            return val
    m = re.search(
        r"(?:rass|راس|رَس)\s*[:\-]?\s*منفی\s*(یک|دو|سه|چهار|پنج|\d)",
        text,
        re.I,
    )
    if m:
        raw = m.group(1)
        val = persian_spoken_number(raw) if not raw.isdigit() else int(raw)
        if val is not None and 1 <= val <= 5:
            return -val
    m = re.search(
        r"(?:rass|راس|رَس)\s*[:\-]?\s*منفی\s*([۰-۹0-9])",
        text,
        re.I,
    )
    if m:
        val = int(m.group(1).translate(_PERSIAN_DIGITS))
        if 1 <= val <= 5:
            return -val
    m = re.search(r"(?:rass|راس|رَس)\s*[:\-]?\s*(\d{1,2})", text, re.I)
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


def _extract_ventilator_mode(text: str) -> str | None:
    """Map spoken / written mode to HakimAI Settings dropdown values."""
    for mode, pattern in _VENT_MODE_PATTERNS:
        if re.search(pattern, text, re.I):
            return mode
    # Explicit «مود …» catch-all after specific patterns
    m = re.search(
        r"مود(?:\s*(?:ونتیلاتور|ونتیلاتور|دستگاه))?\s*[:\-]?\s*"
        r"([A-Za-zآ-ی0-9\s\-/]+?)(?=(?:peep|پیپ|fio2|فی|vt|وی\s*تی|rr|سن|قد|وزن|لوله|$|\.))",
        text,
        re.I,
    )
    if m:
        chunk = normalize_persian_text(m.group(1))
        for mode, pattern in _VENT_MODE_PATTERNS:
            if re.search(pattern, chunk, re.I):
                return mode
    return None


def _number_after_labels(
    text: str,
    labels: tuple[str, ...],
    *,
    min_v: float,
    max_v: float,
    as_int: bool = False,
) -> float | int | None:
    """Find a numeric (digit or spoken Persian) value after any label."""
    label_re = "|".join(labels)
    # digits first
    m = re.search(
        rf"(?:{label_re})\s*(?:set|ست)?\s*[:\-]?\s*(\d+(?:\.\d+)?)",
        text,
        re.I,
    )
    if m:
        val = float(m.group(1))
        if min_v <= val <= max_v:
            return int(val) if as_int and val == int(val) else (int(val) if as_int else val)
    # spoken: label + up to 4 Persian number words
    m = re.search(
        rf"(?:{label_re})\s*(?:set|ست)?\s*[:\-]?\s*"
        r"((?:[^\s]+(?:\s+و\s+[^\s]+){0,3}))",
        text,
        re.I,
    )
    if m:
        phrase = m.group(1).strip()
        # strip trailing unit words so persian_spoken_number can parse
        phrase = re.sub(
            r"\s*(?:درصد|percent|%|سانتی|cmh2o|cm\s*h2o|میلی[\s\-]?لیتر|ml|"
            r"ثانیه|sec|bpm|لیتر(?:\s*بر\s*دقیقه)?|l/?min).*$",
            "",
            phrase,
            flags=re.I,
        ).strip()
        val_i = persian_spoken_number(phrase)
        if val_i is not None and min_v <= val_i <= max_v:
            return int(val_i) if as_int else float(val_i)
    return None


def _extract_peep(text: str) -> float | None:
    """Settings-tab PEEP set (not measured / auto-peep)."""
    val = _number_after_labels(
        text,
        (
            r"peep\s*set",
            r"پیپ\s*ست",
            r"پی\s*ای\s*ای\s*پی\s*ست",
        ),
        min_v=0,
        max_v=40,
    )
    if val is not None:
        return float(val)
    # Strip measured/auto phrases so bare peep/پیپ does not steal them
    cleaned = re.sub(
        r"(?:auto[\s\-]?peep|اتو\s*پیپ|peep\s*measured|measured\s*peep|"
        r"پیپ\s*اندازه(?:\s*|‌)?گیری(?:\s*شده)?|peep\s*total)"
        r"[^\d]{0,20}\d+(?:\.\d+)?",
        " ",
        text,
        flags=re.I,
    )
    return _number_after_labels(
        cleaned,
        (r"peep", r"پیپ", r"پی\s*ای\s*ای\s*پی", r"پی\s*ایپ"),
        min_v=0,
        max_v=40,
    )


def _extract_fio2(text: str) -> float | None:
    # Prefer explicit FiO2 / اکسیژن درصد
    val = _number_after_labels(
        text,
        (
            r"fio2",
            r"fi\s*o\s*2",
            r"فی\s*او\s*دو",
            r"فیو\s*دو",
            r"اکسیژن(?:\s*الهامی)?",
            r"درصد\s*اکسیژن",
        ),
        min_v=21,
        max_v=100,
    )
    if val is not None:
        return float(val)
    # «اکسیژن چهل درصد»
    m = re.search(
        r"اکسیژن\s*((?:[^\s]+(?:\s+و\s+[^\s]+){0,2}|\d{2,3}))\s*(?:درصد|percent|%)",
        text,
        re.I,
    )
    if m:
        raw = m.group(1)
        if re.fullmatch(r"\d+(?:\.\d+)?", raw):
            v = float(raw)
        else:
            spoken = persian_spoken_number(raw)
            v = float(spoken) if spoken is not None else None
        if v is not None and 21 <= v <= 100:
            return v
    return None


def _extract_vt_set(text: str) -> int | None:
    val = _number_after_labels(
        text,
        (
            r"vt\s*set",
            r"وی\s*تی\s*ست",
            r"tidal\s*volume\s*set",
        ),
        min_v=100,
        max_v=1200,
        as_int=True,
    )
    if val is not None:
        return int(val)
    # bare VT / وی تی — but not VTe / وی تی ای
    if re.search(r"vte|وی\s*تی\s*ای", text, re.I):
        m = re.search(
            r"(?:vt\s*set|وی\s*تی\s*ست)\s*[:\-]?\s*(\d{2,4})",
            text,
            re.I,
        )
        if m:
            v = int(m.group(1))
            if 100 <= v <= 1200:
                return v
        return None
    return _number_after_labels(
        text,
        (r"\bvt\b", r"وی\s*تی", r"حجم\s*(?:جزر\s*و\s*مدی|tidal)", r"tidal\s*volume"),
        min_v=100,
        max_v=1200,
        as_int=True,
    )


def _extract_rr_set(text: str) -> int | None:
    val = _number_after_labels(
        text,
        (
            r"rr\s*set",
            r"آر\s*آر\s*ست",
            r"نرخ\s*تنفس\s*ست",
            r"set\s*respiratory\s*rate",
        ),
        min_v=4,
        max_v=60,
        as_int=True,
    )
    if val is not None:
        return int(val)
    # bare RR only when total/spontaneous not present
    if re.search(r"rr\s*total|rr\s*spont|آر\s*آر\s*توتال|آر\s*آر\s*اسپانت", text, re.I):
        return None
    return _number_after_labels(
        text,
        (r"\brr\b", r"آر\s*آر", r"نرخ\s*تنفس", r"تعداد\s*تنفس", r"respiratory\s*rate"),
        min_v=4,
        max_v=60,
        as_int=True,
    )


def _extract_pi(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"\bpi\b", r"پی\s*آی", r"فشار\s*دمی", r"inspiratory\s*pressure"),
        min_v=0,
        max_v=60,
    )


def _extract_ps(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"\bps\b",
            r"پی\s*اس",
            r"فشار\s*حمایت",
            r"حمایت\s*تنفسی",
            r"pressure\s*support",
        ),
        min_v=0,
        max_v=40,
    )


def _extract_p_hi(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"p\s*hi", r"پی\s*های", r"پی\s*های", r"فشار\s*بالا"),
        min_v=0,
        max_v=60,
    )


def _extract_p_lo(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"p\s*lo", r"پی\s*لو", r"فشار\s*پایین"),
        min_v=0,
        max_v=40,
    )


def _extract_t_hi(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"t\s*hi", r"تی\s*های", r"زمان\s*بالا"),
        min_v=0.1,
        max_v=30,
    )


def _extract_t_lo(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"t\s*lo", r"تی\s*لو", r"زمان\s*پایین"),
        min_v=0.1,
        max_v=30,
    )


def _extract_ti_max(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"ti\s*max", r"تی\s*آی\s*مکس", r"تی\s*آی\s*макс", r"زمان\s*دم\s*حداکثر"),
        min_v=0.1,
        max_v=10,
    )


def _extract_cycle_criteria(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"cycle\s*criteria", r"سایکل\s*کرایتریا", r"معیار\s*سیکل"),
        min_v=1,
        max_v=100,
    )


def _extract_rise_time(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"rise\s*time", r"رایز\s*تایم", r"زمان\s*صعود"),
        min_v=0,
        max_v=5,
    )


def _extract_trigger_sensitivity(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"trigger\s*sensitivity",
            r"trigger\s*flow",
            r"تریگر",
            r"حساسیت\s*تریگر",
        ),
        min_v=0.1,
        max_v=20,
    )


# ─── Measurement tab ─────────────────────────────────────────────────────────

def _extract_rr_total(text: str) -> int | None:
    val = _number_after_labels(
        text,
        (
            r"rr\s*total",
            r"آر\s*آر\s*توتال",
            r"آر\s*آر\s*کل",
            r"تنفس\s*کل",
            r"تعداد\s*تنفس\s*کل",
            r"total\s*(?:respiratory\s*)?rate",
        ),
        min_v=4,
        max_v=80,
        as_int=True,
    )
    return int(val) if val is not None else None


def _extract_rr_spontaneous(text: str) -> int | None:
    val = _number_after_labels(
        text,
        (
            r"rr\s*spontaneous",
            r"rr\s*spont",
            r"آر\s*آر\s*اسپانتانیوس",
            r"آر\s*آر\s*اسپانت",
            r"تنفس\s*خودبخودی",
            r"تنفس\s*اسپانتانیوس",
            r"spontaneous\s*(?:respiratory\s*)?rate",
        ),
        min_v=0,
        max_v=80,
        as_int=True,
    )
    return int(val) if val is not None else None


def _extract_vte(text: str) -> int | None:
    val = _number_after_labels(
        text,
        (
            r"vte",
            r"vt\s*e\b",
            r"وی\s*تی\s*ای",
            r"حجم\s*بازدمی",
            r"expired\s*(?:tidal\s*)?volume",
        ),
        min_v=50,
        max_v=1200,
        as_int=True,
    )
    return int(val) if val is not None else None


def _extract_vt_ibw(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"vt\s*/\s*ibw", r"vt\s*ibw", r"وی\s*تی\s*بر\s*آی\s*بی\s*دبلیو", r"وی\s*تی\s*آی\s*بی\s*دبلیو"),
        min_v=2,
        max_v=20,
    )


def _extract_minute_ventilation(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"minute\s*ventilation",
            r"\bmv\b",
            r"تهویه\s*دقیقه‌ای",
            r"مینیت\s*ونتیلیشن",
            r"مینا\s*ونتیلیشن",
        ),
        min_v=0.5,
        max_v=40,
    )


def _extract_spontaneous_mv(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"spontaneous\s*mv",
            r"spont\s*mv",
            r"اسپانتانیوس\s*ام\s*وی",
            r"تهویه\s*خودبخودی",
        ),
        min_v=0,
        max_v=40,
    )


def _extract_peak_pressure(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"peak\s*pressure",
            r"ppeak",
            r"pip\b",
            r"پیک\s*پرشر",
            r"فشار\s*پیک",
            r"فشار\s*اوج",
        ),
        min_v=0,
        max_v=80,
    )


def _extract_plateau_pressure(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"plateau\s*pressure",
            r"pplat",
            r"پلاتو",
            r"فشار\s*پلاتو",
        ),
        min_v=0,
        max_v=80,
    )


def _extract_peep_measured(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"peep\s*measured",
            r"measured\s*peep",
            r"پیپ\s*اندازه(?:‌| )?گیری(?:\s*شده)?",
            r"پیپ\s*اندازه‌گیری",
            r"peep\s*total",
        ),
        min_v=0,
        max_v=40,
    )


def _extract_auto_peep(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"auto[\s\-]?peep",
            r"intrinsic\s*peep",
            r"اتو\s*پیپ",
            r"اتوپیب",
            r"پیپ\s*ذاتی",
        ),
        min_v=0,
        max_v=30,
    )


def _extract_mean_pressure(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"mean\s*pressure",
            r"pmean",
            r"میانگین\s*فشار",
            r"فشار\s*متوسط",
            r"مین\s*پرشر",
        ),
        min_v=0,
        max_v=50,
    )


def _extract_driving_pressure(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"driving\s*pressure",
            r"درایوینگ\s*پرشر",
            r"فشار\s*محرک",
            r"دلتا\s*پی",
            r"delta\s*p\b",
        ),
        min_v=0,
        max_v=50,
    )


def _extract_ie_ratio(text: str) -> str | None:
    m = re.search(
        r"(?:i\s*:\s*e|آی\s*[:\-]?\s*ای|نسبت\s*دم\s*(?:به\s*)?بازدم)\s*[:\-]?\s*"
        r"([^\s]+)\s*(?:[:]|به)\s*([^\s]+)",
        text,
        re.I,
    )
    if not m:
        return None
    left_raw = m.group(1).strip(" .،")
    right_raw = m.group(2).strip(" .،")
    if re.fullmatch(r"\d+(?:\.\d+)?", left_raw):
        left: str | None = left_raw
    else:
        spoken_l = persian_spoken_number(left_raw)
        left = str(spoken_l) if spoken_l is not None else None
    if re.fullmatch(r"\d+(?:\.\d+)?", right_raw):
        right: str | None = right_raw
    else:
        spoken_r = persian_spoken_number(right_raw)
        right = str(spoken_r) if spoken_r is not None else None
    if left is not None and right is not None:
        return f"{left}:{right}"
    return None


def _extract_peak_flow_insp(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"peak\s*flow\s*inspiratory",
            r"inspiratory\s*peak\s*flow",
            r"پیک\s*فلو\s*دمی",
            r"فلو\s*دمی",
            r"peak\s*insp(?:iratory)?\s*flow",
        ),
        min_v=1,
        max_v=200,
    )


def _extract_peak_flow_exp(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"peak\s*flow\s*expiratory",
            r"expiratory\s*peak\s*flow",
            r"پیک\s*فلو\s*بازدمی",
            r"فلو\s*بازدمی",
            r"peak\s*exp(?:iratory)?\s*flow",
        ),
        min_v=1,
        max_v=200,
    )


def _extract_r_inspiratory(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"r\s*inspiratory",
            r"inspiratory\s*resistance",
            r"مقاومت\s*دمی",
            r"آر\s*دمی",
        ),
        min_v=0,
        max_v=100,
    )


def _extract_rcexp(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"rcexp", r"rc\s*exp", r"آر\s*سی\s*اکسپ", r"ثابت\s*زمان\s*بازدم"),
        min_v=0.1,
        max_v=20,
    )


def _extract_compliance_static(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"compliance\s*static",
            r"static\s*compliance",
            r"cstat",
            r"کمپلیانس\s*استاتیک",
            r"کمپلیانس\s*ایستا",
        ),
        min_v=1,
        max_v=200,
    )


def _extract_compliance_dynamic(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"compliance\s*dynamic",
            r"dynamic\s*compliance",
            r"cdyn",
            r"کمپلیانس\s*دینامیک",
            r"کمپلیانس\s*پویا",
        ),
        min_v=1,
        max_v=200,
    )


def _extract_wob(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"\bwob\b", r"work\s*of\s*breathing", r"کار\s*تنفس", r"دبلیو\s*او\s*بی"),
        min_v=0,
        max_v=20,
    )


def _extract_rsbi(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"\brsbi\b", r"آر\s*اس\s*بی\s*آی", r"rapid\s*shallow"),
        min_v=10,
        max_v=400,
    )


def _extract_leak(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"\bleak\b", r"نشتی", r"لیک", r"leak\s*%"),
        min_v=0,
        max_v=100,
    )


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
    if key == "ventilator_mode":
        return str(value)
    if key == "peep_cmh2o":
        return f"{value} cmH2O"
    if key == "fio2_pct":
        return f"{value}%"
    if key == "vt_set_ml":
        return f"{value} ml"
    if key == "rr_set_bpm":
        return f"{value} bpm"
    return str(value)


def extract_patient_demographics(transcript: str) -> dict[str, Any]:
    """Parse HakimAI form fields (patient tab + ventilator settings) from speech text.

    Backward-compatible name; returns flat keys + found/missing lists.
    Existing patient keys are unchanged; vent settings are additive.
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

    # Ventilator settings tab (additive)
    ventilator_mode = _extract_ventilator_mode(text)
    vt_set_ml = _extract_vt_set(text)
    pi_cmh2o = _extract_pi(text)
    p_hi_cmh2o = _extract_p_hi(text)
    p_lo_cmh2o = _extract_p_lo(text)
    t_hi_sec = _extract_t_hi(text)
    t_lo_sec = _extract_t_lo(text)
    rr_set_bpm = _extract_rr_set(text)
    ti_max_sec = _extract_ti_max(text)
    ps_cmh2o = _extract_ps(text)
    cycle_criteria_pct = _extract_cycle_criteria(text)
    rise_time_sec = _extract_rise_time(text)
    trigger_sensitivity_lpm = _extract_trigger_sensitivity(text)
    peep_cmh2o = _extract_peep(text)
    fio2_pct = _extract_fio2(text)

    # Measurement tab (additive)
    rr_total_bpm = _extract_rr_total(text)
    rr_spontaneous_bpm = _extract_rr_spontaneous(text)
    vte_ml = _extract_vte(text)
    vt_ibw_ml_kg = _extract_vt_ibw(text)
    minute_ventilation_lpm = _extract_minute_ventilation(text)
    spontaneous_mv_lpm = _extract_spontaneous_mv(text)
    peak_pressure_cmh2o = _extract_peak_pressure(text)
    plateau_pressure_cmh2o = _extract_plateau_pressure(text)
    peep_measured_cmh2o = _extract_peep_measured(text)
    auto_peep_cmh2o = _extract_auto_peep(text)
    mean_pressure_cmh2o = _extract_mean_pressure(text)
    driving_pressure_cmh2o = _extract_driving_pressure(text)
    ie_ratio = _extract_ie_ratio(text)
    peak_flow_insp_lpm = _extract_peak_flow_insp(text)
    peak_flow_exp_lpm = _extract_peak_flow_exp(text)
    r_inspiratory = _extract_r_inspiratory(text)
    rcexp_sec = _extract_rcexp(text)
    compliance_static = _extract_compliance_static(text)
    compliance_dynamic = _extract_compliance_dynamic(text)
    wob_jl = _extract_wob(text)
    rsbi = _extract_rsbi(text)
    leak_pct = _extract_leak(text)

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
        "ventilator_mode": ventilator_mode,
        "vt_set_ml": vt_set_ml,
        "pi_cmh2o": pi_cmh2o,
        "p_hi_cmh2o": p_hi_cmh2o,
        "p_lo_cmh2o": p_lo_cmh2o,
        "t_hi_sec": t_hi_sec,
        "t_lo_sec": t_lo_sec,
        "rr_set_bpm": rr_set_bpm,
        "ti_max_sec": ti_max_sec,
        "ps_cmh2o": ps_cmh2o,
        "cycle_criteria_pct": cycle_criteria_pct,
        "rise_time_sec": rise_time_sec,
        "trigger_sensitivity_lpm": trigger_sensitivity_lpm,
        "peep_cmh2o": peep_cmh2o,
        "fio2_pct": fio2_pct,
        "rr_total_bpm": rr_total_bpm,
        "rr_spontaneous_bpm": rr_spontaneous_bpm,
        "vte_ml": vte_ml,
        "vt_ibw_ml_kg": vt_ibw_ml_kg,
        "minute_ventilation_lpm": minute_ventilation_lpm,
        "spontaneous_mv_lpm": spontaneous_mv_lpm,
        "peak_pressure_cmh2o": peak_pressure_cmh2o,
        "plateau_pressure_cmh2o": plateau_pressure_cmh2o,
        "peep_measured_cmh2o": peep_measured_cmh2o,
        "auto_peep_cmh2o": auto_peep_cmh2o,
        "mean_pressure_cmh2o": mean_pressure_cmh2o,
        "driving_pressure_cmh2o": driving_pressure_cmh2o,
        "ie_ratio": ie_ratio,
        "peak_flow_insp_lpm": peak_flow_insp_lpm,
        "peak_flow_exp_lpm": peak_flow_exp_lpm,
        "r_inspiratory": r_inspiratory,
        "rcexp_sec": rcexp_sec,
        "compliance_static": compliance_static,
        "compliance_dynamic": compliance_dynamic,
        "wob_jl": wob_jl,
        "rsbi": rsbi,
        "leak_pct": leak_pct,
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


def finalize_patient_fields(fields: dict[str, Any], *, raw_text: str = "") -> dict[str, Any]:
    """Recompute IBW / found / missing after merge or manual edit."""
    gender = fields.get("gender")
    height_cm = fields.get("height_cm")
    height_int: int | None
    if isinstance(height_cm, (int, float)):
        height_int = int(height_cm)
    else:
        height_int = None
    ibw = compute_ibw_kg(
        gender if gender in ("male", "female") else None,
        height_int,
    )
    out: dict[str, Any] = {k: fields.get(k) for k in FIELD_LABELS_FA}
    out["ibw_kg"] = ibw
    found = [k for k, v in out.items() if v is not None]
    if "ibw_kg" in found and (out.get("gender") is None or out.get("height_cm") is None):
        found = [k for k in found if k != "ibw_kg"]
        out["ibw_kg"] = None
    missing = [k for k in FIELD_LABELS_FA if out.get(k) is None]
    return {
        **out,
        "raw_text": raw_text if raw_text else (fields.get("raw_text") or ""),
        "found": found,
        "missing": missing,
        "extract_version": fields.get("extract_version") or EXTRACT_VERSION,
    }


def merge_patient_extractions(
    base: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Merge a new extract into an existing result (new non-null values win)."""
    if not base:
        return incoming
    merged: dict[str, Any] = {k: base.get(k) for k in FIELD_LABELS_FA}
    for key in FIELD_LABELS_FA:
        if key == "ibw_kg":
            continue
        new_val = incoming.get(key)
        if new_val is not None:
            merged[key] = new_val
    raw_parts = [
        p.strip()
        for p in (base.get("raw_text") or "", incoming.get("raw_text") or "")
        if p and str(p).strip()
    ]
    raw = " | ".join(raw_parts)
    return finalize_patient_fields(merged, raw_text=raw)


def export_fields_payload(result: dict[str, Any]) -> dict[str, Any]:
    """JSON-friendly payload for clipboard / HakimAI handoff experiments."""
    return {
        "fields": {k: result.get(k) for k in FIELD_LABELS_FA},
        "found": list(result.get("found") or []),
        "missing": list(result.get("missing") or []),
        "raw_text": result.get("raw_text") or "",
        "extract_version": result.get("extract_version") or EXTRACT_VERSION,
    }


def confirmation_speech_fa(result: dict[str, Any], *, max_items: int = 6) -> str:
    """Short Persian TTS confirmation of extracted fields."""
    parts: list[str] = []
    priority = (
        "gender",
        "age",
        "height_cm",
        "weight_kg",
        "ventilator_mode",
        "peep_cmh2o",
        "fio2_pct",
        "vt_set_ml",
        "rr_set_bpm",
        "ventilator_days",
        "tube_type",
        "indication",
        "rass",
        "diagnosis_category",
        "fever",
        "sedation_active",
        "recent_surgery",
    )
    for key in priority:
        val = result.get(key)
        if val is None:
            continue
        label = FIELD_LABELS_FA.get(key, key)
        parts.append(f"{label} {format_field_value(key, val)}")
        if len(parts) >= max_items:
            break
    if not parts:
        return "چیزی برای تأیید پیدا نشد."
    return "، ".join(parts) + ". درسته؟"


def gender_label_fa(gender: Gender | None) -> str:
    if gender == "male":
        return "مرد"
    if gender == "female":
        return "زن"
    return ""
