"""Unit tests for API key auth helpers (no RAG / model load)."""
from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, MagicMock

from api_auth import api_keys_match, configured_api_key, enforce_api_key, is_public_path


class ApiAuthTests(unittest.TestCase):
    def test_public_paths(self) -> None:
        self.assertTrue(is_public_path("/"))
        self.assertTrue(is_public_path("/docs"))
        self.assertTrue(is_public_path("/openapi.json"))
        self.assertTrue(is_public_path("/voice/audio/abc.mp3"))
        self.assertTrue(is_public_path("/voice/audio/audio/abc.mp3"))
        self.assertFalse(is_public_path("/jobs/chat"))
        self.assertFalse(is_public_path("/stt/ask"))

    def test_api_keys_match(self) -> None:
        self.assertTrue(api_keys_match("secret-key", "secret-key"))
        self.assertFalse(api_keys_match("wrong", "secret-key"))
        self.assertFalse(api_keys_match(None, "secret-key"))
        self.assertFalse(api_keys_match("", "secret-key"))

    def test_configured_api_key_reads_env(self) -> None:
        old = os.environ.get("API_KEY")
        try:
            os.environ["API_KEY"] = "  abc123  "
            self.assertEqual(configured_api_key(), "abc123")
            del os.environ["API_KEY"]
            self.assertEqual(configured_api_key(), "")
        finally:
            if old is None:
                os.environ.pop("API_KEY", None)
            else:
                os.environ["API_KEY"] = old


class ApiAuthMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_missing_key_when_configured(self) -> None:
        old = os.environ.get("API_KEY")
        os.environ["API_KEY"] = "test-secret"
        try:
            request = MagicMock()
            request.url.path = "/jobs/chat"
            request.headers.get.return_value = None
            call_next = AsyncMock()
            resp = await enforce_api_key(request, call_next)
            self.assertEqual(resp.status_code, 401)
            call_next.assert_not_awaited()
        finally:
            if old is None:
                os.environ.pop("API_KEY", None)
            else:
                os.environ["API_KEY"] = old

    async def test_allows_valid_key(self) -> None:
        old = os.environ.get("API_KEY")
        os.environ["API_KEY"] = "test-secret"
        try:
            request = MagicMock()
            request.url.path = "/jobs/chat"
            request.headers.get.return_value = "test-secret"
            expected = MagicMock(name="ok")
            call_next = AsyncMock(return_value=expected)
            resp = await enforce_api_key(request, call_next)
            self.assertIs(resp, expected)
            call_next.assert_awaited_once()
        finally:
            if old is None:
                os.environ.pop("API_KEY", None)
            else:
                os.environ["API_KEY"] = old

    async def test_public_path_skips_auth(self) -> None:
        old = os.environ.get("API_KEY")
        os.environ["API_KEY"] = "test-secret"
        try:
            request = MagicMock()
            request.url.path = "/"
            expected = MagicMock(name="health")
            call_next = AsyncMock(return_value=expected)
            resp = await enforce_api_key(request, call_next)
            self.assertIs(resp, expected)
        finally:
            if old is None:
                os.environ.pop("API_KEY", None)
            else:
                os.environ["API_KEY"] = old


if __name__ == "__main__":
    unittest.main()
