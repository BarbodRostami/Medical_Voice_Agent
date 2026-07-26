"""Regression tests for GitHub issues #4–#12 (no model load)."""
from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.llm_output import clean_llm_output
from backend.storage_keys import build_audio_proxy_url

ROOT = Path(__file__).resolve().parents[1]
MAIN_API = ROOT / "backend" / "main_api.py"


class AlreadyFixedBugsTests(unittest.TestCase):
    """Issues that were fixed earlier — keep as regression guards."""

    def test_issue6_preserves_systemic(self) -> None:
        raw = "The systemic inflammatory response requires monitoring."
        self.assertIn("systemic", clean_llm_output(raw, "q").lower())
        self.assertIn("systemic", clean_llm_output(raw, "BP").lower())

    def test_issue10_no_double_audio_path(self) -> None:
        with patch.dict(
            os.environ,
            {
                "API_KEY": "",
                "AUDIO_SIGNING_SECRET": "",
                "AUDIO_PROXY_REQUIRE_SIGNATURE": "0",
            },
            clear=False,
        ):
            url = build_audio_proxy_url("http://192.168.1.15:8000", "x.mp3")
            self.assertEqual(url, "http://192.168.1.15:8000/voice/audio/x.mp3")
            self.assertNotIn("/audio/audio/", url)

    def test_issue4_boto3_in_requirements_ui(self) -> None:
        text = (ROOT / "requirements-ui.txt").read_text(encoding="utf-8")
        self.assertIn("boto3", text)

    def test_issue5_stream_env_in_compose(self) -> None:
        text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("BACKEND_STREAM_URL=http://backend:8000/chat/stream", text)

    def test_issue8_whisper_lock_present(self) -> None:
        text = MAIN_API.read_text(encoding="utf-8")
        self.assertIn("_whisper_lock", text)
        self.assertIn("with _whisper_lock:", text)

    def test_issue9_empty_body_returns_400(self) -> None:
        text = MAIN_API.read_text(encoding="utf-8")
        self.assertIn('detail="Empty request body."', text)
        self.assertIn("status_code=400", text)

    def test_issue11_no_builtins_nn_workaround(self) -> None:
        text = MAIN_API.read_text(encoding="utf-8")
        self.assertNotIn("builtins.nn", text)


class Issue7StreamQueryTests(unittest.TestCase):
    def test_chat_stream_assigns_query_at_function_body_level(self) -> None:
        """#7/#5: ``query = request.query`` must not sit under the init guard ``if``."""
        tree = ast.parse(MAIN_API.read_text(encoding="utf-8"))
        fn = next(
            n
            for n in tree.body
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "chat_stream"
        )
        # Top-level assigns in function body (not nested inside If)
        top_assigns = [
            stmt
            for stmt in fn.body
            if isinstance(stmt, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "query" for t in stmt.targets
            )
        ]
        self.assertTrue(
            top_assigns,
            "chat_stream must assign query = request.query at function body level",
        )
        # Ensure the dead-indent bug is gone: query assign must not be the only
        # child after raise inside the first If
        first_if = next((s for s in fn.body if isinstance(s, ast.If)), None)
        self.assertIsNotNone(first_if)
        nested_query = [
            n
            for n in first_if.body  # type: ignore[union-attr]
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "query" for t in n.targets)
        ]
        self.assertEqual(
            nested_query,
            [],
            "query assignment must not be nested under the uninitialized-system If",
        )


class Issue12DedupeTests(unittest.TestCase):
    def test_shared_rag_and_upload_helpers_exist(self) -> None:
        text = MAIN_API.read_text(encoding="utf-8")
        self.assertIn("def _rag_answer(", text)
        self.assertIn("def _upload_audio_url(", text)
        self.assertIn("_rag_answer(query)", text)
        self.assertIn("_upload_audio_url(", text)


if __name__ == "__main__":
    unittest.main()
