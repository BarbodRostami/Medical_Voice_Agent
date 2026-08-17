"""EXPERIMENT — visual gold-label / eval page (does not replace voice_form_ui).

    streamlit run backend/experiments/voice_eval_ui.py --server.port 8610
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from backend.experiments.eval_voice_form import (
    SKIP_KEYS,
    evaluate_dataset,
    init_gold_stubs,
    load_gold,
    score_sample,
)
from backend.experiments.form_extract import FIELD_LABELS_FA, extract_patient_demographics
from backend.experiments.voice_dataset import DATASET_DIR

DEMO_TRANSCRIPT = "پتاسیم ممیز نه، پروکلسیتونین ممیز هشت، سدیم صد و چهل"
DEMO_GOLD = {"k": 0.9, "procalcitonin": 0.8, "na": 140}

st.set_page_config(page_title="Voice form eval", layout="wide")
st.title("ارزیابی فرم صوتی — برچسب طلایی")
st.caption(
    "این صفحه جدا از UI ضبط است (پورت ۸۶۰۱). "
    "اینجا می‌بینید استخراج با آنچه واقعاً گفته شده چه فرقی دارد."
)

st.markdown(
    """
**سه ستون یعنی چه؟**
1. **گفته شده (gold)** — حقیقت؛ شما از روی صدا/قصد خودتان پر می‌کنید.
2. **استخراج پارسر** — خروجی کد از روی متن Whisper (ممکن است غلط باشد).
3. **امتیاز** — درست / غلط / جاافتاده / پرشدهٔ اضافه.

خروجی سبز UI دقت نیست. دقت یعنی مقایسه با gold.
"""
)

tab_demo, tab_data, tab_score = st.tabs(["مثال ثابت", "نمونه‌های ذخیره‌شده", "امتیاز کل"])


def _label(key: str) -> str:
    return FIELD_LABELS_FA.get(key, key)


def _clean_pred(fields: dict) -> dict:
    return {k: v for k, v in fields.items() if k not in SKIP_KEYS and v is not None}


def _row_status(key: str, pred: dict, gold: dict) -> str:
    if key in gold and key not in pred:
        return "جاافتاده (گفتید، پر نشد)"
    if key in pred and key not in gold:
        return "اضافه (پر شد، در gold نیست)"
    if key in gold and key in pred:
        from backend.experiments.eval_voice_form import values_match

        return "درست" if values_match(key, pred[key], gold[key]) else "مقدار غلط"
    return ""


def render_compare(transcript: str, predicted: dict, gold: dict) -> None:
    st.text_area("متن Whisper / نمونه", transcript, height=80, disabled=True)
    pred = _clean_pred(predicted)
    keys = sorted(set(pred) | set(gold))
    rows = []
    for key in keys:
        rows.append(
            {
                "فیلد": _label(key),
                "کلید": key,
                "gold (باید باشد)": gold.get(key, "—"),
                "استخراج": pred.get(key, "—"),
                "وضعیت": _row_status(key, pred, gold),
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)
    score = score_sample(predicted, gold)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("درست", score["n_correct"])
    c2.metric("غلط", len(score["wrong"]))
    c3.metric("جاافتاده", len(score["miss"]))
    c4.metric("اضافه", len(score["extra"]))
    n = score["n_gold"] or 1
    st.progress(score["n_correct"] / n, text=f"دقت فیلد: {score['accuracy']:.0%}")


with tab_demo:
    st.subheader("یک کلیپ ساختگی — بدون نیاز به دیتاست")
    st.write("فرض: شما گفتید پتاسیم ۰٫۹، پروکلسیتونین ۰٫۸، سدیم ۱۴۰.")
    demo_pred = extract_patient_demographics(DEMO_TRANSCRIPT)
    render_compare(DEMO_TRANSCRIPT, demo_pred, DEMO_GOLD)
    st.info(
        "اگر استخراج با gold یکی نبود، یعنی پارسر از همین متن اشتباه درآورده. "
        "اگر متن Whisper «ممیز» را انداخته باشد، gold را از صدای خودتان می‌گذارید نه از متن."
    )


with tab_data:
    st.subheader(f"پوشه `{DATASET_DIR}`")
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("ساخت stub طلایی از نمونه‌ها"):
            n = init_gold_stubs(DATASET_DIR)
            st.success(f"{n} فایل *.gold.json ساخته شد (موجودها بازنویسی نشدند).")
    sidecars = []
    if DATASET_DIR.is_dir():
        sidecars = sorted(
            p for p in DATASET_DIR.glob("*.json") if not p.name.endswith(".gold.json")
        )
    st.write(f"تعداد sidecar: {len(sidecars)}")
    if not sidecars:
        st.warning(
            "هنوز نمونه‌ای ذخیره نشده. در http://localhost:8601 ضبط کنید "
            "(API روی ۸۱۰۰). بعد همین صفحه را Refresh کنید."
        )
    else:
        names = [p.name for p in sidecars]
        choice = st.selectbox("نمونه", names)
        sidecar = DATASET_DIR / choice
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        transcript = str(payload.get("transcript") or "")
        predicted = extract_patient_demographics(transcript)
        gold = load_gold(sidecar, payload) or {}
        audio = sidecar.with_suffix(".ogg")
        if not audio.exists():
            audio = sidecar.with_suffix(".webm")
        if audio.exists():
            st.audio(str(audio))
        st.caption("Gold را اصلاح کنید: فقط فیلدهای گفته‌شده. مقدار باید حقیقت باشد نه کپی استخراج.")
        gold_text = st.text_area(
            "gold JSON",
            json.dumps(gold or _clean_pred(payload.get("extracted") or {}), ensure_ascii=False, indent=2),
            height=220,
            key=f"gold_{choice}",
        )
        if st.button("ذخیره gold"):
            try:
                parsed = json.loads(gold_text)
                if not isinstance(parsed, dict):
                    raise ValueError("باید یک object باشد")
                if "gold" in parsed and isinstance(parsed["gold"], dict):
                    parsed = parsed["gold"]
                gold_path = sidecar.with_name(f"{sidecar.stem}.gold.json")
                gold_path.write_text(
                    json.dumps(
                        {"transcript": transcript, "gold": parsed},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                st.success(f"ذخیره شد: {gold_path.name}")
                gold = parsed
            except (json.JSONDecodeError, ValueError) as exc:
                st.error(str(exc))
        if gold:
            render_compare(transcript, predicted, gold)
        else:
            st.info("برای این فایل هنوز gold نیست. JSON بالا را ذخیره کنید.")


with tab_score:
    result = evaluate_dataset(DATASET_DIR)
    overall = result["overall"]
    st.metric("نمونه برچسب‌خورده", overall.get("n_labeled", 0))
    st.metric("بدون gold", result["skipped_no_gold"])
    if overall.get("n_labeled"):
        st.metric("دقت فیلد", f"{overall['field_accuracy']:.0%}")
        st.write(
            f"درست {overall['n_correct']} از {overall['n_gold']} — "
            f"غلط {overall['n_wrong']} — جاافتاده {overall['n_miss']} — اضافه {overall['n_extra']}"
        )
        by_field = overall.get("by_field") or {}
        if by_field:
            table = []
            for key, stats in sorted(by_field.items()):
                acc = (stats["correct"] / stats["n"]) if stats["n"] else 0.0
                table.append(
                    {
                        "فیلد": _label(key),
                        "درست": stats["correct"],
                        "غلط": stats["wrong"],
                        "جاافتاده": stats["miss"],
                        "دقت": f"{acc:.0%}",
                    }
                )
            st.dataframe(table, use_container_width=True, hide_index=True)
    else:
        st.warning("بعد از ذخیرهٔ حداقل یک gold، اینجا درصد کل می‌آید.")
