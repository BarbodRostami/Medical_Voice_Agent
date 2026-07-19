"""Unit tests for collaborator cases helpers (no RAG / model load)."""
from __future__ import annotations

import unittest

from case_store import new_meta, output_audio_key, validate_case_id
from medical_voice_utils import build_audio_proxy_url, resolve_storage_key


class CaseStoreTests(unittest.TestCase):
    def test_validate_case_id_ok(self) -> None:
        self.assertEqual(validate_case_id("patient-42"), "patient-42")
        self.assertEqual(validate_case_id("  abc.123_x  "), "abc.123_x")

    def test_validate_case_id_rejects_path(self) -> None:
        with self.assertRaises(ValueError):
            validate_case_id("../secret")
        with self.assertRaises(ValueError):
            validate_case_id("a/b")
        with self.assertRaises(ValueError):
            validate_case_id("")

    def test_output_key_layout(self) -> None:
        self.assertEqual(
            output_audio_key("case-1"),
            "cases/case-1/output/reply.mp3",
        )

    def test_new_meta_defaults(self) -> None:
        meta = new_meta("case-1", mode="text")
        self.assertEqual(meta["uuid"], "case-1")
        self.assertEqual(meta["status"], "queued")
        self.assertEqual(meta["mode"], "text")
        self.assertEqual(meta["output_key"], "cases/case-1/output/reply.mp3")

    def test_resolve_storage_key_cases_passthrough(self) -> None:
        key = "cases/case-1/output/reply.mp3"
        self.assertEqual(resolve_storage_key(key), key)
        self.assertEqual(resolve_storage_key("audio/x.mp3"), "audio/x.mp3")
        self.assertEqual(resolve_storage_key("x.mp3"), "audio/x.mp3")

    def test_case_audio_proxy_url(self) -> None:
        url = build_audio_proxy_url(
            "http://192.168.1.15:8000",
            "cases/case-1/output/reply.mp3",
        )
        self.assertEqual(
            url,
            "http://192.168.1.15:8000/voice/audio/cases/case-1/output/reply.mp3",
        )


if __name__ == "__main__":
    unittest.main()
