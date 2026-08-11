"""Unit tests for collaborator cases helpers (no RAG / model load)."""
from __future__ import annotations

import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.case_store import (
    new_meta,
    output_audio_key,
    output_json_key,
    tehran_date_str,
    validate_case_id,
    find_input_audio_key,
    download_case_input_audio,
)
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

    def test_output_json_key_dated(self) -> None:
        key = output_json_key("case-1", day="2026-07-19")
        self.assertEqual(key, "2026-07-19/case-1.json")

    def test_tehran_date_format(self) -> None:
        self.assertRegex(tehran_date_str(), r"^\d{4}-\d{2}-\d{2}$")

    def test_new_meta_has_dated_output_key_no_public_s3_fields(self) -> None:
        with patch("backend.case_store.tehran_date_str", return_value="2026-07-19"):
            meta = new_meta("case-1", mode="text")
        self.assertEqual(meta["status"], "queued")
        self.assertEqual(meta["output_key"], "2026-07-19/case-1.mp3")
        self.assertEqual(meta["output_json_key"], "2026-07-19/case-1.json")
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
    """Collaborator audio path returns transcript + optional fields JSON (no LLM)."""

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
                "transcribe_form_demographics_audio",
                return_value="بیمار آقای ۴۵ ساله قد ۱۷۵ سانتی‌متر",
            ),
            patch.object(api, "save_output_text"),
            patch.object(
                api,
                "save_collaborator_stt_json",
                return_value="2026-07-19/stt-only-unit-1.json",
            ) as save_json,
            patch.object(api, "_safe_log"),
            patch.object(api, "_cases", {case_id: patches[case_id]}),
            patch.object(api, "_cases_lock", MagicMock()),
        ):
            # Make lock a real context manager
            from threading import Lock

            api._cases_lock = Lock()
            api._cases = {case_id: patches[case_id]}
            api._worker_case_audio(case_id, path, "http://127.0.0.1:8000")

        meta = patches[case_id]
        self.assertEqual(meta["status"], "ready")
        self.assertEqual(meta["text"], "بیمار آقای ۴۵ ساله قد ۱۷۵ سانتی‌متر")
        self.assertEqual(meta["transcript"], meta["text"])
        self.assertEqual(meta["answer"], meta["text"])
        self.assertIsNone(meta.get("error"))
        self.assertIsInstance(meta.get("fields"), dict)
        self.assertEqual(meta["fields"]["gender"], "male")
        self.assertEqual(meta["fields"]["age"], 45)
        self.assertEqual(meta["fields"]["height_cm"], 175)
        self.assertIn("gender", meta["fields"]["found"])
        self.assertTrue(meta.get("output_json_key", "").endswith(".json"))
        save_json.assert_called_once()
        s3_body = save_json.call_args.args[1]
        self.assertEqual(s3_body["text"], meta["text"])
        self.assertEqual(s3_body["fields"]["age"], 45)
        self.assertFalse(Path(path).exists())

        # Legacy Behin get-msg: text only, no fields
        legacy = api._case_public_view(meta)
        self.assertEqual(legacy["text"], meta["text"])
        self.assertNotIn("fields", legacy)

        # New get-text: text + fields
        view = api._case_get_text_view(meta)
        self.assertEqual(view["text"], meta["text"])
        self.assertIn("fields", view)
        self.assertEqual(view["fields"]["age"], 45)


class S3PreuploadInputTests(unittest.TestCase):
    """HakimAI uploads cases/{uuid}/input/audio.* then POSTs uuid only."""

    def test_find_input_audio_key_prefers_webm(self) -> None:
        with patch(
            "backend.case_store.storage_object_exists",
            side_effect=lambda k: k.endswith("audio.webm"),
        ):
            key = find_input_audio_key("case-pre")
        self.assertEqual(key, "cases/case-pre/input/audio.webm")

    def test_find_input_audio_key_falls_back_wav(self) -> None:
        with patch(
            "backend.case_store.storage_object_exists",
            side_effect=lambda k: k.endswith("audio.wav"),
        ):
            key = find_input_audio_key("case-pre")
        self.assertEqual(key, "cases/case-pre/input/audio.wav")

    def test_download_case_input_audio_missing(self) -> None:
        with patch("backend.case_store.storage_object_exists", return_value=False):
            with self.assertRaises(FileNotFoundError):
                download_case_input_audio("missing-case")

    def test_download_case_input_audio_ok(self) -> None:
        with (
            patch(
                "backend.case_store.storage_object_exists",
                side_effect=lambda k: k.endswith("audio.mp3"),
            ),
            patch(
                "backend.case_store.get_storage_object",
                return_value=b"fake-mp3",
            ),
        ):
            raw, key = download_case_input_audio("case-pre")
        self.assertEqual(raw, b"fake-mp3")
        self.assertEqual(key, "cases/case-pre/input/audio.mp3")

    def test_enqueue_from_s3_queues_worker(self) -> None:
        import backend.main_api as api

        case_id = "s3-pre-unit-1"
        submitted: list[tuple] = []

        class FakeExec:
            def submit(self, fn, *args, **kwargs):
                submitted.append((fn, args, kwargs))

        with (
            patch.object(
                api,
                "download_case_input_audio",
                return_value=(b"ID3fake", "cases/s3-pre-unit-1/input/audio.mp3"),
            ),
            patch.object(api, "_job_executor", FakeExec()),
            patch.object(api, "_set_case"),
            patch.object(api, "new_meta", wraps=new_meta),
        ):
            out = api._enqueue_case_audio_from_s3(case_id, "http://127.0.0.1:8000")

        self.assertEqual(out["status"], "queued")
        self.assertEqual(out["mode"], "audio")
        self.assertEqual(out["uuid"], case_id)
        self.assertEqual(len(submitted), 1)
        fn, args, _ = submitted[0]
        self.assertIs(fn, api._worker_case_audio)
        self.assertEqual(args[0], case_id)
        self.assertTrue(str(args[1]).endswith(".mp3"))
        Path(args[1]).unlink(missing_ok=True)

    def test_enqueue_from_s3_404_when_missing(self) -> None:
        import backend.main_api as api
        from fastapi import HTTPException

        with patch.object(
            api,
            "download_case_input_audio",
            side_effect=FileNotFoundError("missing"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                api._enqueue_case_audio_from_s3("nope", "http://127.0.0.1:8000")
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
