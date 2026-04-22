"""Tests for /api/v1/admin/send_summary.

Regression focus: the endpoint must tolerate schema drift in 送信_* sheets
(legacy 15-col header paired with canonical-positioned 18/21-col rows), and
never leak raw cell values that aren't known job categories into by_category.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from auth.api_key import verify_api_key
from main import app


def _fake_operator():
    return {"operator_id": "test", "name": "Test", "role": "admin"}


@pytest.fixture
def client():
    app.dependency_overrides[verify_api_key] = _fake_operator
    yield TestClient(app)
    app.dependency_overrides.pop(verify_api_key, None)


EXPECTED_HEADERS = [
    "日時", "会員番号", "職種カテゴリ", "テンプレート種別", "テンプレートVer",
    "生成パス", "パターン", "年齢層", "資格", "経験区分",
    "希望雇用形態", "就業状況", "地域", "曜日", "時間帯",
    "全文",
    "返信", "返信日", "返信カテゴリ",
    "応募", "応募日",
]

LEGACY_HEADERS = [
    "日時", "会員番号", "テンプレート種別", "生成パス", "パターン",
    "年齢層", "資格", "経験区分", "希望雇用形態", "就業状況",
    "曜日", "時間帯",
    "返信", "返信日", "返信カテゴリ",
]


def _current_month_prefix() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m")


def _canonical_row(job_category="nurse", qualifications="看護師", full_text=""):
    row = [""] * len(EXPECTED_HEADERS)
    row[EXPECTED_HEADERS.index("日時")] = f"{_current_month_prefix()}-07 10:00:00"
    row[EXPECTED_HEADERS.index("会員番号")] = "M001"
    row[EXPECTED_HEADERS.index("職種カテゴリ")] = job_category
    row[EXPECTED_HEADERS.index("資格")] = qualifications
    row[EXPECTED_HEADERS.index("全文")] = full_text
    return row


class TestSendSummaryCanonicalSchema:
    def test_counts_by_category(self, client):
        rows = [
            EXPECTED_HEADERS,
            _canonical_row(job_category="nurse"),
            _canonical_row(job_category="nurse"),
            _canonical_row(job_category="rehab_pt"),
        ]
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = rows
            res = client.get("/api/v1/admin/send_summary?company=ark-visiting-nurse")
        body = res.json()
        assert body["total"] == 3
        assert body["by_category"]["看護師"] == 2
        assert body["by_category"]["PT"] == 1


class TestSendSummaryScenariosWithSchemaDrift:
    def test_does_not_leak_scout_body_into_categories(self, client):
        """The production bug: ARK's legacy header paired with canonical rows
        caused row[col_map['職種カテゴリ']] to return the 全文 column contents
        (a ~1300-char scout letter), which then became a by_category key.
        """
        long_body = "はじめまして。突然のご連絡..." + "x" * 1200
        # Legacy header on row 1, but rows are written in canonical 21-col order
        rows = [LEGACY_HEADERS] + [
            _canonical_row(job_category="nurse", qualifications="看護師", full_text=long_body)
            for _ in range(5)
        ]
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = rows
            res = client.get("/api/v1/admin/send_summary?company=ark-visiting-nurse")
        body = res.json()
        # No key should be a raw scout body
        for key in body["by_category"]:
            assert len(key) < 50, f"leaked long string as category key: {key[:80]}"
        # Categorization should still work via qualifications fallback
        assert body["by_category"].get("看護師", 0) == 5

    def test_rejects_unknown_cat_value_and_falls_back_to_qualifications(self, client):
        """Even without header drift, defensively reject garbage in the 職種カテゴリ
        cell (e.g. from an older writer that put something unexpected there)."""
        junk_row = _canonical_row(job_category="まるごと本文テキスト" * 20, qualifications="看護師")
        rows = [EXPECTED_HEADERS, junk_row]
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = rows
            res = client.get("/api/v1/admin/send_summary?company=ark-visiting-nurse")
        body = res.json()
        assert body["total"] == 1
        assert body["by_category"].get("看護師") == 1
        for key in body["by_category"]:
            assert len(key) < 50

    def test_empty_category_falls_back_to_qualifications(self, client):
        row = _canonical_row(job_category="", qualifications="看護師, 自動車運転免許")
        rows = [EXPECTED_HEADERS, row]
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = rows
            res = client.get("/api/v1/admin/send_summary?company=ark-visiting-nurse")
        body = res.json()
        assert body["by_category"].get("看護師") == 1

    def test_unknown_qualification_becomes_fumei(self, client):
        row = _canonical_row(job_category="", qualifications="")
        rows = [EXPECTED_HEADERS, row]
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = rows
            res = client.get("/api/v1/admin/send_summary?company=ark-visiting-nurse")
        body = res.json()
        assert body["by_category"].get("不明") == 1
