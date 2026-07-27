"""Unit tests for collaborator cases helpers (no RAG / model load)."""
from __future__ import annotations

import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.case_store import new_meta, output_audio_key, tehran_date_str, validate_case_id
from backend.storage_keys import build_audio_proxy_url, resolve_storage_key


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

    def test_output_key_uses_date_not_audio_prefix(self) -> None:
        key = output_audio_key("case-1", day="2026-07-19")
        self.assertEqual(key, "2026-07-19/case-1.mp3")
        self.assertFalse(key.startswith("audio/"))

    def test_tehran_date_format(self) -> None:
        self.assertRegex(tehran_date_str(), r"^\d{4}-\d{2}-\d{2}$")

    def test_new_meta_has_dated_output_key_no_public_s3_fields(self) -> None:
        with patch("backend.case_store.tehran_date_str", return_value="2026-07-19"):
            meta = new_meta("case-1", mode="text")
        self.assertEqual(meta["status"], "queued")
        self.assertEqual(meta["output_key"], "2026-07-19/case-1.mp3")
        self.assertEqual(meta["day"], "2026-07-19")
        self.assertNotIn("s3_bucket", meta)
        self.assertNotIn("s3_key", meta)

    def test_resolve_storage_key_dated_passthrough(self) -> None:
        key = "2026-07-19/uuid.mp3"
        self.assertEqual(resolve_storage_key(key), key)
        self.assertEqual(resolve_storage_key("audio/x.mp3"), "audio/x.mp3")
        self.assertEqual(resolve_storage_key("cases/a/meta.json"), "cases/a/meta.json")
        self.assertEqual(resolve_storage_key("x.mp3"), "audio/x.mp3")

    def test_dated_audio_proxy_url(self) -> None:
        with patch.dict(
            os.environ,
            {
                "API_KEY": "",
                "AUDIO_SIGNING_SECRET": "",
                "AUDIO_PROXY_REQUIRE_SIGNATURE": "0",
            },
            clear=False,
        ):
            url = build_audio_proxy_url(
                "http://192.168.1.235:8000",
                "2026-07-19/case-1.mp3",
            )
            self.assertEqual(
                url,
                "http://192.168.1.235:8000/voice/audio/2026-07-19/case-1.mp3",
            )


class SttOnlyCaseWorkerTests(unittest.TestCase):
    """Collaborator audio path must return transcript as text without calling LLM."""

    def test_worker_sets_ready_with_transcript_as_text(self) -> None:
        import backend.main_api as api

        case_id = "stt-only-unit-1"
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(b"RIFF....WAVEfmt ")
            path = tmp.name

        patches: dict[str, dict] = {
            case_id: new_meta(case_id, mode="audio"),
        }

        def fake_patch(cid: str, **kwargs: object) -> None:
            patches[cid].update(kwargs)

        with (
            patch.object(api, "_patch_case", side_effect=fake_patch),
            patch.object(api, "_get_whisper", return_value=MagicMock()),
            patch.object(
                api,
                "transcribe_medical_speech",
                return_value="سلام یک دو سه",
            ),
            patch.object(api, "save_output_text"),
            patch.object(api, "_safe_log"),
        ):
            api._worker_case_audio(case_id, path, "http://127.0.0.1:8000")

        meta = patches[case_id]
        self.assertEqual(meta["status"], "ready")
        self.assertEqual(meta["text"], "سلام یک دو سه")
        self.assertEqual(meta["transcript"], "سلام یک دو سه")
        self.assertEqual(meta["answer"], "سلام یک دو سه")
        self.assertIsNone(meta.get("error"))
        self.assertFalse(Path(path).exists())


if __name__ == "__main__":
    unittest.main()
