"""Tests for the manual send recording endpoint (Phase C).

Captures sends that happen in JOBMEDLEY's UI directly (without going through
the orchestrator API), so the dashboards reflect actual usage.
"""
from __future__ import annotations

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


SEND_DATA_HEADERS = [
    "日時", "会員番号", "職種カテゴリ", "テンプレート種別", "テンプレートVer",
    "生成パス", "パターン", "年齢層", "資格", "経験区分",
    "希望雇用形態", "就業状況", "地域", "曜日", "時間帯",
    "返信", "返信日", "返信カテゴリ",
]


class TestRecordManualSend:
    def test_appends_with_manual_marker(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [SEND_DATA_HEADERS]
            res = client.post(
                "/api/v1/admin/record_manual_send",
                json={
                    "company_id": "ark-visiting-nurse",
                    "member_id": "M_MANUAL_001",
                    "sent_at": "2026-04-07T15:30:00",
                    "qualifications": "看護師",
                    "age": "42歳",
                },
            )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["recorded"] is True
        mw.append_row.assert_called_once()
        sheet_name, row = mw.append_row.call_args[0]
        assert sheet_name == "送信_アーク訪看"
        assert len(row) == len(SEND_DATA_HEADERS)
        # canonical positional order
        assert row[SEND_DATA_HEADERS.index("会員番号")] == "M_MANUAL_001"
        assert row[SEND_DATA_HEADERS.index("生成パス")] == "manual"
        assert row[SEND_DATA_HEADERS.index("テンプレート種別")] == "(手動)"
        # 日時 should be present
        assert row[SEND_DATA_HEADERS.index("日時")] == "2026-04-07T15:30:00"

    def test_dedup_same_member_same_day(self, client):
        existing = ["", ""] * 9
        existing[SEND_DATA_HEADERS.index("日時")] = "2026-04-07T08:00:00"
        existing[SEND_DATA_HEADERS.index("会員番号")] = "M_DUP"
        existing[SEND_DATA_HEADERS.index("生成パス")] = "manual"
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [SEND_DATA_HEADERS, existing]
            res = client.post(
                "/api/v1/admin/record_manual_send",
                json={
                    "company_id": "ark-visiting-nurse",
                    "member_id": "M_DUP",
                    "sent_at": "2026-04-07T15:30:00",
                },
            )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["recorded"] is False
        assert body["reason"] == "duplicate"
        mw.append_row.assert_not_called()

    def test_dedup_only_within_same_day(self, client):
        """同じ会員IDでも日付が違えば別レコードとして記録される。"""
        existing = ["", ""] * 9
        existing[SEND_DATA_HEADERS.index("日時")] = "2026-04-06T08:00:00"
        existing[SEND_DATA_HEADERS.index("会員番号")] = "M_DUP"
        existing[SEND_DATA_HEADERS.index("生成パス")] = "manual"
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [SEND_DATA_HEADERS, existing]
            res = client.post(
                "/api/v1/admin/record_manual_send",
                json={
                    "company_id": "ark-visiting-nurse",
                    "member_id": "M_DUP",
                    "sent_at": "2026-04-07T15:30:00",
                },
            )
        assert res.status_code == 200
        assert res.json()["recorded"] is True
        mw.append_row.assert_called_once()

    def test_unknown_company_returns_404(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            res = client.post(
                "/api/v1/admin/record_manual_send",
                json={"company_id": "no-such", "member_id": "M001", "sent_at": "2026-04-07T15:30:00"},
            )
        assert res.status_code == 404

    def test_missing_member_id_returns_400(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            res = client.post(
                "/api/v1/admin/record_manual_send",
                json={"company_id": "ark-visiting-nurse", "sent_at": "2026-04-07T15:30:00"},
            )
        assert res.status_code == 400
