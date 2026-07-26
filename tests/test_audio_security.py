"""Unit tests for audio proxy allowlist + HMAC signing."""
from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

from backend.audio_security import (
    append_audio_signature,
    audio_signing_enabled,
    is_allowed_audio_proxy_key,
    sign_audio_key,
    verify_audio_signature,
)
from backend.storage_keys import build_audio_proxy_url, resolve_storage_key


class AudioAllowlistTests(unittest.TestCase):
    def test_allows_bare_audio_and_dated(self) -> None:
        self.assertTrue(is_allowed_audio_proxy_key("abc123.mp3"))
        self.assertTrue(is_allowed_audio_proxy_key("audio/abc123.mp3"))
        self.assertTrue(is_allowed_audio_proxy_key("2026-07-19/uuid.mp3"))

    def test_rejects_cases_and_traversal(self) -> None:
        self.assertFalse(is_allowed_audio_proxy_key("cases/u1/meta.json"))
        self.assertFalse(is_allowed_audio_proxy_key("../etc/passwd"))
        self.assertFalse(is_allowed_audio_proxy_key("audio/../secret.mp3"))
        self.assertFalse(is_allowed_audio_proxy_key("audio/x.wav"))

    def test_resolve_rejects_dotdot(self) -> None:
        with self.assertRaises(ValueError):
            resolve_storage_key("../secret")


class AudioSigningTests(unittest.TestCase):
    def test_signing_roundtrip(self) -> None:
        with patch.dict(
            os.environ,
            {"API_KEY": "test-secret", "AUDIO_PROXY_REQUIRE_SIGNATURE": "1"},
            clear=False,
        ):
            self.assertTrue(audio_signing_enabled())
            exp, sig = sign_audio_key("abc.mp3", ttl_sec=120)
            self.assertTrue(verify_audio_signature("abc.mp3", str(exp), sig))
            self.assertFalse(verify_audio_signature("abc.mp3", str(exp), "deadbeef"))
            self.assertFalse(
                verify_audio_signature("other.mp3", str(exp), sig),
            )

    def test_expired_signature_rejected(self) -> None:
        with patch.dict(os.environ, {"API_KEY": "test-secret"}, clear=False):
            past = int(time.time()) - 10
            from backend.audio_security import _sign_payload

            sig = _sign_payload("abc.mp3", past)
            self.assertFalse(verify_audio_signature("abc.mp3", str(past), sig))

    def test_proxy_url_unsigned_when_disabled(self) -> None:
        with patch.dict(
            os.environ,
            {
                "API_KEY": "",
                "AUDIO_SIGNING_SECRET": "",
                "AUDIO_PROXY_REQUIRE_SIGNATURE": "0",
            },
            clear=False,
        ):
            url = build_audio_proxy_url("http://192.168.1.15:8000", "abc123.mp3")
            self.assertEqual(url, "http://192.168.1.15:8000/voice/audio/abc123.mp3")
            self.assertNotIn("sig=", url)

    def test_proxy_url_signed_when_enabled(self) -> None:
        with patch.dict(
            os.environ,
            {"API_KEY": "test-secret", "AUDIO_PROXY_REQUIRE_SIGNATURE": "1"},
            clear=False,
        ):
            url = build_audio_proxy_url("http://192.168.1.15:8000", "abc123.mp3")
            self.assertTrue(url.startswith("http://192.168.1.15:8000/voice/audio/abc123.mp3?"))
            self.assertIn("exp=", url)
            self.assertIn("sig=", url)

    def test_append_noop_when_disabled(self) -> None:
        with patch.dict(
            os.environ,
            {"AUDIO_PROXY_REQUIRE_SIGNATURE": "0", "API_KEY": "x"},
            clear=False,
        ):
            self.assertEqual(
                append_audio_signature("http://h/voice/audio/a.mp3", "a.mp3"),
                "http://h/voice/audio/a.mp3",
            )


if __name__ == "__main__":
    unittest.main()
