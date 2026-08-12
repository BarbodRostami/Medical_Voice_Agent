"""Unit tests for experimental patient-tab form extraction (no models)."""
from __future__ import annotations

import unittest

from backend.experiments.form_extract import (
    FIELD_LABELS_FA,
    compute_ibw_kg,
    compute_map_mmhg,
    compute_pf_ratio,
    compute_vt_ibw_ml_kg,
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

    def test_collaborator_garbled_stt(self) -> None:
        """Real collaborator STT garbling must still fill gender/age/height."""
        r = extract_patient_demographics(
            "جنس، بیمار، مرد است. سن بیمار، چهل و پنج سال است. "
            "قد بیمار، سد و حفتاد و پنج سنتی میت است. جنس، بیمار، مرد است."
        )
        self.assertEqual(r["gender"], "male")
        self.assertEqual(r["age"], 45)
        self.assertEqual(r["height_cm"], 175)
        self.assertIsNotNone(r["ibw_kg"])

    def test_sen_sal_ast_spoken_age(self) -> None:
        r = extract_patient_demographics("سن بیمار چهل و پنج سال است")
        self.assertEqual(r["age"], 45)

    def test_ventilator_settings_required(self) -> None:
        r = extract_patient_demographics(
            "مود VCV پیپ پنج فی او دو چهل درصد"
        )
        self.assertEqual(r["ventilator_mode"], "VCV")
        self.assertEqual(r["peep_cmh2o"], 5.0)
        self.assertEqual(r["fio2_pct"], 40.0)
        self.assertIn("ventilator_mode", r["found"])
        self.assertIn("peep_cmh2o", r["found"])
        self.assertIn("fio2_pct", r["found"])
        # Patient keys still present in schema
        self.assertIn("gender", r["missing"])
        self.assertIn("ventilator_mode", FIELD_LABELS_FA)

    def test_ventilator_modes_dropdown(self) -> None:
        from backend.experiments.form_extract import _extract_ventilator_mode

        cases = {
            "مود پی سی وی": "PCV",
            "SIMV-V": "SIMV-V",
            "simv p": "SIMV-P",
            "PSV / CPAP": "PSV/CPAP",
            "APRV": "APRV",
            "PRVC": "PRVC",
            "وی سی وی": "VCV",
        }
        for spoken, expected in cases.items():
            self.assertEqual(
                _extract_ventilator_mode(spoken),
                expected,
                msg=spoken,
            )

    def test_ventilator_extra_params(self) -> None:
        r = extract_patient_demographics(
            "مود PCV وی تی پانصد آر آر شانزده فشار دمی بیست "
            "پی اس ده تریگر دو"
        )
        self.assertEqual(r["ventilator_mode"], "PCV")
        self.assertEqual(r["vt_set_ml"], 500)
        self.assertEqual(r["rr_set_bpm"], 16)
        self.assertEqual(r["pi_cmh2o"], 20.0)
        self.assertEqual(r["ps_cmh2o"], 10.0)
        self.assertEqual(r["trigger_sensitivity_lpm"], 2.0)

    def test_patient_fields_unchanged_with_vent_schema(self) -> None:
        """Adding vent keys must not break classic patient extract."""
        r = extract_patient_demographics(
            "بیمار آقای ۴۵ ساله با قد ۱۷۵ سانتی‌متر وزن ۸۰ کیلو تب دارد"
        )
        self.assertEqual(r["gender"], "male")
        self.assertEqual(r["age"], 45)
        self.assertEqual(r["height_cm"], 175)
        self.assertEqual(r["weight_kg"], 80.0)
        self.assertTrue(r["fever"])
        self.assertIsNone(r["ventilator_mode"])
        self.assertIsNone(r["peep_cmh2o"])
        self.assertIsNone(r["fio2_pct"])
        self.assertIsNone(r["rr_total_bpm"])
        self.assertIsNone(r["peak_pressure_cmh2o"])

    def test_measurement_fields(self) -> None:
        r = extract_patient_demographics(
            "آر آر توتال ۲۰ آر آر اسپانتانیوس ۸ وی تی ای ۴۵۰ "
            "پیک پرشر ۲۸ پلاتو ۲۲ پیپ اندازه‌گیری ۵ اتو پیپ ۲ "
            "آی ای ۱ به ۲ لیک ۳ درصد RSBI ۱۱۰"
        )
        self.assertEqual(r["rr_total_bpm"], 20)
        self.assertEqual(r["rr_spontaneous_bpm"], 8)
        self.assertEqual(r["vte_ml"], 450)
        self.assertEqual(r["peak_pressure_cmh2o"], 28.0)
        self.assertEqual(r["plateau_pressure_cmh2o"], 22.0)
        self.assertEqual(r["peep_measured_cmh2o"], 5.0)
        self.assertEqual(r["auto_peep_cmh2o"], 2.0)
        self.assertEqual(r["ie_ratio"], "1:2")
        self.assertEqual(r["leak_pct"], 3.0)
        self.assertEqual(r["rsbi"], 110.0)
        # Settings peep set should stay empty when only measured spoken
        self.assertIsNone(r["peep_cmh2o"])

    def test_vt_ibw_computed_from_vte_and_ibw(self) -> None:
        r = extract_patient_demographics(
            "بیمار آقای قد ۱۷۵ سانتی‌متر وی تی ای ۴۵۰"
        )
        self.assertEqual(r["vte_ml"], 450)
        self.assertIsNotNone(r["ibw_kg"])
        expected = compute_vt_ibw_ml_kg(450, r["ibw_kg"])
        self.assertEqual(r["vt_ibw_ml_kg"], expected)
        self.assertIn("vt_ibw_ml_kg", r["found"])

    def test_vt_ibw_spoken_wins_without_vte(self) -> None:
        r = extract_patient_demographics("VT/IBW 6.5")
        self.assertEqual(r["vt_ibw_ml_kg"], 6.5)
        self.assertIsNone(r["vte_ml"])
        self.assertIsNone(r["ibw_kg"])

    def test_vt_ibw_recomputed_on_merge(self) -> None:
        base = extract_patient_demographics("بیمار آقای قد ۱۷۵ سانتی‌متر")
        incoming = extract_patient_demographics("وی تی ای ۴۵۰")
        merged = merge_patient_extractions(base, incoming)
        self.assertEqual(merged["vte_ml"], 450)
        self.assertEqual(
            merged["vt_ibw_ml_kg"],
            compute_vt_ibw_ml_kg(450, merged["ibw_kg"]),
        )

    def test_compute_vt_ibw_helper(self) -> None:
        self.assertEqual(compute_vt_ibw_ml_kg(450, 70.0), 6.4)
        self.assertIsNone(compute_vt_ibw_ml_kg(None, 70.0))
        self.assertIsNone(compute_vt_ibw_ml_kg(450, None))
        self.assertIsNone(compute_vt_ibw_ml_kg(450, 0))

    def test_abg_fields_and_pf_ratio(self) -> None:
        r = extract_patient_demographics(
            "پی اچ ۷٫۳۵ پی ای سی او دو ۴۰ پی ای او دو ۸۰ "
            "اس ای او دو ۹۵ بیکربنات ۲۴ بیس اکسس منفی ۲ "
            "فی او دو ۴۰ درصد"
        )
        self.assertEqual(r["ph"], 7.35)
        self.assertEqual(r["paco2_mmhg"], 40.0)
        self.assertEqual(r["pao2_mmhg"], 80.0)
        self.assertEqual(r["sao2_pct"], 95.0)
        self.assertEqual(r["hco3_meq_l"], 24.0)
        self.assertEqual(r["base_excess_meq_l"], -2.0)
        self.assertEqual(r["fio2_pct"], 40.0)
        self.assertEqual(r["pf_ratio"], compute_pf_ratio(80.0, 40.0))
        self.assertEqual(r["pf_ratio"], 200.0)

    def test_pf_ratio_recomputed_on_merge(self) -> None:
        base = extract_patient_demographics("فی او دو پنجاه درصد")
        incoming = extract_patient_demographics("پی ای او دو ۱۰۰")
        merged = merge_patient_extractions(base, incoming)
        self.assertEqual(merged["pao2_mmhg"], 100.0)
        self.assertEqual(merged["fio2_pct"], 50.0)
        self.assertEqual(merged["pf_ratio"], 200.0)

    def test_ph_spoken_medical_style(self) -> None:
        r = extract_patient_demographics("پی اچ هفت و سی و پنج")
        self.assertEqual(r["ph"], 7.35)

    def test_hemodynamics_and_map(self) -> None:
        r = extract_patient_demographics(
            "فشار خون ۱۲۰ روی ۸۰ اچ آر ۹۰ دما ۳۷ "
            "خروجی ادرار ۵۰ بالانس مایعات مثبت ۵۰۰ وازوپرسور ندارد"
        )
        self.assertEqual(r["sbp_mmhg"], 120.0)
        self.assertEqual(r["dbp_mmhg"], 80.0)
        self.assertEqual(r["map_mmhg"], compute_map_mmhg(120.0, 80.0))
        self.assertEqual(r["map_mmhg"], 93.3)
        self.assertEqual(r["hr_bpm"], 90.0)
        self.assertEqual(r["temperature_c"], 37.0)
        self.assertEqual(r["urine_output_ml_hr"], 50.0)
        self.assertEqual(r["io_balance_24h_ml"], 500.0)
        self.assertFalse(r["vasopressor_active"])

    def test_map_from_spoken_bp_pair(self) -> None:
        r = extract_patient_demographics("فشار خون صد و بیست روی هشتاد")
        self.assertEqual(r["sbp_mmhg"], 120.0)
        self.assertEqual(r["dbp_mmhg"], 80.0)
        self.assertEqual(r["map_mmhg"], 93.3)

    def test_map_recomputed_on_merge(self) -> None:
        base = extract_patient_demographics("اس بی پی ۱۱۰")
        incoming = extract_patient_demographics("دی بی پی ۷۰")
        merged = merge_patient_extractions(base, incoming)
        self.assertEqual(merged["sbp_mmhg"], 110.0)
        self.assertEqual(merged["dbp_mmhg"], 70.0)
        self.assertEqual(merged["map_mmhg"], compute_map_mmhg(110.0, 70.0))

    def test_compute_map_helper(self) -> None:
        self.assertEqual(compute_map_mmhg(120, 80), 93.3)
        self.assertIsNone(compute_map_mmhg(None, 80))
        self.assertIsNone(compute_map_mmhg(120, None))
        self.assertIsNone(compute_map_mmhg(70, 90))


if __name__ == "__main__":
    unittest.main()
