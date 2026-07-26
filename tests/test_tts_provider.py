"""Unit tests for TTS speech-prep (no network / no model load)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.medical_voice_utils import (
    normalize_digits_for_speech,
    polish_spoken_phrasing,
    prepare_text_for_tts,
    replace_abbreviations,
    tts_to_mp3,
)


class SpeechPrepTests(unittest.TestCase):
    def test_spo2_and_peep_expanded(self) -> None:
        out = prepare_text_for_tts("بیمار SpO2 پایین و PEEP بالاست", use_llm=False)
        self.assertIn("اشباع اکسیژن", out)
        self.assertIn("فشار مثبت انتهای بازدمی", out)
        self.assertNotIn("SpO2", out)
        self.assertNotIn("PEEP", out)

    def test_spoken_order_patient_after_vital(self) -> None:
        out = prepare_text_for_tts(
            "بیمار SpO2 برابر ۹۲ درصد، PEEP برابر 8 و MAP برابر 70 است.",
            use_llm=False,
        )
        self.assertTrue(out.startswith("اشباع اکسیژن بیمار برابر"))
        self.assertIn("92", out)
        self.assertNotIn("بیمار اشباع اکسیژن", out)

    def test_polish_spoken_phrasing_unit(self) -> None:
        out = polish_spoken_phrasing("بیمار اشباع اکسیژن برابر 92 درصد")
        self.assertEqual(out, "اشباع اکسیژن بیمار برابر 92 درصد")

    def test_persian_digits_become_ascii_by_default(self) -> None:
        with patch.dict("os.environ", {"TTS_DIGIT_MODE": "ascii"}, clear=False):
            out = prepare_text_for_tts(
                "اشباع اکسیژن ۹۲ درصد و ETCO2 برابر ۳۵",
                use_llm=False,
            )
        self.assertIn("92", out)
        self.assertIn("35", out)
        self.assertNotIn("۹۲", out)
        self.assertNotIn("۳۵", out)

    def test_digit_mode_words(self) -> None:
        with patch.dict("os.environ", {"TTS_DIGIT_MODE": "words"}, clear=False):
            out = normalize_digits_for_speech("مقدار ۹۲ و ۳.۵")
        self.assertIn("نود و دو", out)
        self.assertIn("سه ممیز پنج", out)
        self.assertNotIn("92", out)

    def test_short_or_not_replaced_in_english(self) -> None:
        # Case-sensitive: lowercase "or" must survive
        out = replace_abbreviations("give fluids or blood")
        self.assertIn(" or ", out)

    def test_uppercase_or_is_operating_room(self) -> None:
        out = replace_abbreviations("بیمار به OR منتقل شد")
        self.assertIn("اتاق عمل", out)

    def test_tts_defaults_to_edge(self) -> None:
        with (
            patch.dict("os.environ", {"TTS_PROVIDER": "edge"}, clear=False),
            patch("backend.medical_voice_utils._edge_tts_mp3", return_value=b"ID3edge") as edge,
            patch("backend.medical_voice_utils._openai_tts_mp3") as oai,
        ):
            audio = tts_to_mp3("سلام")
        self.assertEqual(audio, b"ID3edge")
        edge.assert_called_once()
        oai.assert_not_called()

    def test_openai_without_key_uses_edge(self) -> None:
        env = {
            "TTS_PROVIDER": "openai",
            "OPENAI_API_KEY": "",
            "OPENAI_TTS_API_KEY": "",
            "GAPGPT_API_KEY": "",
        }
        with (
            patch.dict("os.environ", env, clear=False),
            patch("backend.medical_voice_utils._edge_tts_mp3", return_value=b"ID3nokey") as edge,
            patch("backend.medical_voice_utils._openai_tts_mp3") as oai,
        ):
            audio = tts_to_mp3("سلام")
        self.assertEqual(audio, b"ID3nokey")
        edge.assert_called_once()
        oai.assert_not_called()

    def test_openai_falls_back_to_edge(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {"TTS_PROVIDER": "openai", "OPENAI_API_KEY": "sk-test"},
                clear=False,
            ),
            patch(
                "backend.medical_voice_utils._openai_tts_mp3",
                side_effect=RuntimeError("upstream down"),
            ),
            patch("backend.medical_voice_utils._edge_tts_mp3", return_value=b"ID3fb") as edge,
        ):
            audio = tts_to_mp3("سلام")
        self.assertEqual(audio, b"ID3fb")
        edge.assert_called_once()


if __name__ == "__main__":
    unittest.main()
