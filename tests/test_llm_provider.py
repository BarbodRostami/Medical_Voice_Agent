"""Unit tests for answer LLM provider (mocked HTTP; no live GapGPT)."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from backend.llm_provider import AnswerLLM, build_rag_messages, _openai_chat_complete


class LlmProviderTests(unittest.TestCase):
    def test_build_rag_messages(self) -> None:
        msgs = build_rag_messages("What is SpO2?", "SpO2 normal 94-98%.")
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["role"], "user")
        self.assertIn("SpO2", msgs[1]["content"])

    def test_openai_chat_complete(self) -> None:
        fake = MagicMock()
        fake.status_code = 200
        fake.json.return_value = {
            "choices": [{"message": {"content": "  Normal SpO2 is 94-98%.  "}}]
        }
        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "sk-test",
                "OPENAI_BASE_URL": "https://api.gapgpt.app/v1",
                "OPENAI_CHAT_MODEL": "gpt-4o-mini",
            },
            clear=False,
        ), patch("backend.llm_provider.requests.post", return_value=fake) as post:
            out = _openai_chat_complete(
                [{"role": "user", "content": "hi"}],
                temperature=0.1,
            )
        self.assertEqual(out, "Normal SpO2 is 94-98%.")
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertIn("/chat/completions", args[0])
        self.assertEqual(kwargs["json"]["model"], "gpt-4o-mini")

    def test_fallback_to_ollama_on_openai_error(self) -> None:
        ollama = MagicMock()
        ollama.invoke.return_value = "ollama-answer"
        client = AnswerLLM(
            provider="openai",
            ollama=ollama,
            ollama_host="http://localhost:11434",
            ollama_model="biomistral:latest",
        )
        with patch(
            "backend.llm_provider._openai_chat_complete",
            side_effect=RuntimeError("boom"),
        ):
            out = client.invoke_messages(
                [{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}]
            )
        self.assertEqual(out, "ollama-answer")
        ollama.invoke.assert_called_once()


if __name__ == "__main__":
    unittest.main()
