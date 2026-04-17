"""Tests for the competitor query template registry."""
from __future__ import annotations

from pipeline.competitor_queries import (
    QUERIES,
    business_type_for,
    queries_for,
)


class TestBusinessTypeFor:
    def test_visiting_nurse_companies(self):
        for cid in (
            "ark-visiting-nurse",
            "lcc-visiting-nurse",
            "ichigo-visiting-nurse",
            "an-visiting-nurse",
        ):
            assert business_type_for(cid) == "visiting_nurse"

    def test_hospital_nurse_companies(self):
        assert business_type_for("nomura-hospital") == "hospital_nurse"
        assert business_type_for("chigasaki-tokushukai") == "hospital_nurse"

    def test_elderly_care_sales(self):
        assert business_type_for("daiwa-house-ls") == "elderly_care_sales"

    def test_unknown_company_falls_back_to_default(self):
        assert business_type_for("some-unknown-company") == "default"


class TestQueriesFor:
    def test_visiting_nurse_uses_訪問看護_keyword(self):
        q = queries_for("ark-visiting-nurse")
        assert "訪問看護" in q.listup
        assert "訪問看護" in q.conditions
        assert "訪問看護" in q.reputation

    def test_hospital_nurse_uses_night_shift_keyword(self):
        q = queries_for("nomura-hospital")
        assert "夜勤" in q.conditions

    def test_elderly_sales_uses_incentive_keyword(self):
        q = queries_for("daiwa-house-ls")
        assert "インセンティブ" in q.conditions or "歩合" in q.conditions

    def test_placeholders_present(self):
        for key, q in QUERIES.items():
            assert "{area}" in q.listup, f"listup missing {{area}} in {key}"
            for field in (q.conditions, q.reputation, q.training_culture):
                assert "{competitor}" in field, f"missing {{competitor}} in {key}"
