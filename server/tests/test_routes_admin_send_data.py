"""Tests for the per-company send_data row CRUD endpoints (Phase B)."""
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


def _row(member_id="M001", **overrides):
    base = {h: "" for h in SEND_DATA_HEADERS}
    base["日時"] = "2026-04-07T10:00:00"
    base["会員番号"] = member_id
    base["職種カテゴリ"] = "nurse"
    base["テンプレート種別"] = "パート_初回"
    base.update(overrides)
    return [base[h] for h in SEND_DATA_HEADERS]


# ---------------------------------------------------------------------------
# GET /api/v1/admin/send_data/{company_id}
# ---------------------------------------------------------------------------

class TestListSendData:
    def test_returns_rows_with_row_index(self, client):
        rows = [SEND_DATA_HEADERS, _row("M001"), _row("M002"), _row("M003")]
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = rows
            res = client.get("/api/v1/admin/send_data/ark-visiting-nurse")
        assert res.status_code == 200
        body = res.json()
        assert "items" in body
        assert "headers" in body
        items = body["items"]
        assert len(items) == 3
        # row_index should be 1-indexed (header is row 1, first data is row 2)
        assert items[0]["_row_index"] == 2
        assert items[1]["_row_index"] == 3
        assert items[2]["_row_index"] == 4
        assert items[0]["会員番号"] == "M001"

    def test_returns_empty_when_sheet_missing(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.side_effect = Exception("not found")
            res = client.get("/api/v1/admin/send_data/ark-visiting-nurse")
        assert res.status_code == 200
        assert res.json()["items"] == []


# ---------------------------------------------------------------------------
# DELETE /api/v1/admin/send_data/{company_id}/{row_index}
# ---------------------------------------------------------------------------

class TestDeleteSendDataRow:
    def test_delete_calls_sheets_writer_with_correct_sheet_name(self, client):
        rows = [SEND_DATA_HEADERS, _row("M001"), _row("M002")]
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = rows
            res = client.delete("/api/v1/admin/send_data/ark-visiting-nurse/2")
        assert res.status_code == 200
        assert res.json()["status"] == "deleted"
        mw.delete_row.assert_called_once()
        call_args = mw.delete_row.call_args
        # First positional: sheet name should be 送信_アーク訪看
        assert call_args[0][0] == "送信_アーク訪看"
        assert call_args[0][1] == 2

    def test_delete_unknown_company_returns_404(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            res = client.delete("/api/v1/admin/send_data/no-such-company/2")
        assert res.status_code == 404

    def test_delete_invalid_row_index_returns_400(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            res = client.delete("/api/v1/admin/send_data/ark-visiting-nurse/0")
        assert res.status_code == 400

    def test_delete_row_index_1_is_header_rejected(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            res = client.delete("/api/v1/admin/send_data/ark-visiting-nurse/1")
        assert res.status_code == 400
