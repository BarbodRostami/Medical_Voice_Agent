"""Extract HakimAI form fields from Persian speech (patient + vent + ABG + hemodynamics).

Used by voice-form experiment UI and collaborator ``/api/cases`` → ``fields``.
Earlier tab keys stay stable; hemodynamics keys are additive.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Literal

Gender = Literal["male", "female"]

EXTRACT_VERSION = "hemo-slot-v12"

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
    "vt_ibw_ml_kg": "VT/IBW (محاسباتی، mL/kg)",
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
    # --- ABG tab (additive) ---
    "ph": "pH",
    "paco2_mmhg": "PaCO2 (mmHg)",
    "pao2_mmhg": "PaO2 (mmHg)",
    "sao2_pct": "SaO2 (%)",
    "hco3_meq_l": "HCO3 (mEq/L)",
    "base_excess_meq_l": "Base Excess (mEq/L)",
    "pf_ratio": "P/F ratio (محاسباتی)",
    # --- Hemodynamics / vital signs tab (additive) ---
    "sbp_mmhg": "SBP (mmHg)",
    "dbp_mmhg": "DBP (mmHg)",
    "map_mmhg": "MAP (محاسباتی، mmHg)",
    "hr_bpm": "HR (bpm)",
    "temperature_c": "دما (°C)",
    "urine_output_ml_hr": "Urine output (mL/hr)",
    "io_balance_24h_ml": "I&O balance 24h (mL)",
    "vasopressor_active": "Vasopressor",
    # --- Lab tab (additive) ---
    "hb_gdl": "Hb (g/dL)",
    "hct_pct": "Hct (%)",
    "wbc_k_ul": "WBC (k/µL)",
    "platelets_k_ul": "Platelets (k/µL)",
    "na_meq_l": "Na (mEq/L)",
    "k_meq_l": "K (mEq/L)",
    "ca_mg_dl": "Ca (mg/dL)",
    "mg_mg_dl": "Mg (mg/dL)",
    "phosphate_mg_dl": "Phosphate (mg/dL)",
    "bun_mg_dl": "BUN (mg/dL)",
    "creatinine_mg_dl": "Creatinine (mg/dL)",
    "albumin_g_dl": "Albumin (g/dL)",
    "ast_u_l": "AST (U/L)",
    "alt_u_l": "ALT (U/L)",
    "bilirubin_mg_dl": "Bilirubin (mg/dL)",
    "crp_mg_l": "CRP (mg/L)",
    "procalcitonin_ng_ml": "Procalcitonin (ng/mL)",
    "glucose_mg_dl": "Glucose (mg/dL)",
    "esr_mm_hr": "ESR (mm/hr)",
    "lactate_mmol_l": "Lactate (mmol/L)",
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


_ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06dc\u06df-\u06e4\u06e7\u06e8\u06ea-\u06ed]")


def normalize_persian_text(text: str) -> str:
    t = normalize_persian_digits(text or "")
    # Strip Arabic diacritics (harakat/tanwin) so «اِم» == «ام» in regex
    t = _ARABIC_DIACRITICS.sub("", t)
    t = t.replace("\u064a", "\u06cc")
    t = t.replace("\u0649", "\u06cc")
    t = t.replace("\u0643", "\u06a9")
    # Delete ZWNJ so «مای‌عات» stays «مایعات» (space would split the label).
    t = t.replace("\u200c", "")
    t = t.replace("\u200f", "").replace("\u200e", "")
    t = t.replace("&amp;", "&")
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
        # Hemodynamics glued / garbled tokens
        ("صدوبیست", "صد و بیست"),
        ("صدو بیست", "صد و بیست"),
        ("صد وبیست", "صد و بیست"),
        ("اسبیپی", "اس بی پی"),
        ("اس بیپی", "اس بی پی"),
        ("اس‌بی‌پی", "اس بی پی"),
        ("اس-بی-پی", "اس بی پی"),
        ("دیبیپی", "دی بی پی"),
        ("دی بیپی", "دی بی پی"),
        ("دی‌بی‌پی", "دی بی پی"),
        ("آیو ", "آی او "),
        ("آی‌او", "آی او"),
        ("i and o", "i&o"),
        ("i & o", "i&o"),
        ("وازپرسور", "وازوپرسور"),
        ("وزوپرسور", "وازوپرسور"),
        ("وازو پرسر", "وازوپرسور"),
        ("وازوپرسر", "وازوپرسور"),
        ("نداره", "ندارد"),
        ("اس تی پی", "اس بی پی"),
        ("اس تیپی", "اس بی پی"),
        ("اس‌تی‌پی", "اس بی پی"),
        ("استیپی", "اس بی پی"),
        ("اس بی بی", "اس بی پی"),
        ("متن بی پی", "اس بی پی"),
        ("متن بی بی", "اس بی پی"),
        ("دی بی بی", "دی بی پی"),
        ("دی تی پی", "دی بی پی"),
        ("تمامی و هفت", "سی و هفت"),
        ("تمامی هفت", "سی و هفت"),
        ("مصیبت پانصد", "مثبت پانصد"),
        ("dama", "دما"),
        ("DAMA", "دما"),
        ("Dama", "دما"),
        ("مای عات", "مایعات"),
        ("ما یعات", "مایعات"),
    ):
        t = t.replace(bad, good)
    t = re.sub(r"(^|\s)سد(\s|$)", r"\1صد\2", t)
    t = re.sub(
        r"(i&o|io|آی\s*او|بالانس)\s*مصیبت",
        r"\1 مثبت",
        t,
        flags=re.I,
    )
    # Spaced Latin vitals → compact tokens for label matchers
    t = re.sub(r"\bs\s*[\.\-]?\s*b\s*[\.\-]?\s*p\b", "sbp", t, flags=re.I)
    t = re.sub(r"\bd\s*[\.\-]?\s*b\s*[\.\-]?\s*p\b", "dbp", t, flags=re.I)
    t = re.sub(r"\bdama\b", "دما", t, flags=re.I)
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


def compute_vt_ibw_ml_kg(
    vte_ml: int | float | None,
    ibw_kg: float | None,
) -> float | None:
    """VT/IBW (mL/kg) from expired tidal volume and IBW."""
    if vte_ml is None or ibw_kg is None:
        return None
    try:
        vte = float(vte_ml)
        ibw = float(ibw_kg)
    except (TypeError, ValueError):
        return None
    if vte <= 0 or ibw <= 0:
        return None
    return round(vte / ibw, 1)


def compute_pf_ratio(
    pao2_mmhg: int | float | None,
    fio2_pct: int | float | None,
) -> float | None:
    """P/F ratio = PaO2 / FiO2 (FiO2 as fraction; ``fio2_pct`` may be 21–100 or 0.21–1)."""
    if pao2_mmhg is None or fio2_pct is None:
        return None
    try:
        pao2 = float(pao2_mmhg)
        fio2 = float(fio2_pct)
    except (TypeError, ValueError):
        return None
    if pao2 <= 0 or fio2 <= 0:
        return None
    frac = fio2 if fio2 <= 1.0 else fio2 / 100.0
    if frac <= 0:
        return None
    return round(pao2 / frac, 1)


def compute_map_mmhg(
    sbp_mmhg: int | float | None,
    dbp_mmhg: int | float | None,
) -> float | None:
    """MAP = DBP + (SBP − DBP) / 3."""
    if sbp_mmhg is None or dbp_mmhg is None:
        return None
    try:
        sbp = float(sbp_mmhg)
        dbp = float(dbp_mmhg)
    except (TypeError, ValueError):
        return None
    if sbp <= 0 or dbp <= 0 or sbp < dbp:
        return None
    return round(dbp + (sbp - dbp) / 3.0, 1)


def compute_driving_pressure(
    plateau_cmh2o: float | None,
    peep_measured_cmh2o: float | None,
    peep_set_cmh2o: float | None,
) -> float | None:
    """Driving Pressure = Plateau − PEEP (measured preferred over set)."""
    peep = peep_measured_cmh2o if peep_measured_cmh2o is not None else peep_set_cmh2o
    if plateau_cmh2o is None or peep is None:
        return None
    dp = round(plateau_cmh2o - peep, 1)
    return dp if 0 < dp < 80 else None


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
        rf"(?:{joined})\s*(?:ندارد|نداره|منفی|نیست|نه|غیرفعال|no)",
        text,
        re.I,
    ):
        return False
    if re.search(rf"(?:بدون|فاقد)\s*(?:{joined})", text, re.I):
        return False
    # «ندارد/نداره X» only when X starts immediately after (same clause)
    if re.search(rf"(?:ندارد|نداره)\s+(?:{joined})", text, re.I):
        return False
    # Trailing polarity: «وازوپرسور … ندارد»
    if re.search(
        rf"(?:{joined})(?:\s+\S+){{0,3}}\s+(?:ندارد|نداره|نیست|نه)\b",
        text,
        re.I,
    ):
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


_SIGN_POS = frozenset({"مثبت", "positive", "مصیبت", "+"})
_SIGN_NEG = frozenset({"منفی", "negative", "-"})


def _format_extracted_number(
    val: float, *, as_int: bool
) -> float | int:
    if as_int:
        return int(val) if val == int(val) else int(val)
    return val


def _parse_tail_number(
    tail: str,
    *,
    min_v: float,
    max_v: float,
    as_int: bool = False,
    allow_decimal: bool = False,
) -> float | int | None:
    """Read the first digit or spoken number in a short window after a label.

    Skips filler words (units, «مایعات», یعنی, …) and optional مثبت/منفی so
    STT can say «بالانس مایعات مثبت پانصد» or «بالانس مایعات مثبت ۵۰۰»
    without a dedicated regex per phrasing.
    """
    tokens = [t for t in re.split(r"[\s:،,;]+", (tail or "").strip()) if t]
    if not tokens:
        return None
    mag_max = max(abs(min_v), abs(max_v), 1.0)
    sign = 1.0
    skipped = 0
    i = 0
    while i < len(tokens):
        tok = tokens[i].strip(".-")
        low = tok.lower()
        if low in _SIGN_POS or tok in _SIGN_POS:
            sign = 1.0
            i += 1
            continue
        if low in _SIGN_NEG or tok in _SIGN_NEG:
            sign = -1.0
            i += 1
            continue
        is_num = bool(re.fullmatch(r"[+\-]?\d+(?:\.\d+)?", tok)) or tok in _ALL_WORDS
        if not is_num:
            skipped += 1
            if skipped > 6:
                return None
            i += 1
            continue
        buf: list[str] = []
        j = i
        n_words = 0
        while j < len(tokens) and n_words < 6:
            piece = tokens[j].strip(".-")
            is_decimal_sep = allow_decimal and piece == "ممیز"
            if piece == "و" or is_decimal_sep or piece in _ALL_WORDS or re.fullmatch(
                r"[+\-]?\d+(?:\.\d+)?", piece
            ):
                buf.append(piece)
                if piece not in ("و", "ممیز"):
                    n_words += 1
                j += 1
                continue
            break
        for n in range(len(buf), 0, -1):
            phrase = " ".join(buf[:n]).strip()
            if not phrase:
                continue
            parsed = _parse_spoken_or_digit(phrase, min_v=0, max_v=mag_max, allow_decimal=allow_decimal)
            if parsed is None:
                continue
            val = float(parsed) * sign
            if min_v <= val <= max_v:
                return _format_extracted_number(val, as_int=as_int)
        return None
    return None


def _number_after_labels(
    text: str,
    labels: tuple[str, ...],
    *,
    min_v: float,
    max_v: float,
    as_int: bool = False,
    allow_decimal: bool = False,
) -> float | int | None:
    """Find a numeric (digit or spoken Persian) value after any label.

    After the label we scan a short window: filler words are skipped, then the
    next spoken or digit number is taken. This is the shared slot-filler so
    each new Whisper wording does not need its own extractor.
    """
    label_re = "|".join(labels)
    for m in re.finditer(rf"(?:{label_re})", text, re.I):
        tail = text[m.end() : m.end() + 96]
        val = _parse_tail_number(tail, min_v=min_v, max_v=max_v, as_int=as_int, allow_decimal=allow_decimal)
        if val is not None:
            return val
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
    # Strip auto-peep / measured-peep phrases (with any following number, digit or spoken)
    # so that bare "peep/پیپ" does not accidentally steal their value.
    cleaned = re.sub(
        r"(?:auto[\s\-]?peep|اتو\s*پیپ|peep\s*measured|measured\s*peep|"
        r"پیپ\s*اندازه(?:\s*|‌)?گیری(?:\s*شده)?|peep\s*total)"
        r"[^\u060C\u060C،,\n]{0,30}",
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
        allow_decimal=True,
    )


def _extract_t_lo(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"t\s*lo", r"تی\s*لو", r"زمان\s*پایین"),
        min_v=0.1,
        max_v=30,
        allow_decimal=True,
    )


def _extract_ti_max(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"ti\s*(?:max|مکس)", r"تی\s*آی\s*(?:مکس|max)", r"زمان\s*دم\s*حداکثر"),
        min_v=0.1,
        max_v=10,
        allow_decimal=True,
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
        allow_decimal=True,
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
            r"آر\s*آر\s*اسپ\S*",
            r"آر\s*آر\s*خودبخودی",
            r"تنفس\s*خودبخودی",
            r"تنفس\s*اسپ\S*",
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
            r"vta\b",
            r"وی\s*تی\s*ای",
            r"وی\s*تی\s*[اآ]",
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
            r"اسپانت\S*\s*mv",
            r"اسپانتانیوس\s*ام\s*وی",
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
            r"پیک\s*پرشر",
            r"فشار\s*پیک",
            r"فشار\s*اوج",
            r"پی\s*پیک",
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
            r"پیپ\s*مژر",
            r"پیپ\s*مجر",
            r"پیپ\s*مزر",
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
        (
            r"rcexp",
            r"rc\s*exp",
            r"آر\s*سی\s*اکسپ\S*",
            r"آر\s*سی\s*ex\S*",
            r"ثابت\s*زمان\s*بازدم",
            r"تایم\s*کانستنت",
        ),
        min_v=0.1,
        allow_decimal=True,
        max_v=20,
    )


def _extract_compliance_static(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"compliance\s*static",
            r"static\s*compliance",
            r"cstat",
            r"کمپل\S*انس\s*استاتیک",
            r"کمپل\S*انس\s*ایستا",
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
            r"کمپل\S*انس\s*دینامیک",
            r"کمپل\S*انس\s*پویا",
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
        allow_decimal=True,
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


def _extract_ph(text: str) -> float | None:
    """pH: digits (7.35) or spoken medical style (هفت و سی و پنج / هفت ممیز سی و پنج)."""
    _ph_label = r"(?:\bph\b|پی\s*اچ|پی‌اچ|بی\s*اچ)"
    m = re.search(
        rf"{_ph_label}\s*[:\-]?\s*(\d+(?:[./٫]\d+)?)",
        text,
        re.I,
    )
    if m:
        val = float(m.group(1).replace("٫", ".").replace("/", "."))
        if 6.5 <= val <= 8.0:
            return round(val, 2)
    m = re.search(
        rf"{_ph_label}\s*[:\-]?\s*"
        r"((?:[^\s]+(?:\s+و\s+[^\s]+){0,4}))",
        text,
        re.I,
    )
    if not m:
        return None
    phrase = m.group(1).strip()
    phrase = re.sub(r"\s*(?:است|بود|می‌باشد).*$", "", phrase).strip()
    if "ممیز" in phrase:
        left, _, right = phrase.partition("ممیز")
        whole = persian_spoken_number(left.strip())
        frac = persian_spoken_number(right.strip())
        if whole is not None and frac is not None and 0 <= frac <= 99:
            val = whole + frac / (10 ** len(str(frac)))
            if 6.5 <= val <= 8.0:
                return round(val, 2)
        return None
    parts = [p for p in re.split(r"\s+و\s+|\s+", phrase) if p]
    if not parts:
        return None
    nums: list[int] = []
    for p in parts:
        if p.isdigit():
            nums.append(int(p))
        elif p in _ALL_WORDS:
            nums.append(_ALL_WORDS[p])
        else:
            return None
    if len(nums) >= 2 and 6 <= nums[0] <= 8:
        frac_total = sum(nums[1:])
        if 0 <= frac_total <= 99:
            val = nums[0] + frac_total / 100.0
            if 6.5 <= val <= 8.0:
                return round(val, 2)
    if len(nums) == 1 and 6.5 <= nums[0] <= 8.0:
        return float(nums[0])
    return None


def _extract_paco2(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"paco2",
            r"pa\s*co2",
            r"پی\s*ای\s*سی\s*او\s*دو",
            r"پی\s*آ\s*سی\s*او\s*دو",
            r"پی\s*اس\s*او\s*دو",   # common Whisper garble
            r"پی\s*اس\s*کو\s*دو",
            r"پا\s*سی\s*او\s*دو",
            r"کربن\s*دی\s*اکسید",
            r"دی\s*اکسید\s*کربن\s*شریانی",
        ),
        min_v=10,
        max_v=150,
    )


def _extract_pao2(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"pao2",
            r"pa\s*o2",
            r"پی\s*ای\s*او\s*دو",
            r"پی\s*آ\s*او\s*دو",
            r"اکسیژن\s*شریانی",
        ),
        min_v=20,
        max_v=600,
    )


def _extract_sao2(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"sao2",
            r"sa\s*o2",
            r"اس\s*ای\s*او\s*دو",
            r"اشباع\s*شریانی",
        ),
        min_v=40,
        max_v=100,
    )


def _extract_hco3(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"hco3",
            r"hco\s*3",
            r"بی\s*کربنات",
            r"بیکربنات",
            r"بیکربینات",
            r"بیکرینات",
            r"اچ\s*سی\s*او\s*سه",
            r"اچ\s*کو\s*سه",
            r"بی\s*کرب",          # truncated Whisper
            r"ام\s*آر\s*ای",      # Whisper garble for بیکربنات
            r"bicarbonate",
        ),
        min_v=5,
        max_v=50,
    )


def _extract_base_excess(text: str) -> float | None:
    """Base Excess — handles مثبت/منفی sign words and spoken numbers."""
    val = _number_after_labels(
        text,
        (
            r"base\s*excess",
            r"\bbe\b",
            r"بیس\s*اکسس",
            r"بیس\s*اکسز",
            r"بیس‌اکسس",
            r"بیس\s*ایکسس",
            r"بیس\s*اکزس",
            r"بیس\s*اگزس",
            r"اضافه\s*باز",
        ),
        min_v=-30,
        max_v=30,
    )
    return float(val) if val is not None else None


def _extract_pf_ratio(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"p\s*/\s*f",
            r"pf\s*ratio",
            r"p\s*f\s*ratio",
            r"پی\s*اف",
            r"نسبت\s*پی\s*اف",
            r"پی\s*به\s*اف",
        ),
        min_v=40,
        max_v=600,
    )


def _extract_bp_pair(text: str) -> tuple[float | None, float | None]:
    """Common «فشار خون ۱۲۰ روی ۸۰» / «120/80» / spoken style."""
    m = re.search(
        r"(?:فشار\s*خون|blood\s*pressure|\bbp\b)\s*[:\-]?\s*"
        r"(\d{2,3})\s*(?:روی|/|بر)\s*(\d{2,3})",
        text,
        re.I,
    )
    if not m:
        m = re.search(r"\b(\d{2,3})\s*/\s*(\d{2,3})\b", text)
    if m:
        sbp, dbp = float(m.group(1)), float(m.group(2))
        if 60 <= sbp <= 260 and 30 <= dbp <= 160 and sbp >= dbp:
            return sbp, dbp
    # Spoken: فشار خون صد و بیست روی هشتاد
    m = re.search(
        r"(?:فشار\s*خون|blood\s*pressure|\bbp\b)\s*[:\-]?\s*"
        r"((?:[^\s]+(?:\s+و\s+[^\s]+){0,3}))\s*(?:روی|/|بر)\s*"
        r"((?:[^\s]+(?:\s+و\s+[^\s]+){0,2}))",
        text,
        re.I,
    )
    if m:
        sbp_i = persian_spoken_number(m.group(1).strip().strip(" .،-"))
        dbp_i = persian_spoken_number(m.group(2).strip().strip(" .،-"))
        if (
            sbp_i is not None
            and dbp_i is not None
            and 60 <= sbp_i <= 260
            and 30 <= dbp_i <= 160
            and sbp_i >= dbp_i
        ):
            return float(sbp_i), float(dbp_i)
    return None, None


def _extract_sbp(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"\bsbp\b",
            r"systolic",
            r"ای[\s\-]*اس[\s\-]*بی[\s\-]*پی",
            r"اس[\s\-]*بی[\s\-]*پی",
            r"اس[\s\-]*تی[\s\-]*پی",
            r"اسبی[\s\-]*پی",
            r"فشار\s*سیستول(?:یک)?",
            r"سیستول(?:یک)?",
        ),
        min_v=60,
        max_v=260,
    )


def _extract_dbp(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"\bdbp\b",
            r"diastolic",
            r"دی[\s\-]*بی[\s\-]*پی",
            r"دیبی[\s\-]*پی",
            r"فشار\s*دیاستول(?:یک)?",
            r"دیاستول(?:یک)?",
        ),
        min_v=30,
        max_v=160,
    )


def _extract_map_spoken(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"\bmap\b",
            r"mean\s*arterial",
            r"ام\s*ای\s*پی",
            r"فشار\s*متوسط\s*شریانی",
        ),
        min_v=30,
        max_v=180,
    )


def _extract_hr(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"\bhr\b",
            r"heart\s*rate",
            r"اچ\s*آر",
            r"ضربان\s*قلب",
            r"نبض",
            r"ضربان",
        ),
        min_v=20,
        max_v=250,
    )


def _parse_spoken_or_digit(
    raw: str,
    *,
    min_v: float,
    max_v: float,
    allow_half: bool = False,
    allow_decimal: bool = False,
) -> float | None:
    """Parse digit or Persian spoken number; optional «و نیم» and decimal fractions.

    When allow_decimal=True, phrases like «صفر و سه» → 0.3, «یک و پنج» → 1.5
    are tried (X و Y where Y is a 1-2 digit number, fraction = Y / 10^len(Y)).
    """
    phrase = (raw or "").strip().strip(" .،-:")
    if not phrase:
        return None
    half = False
    if allow_half and re.search(r"\bنیم\b", phrase):
        half = True
        phrase = re.sub(r"\s*و?\s*نیم\b", "", phrase).strip()
    # Handle explicit decimal point word ممیز: «صفر ممیز سه» → 0.3
    if "ممیز" in phrase:
        left, _, right = phrase.partition("ممیز")
        whole = persian_spoken_number(left.strip()) or (0 if left.strip() in ("صفر", "0") else None)
        frac_int = persian_spoken_number(right.strip())
        if whole is not None and frac_int is not None and 0 <= frac_int <= 99:
            val = whole + frac_int / (10 ** len(str(frac_int)))
            if half:
                val += 0.5
            if min_v <= val <= max_v:
                return round(val, 2)
        return None
    if re.fullmatch(r"[+\-]?\d+(?:\.\d+)?", phrase):
        val = float(phrase)
        if half:
            val += 0.5
        if min_v <= val <= max_v:
            return round(val, 1)
        return None
    # First try standard spoken number (handles compound numbers like «سی و پنج» = 35)
    spoken = persian_spoken_number(phrase)
    if spoken is not None:
        val = float(spoken)
        if half:
            val += 0.5
        if min_v <= val <= max_v:
            return round(val, 1)
    # Allow decimal only when left part is a single digit (0-9): «یک و پنج» → 1.5
    # This avoids mis-parsing compound numbers like «سی و پنج» (35) as 30.5.
    if allow_decimal and " و " in phrase:
        left_tok, _, right_tok = phrase.partition(" و ")
        left_val = persian_spoken_number(left_tok.strip())
        right_val = persian_spoken_number(right_tok.strip())
        if left_val is not None and right_val is not None and 0 <= left_val <= 9 and 0 <= right_val <= 99:
            val = left_val + right_val / (10 ** len(str(int(right_val))))
            if half:
                val += 0.5
            if min_v <= val <= max_v:
                return round(val, 2)
    return None


def _extract_temperature(text: str) -> float | None:
    """Body temperature (C); tolerant of STT label variants."""
    labels = (
        r"temperature",
        r"body\s*temp(?:erature)?",
        r"\btemp\b",
        r"\bdama\b",
        r"تمپ(?:راتور)?",
        r"دما(?:ی\s*بدن)?",
        r"حرارت(?:\s*بدن)?",
        r"درجه\s*حرارت(?:\s*بدن)?",
        r"درجه\s*سانتی[\s\-]?گراد",
    )
    val = _number_after_labels(text, labels, min_v=30, max_v=45)
    if val is not None:
        return float(val)

    label_re = "|".join(labels)
    m = re.search(
        rf"(?:{label_re})\s*[:\-]?\s*"
        r"((?:[^\s]+(?:\s+و\s+[^\s]+){0,3}|\d+(?:\.\d+)?))",
        text,
        re.I,
    )
    if m:
        parsed = _parse_spoken_or_digit(
            m.group(1), min_v=30, max_v=45, allow_half=True
        )
        if parsed is not None:
            return parsed

    # «سی و هفت درجه» / «۳۷ درجه سانتی‌گراد» without explicit دما
    m = re.search(
        r"((?:[^\s]+(?:\s+و\s+[^\s]+){0,3}|\d+(?:\.\d+)?))\s*"
        r"(?:درجه(?:\s*(?:سانتی[\s\-]?گراد|حرارت|سلسیوس))?|°\s*c|\bcelsius\b)",
        text,
        re.I,
    )
    if m:
        parsed = _parse_spoken_or_digit(
            m.group(1), min_v=30, max_v=45, allow_half=True
        )
        if parsed is not None:
            return parsed
    return None


def _extract_urine_output(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"urine\s*output",
            r"urine",
            r"خروجی\s*ادرار",
            r"ادرار(?:\s*خروجی)?",
            r"یورین",
        ),
        min_v=0,
        max_v=1000,
    )


def _extract_io_balance_24h(text: str) -> float | None:
    """24h I&O: require explicit بالانس/I&O keyword to avoid false ABG matches."""
    val = _number_after_labels(
        text,
        (
            r"بالانس[\s\-]*ما[\s]*ی[\s]*عات",
            r"تعادل[\s\-]*ما[\s]*ی[\s]*عات",
            r"i\s*&\s*o",
            r"\bi&o\b",
            r"i\s*and\s*o",
            r"io\s*balance",
            r"fluid\s*balance",
            r"intake\s*output",
            r"input\s*output",
            # at least one space/dash required so «آیاو» (no space = SaO2 garble) does not match
            r"آی[\s\-]+او",
            r"آی\s+اند\s+او",
            r"آی\s+and\s+او",
            r"بالانس\s*(?:۲۴|24)\s*ساعته",
            r"اینتیک\s*آوت\s*پوت",
            r"بالانس",
        ),
        min_v=-5000,
        max_v=5000,
    )
    if val is not None:
        return float(val)
    # Value-before-label: «مثبت پانصد بالانس»
    m = re.search(
        r"(منفی|مثبت|مصیبت|negative|positive)\s+"
        r"((?:[^\s]+(?:\s+و\s+[^\s]+){0,3}|\d+(?:\.\d+)?))\s+"
        r"(?:بالانس|i\s*&\s*o|آی[\s\-]+او|fluid\s*balance)",
        text,
        re.I,
    )
    if not m:
        return None
    raw = m.group(2).strip()
    parsed = _parse_spoken_or_digit(raw, min_v=0, max_v=5000)
    if parsed is None:
        return None
    sw = m.group(1).strip().lower()
    val_f = -abs(float(parsed)) if sw in _SIGN_NEG else abs(float(parsed))
    if -5000 <= val_f <= 5000:
        return val_f
    return None


def _extract_vasopressor(text: str) -> bool | None:
    return _extract_bool_flag(
        text,
        (
            r"vasopressor",
            r"vaso\s*pressor",
            r"وازوپرسور",
            r"وازو\s*پرسور",
            r"وازو\s*پرسر",
            r"وازپرسور",
            r"وزوپرسور",
            r"وازوپرسورها",
            r"نوراپی\s*نفرین",
            r"norepi(?:nephrine)?",
            r"noradrenaline",
        ),
    )


# ── Lab extractors ─────────────────────────────────────────────────────────────

def _extract_hb(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"\bhb\b", r"hemoglobin", r"هموگلوبین", r"هموگلبین",
            r"هموگلوبن", r"هموگلوبیم", r"هب\b", r"اچ\s*بی\b",
        ),
        min_v=3.0, max_v=25.0,
        allow_decimal=True,
    )


def _extract_hct(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"\bhct\b", r"hematocrit", r"هماتوکریت", r"هموتوکریت"),
        min_v=5.0, max_v=75.0,
        allow_decimal=True,
    )


def _extract_wbc(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"\bwbc\b", r"white\s*blood\s*cell", r"گلبول\s*سفید", r"وایت\s*بلاد\s*سل", r"لکوسیت"),
        min_v=0.1, max_v=500.0,
        allow_decimal=True,
    )


def _extract_platelets(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"platelet", r"پلاکت", r"ترومبوسیت"),
        min_v=1.0, max_v=3000.0,
        allow_decimal=True,
    )


def _extract_na(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"\bna\b", r"\bsodium\b", r"سدیم", r"سدیوم",
            r"سدیام", r"سدیامً", r"نا\s*(?=[\d۰-۹])",
            r"(?<![آا-ی])نا(?=\s*[:؛]?\s*[\d۰-۹])",
        ),
        min_v=100.0, max_v=185.0,
        allow_decimal=True,
    )


def _extract_k(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"\bk\b", r"\bpotassium\b", r"پتاسیم", r"پتاسیوم",
            r"پتاسیمم", r"پطاسیم", r"کا\s*(?=[\d۰-۹])",
            r"(?<!\w)k(?=\s*[:؛]?\s*[\d۰-۹])",
        ),
        min_v=1.0, max_v=9.0,
        allow_decimal=True,
    )


def _extract_ca(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"\bca\b", r"\bcalcium\b", r"کلسیم", r"کلسیوم"),
        min_v=4.0, max_v=18.0,
        allow_decimal=True,
    )


def _extract_mg(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"\bmg\b", r"\bmagnesium\b", r"منیزیم", r"منیزیوم"),
        min_v=0.5, max_v=6.0,
        allow_decimal=True,
    )


def _extract_phosphate(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"phosphate", r"phosphorus", r"فسفات", r"فسفر", r"فسفاط", r"فاسفات", r"فسفیت"),
        min_v=0.3, max_v=15.0,
        allow_decimal=True,
    )


def _extract_bun(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"\bbun\b", r"blood\s*urea\s*nitrogen", r"اوره", r"یوریا", r"بی\s*یو\s*ان"),
        min_v=1.0, max_v=500.0,
        allow_decimal=True,
    )


def _extract_creatinine(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"creatinine", r"کراتینین", r"کراتنین", r"\bcr\b"),
        min_v=0.2, max_v=30.0,
        allow_decimal=True,
    )


def _extract_albumin(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"albumin", r"آلبومین", r"البومین"),
        min_v=0.5, max_v=6.0,
        allow_decimal=True,
    )


def _extract_ast(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"\bast\b", r"\bsgot\b", r"آ\s*اس\s*تی", r"اس\s*جی\s*او\s*تی"),
        min_v=5.0, max_v=10000.0,
    )


def _extract_alt(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"\balt\b", r"\bsgpt\b", r"آ\s*ال\s*تی", r"اس\s*جی\s*پی\s*تی"),
        min_v=5.0, max_v=10000.0,
    )


def _extract_bilirubin(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"bilirubin", r"بیلیروبین", r"بیلی\s*روبین"),
        min_v=0.1, max_v=60.0,
        allow_decimal=True,
    )


def _extract_crp(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"\bcrp\b", r"c[\s\-]?reactive\s*protein", r"سی\s*آر\s*پی"),
        min_v=0.0, max_v=1000.0,
        allow_decimal=True,
    )


def _extract_procalcitonin(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"procalcitonin", r"\bpct\b", r"پروکلسیتونین", r"پروکلسیونین", r"پی\s*سی\s*تی"),
        min_v=0.0, max_v=1000.0,
        allow_decimal=True,
    )


def _extract_glucose(text: str) -> float | None:
    return _number_after_labels(
        text,
        (r"glucose", r"گلوکز", r"قند\s*خون", r"قند\b", r"بلاد\s*شوگر"),
        min_v=20.0, max_v=1500.0,
    )


def _extract_esr(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"\besr\b", r"\besrc\b", r"\besc\b",
            r"erythrocyte\s*sedimentation", r"رسوب\s*خون",
            r"ای\s*اس\s*آر", r"ای\s*اس\s*ار", r"ا\s*س\s*ر\b",
            r"سرعت\s*رسوب",
        ),
        min_v=0.0, max_v=200.0,
    )


def _extract_lactate(text: str) -> float | None:
    return _number_after_labels(
        text,
        (
            r"lactate", r"lactic\s*acid", r"لاکتات", r"لاکتیک",
            r"لاکتیت", r"لاکتاط", r"لاکتت",
        ),
        min_v=0.1, max_v=30.0,
        allow_decimal=True,
    )


# ── End Lab extractors ─────────────────────────────────────────────────────────


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
    if key in ("sedation_active", "recent_surgery", "fever", "vasopressor_active"):
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
    if key == "paco2_mmhg":
        return f"{value} mmHg"
    if key == "pao2_mmhg":
        return f"{value} mmHg"
    if key == "sao2_pct":
        return f"{value}%"
    if key == "hco3_meq_l":
        return f"{value} mEq/L"
    if key == "base_excess_meq_l":
        return f"{value} mEq/L"
    if key in ("sbp_mmhg", "dbp_mmhg", "map_mmhg"):
        return f"{value} mmHg"
    if key == "hr_bpm":
        return f"{value} bpm"
    if key == "temperature_c":
        return f"{value} °C"
    if key == "urine_output_ml_hr":
        return f"{value} mL/hr"
    if key == "io_balance_24h_ml":
        return f"{value} mL"
    if key == "vt_set_ml":
        return f"{value} ml"
    if key == "rr_set_bpm":
        return f"{value} bpm"
    return str(value)


def _fill_nulls_second_pass(text: str, fields: dict[str, Any]) -> None:
    """Second pass: fill remaining null keys with looser label/number windows.

    Does not overwrite values already set. Used so STT variants like ``I&O`` /
    glued SBP still populate after the primary extractors.
    """
    extras: dict[str, tuple[tuple[str, ...], float, float]] = {
        "sbp_mmhg": (
            (r"\bsbp\b", r"اس[\s\-]*بی[\s\-]*پی", r"اس[\s\-]*تی[\s\-]*پی", r"سیستول"),
            60,
            260,
        ),
        "dbp_mmhg": (
            (r"\bdbp\b", r"دی[\s\-]*بی[\s\-]*پی", r"دیاستول"),
            30,
            160,
        ),
        "hr_bpm": ((r"\bhr\b", r"اچ[\s\-]*آر", r"ضربان", r"نبض"), 20, 250),
        "temperature_c": ((r"دما", r"تمپ", r"\bdama\b", r"حرارت", r"temperature"), 30, 45),
        "urine_output_ml_hr": ((r"ادرار", r"urine", r"یورین"), 0, 1000),
        "io_balance_24h_ml": (
            (
                r"\bi&o\b",
                r"آی[\s\-]+او",
                r"بالانس[\s\-]*ما[\s]*ی[\s]*عات",
                r"بالانس[\s\-]*مایعات",
                r"بالانس",
            ),
            -5000,
            5000,
        ),
    }
    for key, (labels, min_v, max_v) in extras.items():
        if fields.get(key) is not None:
            continue
        val = _number_after_labels(text, labels, min_v=min_v, max_v=max_v)
        if val is not None:
            fields[key] = float(val)
    if fields.get("io_balance_24h_ml") is None:
        fields["io_balance_24h_ml"] = _extract_io_balance_24h(text)
    if fields.get("sbp_mmhg") is None:
        fields["sbp_mmhg"] = _extract_sbp(text)
    if fields.get("vasopressor_active") is None:
        fields["vasopressor_active"] = _extract_vasopressor(text)


_LLM_HEMO_SYSTEM = """\
You are a medical data extractor for Persian ICU speech (possibly with STT errors).
Extract the following fields and return ONLY a valid JSON object — no markdown, no explanation.

HEMODYNAMICS:
  sbp_mmhg            — systolic BP mmHg (number or null)
  dbp_mmhg            — diastolic BP mmHg (number or null)
  hr_bpm              — heart rate bpm (number or null)
  temperature_c       — body temperature °C (number or null)
  urine_output_ml_hr  — urine output mL/hr (number or null)
  io_balance_24h_ml   — 24-hour I&O fluid balance mL (number or null)
                        IMPORTANT: extract ONLY when the text explicitly mentions
                        بالانس، آی او، I&O، fluid balance, or تعادل مایعات.
                        Do NOT extract from Base Excess, بیس اکسس, or other ABG fields.
  vasopressor_active  — true/false/null

ABG:
  ph                  — arterial pH (number or null, typically 7.0–7.6)
  paco2_mmhg          — PaCO2 mmHg (number or null)
  pao2_mmhg           — PaO2 mmHg (number or null)
  sao2_pct            — SaO2 % (number or null)
  hco3_meq_l          — HCO3 mEq/L (number or null)
  base_excess_meq_l   — Base Excess mEq/L, positive when مثبت, negative when منفی (number or null)

VENTILATOR MEASUREMENTS:
  rr_total_bpm        — total respiratory rate bpm (number or null); look for آر آر توتال / RR total
  rr_spontaneous_bpm  — spontaneous respiratory rate bpm (number or null); look for آر آر اسپانتانیوس / RR spontaneous / آر آر اسپونتانیوس
  rsbi                — Rapid Shallow Breathing Index (number or null, typically 30–200); look for RSBI / آر اس بی آی
  rcexp_sec           — expiratory time constant seconds (number or null, typically 0.1–5); look for RC exp / آر سی اکسپ / ثابت زمان بازدم
  wob_jl              — work of breathing J/L (number or null, typically 0–5); look for WOB / کار تنفس

LAB VALUES (fallback only — fill if regex missed):
  hb_gdl              — hemoglobin g/dL (number or null, 3–25); هموگلوبین / Hb / اچ بی
  hct_pct             — hematocrit % (number or null, 5–75); هماتوکریت / HCT
  wbc_k_ul            — WBC k/μL (number or null, 0.1–500); گلبول سفید / WBC / لکوسیت
  platelets_k_ul      — platelets k/μL (number or null, 1–3000); پلاکت / ترومبوسیت
  na_meq_l            — sodium mEq/L (number or null, 100–185); سدیم / Na / سدیوم
  k_meq_l             — potassium mEq/L (number or null, 1–9); پتاسیم / K / پتاسیوم
  ca_mg_dl            — calcium mg/dL (number or null, 4–18); کلسیم / Ca
  mg_mg_dl            — magnesium mg/dL (number or null, 0.5–6); منیزیم / Mg
  phosphate_mg_dl     — phosphate mg/dL (number or null, 0.3–15); فسفات / فسفر
  bun_mg_dl           — BUN mg/dL (number or null, 1–500); اوره / BUN / یوریا
  creatinine_mg_dl    — creatinine mg/dL (number or null, 0.2–30); کراتینین / Cr
  albumin_g_dl        — albumin g/dL (number or null, 0.5–6); آلبومین
  ast_u_l             — AST U/L (number or null, 5–10000); آ اس تی / SGOT
  alt_u_l             — ALT U/L (number or null, 5–10000); آ ال تی / SGPT
  bilirubin_mg_dl     — bilirubin mg/dL (number or null, 0.1–60); بیلیروبین
  crp_mg_l            — CRP mg/L (number or null, 0–1000); سی آر پی / CRP
  procalcitonin_ng_ml — procalcitonin ng/mL (number or null, 0–1000); پروکلسیتونین / PCT
  glucose_mg_dl       — glucose mg/dL (number or null, 20–1500); گلوکز / قند / قند خون
  esr_mm_hr           — ESR mm/hr (number or null, 0–200); ای اس آر / رسوب خون / سرعت رسوب
  lactate_mmol_l      — lactate mmol/L (number or null, 0.1–30); لاکتات

        Rules:
- Return null for any field not mentioned in the text.
- Convert Persian spoken numbers: پانصد=500, هشتاد=80, سی و پنج=35, هفت=7, etc.
  Compound numbers like سی و پنج=35, صد و سی و هشت=138, چهل=40 (NOT decimal — no ممیز).
- Fractions ONLY when ممیز is spoken, e.g. یک ممیز پنج=1.5, صفر ممیز سه=0.3.
- Fractions like "هفت و سی و پنج" = 7.35 (for pH, using ممیز implicitly for pH).
- io_balance_24h_ml: positive when مثبت/positive, negative when منفی/negative.
- base_excess_meq_l: positive when مثبت/positive, negative when منفی/negative.
- Return ONLY the JSON object.
"""

_LLM_HEMO_FIELDS = (
    "sbp_mmhg",
    "dbp_mmhg",
    "hr_bpm",
    "temperature_c",
    "urine_output_ml_hr",
    "io_balance_24h_ml",
    "vasopressor_active",
    "ph",
    "paco2_mmhg",
    "pao2_mmhg",
    "sao2_pct",
    "hco3_meq_l",
    "base_excess_meq_l",
)

# These fields use LLM only as fallback (only_missing=True): regex is tried first.
_LLM_FALLBACK_FIELDS: tuple[str, ...] = (
    "rr_total_bpm",
    "rr_spontaneous_bpm",
    "rsbi",
    "rcexp_sec",
    "wob_jl",
    # Lab fields — LLM as fallback when regex fails due to STT garbling
    "hb_gdl",
    "hct_pct",
    "wbc_k_ul",
    "platelets_k_ul",
    "na_meq_l",
    "k_meq_l",
    "ca_mg_dl",
    "mg_mg_dl",
    "phosphate_mg_dl",
    "bun_mg_dl",
    "creatinine_mg_dl",
    "albumin_g_dl",
    "ast_u_l",
    "alt_u_l",
    "bilirubin_mg_dl",
    "crp_mg_l",
    "procalcitonin_ng_ml",
    "glucose_mg_dl",
    "esr_mm_hr",
    "lactate_mmol_l",
)


_LLM_FIELD_RANGES: dict[str, tuple[float, float]] = {
    "sbp_mmhg": (60.0, 260.0),
    "dbp_mmhg": (30.0, 160.0),
    "hr_bpm": (20.0, 250.0),
    "temperature_c": (30.0, 45.0),
    "urine_output_ml_hr": (0.0, 2000.0),
    "io_balance_24h_ml": (-10000.0, 10000.0),
    "ph": (6.5, 7.8),
    "paco2_mmhg": (10.0, 150.0),
    "pao2_mmhg": (20.0, 600.0),
    "sao2_pct": (40.0, 100.0),
    "hco3_meq_l": (5.0, 50.0),
    "base_excess_meq_l": (-30.0, 30.0),
    "fio2_pct": (21.0, 100.0),
    "rr_total_bpm": (1.0, 60.0),
    "rr_spontaneous_bpm": (0.0, 60.0),
    "rsbi": (10.0, 400.0),
    "rcexp_sec": (0.1, 10.0),
    "wob_jl": (0.0, 20.0),
    # Lab ranges
    "hb_gdl": (3.0, 25.0),
    "hct_pct": (5.0, 75.0),
    "wbc_k_ul": (0.1, 500.0),
    "platelets_k_ul": (1.0, 3000.0),
    "na_meq_l": (100.0, 185.0),
    "k_meq_l": (1.0, 9.0),
    "ca_mg_dl": (4.0, 18.0),
    "mg_mg_dl": (0.5, 6.0),
    "phosphate_mg_dl": (0.3, 15.0),
    "bun_mg_dl": (1.0, 500.0),
    "creatinine_mg_dl": (0.2, 30.0),
    "albumin_g_dl": (0.5, 6.0),
    "ast_u_l": (5.0, 10000.0),
    "alt_u_l": (5.0, 10000.0),
    "bilirubin_mg_dl": (0.1, 60.0),
    "crp_mg_l": (0.0, 1000.0),
    "procalcitonin_ng_ml": (0.0, 1000.0),
    "glucose_mg_dl": (20.0, 1500.0),
    "esr_mm_hr": (0.0, 200.0),
    "lactate_mmol_l": (0.1, 30.0),
}


def _llm_call(transcript: str) -> dict[str, Any] | None:
    """Call GapGPT/OpenAI and return parsed JSON dict, or None on any failure."""
    llm_flag = os.getenv("FORM_EXTRACT_LLM", "0").strip().lower()
    if llm_flag not in ("1", "true", "yes", "on", "auto"):
        return None

    api_key = (
        os.getenv("OPENAI_API_KEY")
        or os.getenv("GAPGPT_API_KEY")
        or os.getenv("OPENAI_TTS_API_KEY")
        or ""
    ).strip().strip("\"'")
    if not api_key:
        return None

    base_url = (
        os.getenv("OPENAI_BASE_URL")
        or os.getenv("GAPGPT_BASE_URL")
        or "https://api.openai.com/v1"
    ).rstrip("/")
    model = (
        os.getenv("FORM_EXTRACT_LLM_MODEL")
        or os.getenv("OPENAI_SPEECH_LLM_MODEL")
        or "gpt-4o-mini"
    ).strip()

    try:
        import requests as _req

        resp = _req.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "temperature": 0,
                "max_tokens": 700,
                "messages": [
                    {"role": "system", "content": _LLM_HEMO_SYSTEM},
                    {"role": "user", "content": transcript[:2000]},
                ],
            },
            timeout=20,
        )
        if resp.status_code >= 400:
            return None
        raw_json = (
            resp.json()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            or ""
        ).strip()
        raw_json = re.sub(r"^```(?:json)?\s*", "", raw_json)
        raw_json = re.sub(r"\s*```$", "", raw_json).strip()
        parsed = json.loads(raw_json)
        # Flatten nested {"HEMODYNAMICS": {...}, "ABG": {...}} if model returns that
        if isinstance(parsed, dict) and not any(k in parsed for k in _LLM_HEMO_FIELDS):
            flat: dict[str, Any] = {}
            for v in parsed.values():
                if isinstance(v, dict):
                    flat.update(v)
            return flat if flat else parsed
        return parsed
    except Exception:
        return None


def _apply_llm_data(data: dict[str, Any], fields: dict[str, Any], *, only_missing: bool) -> None:
    """Merge validated LLM output into fields dict.

    When only_missing=True, existing non-None values are kept (fallback mode).
    When only_missing=False (primary), LLM values overwrite regex AND explicit
    LLM nulls clear regex false-positives for covered fields.
    Fallback fields (_LLM_FALLBACK_FIELDS) always use only_missing=True regardless
    of the caller's only_missing setting, so regex is never overwritten for them.
    """
    all_keys = list(_LLM_HEMO_FIELDS) + list(_LLM_FALLBACK_FIELDS)
    for key in all_keys:
        effective_only_missing = only_missing or (key in _LLM_FALLBACK_FIELDS)
        if effective_only_missing and fields.get(key) is not None:
            continue
        if key not in data:
            continue
        val = data.get(key)
        if val is None:
            if not effective_only_missing:
                fields[key] = None
            continue
        if key == "vasopressor_active":
            if isinstance(val, bool):
                fields[key] = val
            elif isinstance(val, str):
                fields[key] = val.strip().lower() in ("true", "yes", "1", "دارد")
            continue
        try:
            num = float(val)
        except (TypeError, ValueError):
            continue
        lo, hi = _LLM_FIELD_RANGES.get(key, (-1e9, 1e9))
        if lo <= num <= hi:
            fields[key] = num


def _llm_hemo_fallback(transcript: str, fields: dict[str, Any]) -> None:
    """LLM extraction: PRIMARY when FORM_EXTRACT_LLM=1, always fills missing fields.

    Strategy:
      1. Call LLM with the full transcript.
      2. LLM results OVERWRITE any regex value that is not in a safe range —
         but only if LLM returned a plausible number (range-checked).
      3. Regex values that LLM returned null for are kept unchanged.

    This means Whisper garbling of labels ("آیاو" for SaO2, "مقر بی اچ" for pH)
    no longer matters — the LLM reads contextual meaning, not exact labels.
    """
    data = _llm_call(transcript)
    if data is None:
        return
    # Primary mode: LLM is authoritative; regex values kept only where LLM is null
    _apply_llm_data(data, fields, only_missing=False)


def extract_patient_demographics(transcript: str) -> dict[str, Any]:
    """Parse HakimAI form fields (patient + vent + measurement + ABG + hemodynamics).

    Backward-compatible name; returns flat keys + found/missing lists.
    Earlier tab keys stay unchanged; hemodynamics keys are additive.
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
    # Like IBW: compute when inputs exist; fall back to spoken value otherwise.
    vt_ibw_ml_kg = compute_vt_ibw_ml_kg(vte_ml, ibw_kg)
    if vt_ibw_ml_kg is None:
        vt_ibw_ml_kg = _extract_vt_ibw(text)
    minute_ventilation_lpm = _extract_minute_ventilation(text)
    spontaneous_mv_lpm = _extract_spontaneous_mv(text)
    peak_pressure_cmh2o = _extract_peak_pressure(text)
    plateau_pressure_cmh2o = _extract_plateau_pressure(text)
    peep_measured_cmh2o = _extract_peep_measured(text)
    auto_peep_cmh2o = _extract_auto_peep(text)
    mean_pressure_cmh2o = _extract_mean_pressure(text)
    driving_pressure_cmh2o = _extract_driving_pressure(text)
    if driving_pressure_cmh2o is None:
        driving_pressure_cmh2o = compute_driving_pressure(
            plateau_pressure_cmh2o, peep_measured_cmh2o, peep_cmh2o
        )
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

    # ABG tab (additive)
    ph = _extract_ph(text)
    paco2_mmhg = _extract_paco2(text)
    pao2_mmhg = _extract_pao2(text)
    sao2_pct = _extract_sao2(text)
    hco3_meq_l = _extract_hco3(text)
    base_excess_meq_l = _extract_base_excess(text)
    pf_ratio = compute_pf_ratio(pao2_mmhg, fio2_pct)
    if pf_ratio is None:
        pf_ratio = _extract_pf_ratio(text)

    # Hemodynamics / vital signs (additive)
    sbp_mmhg = _extract_sbp(text)
    dbp_mmhg = _extract_dbp(text)
    if sbp_mmhg is None or dbp_mmhg is None:
        pair_sbp, pair_dbp = _extract_bp_pair(text)
        if sbp_mmhg is None:
            sbp_mmhg = pair_sbp
        if dbp_mmhg is None:
            dbp_mmhg = pair_dbp
    map_mmhg = compute_map_mmhg(sbp_mmhg, dbp_mmhg)
    if map_mmhg is None:
        map_mmhg = _extract_map_spoken(text)
    hr_bpm = _extract_hr(text)
    temperature_c = _extract_temperature(text)
    urine_output_ml_hr = _extract_urine_output(text)
    io_balance_24h_ml = _extract_io_balance_24h(text)
    vasopressor_active = _extract_vasopressor(text)

    # Lab tab
    hb_gdl = _extract_hb(text)
    hct_pct = _extract_hct(text)
    wbc_k_ul = _extract_wbc(text)
    platelets_k_ul = _extract_platelets(text)
    na_meq_l = _extract_na(text)
    k_meq_l = _extract_k(text)
    ca_mg_dl = _extract_ca(text)
    mg_mg_dl = _extract_mg(text)
    phosphate_mg_dl = _extract_phosphate(text)
    bun_mg_dl = _extract_bun(text)
    creatinine_mg_dl = _extract_creatinine(text)
    albumin_g_dl = _extract_albumin(text)
    ast_u_l = _extract_ast(text)
    alt_u_l = _extract_alt(text)
    bilirubin_mg_dl = _extract_bilirubin(text)
    crp_mg_l = _extract_crp(text)
    procalcitonin_ng_ml = _extract_procalcitonin(text)
    glucose_mg_dl = _extract_glucose(text)
    esr_mm_hr = _extract_esr(text)
    lactate_mmol_l = _extract_lactate(text)

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
        "ph": ph,
        "paco2_mmhg": paco2_mmhg,
        "pao2_mmhg": pao2_mmhg,
        "sao2_pct": sao2_pct,
        "hco3_meq_l": hco3_meq_l,
        "base_excess_meq_l": base_excess_meq_l,
        "pf_ratio": pf_ratio,
        "sbp_mmhg": sbp_mmhg,
        "dbp_mmhg": dbp_mmhg,
        "map_mmhg": map_mmhg,
        "hr_bpm": hr_bpm,
        "temperature_c": temperature_c,
        "urine_output_ml_hr": urine_output_ml_hr,
        "io_balance_24h_ml": io_balance_24h_ml,
        "vasopressor_active": vasopressor_active,
        "hb_gdl": hb_gdl,
        "hct_pct": hct_pct,
        "wbc_k_ul": wbc_k_ul,
        "platelets_k_ul": platelets_k_ul,
        "na_meq_l": na_meq_l,
        "k_meq_l": k_meq_l,
        "ca_mg_dl": ca_mg_dl,
        "mg_mg_dl": mg_mg_dl,
        "phosphate_mg_dl": phosphate_mg_dl,
        "bun_mg_dl": bun_mg_dl,
        "creatinine_mg_dl": creatinine_mg_dl,
        "albumin_g_dl": albumin_g_dl,
        "ast_u_l": ast_u_l,
        "alt_u_l": alt_u_l,
        "bilirubin_mg_dl": bilirubin_mg_dl,
        "crp_mg_l": crp_mg_l,
        "procalcitonin_ng_ml": procalcitonin_ng_ml,
        "glucose_mg_dl": glucose_mg_dl,
        "esr_mm_hr": esr_mm_hr,
        "lactate_mmol_l": lactate_mmol_l,
    }
    _fill_nulls_second_pass(text, fields)
    if fields.get("map_mmhg") is None:
        fields["map_mmhg"] = compute_map_mmhg(
            fields.get("sbp_mmhg"), fields.get("dbp_mmhg")
        )
    # LLM fallback: fill any still-missing hemo field via GapGPT/OpenAI
    _llm_hemo_fallback(raw, fields)
    # Recompute MAP if LLM filled sbp/dbp but not map
    if fields.get("map_mmhg") is None:
        fields["map_mmhg"] = compute_map_mmhg(
            fields.get("sbp_mmhg"), fields.get("dbp_mmhg")
        )
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
    """Recompute IBW / VT/IBW / P/F / MAP / found / missing after merge or manual edit."""
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
    computed_vt_ibw = compute_vt_ibw_ml_kg(out.get("vte_ml"), ibw)
    if computed_vt_ibw is not None:
        out["vt_ibw_ml_kg"] = computed_vt_ibw
    computed_pf = compute_pf_ratio(out.get("pao2_mmhg"), out.get("fio2_pct"))
    if computed_pf is not None:
        out["pf_ratio"] = computed_pf
    computed_map = compute_map_mmhg(out.get("sbp_mmhg"), out.get("dbp_mmhg"))
    if computed_map is not None:
        out["map_mmhg"] = computed_map
    computed_dp = compute_driving_pressure(
        out.get("plateau_pressure_cmh2o"),
        out.get("peep_measured_cmh2o"),
        out.get("peep_cmh2o"),
    )
    if computed_dp is not None and out.get("driving_pressure_cmh2o") is None:
        out["driving_pressure_cmh2o"] = computed_dp
    found = [k for k, v in out.items() if v is not None]
    if "ibw_kg" in found and (out.get("gender") is None or out.get("height_cm") is None):
        found = [k for k in found if k != "ibw_kg"]
        out["ibw_kg"] = None
        # IBW cleared → drop derived VT/IBW unless it was only spoken without VTe
        if computed_vt_ibw is not None:
            out["vt_ibw_ml_kg"] = None
            found = [k for k in found if k != "vt_ibw_ml_kg"]
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
