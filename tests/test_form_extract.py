"""Unit tests for experimental patient-tab form extraction (no models)."""
from __future__ import annotations

import unittest

from backend.experiments.form_extract import (
    compute_ibw_kg,
    confirmation_speech_fa,
    export_fields_payload,
    extract_patient_demographics,
    merge_patient_extractions,
)


class FormExtractTests(unittest.TestCase):
    def test_full_male_persian(self) -> None:
        r = extract_patient_demographics(
            "بیمار آقای ۴۵ ساله با قد ۱۷۵ سانتی‌متر"
        )
        self.assertEqual(r["gender"], "male")
        self.assertEqual(r["age"], 45)
        self.assertEqual(r["height_cm"], 175)
        self.assertIsNotNone(r["ibw_kg"])

    def test_spoken_age_and_height(self) -> None:
        r = extract_patient_demographics(
            "بیمار، زن، سی و دو ساله قد صد و شصت سانتی‌متر وزن هفتاد کیلو"
        )
        self.assertEqual(r["gender"], "female")
        self.assertEqual(r["age"], 32)
        self.assertEqual(r["height_cm"], 160)
        self.assertEqual(r["weight_kg"], 70.0)

    def test_icu_fields(self) -> None:
        r = extract_patient_demographics(
            "سه روز ونتیلاتور لوله ETT اندیکاسیون اورژانس RASS منفی دو "
            "تشخیص ARDS تب دارد جراحی اخیر ندارد sedation فعال "
            "ترشحات زیاد CXR: انفیلتراسیون دوطرفه"
        )
        self.assertEqual(r["ventilator_days"], 3.0)
        self.assertEqual(r["tube_type"], "ETT")
        self.assertEqual(r["indication"], "emergency")
        self.assertEqual(r["rass"], -2)
        self.assertEqual(r["diagnosis_category"], "ARDS")
        self.assertTrue(r["fever"])
        self.assertFalse(r["recent_surgery"])
        self.assertTrue(r["sedation_active"])
        self.assertEqual(r["secretion_intensity"], "زیاد")
        self.assertIn("انفیلتراسیون", r["cxr_summary"] or "")

    def test_ett_spoken_persian(self) -> None:
        r = extract_patient_demographics("لوله ای تی تی")
        self.assertEqual(r["tube_type"], "ETT")

    def test_trach_synonym(self) -> None:
        r = extract_patient_demographics("بیمار لوله تراک دارد")
        self.assertEqual(r["tube_type"], "Trach")

    def test_merge_keeps_old_and_fills_new(self) -> None:
        base = extract_patient_demographics("بیمار آقای ۴۵ ساله قد ۱۷۵")
        incoming = extract_patient_demographics("وزن هشتاد کیلو تب دارد")
        merged = merge_patient_extractions(base, incoming)
        self.assertEqual(merged["gender"], "male")
        self.assertEqual(merged["age"], 45)
        self.assertEqual(merged["height_cm"], 175)
        self.assertEqual(merged["weight_kg"], 80.0)
        self.assertTrue(merged["fever"])
        self.assertIn("۴۵", merged["raw_text"])
        self.assertIn("وزن", merged["raw_text"])

    def test_confirmation_speech(self) -> None:
        r = extract_patient_demographics("بیمار خانم سی ساله قد ۱۶۰")
        speech = confirmation_speech_fa(r)
        self.assertIn("درسته؟", speech)
        self.assertTrue(len(speech) > 10)

    def test_export_payload(self) -> None:
        r = extract_patient_demographics("آقای ۵۰ ساله")
        payload = export_fields_payload(r)
        self.assertIn("fields", payload)
        self.assertEqual(payload["fields"]["age"], 50)
        self.assertIn("missing", payload)

    def test_ibw_formula(self) -> None:
        ibw = compute_ibw_kg("male", 175)
        self.assertIsNotNone(ibw)
        assert ibw is not None
        self.assertTrue(65 < ibw < 80)

    def test_empty(self) -> None:
        r = extract_patient_demographics("")
        self.assertIn("gender", r["missing"])
        self.assertIn("age", r["missing"])


if __name__ == "__main__":
    unittest.main()
