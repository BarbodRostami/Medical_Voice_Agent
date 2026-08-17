"""Benchmark: Regex-only vs Regex+Fuzzy extraction accuracy.

Run:
    python tests/benchmark_fuzzy.py

Compares extraction accuracy before and after fuzzy matching by temporarily
disabling the fuzzy fallback and re-running the same test cases.
"""
from __future__ import annotations
import sys
import re
from difflib import SequenceMatcher

sys.path.insert(0, ".")

# ── Test cases: (transcript_with_garbling, extractor_fn_name, expected_value) ─
# Garbling types:
#   [del]   = حذف یک یا چند حرف
#   [sub]   = جایگزینی حرف
#   [ins]   = اضافه شدن حرف
#   [swap]  = جابجایی حرف
CASES: list[tuple[str, str, float, str]] = [
    # ── Hb ──────────────────────────────────────────────────────────────────
    ("هموگلوبین یازده",          "_extract_hb", 11.0, "exact"),
    ("هموگلبین یازده",           "_extract_hb", 11.0, "[del] حذف 'و'"),
    ("هموگلوین یازده",           "_extract_hb", 11.0, "[del] حذف 'ب'"),
    ("هموگلوبیم یازده",          "_extract_hb", 11.0, "[sub] ن→م"),
    ("همو گلوبین یازده",         "_extract_hb", 11.0, "[ins] فاصله"),
    ("هموگلوبن یازده",           "_extract_hb", 11.0, "[del] حذف 'ی'"),
    # ── Hct ─────────────────────────────────────────────────────────────────
    ("هماتوکریت سی و پنج",       "_extract_hct", 35.0, "exact"),
    ("هموتوکریت سی و پنج",       "_extract_hct", 35.0, "[sub] ا→و"),
    ("هماتوکریط سی و پنج",       "_extract_hct", 35.0, "[sub] ت→ط"),
    ("هماتو کریت سی و پنج",      "_extract_hct", 35.0, "[ins] فاصله"),
    ("هماتوکریتت سی و پنج",      "_extract_hct", 35.0, "[ins] تکرار"),
    # ── Na ──────────────────────────────────────────────────────────────────
    ("سدیم صد و سی و هشت",       "_extract_na", 138.0, "exact"),
    ("سدیوم صد و سی و هشت",      "_extract_na", 138.0, "[ins] و"),
    ("سدیام صد و سی و هشت",      "_extract_na", 138.0, "[sub] ی→یا"),
    ("سدیمم صد و سی و هشت",      "_extract_na", 138.0, "[ins] تکرار م"),
    ("سدم صد و سی و هشت",        "_extract_na", 138.0, "[del] حذف 'ی'"),
    # ── K ───────────────────────────────────────────────────────────────────
    ("پتاسیم چهار ممیز دو",       "_extract_k", 4.2,  "exact"),
    ("پتاسیوم چهار ممیز دو",      "_extract_k", 4.2,  "[ins] و"),
    ("پتاسیمم چهار ممیز دو",      "_extract_k", 4.2,  "[ins] تکرار"),
    ("پطاسیم چهار ممیز دو",       "_extract_k", 4.2,  "[sub] ت→ط"),
    ("پتاسم چهار ممیز دو",        "_extract_k", 4.2,  "[del] حذف 'ی'"),
    # ── Phosphate ───────────────────────────────────────────────────────────
    ("فسفات سه ممیز پنج",         "_extract_phosphate", 3.5, "exact"),
    ("فسفاط سه ممیز پنج",         "_extract_phosphate", 3.5, "[sub] ت→ط"),
    ("فاسفات سه ممیز پنج",        "_extract_phosphate", 3.5, "[ins] ا"),
    ("فسفیت سه ممیز پنج",         "_extract_phosphate", 3.5, "[sub] ا→ی"),
    ("فسفت سه ممیز پنج",          "_extract_phosphate", 3.5, "[del] حذف 'ا'"),
    # ── BUN ─────────────────────────────────────────────────────────────────
    ("اوره چهل",                  "_extract_bun", 40.0, "exact"),
    ("اوره ی چهل",                "_extract_bun", 40.0, "[ins] ی"),
    ("اورهه چهل",                 "_extract_bun", 40.0, "[ins] تکرار"),
    ("اوری چهل",                  "_extract_bun", 40.0, "[sub] ه→ی"),
    # ── Creatinine ──────────────────────────────────────────────────────────
    ("کراتینین یک ممیز دو",       "_extract_creatinine", 1.2, "exact"),
    ("کراتنین یک ممیز دو",        "_extract_creatinine", 1.2, "[del] حذف 'ی'"),
    ("کراتینیین یک ممیز دو",      "_extract_creatinine", 1.2, "[ins] تکرار"),
    ("کراتنیین یک ممیز دو",       "_extract_creatinine", 1.2, "[del+ins]"),
    # ── ESR ─────────────────────────────────────────────────────────────────
    ("ای اس آر بیست",             "_extract_esr", 20.0, "exact"),
    ("ای اس ار بیست",             "_extract_esr", 20.0, "[sub] آ→ا"),
    ("ESRC بیست",                 "_extract_esr", 20.0, "[ins] C"),
    ("ESR بیست",                  "_extract_esr", 20.0, "latin exact"),
    # ── Lactate ─────────────────────────────────────────────────────────────
    ("لاکتات دو",                 "_extract_lactate", 2.0, "exact"),
    ("لاکتیت دو",                 "_extract_lactate", 2.0, "[sub] ا→ی"),
    ("لاکتاط دو",                 "_extract_lactate", 2.0, "[sub] ت→ط"),
    ("لاکتت دو",                  "_extract_lactate", 2.0, "[del] حذف 'ا'"),
    ("لاکتیک اسید دو",            "_extract_lactate", 2.0, "lactic acid"),
]


def _run_cases(use_fuzzy: bool) -> dict[str, list[bool]]:
    """Run all cases with fuzzy enabled or disabled, return per-field results."""
    import backend.experiments.form_extract as fe

    if not use_fuzzy:
        # Monkey-patch: disable fuzzy by replacing _fuzzy_label_search with always-None
        original = fe._fuzzy_label_search
        fe._fuzzy_label_search = lambda *a, **kw: None  # type: ignore[method-assign]

    results: dict[str, list[bool]] = {}
    for text, fn_name, expected, _ in CASES:
        fn = getattr(fe, fn_name)
        result = fn(text)
        ok = result is not None and abs(float(result) - expected) < 0.05
        results.setdefault(fn_name, []).append(ok)

    if not use_fuzzy:
        fe._fuzzy_label_search = original  # type: ignore[method-assign]

    return results


def _pct(hits: int, total: int) -> str:
    return f"{hits}/{total} ({100*hits//total}%)"


def main() -> None:
    print("\n" + "=" * 60)
    print("  FUZZY MATCHING BENCHMARK")
    print("=" * 60)

    regex_results  = _run_cases(use_fuzzy=False)
    fuzzy_results  = _run_cases(use_fuzzy=True)

    # Per-field report
    fn_labels = {
        "_extract_hb":          "Hb (هموگلوبین)",
        "_extract_hct":         "Hct (هماتوکریت)",
        "_extract_na":          "Na (سدیم)",
        "_extract_k":           "K (پتاسیم)",
        "_extract_phosphate":   "Phosphate (فسفات)",
        "_extract_bun":         "BUN (اوره)",
        "_extract_creatinine":  "Creatinine (کراتینین)",
        "_extract_esr":         "ESR (ای اس آر)",
        "_extract_lactate":     "Lactate (لاکتات)",
    }

    print(f"\n{'Field':<26} {'Regex only':>12} {'Regex+Fuzzy':>13} {'Improvement':>13}")
    print("-" * 68)

    total_regex = total_fuzzy = total_cases = 0
    for fn, label in fn_labels.items():
        r = regex_results.get(fn, [])
        f = fuzzy_results.get(fn, [])
        rh, fh, n = sum(r), sum(f), len(r)
        total_regex += rh
        total_fuzzy += fh
        total_cases += n
        diff = fh - rh
        diff_str = f"+{diff}" if diff > 0 else str(diff)
        diff_pct = f"({100*diff//n:+d}%)" if n else ""
        print(f"{label:<26} {_pct(rh,n):>12} {_pct(fh,n):>13} {diff_str:>5} {diff_pct:>7}")

    print("-" * 68)
    print(
        f"{'OVERALL':<26} {_pct(total_regex, total_cases):>12} "
        f"{_pct(total_fuzzy, total_cases):>13} "
        f"{'+' if total_fuzzy >= total_regex else ''}"
        f"{total_fuzzy - total_regex:>4}  "
        f"({100*(total_fuzzy-total_regex)//total_cases:+d}%)"
    )

    # Detail: which cases improved?
    print("\n── Cases where Fuzzy helped ──────────────────────────────────")
    improved = 0
    for i, (text, fn_name, expected, garble) in enumerate(CASES):
        fn_results_r = regex_results.get(fn_name, [])
        fn_results_f = fuzzy_results.get(fn_name, [])
        idx = [c[0] for c in CASES[:i+1] if c[1] == fn_name].index(i) if False else None
        # Re-derive per-case index
    # Simpler: re-run per case
    import backend.experiments.form_extract as fe
    for text, fn_name, expected, garble in CASES:
        fn = getattr(fe, fn_name)
        # without fuzzy
        orig = fe._fuzzy_label_search
        fe._fuzzy_label_search = lambda *a, **kw: None  # type: ignore[method-assign]
        r_val = fn(text)
        fe._fuzzy_label_search = orig
        # with fuzzy
        f_val = fn(text)
        r_ok = r_val is not None and abs(float(r_val) - expected) < 0.05
        f_ok = f_val is not None and abs(float(f_val) - expected) < 0.05
        if f_ok and not r_ok:
            improved += 1
            print(f"  ✓ {fn_name:<22} | {garble:<18} | '{text}' → {f_val}")

    if improved == 0:
        print("  (هیچ — regex همه را گرفت، fuzzy کمکی نکرد)")

    print(f"\n  Fuzzy rescued {improved} case(s) that regex missed.\n")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
