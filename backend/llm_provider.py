"""Answer LLM providers: local Ollama (default) or OpenAI-compatible (GapGPT).

Used by the main RAG path in ``main_api``. TTS/STT stay on their own flags.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import requests
from langchain_community.llms import Ollama as OllamaLLM

from backend.provider_config import (
    llm_provider,
    openai_chat_model,
    openai_compatible_config,
)


def ollama_model_name() -> str:
    return (os.getenv("OLLAMA_LLM_MODEL") or os.getenv("LLM_MODEL") or "biomistral:latest").strip()


RAG_SYSTEM_PROMPT = (
    "You are an expert medical assistant specialized in critical care and clinical medicine.\n"
    "Answer the user's question using ONLY the provided context.\n\n"
    "Answer format rules:\n"
    "1. Always state exact normal ranges or values when relevant (include units).\n"
    "2. If the question asks about pediatric vs adult differences, mention both.\n"
    "3. Write in clear, concise prose. No markdown headers or bullet dashes.\n"
    "4. Use numbered lists only when listing 3+ distinct items.\n"
    "5. If the context does not contain enough information, say exactly: "
    "'The provided documents do not contain enough information to answer this question.'"
)


def build_rag_messages(query: str, context: str) -> list[dict[str, str]]:
    """Chat-style messages for OpenAI-compatible APIs."""
    return [
        {"role": "system", "content": RAG_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Context:\n{context}\n\nQuestion:\n{query}",
        },
    ]


def format_chatml(system: str, user: str) -> str:
    """BioMistral / Ollama ChatML completion prompt."""
    return (
        f"<|im_start|>system\n{system}<|im_end|>\n"
        f"<|im_start|>user\n{user}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )


def build_rag_chatml_prompt(query: str, context: str) -> str:
    user = f"Context:\n{context}\n\nQuestion:\n{query}"
    return format_chatml(RAG_SYSTEM_PROMPT, user)


class AnswerLLM:
    """Thin facade: chat messages for OpenAI, ChatML via Ollama as fallback."""

    def __init__(
        self,
        *,
        provider: str,
        ollama: OllamaLLM | None = None,
        ollama_host: str = "http://localhost:11434",
        ollama_model: str = "biomistral:latest",
    ) -> None:
        self.provider = provider
        self.ollama = ollama
        self.ollama_host = ollama_host.rstrip("/")
        self.ollama_model = ollama_model
        self.active_model = (
            openai_chat_model() if provider == "openai" else ollama_model
        )

    @property
    def ready(self) -> bool:
        if self.provider == "openai":
            return openai_compatible_config().configured
        return self.ollama is not None

    def invoke_messages(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        timeout: int = 180,
    ) -> str:
        if self.provider == "openai":
            try:
                return _openai_chat_complete(
                    messages, temperature=temperature, timeout=timeout
                )
            except Exception as exc:
                print(f"LLM_PROVIDER=openai failed ({exc}); falling back to Ollama")
                if self.ollama is None:
                    raise
                return self._ollama_from_messages(messages)

        return self._ollama_from_messages(messages)

    def invoke(self, prompt: str) -> str:
        """Legacy single-string invoke (ChatML or raw user text)."""
        if self.provider == "openai":
            messages = [{"role": "user", "content": prompt}]
            return self.invoke_messages(messages)
        if self.ollama is None:
            raise RuntimeError("Ollama LLM is not initialized")
        return str(self.ollama.invoke(prompt))

    def stream_messages(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        timeout: int = 180,
    ) -> Iterator[str]:
        if self.provider == "openai":
            try:
                yield from _openai_chat_stream(
                    messages, temperature=temperature, timeout=timeout
                )
                return
            except Exception as exc:
                print(f"LLM stream openai failed ({exc}); falling back to Ollama")
                if self.ollama is None:
                    yield f"\n[Error: {exc}]"
                    return
        yield from self._ollama_stream_from_messages(messages, temperature=temperature)

    def _ollama_from_messages(self, messages: list[dict[str, str]]) -> str:
        if self.ollama is None:
            raise RuntimeError("Ollama LLM is not initialized")
        system = ""
        user_parts: list[str] = []
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if role == "system":
                system = content
            else:
                user_parts.append(content)
        prompt = format_chatml(system, "\n\n".join(user_parts))
        return str(self.ollama.invoke(prompt))

    def _ollama_stream_from_messages(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
    ) -> Iterator[str]:
        system = ""
        user_parts: list[str] = []
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content", "")
            else:
                user_parts.append(m.get("content", ""))
        prompt = format_chatml(system, "\n\n".join(user_parts))
        try:
            resp = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": True,
                    "options": {
                        "temperature": temperature,
                        "stop": ["<|im_start|>", "<|im_end|>", "user:", "assistant:"],
                    },
                },
                stream=True,
                timeout=180,
            )
            for line in resp.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                token = data.get("response", "")
                if token:
                    yield token
                if data.get("done"):
                    break
        except Exception as e:
            yield f"\n[Error: {e}]"


def _openai_chat_complete(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
    timeout: int = 180,
) -> str:
    cfg = openai_compatible_config()
    if not cfg.configured:
        raise RuntimeError("OPENAI_API_KEY (or GAPGPT_API_KEY) is not set")
    model = openai_chat_model()
    response = requests.post(
        f"{cfg.base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": temperature,
            "messages": messages,
        },
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Chat LLM HTTP {response.status_code}: {response.text[:300]}"
        )
    data = response.json()
    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    out = (content or "").strip()
    if not out:
        raise RuntimeError("Chat LLM returned empty content")
    return out


def _openai_chat_stream(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
    timeout: int = 180,
) -> Iterator[str]:
    cfg = openai_compatible_config()
    if not cfg.configured:
        raise RuntimeError("OPENAI_API_KEY (or GAPGPT_API_KEY) is not set")
    model = openai_chat_model()
    response = requests.post(
        f"{cfg.base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": temperature,
            "messages": messages,
            "stream": True,
        },
        stream=True,
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Chat LLM stream HTTP {response.status_code}: {response.text[:300]}"
        )
    for line in response.iter_lines(decode_unicode=True):
        if not line:
            continue
        if line.startswith("data: "):
            payload = line[6:].strip()
        else:
            payload = line.strip()
        if payload == "[DONE]":
            break
        try:
            data: dict[str, Any] = json.loads(payload)
        except json.JSONDecodeError:
            continue
        delta = data.get("choices", [{}])[0].get("delta", {})
        token = delta.get("content") or ""
        if token:
            yield token


def create_answer_llm(*, ollama_host: str) -> AnswerLLM:
    """Build the process-wide answer LLM from env (keeps Ollama warm for fallback)."""
    provider = llm_provider()
    model = ollama_model_name()
    ollama = OllamaLLM(
        model=model,
        base_url=ollama_host,
        temperature=0.1,
        stop=["<|im_start|>", "<|im_end|>", "user:", "assistant:"],
    )
    if provider == "openai":
        cfg = openai_compatible_config()
        if not cfg.configured:
            print("LLM_PROVIDER=openai but no API key; using Ollama")
            provider = "ollama"
        else:
            print(
                f"Answer LLM: OpenAI-compatible ({cfg.base_url}) "
                f"model={openai_chat_model()} (Ollama kept as fallback)"
            )
    else:
        print(f"Answer LLM: Ollama model={model} host={ollama_host}")
    return AnswerLLM(
        provider=provider,
        ollama=ollama,
        ollama_host=ollama_host,
        ollama_model=model,
    )
