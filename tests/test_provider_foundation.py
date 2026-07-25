"""Unit tests for cloud/local provider foundation (no network)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.provider_config import (
    openai_compatible_config,
    provider_status_summary,
    speech_normalize_llm_enabled,
    stt_provider,
    tts_provider,
)
from backend.stt_utils import transcribe_medical_audio


class ProviderConfigTests(unittest.TestCase):
    def test_defaults_are_local(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "TTS_PROVIDER": "",
                "STT_PROVIDER": "",
                "SPEECH_NORMALIZE_LLM": "",
                "OPENAI_API_KEY": "",
                "GAPGPT_API_KEY": "",
            },
            clear=False,
        ):
            # Empty string → code treats as unset via `or "edge"`
            self.assertEqual(tts_provider() or "edge", "edge")
            self.assertEqual(stt_provider() or "local", "local")
            self.assertFalse(speech_normalize_llm_enabled())

    def test_gapgpt_key_alias(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "",
                "OPENAI_TTS_API_KEY": "",
                "GAPGPT_API_KEY": "sk-gap-test",
                "OPENAI_BASE_URL": "",
                "GAPGPT_BASE_URL": "https://api.gapgpt.app/v1",
            },
            clear=False,
        ):
            cfg = openai_compatible_config()
            self.assertTrue(cfg.configured)
            self.assertEqual(cfg.api_key, "sk-gap-test")
            self.assertEqual(cfg.base_url, "https://api.gapgpt.app/v1")

    def test_status_hides_secrets(self) -> None:
        with patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "sk-secret", "TTS_PROVIDER": "edge"},
            clear=False,
        ):
            status = provider_status_summary()
        self.assertTrue(status["openai_api_key_set"])
        blob = str(status)
        self.assertNotIn("sk-secret", blob)


class SttProviderTests(unittest.TestCase):
    def test_openai_stt_falls_back_to_local(self) -> None:
        local = MagicMock(return_value="از ویسپر لوکال")
        getter = MagicMock(return_value=object())

        with (
            patch.dict(
                "os.environ",
                {"STT_PROVIDER": "openai", "OPENAI_API_KEY": "sk-x"},
                clear=False,
            ),
            patch(
                "backend.stt_utils._openai_transcribe_file",
                side_effect=RuntimeError("upstream down"),
            ),
            patch("backend.stt_utils.transcribe_medical_speech", local),
            patch(
                "backend.stt_utils.normalize_audio_for_stt",
                return_value=("in.wav", False),
            ),
        ):
            text = transcribe_medical_audio("in.wav", local_model_getter=getter)

        self.assertEqual(text, "از ویسپر لوکال")
        getter.assert_called_once()
        local.assert_called_once()

    def test_openai_stt_without_key_uses_local(self) -> None:
        local = MagicMock(return_value="لوکال")
        getter = MagicMock(return_value=object())
        with (
            patch.dict(
                "os.environ",
                {
                    "STT_PROVIDER": "openai",
                    "OPENAI_API_KEY": "",
                    "GAPGPT_API_KEY": "",
                    "OPENAI_TTS_API_KEY": "",
                },
                clear=False,
            ),
            patch("backend.stt_utils.transcribe_medical_speech", local),
            patch("backend.stt_utils._openai_transcribe_file") as cloud,
        ):
            text = transcribe_medical_audio("in.wav", local_model_getter=getter)
        self.assertEqual(text, "لوکال")
        cloud.assert_not_called()


if __name__ == "__main__":
    unittest.main()
