"""Shared cloud/local provider settings for TTS, STT, and optional speech LLM.

Defaults always prefer local free paths. Paid OpenAI-compatible APIs (OpenAI,
GapGPT, …) are opt-in via env; callers must fall back to local on failure.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    """Credentials + base URL for OpenAI-compatible HTTP APIs."""

    api_key: str
    base_url: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


def openai_compatible_config() -> OpenAICompatibleConfig:
    """Resolve API key + base URL (GapGPT, OpenAI, or any compatible proxy)."""
    api_key = (
        os.getenv("OPENAI_API_KEY")
        or os.getenv("OPENAI_TTS_API_KEY")
        or os.getenv("GAPGPT_API_KEY")
        or ""
    ).strip().strip('"').strip("'")
    base = (
        os.getenv("OPENAI_BASE_URL")
        or os.getenv("GAPGPT_BASE_URL")
        or "https://api.openai.com/v1"
    ).strip().rstrip("/")
    return OpenAICompatibleConfig(api_key=api_key, base_url=base)


def tts_provider() -> str:
    """``edge`` (default) | ``openai``."""
    return (os.getenv("TTS_PROVIDER") or "edge").strip().lower()


def stt_provider() -> str:
    """``local`` (default Whisper) | ``openai`` (cloud transcriptions API)."""
    return (os.getenv("STT_PROVIDER") or "local").strip().lower()


def speech_normalize_llm_enabled() -> bool:
    """Optional chat rewrite after dictionary speech-prep. Default off."""
    raw = (os.getenv("SPEECH_NORMALIZE_LLM") or "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def tts_digit_mode() -> str:
    mode = (os.getenv("TTS_DIGIT_MODE") or "ascii").strip().lower()
    if mode not in ("ascii", "words", "persian"):
        return "ascii"
    return mode


def openai_tts_model() -> str:
    return (os.getenv("OPENAI_TTS_MODEL") or "tts-1-hd").strip()


def openai_tts_voice() -> str:
    return (os.getenv("OPENAI_TTS_VOICE") or "nova").strip()


def openai_stt_model() -> str:
    return (os.getenv("OPENAI_STT_MODEL") or "whisper-1").strip()


def openai_speech_llm_model() -> str:
    return (os.getenv("OPENAI_SPEECH_LLM_MODEL") or os.getenv("OPENAI_CHAT_MODEL") or "gpt-4o-mini").strip()


def llm_provider() -> str:
    """Answer LLM for RAG: ``ollama`` (default) | ``openai`` (GapGPT / OpenAI-compatible)."""
    return (os.getenv("LLM_PROVIDER") or "ollama").strip().lower()


def openai_chat_model() -> str:
    return (
        os.getenv("OPENAI_CHAT_MODEL")
        or os.getenv("LLM_CHAT_MODEL")
        or "gpt-4o-mini"
    ).strip()


def provider_status_summary() -> dict[str, object]:
    """Safe status dict for smoke scripts / debugging (no secrets)."""
    cfg = openai_compatible_config()
    return {
        "llm_provider": llm_provider(),
        "openai_chat_model": openai_chat_model(),
        "tts_provider": tts_provider(),
        "stt_provider": stt_provider(),
        "tts_digit_mode": tts_digit_mode(),
        "speech_normalize_llm": speech_normalize_llm_enabled(),
        "openai_base_url": cfg.base_url,
        "openai_api_key_set": cfg.configured,
        "openai_tts_model": openai_tts_model(),
        "openai_tts_voice": openai_tts_voice(),
        "openai_stt_model": openai_stt_model(),
        "openai_speech_llm_model": openai_speech_llm_model(),
        "fallback": {
            "llm": "ollama biomistral",
            "tts": "edge-tts",
            "stt": "local faster-whisper",
            "speech_normalize": "dictionary prepare_text_for_tts",
        },
    }
