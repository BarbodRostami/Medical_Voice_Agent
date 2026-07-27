"""EXPERIMENT ONLY — extract patient demographics from Persian speech text.

Not part of the HakimAI / production collaborator contract.
Used by ``backend/experiments/voice_form_ui.py``.
"""
from __future__ import annotations

import re
from typing import Any, Literal

Gender = Literal["male", "female"]

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

_MALE = re.compile(
    r"(?:\bمرد\b|\bآقا(?:ی)?\b|\bپسر\b|\bmale\b|\bman\b|\bmr\.?\b)",
    re.IGNORECASE,
)
_FEMALE = re.compile(
    r"(?:\bزن\b|\bخانم\b|\bبانو\b|\bدختر\b|\bfemale\b|\bwoman\b|\bmrs?\.?\b|\bmiss\b)",
    re.IGNORECASE,
)

# سن ۴۵ / سن: 45 / ۴۵ ساله / ۴۵ سال سن داره
_AGE = re.compile(
    r"(?:"
    r"سن(?:\s*(?:بیمار|او|ایشان))?\s*(?:حدود|تقریباً|تقریبا)?\s*[:\-]?\s*(\d{1,3})"
    r"|"
    r"(\d{1,3})\s*سال(?:ه|گی)?"
    r")",
)

# قد ۱۷۵ / قد: 175 سانتی‌متر / ۱۷۵ سانت / height 175 cm
_HEIGHT = re.compile(
    r"(?:"
    r"قد(?:\s*(?:بیمار|او|ایشان))?\s*(?:حدود|تقریباً|تقریبا)?\s*[:\-]?\s*(\d{2,3})"
    r"(?:\s*(?:سانتی[\s\-]?متر|سانت(?:ی)?|cm|سم))?"
    r"|"
    r"(\d{2,3})\s*(?:سانتی[\s\-]?متر|سانت(?:ی)?|cm)\b"
    r"|"
    r"height\s*[:\-]?\s*(\d{2,3})\s*(?:cm)?"
    r")",
    re.IGNORECASE,
)


def normalize_persian_digits(text: str) -> str:
    """Map Persian/Arabic-Indic digits to ASCII."""
    return text.translate(_PERSIAN_DIGITS)


def extract_patient_demographics(transcript: str) -> dict[str, Any]:
    """Parse gender / age / height_cm from free Persian (or mixed) text.

    Returns a dict suitable for form binding::

        {
          "gender": "male"|"female"|None,
          "age": int|None,
          "height_cm": int|None,
          "raw_text": str,
          "found": ["gender", ...],
          "missing": ["age", ...],
        }
    """
    raw = (transcript or "").strip()
    text = normalize_persian_digits(raw)

    gender: Gender | None = None
    if _MALE.search(text) and not _FEMALE.search(text):
        gender = "male"
    elif _FEMALE.search(text) and not _MALE.search(text):
        gender = "female"
    elif _MALE.search(text) and _FEMALE.search(text):
        # Both mentioned — take the first match position
        m_pos = _MALE.search(text)
        f_pos = _FEMALE.search(text)
        assert m_pos is not None and f_pos is not None
        gender = "male" if m_pos.start() < f_pos.start() else "female"

    age: int | None = None
    age_m = _AGE.search(text)
    if age_m:
        digits = next(g for g in age_m.groups() if g)
        val = int(digits)
        if 0 < val < 130:
            age = val

    height_cm: int | None = None
    h_m = _HEIGHT.search(text)
    if h_m:
        digits = next(g for g in h_m.groups() if g)
        val = int(digits)
        if 40 <= val <= 250:
            height_cm = val

    fields = {"gender": gender, "age": age, "height_cm": height_cm}
    found = [k for k, v in fields.items() if v is not None]
    missing = [k for k, v in fields.items() if v is None]
    return {
        **fields,
        "raw_text": raw,
        "found": found,
        "missing": missing,
    }


def gender_label_fa(gender: Gender | None) -> str:
    if gender == "male":
        return "مرد"
    if gender == "female":
        return "زن"
    return ""
