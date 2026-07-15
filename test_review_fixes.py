"""Unit tests for PR review fixes (#6, #9, #10)."""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from main_api import _clean_llm_output, app
from medical_voice_utils import build_audio_proxy_url, resolve_storage_key


class ReviewFixTests(unittest.TestCase):
    def test_clean_llm_output_preserves_system_in_medical_text(self) -> None:
        raw = "The systemic inflammatory response requires monitoring."
        cleaned = _clean_llm_output(raw, "test query")
        self.assertIn("systemic", cleaned.lower())

    def test_clean_llm_output_strips_leading_role_label(self) -> None:
        raw = "assistant: Normal range is 95-100%."
        cleaned = _clean_llm_output(raw, "heart rate")
        self.assertFalse(cleaned.lower().startswith("assistant"))
        self.assertIn("95-100", cleaned)

    def test_audio_proxy_url_single_audio_segment(self) -> None:
        url = build_audio_proxy_url("http://192.168.1.15:8000", "abc123.mp3")
        self.assertEqual(url, "http://192.168.1.15:8000/voice/audio/abc123.mp3")
        self.assertNotIn("/audio/audio/", url)

    def test_resolve_storage_key_from_public_name(self) -> None:
        self.assertEqual(resolve_storage_key("abc.mp3"), "audio/abc.mp3")
        self.assertEqual(resolve_storage_key("audio/abc.mp3"), "audio/abc.mp3")

    def test_voice_report_empty_body_returns_400(self) -> None:
        client = TestClient(app)
        resp = client.post("/jobs/voice-report", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Empty", resp.json()["detail"])


if __name__ == "__main__":
    unittest.main()
