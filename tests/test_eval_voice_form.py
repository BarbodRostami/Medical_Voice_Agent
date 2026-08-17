"""Unit tests for voice-form gold scoring (no models, no dataset files)."""
from __future__ import annotations

import unittest

from backend.experiments.eval_voice_form import score_sample, values_match


class EvalVoiceFormTests(unittest.TestCase):
    def test_values_match_decimal_tolerance(self) -> None:
        self.assertTrue(values_match("procalcitonin", 0.8, 0.8))
        self.assertTrue(values_match("k", 3.5, 3.51))
        self.assertFalse(values_match("wbc", 11000, 15000))

    def test_score_sample_wrong_miss_extra(self) -> None:
        predicted = {"k": 3.5, "na": 140, "wbc": 9000}
        gold = {"k": 3.5, "na": 138}
        score = score_sample(predicted, gold)
        self.assertIn("k", score["correct"])
        self.assertIn("na", score["wrong"])
        self.assertIn("wbc", score["extra"])
        self.assertEqual(score["miss"], [])

    def test_score_sample_miss(self) -> None:
        score = score_sample({}, {"hb": 10.0})
        self.assertEqual(score["miss"], ["hb"])
        self.assertEqual(score["n_correct"], 0)


if __name__ == "__main__":
    unittest.main()
