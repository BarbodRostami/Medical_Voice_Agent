"""Score voice-form extraction against gold labels.

Does not change production HakimAI routes. Reads sidecars under
``assets/audio/dataset/*.json`` and optional ``*.gold.json``.

Usage:
    python -m backend.experiments.eval_voice_form
    python -m backend.experiments.eval_voice_form --init-gold
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from backend.experiments.form_extract import extract_patient_demographics
from backend.experiments.voice_dataset import DATASET_DIR

SKIP_KEYS = {
    "raw_text",
    "found",
    "missing",
    "extract_version",
    "map",
    "pf_ratio",
    "driving_pressure",
    "vt_ibw",
}

ABS_TOL = {
    "ph": 0.02,
    "temp": 0.2,
    "fio2": 0.02,
    "k": 0.05,
    "ca": 0.1,
    "mg": 0.1,
    "phosphate": 0.1,
    "albumin": 0.1,
    "creatinine": 0.1,
    "bilirubin": 0.1,
    "procalcitonin": 0.05,
    "lactate": 0.1,
    "rise_time": 0.05,
    "ti_max": 0.1,
    "auto_peep": 0.2,
    "ie_ratio": 0.05,
    "mv": 0.2,
    "wob": 0.2,
    "rc_exp": 0.1,
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_gold(sidecar: Path, payload: dict[str, Any]) -> dict[str, Any] | None:
    gold = payload.get("gold")
    if isinstance(gold, dict) and gold:
        return {k: v for k, v in gold.items() if v is not None}
    gold_path = sidecar.with_name(f"{sidecar.stem}.gold.json")
    if gold_path.is_file():
        data = _load_json(gold_path)
        fields = data.get("gold", data)
        if isinstance(fields, dict):
            return {k: v for k, v in fields.items() if v is not None}
    return None


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return None
    return None


def values_match(key: str, predicted: Any, gold: Any) -> bool:
    if predicted is None or gold is None:
        return False
    p_num = _as_number(predicted)
    g_num = _as_number(gold)
    if p_num is not None and g_num is not None:
        tol = ABS_TOL.get(key, 0.51 if abs(g_num) >= 1 else 0.051)
        return abs(p_num - g_num) <= tol
    return str(predicted).strip().casefold() == str(gold).strip().casefold()


def score_sample(
    predicted: dict[str, Any],
    gold: dict[str, Any],
) -> dict[str, Any]:
    gold_keys = {k for k in gold if k not in SKIP_KEYS}
    pred_keys = {k for k, v in predicted.items() if k not in SKIP_KEYS and v is not None}

    correct: list[str] = []
    wrong: list[str] = []
    miss: list[str] = []
    extra: list[str] = []

    for key in sorted(gold_keys):
        gold_val = gold[key]
        pred_val = predicted.get(key)
        if pred_val is None:
            miss.append(key)
        elif values_match(key, pred_val, gold_val):
            correct.append(key)
        else:
            wrong.append(key)

    for key in sorted(pred_keys - gold_keys):
        extra.append(key)

    n_gold = len(gold_keys)
    accuracy = (len(correct) / n_gold) if n_gold else 0.0
    return {
        "correct": correct,
        "wrong": wrong,
        "miss": miss,
        "extra": extra,
        "n_gold": n_gold,
        "n_correct": len(correct),
        "accuracy": accuracy,
    }


def evaluate_dataset(dataset_dir: Path | None = None) -> dict[str, Any]:
    directory = dataset_dir or DATASET_DIR
    samples: list[dict[str, Any]] = []
    skipped_no_gold = 0

    if not directory.is_dir():
        return {"samples": [], "skipped_no_gold": 0, "overall": _empty_overall()}

    sidecars = sorted(
        p for p in directory.glob("*.json") if not p.name.endswith(".gold.json")
    )
    for sidecar in sidecars:
        payload = _load_json(sidecar)
        gold = load_gold(sidecar, payload)
        if not gold:
            skipped_no_gold += 1
            continue
        transcript = str(payload.get("transcript") or "")
        predicted = extract_patient_demographics(transcript)
        score = score_sample(predicted, gold)
        samples.append(
            {
                "file": sidecar.name,
                "transcript": transcript,
                "score": score,
                "predicted": {
                    k: v
                    for k, v in predicted.items()
                    if k not in SKIP_KEYS and v is not None
                },
                "gold": gold,
            }
        )

    overall = _aggregate(samples)
    overall["skipped_no_gold"] = skipped_no_gold
    overall["n_labeled"] = len(samples)
    return {"samples": samples, "skipped_no_gold": skipped_no_gold, "overall": overall}


def _empty_overall() -> dict[str, Any]:
    return {
        "n_labeled": 0,
        "skipped_no_gold": 0,
        "field_accuracy": 0.0,
        "n_correct": 0,
        "n_gold": 0,
        "n_wrong": 0,
        "n_miss": 0,
        "n_extra": 0,
        "by_field": {},
    }


def _aggregate(samples: list[dict[str, Any]]) -> dict[str, Any]:
    n_correct = n_gold = n_wrong = n_miss = n_extra = 0
    by_field: dict[str, dict[str, int]] = {}
    for sample in samples:
        score = sample["score"]
        n_correct += score["n_correct"]
        n_gold += score["n_gold"]
        n_wrong += len(score["wrong"])
        n_miss += len(score["miss"])
        n_extra += len(score["extra"])
        gold = sample["gold"]
        predicted = sample["predicted"]
        for key in gold:
            if key in SKIP_KEYS:
                continue
            stats = by_field.setdefault(key, {"correct": 0, "wrong": 0, "miss": 0, "n": 0})
            stats["n"] += 1
            if key not in predicted:
                stats["miss"] += 1
            elif values_match(key, predicted[key], gold[key]):
                stats["correct"] += 1
            else:
                stats["wrong"] += 1
    return {
        "n_labeled": len(samples),
        "field_accuracy": (n_correct / n_gold) if n_gold else 0.0,
        "n_correct": n_correct,
        "n_gold": n_gold,
        "n_wrong": n_wrong,
        "n_miss": n_miss,
        "n_extra": n_extra,
        "by_field": by_field,
    }


def init_gold_stubs(dataset_dir: Path | None = None) -> int:
    """Create empty gold files next to unlabeled sidecars. Does not overwrite."""
    directory = dataset_dir or DATASET_DIR
    if not directory.is_dir():
        return 0
    created = 0
    for sidecar in directory.glob("*.json"):
        if sidecar.name.endswith(".gold.json"):
            continue
        payload = _load_json(sidecar)
        if payload.get("gold"):
            continue
        gold_path = sidecar.with_name(f"{sidecar.stem}.gold.json")
        if gold_path.exists():
            continue
        extracted = payload.get("extracted") or {}
        stub = {
            "transcript": payload.get("transcript", ""),
            "note": "Fill gold with values that were actually spoken. Delete keys that were not said.",
            "gold": {
                k: v
                for k, v in extracted.items()
                if k not in SKIP_KEYS and v is not None
            },
        }
        gold_path.write_text(json.dumps(stub, ensure_ascii=False, indent=2), encoding="utf-8")
        created += 1
    return created


def _print_report(result: dict[str, Any]) -> None:
    overall = result["overall"]
    print(f"labeled samples: {overall.get('n_labeled', 0)}")
    print(f"skipped (no gold): {result['skipped_no_gold']}")
    print(
        "field accuracy: "
        f"{overall['field_accuracy']:.1%} "
        f"({overall['n_correct']}/{overall['n_gold']})"
    )
    print(
        f"wrong={overall['n_wrong']}  miss={overall['n_miss']}  extra={overall['n_extra']}"
    )
    by_field = overall.get("by_field") or {}
    if by_field:
        print("\nper-field:")
        for key in sorted(by_field):
            stats = by_field[key]
            acc = (stats["correct"] / stats["n"]) if stats["n"] else 0.0
            print(
                f"  {key:20} {acc:6.1%}  "
                f"ok={stats['correct']} wrong={stats['wrong']} miss={stats['miss']}"
            )
    for sample in result["samples"]:
        score = sample["score"]
        print(f"\n{sample['file']}: {score['accuracy']:.0%} ({score['n_correct']}/{score['n_gold']})")
        if score["wrong"]:
            print(f"  wrong: {', '.join(score['wrong'])}")
        if score["miss"]:
            print(f"  miss:  {', '.join(score['miss'])}")
        if score["extra"]:
            print(f"  extra: {', '.join(score['extra'])}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate voice-form extraction vs gold labels")
    parser.add_argument("--init-gold", action="store_true", help="Create gold stubs from extracted fields")
    parser.add_argument("--dataset-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    directory = args.dataset_dir or DATASET_DIR
    if args.init_gold:
        n = init_gold_stubs(directory)
        print(f"created {n} gold stub(s) in {directory}")
        print("Edit each *.gold.json: keep only fields that were actually spoken.")
        return 0

    result = evaluate_dataset(directory)
    _print_report(result)
    if result["overall"].get("n_labeled", 0) == 0:
        print(
            "\nNo gold labels yet. Record samples in the UI, then run:\n"
            "  python -m backend.experiments.eval_voice_form --init-gold",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
