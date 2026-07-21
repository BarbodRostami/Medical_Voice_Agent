"""Unit tests for PR review fixes — no RAG / model load at import time."""
from __future__ import annotations

import unittest

from backend.llm_output import clean_llm_output
from backend.medical_voice_utils import build_audio_proxy_url, resolve_storage_key


class ReviewFixTests(unittest.TestCase):
    def test_clean_llm_output_preserves_system_in_medical_text(self) -> None:
        raw = "The systemic inflammatory response requires monitoring."
        cleaned = clean_llm_output(raw, "test query")
        self.assertIn("systemic", cleaned.lower())

    def test_clean_llm_output_strips_leading_role_label(self) -> None:
        raw = "assistant: Normal range is 95-100%."
        cleaned = clean_llm_output(raw, "heart rate")
        self.assertFalse(cleaned.lower().startswith("assistant"))
        self.assertIn("95-100", cleaned)

    def test_audio_proxy_url_single_audio_segment(self) -> None:
        url = build_audio_proxy_url("http://192.168.1.15:8000", "abc123.mp3")
        self.assertEqual(url, "http://192.168.1.15:8000/voice/audio/abc123.mp3")
        self.assertNotIn("/audio/audio/", url)

    def test_resolve_storage_key_from_public_name(self) -> None:
        self.assertEqual(resolve_storage_key("abc.mp3"), "audio/abc.mp3")
        self.assertEqual(resolve_storage_key("audio/abc.mp3"), "audio/abc.mp3")
        self.assertEqual(
            resolve_storage_key("cases/u1/output/reply.mp3"),
            "cases/u1/output/reply.mp3",
        )
        self.assertEqual(
            resolve_storage_key("2026-07-19/u1.mp3"),
            "2026-07-19/u1.mp3",
        )


if __name__ == "__main__":
    unittest.main()
