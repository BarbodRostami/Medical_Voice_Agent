"""Light-weight LLM text cleanup (no heavy model imports)."""
from __future__ import annotations

import re


def clean_llm_output(raw: str, query: str) -> str:
    """Strip chat-role labels and prompt leakage without touching medical words."""
    text = raw.replace("<|im_start|>", "").replace("<|im_end|>", "")
    # Strip leading chat-role label only — do not remove "system" inside medical text
    text = re.sub(r"^\s*(assistant|user|system)\s*:?\s*", "", text, flags=re.IGNORECASE)
    for phrase in [
        "You are an expert medical assistant",
        "Answer the user's question",
        "Context:",
        query[:50],
    ]:
        if phrase in text:
            text = text.split(phrase)[-1]
    text = text.strip().lstrip(":").strip()
    if text.lower().startswith("answer:"):
        text = text[7:].strip()
    return text if len(text) >= 5 else raw.strip()
