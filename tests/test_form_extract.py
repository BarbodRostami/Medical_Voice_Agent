"""Unit tests for experimental patient-form extraction (no models)."""
from __future__ import annotations

import unittest

from backend.experiments.form_extract import extract_patient_demographics


class FormExtractTests(unittest.TestCase):
    def test_full_male_persian(self) -> None:
        r = extract_patient_demographics(
            "بیمار آقای ۴۵ ساله با قد ۱۷۵ سانتی‌متر"
        )
        self.assertEqual(r["gender"], "male")
        self.assertEqual(r["age"], 45)
        self.assertEqual(r["height_cm"], 175)
        self.assertEqual(r["missing"], [])

    def test_female_and_age(self) -> None:
        r = extract_patient_demographics("خانم ۳۲ ساله")
        self.assertEqual(r["gender"], "female")
        self.assertEqual(r["age"], 32)
        self.assertIsNone(r["height_cm"])
        self.assertIn("height_cm", r["missing"])

    def test_height_only_cm(self) -> None:
        r = extract_patient_demographics("قد بیمار ۱۶۰ سانت است")
        self.assertEqual(r["height_cm"], 160)
        self.assertIsNone(r["gender"])

    def test_empty(self) -> None:
        r = extract_patient_demographics("")
        self.assertEqual(set(r["missing"]), {"gender", "age", "height_cm"})


if __name__ == "__main__":
    unittest.main()
