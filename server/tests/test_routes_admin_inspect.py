"""Tests for the diagnostic inspect endpoints.

Covers:
- POST /admin/inspect_send_sheets with include_headers=True (column-drift triage)
- POST /admin/inspect_sheet_shape (arbitrary sheet header + sample row)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

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


EXPECTED_SEND_HEADERS = [
    "日時", "会員番号", "職種カテゴリ", "テンプレート種別", "テンプレートVer",
    "生成パス", "パターン", "年齢層", "資格", "経験区分",
    "希望雇用形態", "就業状況", "地域", "曜日", "時間帯",
    "全文",
    "返信", "返信日", "返信カテゴリ",
    "応募", "応募日",
]


def _make_service_mock(sheet_titles: list[str]):
    """Build a service mock that returns the given sheet titles on .get()."""
    service = MagicMock()
    meta = {
        "sheets": [
            {"properties": {"title": t, "gridProperties": {"rowCount": 100}}}
            for t in sheet_titles
        ]
    }
    service.spreadsheets().get().execute.return_value = meta
    return service


class TestInspectSendSheets:
    def test_include_headers_flags_drift(self, client):
        """A sheet whose header row is missing 全文 should be flagged."""
        drifted_headers = [h for h in EXPECTED_SEND_HEADERS if h != "全文"]
        sample = ["2026-04-01"] + [""] * (len(drifted_headers) - 1)

        with patch("db.sheets_writer.sheets_writer") as mw, \
             patch("db.sheets_client.sheets_client") as mc:
            mw._get_service.return_value = _make_service_mock(["送信_テスト訪看"])
            mw.get_all_rows.return_value = [drifted_headers, sample]
            mc.get_companies_with_keywords.return_value = []
            res = client.post(
                "/api/v1/admin/inspect_send_sheets",
                json={"include_headers": True},
            )
        assert res.status_code == 200, res.text
        body = res.json()
        assert len(body["send_sheets"]) == 1
        entry = body["send_sheets"][0]
        assert entry["header_count"] == len(EXPECTED_SEND_HEADERS) - 1
        assert "全文" in entry["missing_expected"]
        assert entry["matches_expected"] is False
        assert entry["headers"] == drifted_headers
        assert entry["sample_row"] == sample

    def test_omits_header_fields_when_flag_not_set(self, client):
        """Default behavior (no include_headers) must not include raw headers."""
        with patch("db.sheets_writer.sheets_writer") as mw, \
             patch("db.sheets_client.sheets_client") as mc:
            mw._get_service.return_value = _make_service_mock(["送信_テスト訪看"])
            mw.get_all_rows.return_value = [EXPECTED_SEND_HEADERS, EXPECTED_SEND_HEADERS]
            mc.get_companies_with_keywords.return_value = []
            res = client.post("/api/v1/admin/inspect_send_sheets", json={})
        body = res.json()
        entry = body["send_sheets"][0]
        assert "headers" not in entry
        assert "sample_row" not in entry
        assert "missing_expected" not in entry
        # Basic shape still returned
        assert entry["data_rows"] == 1


class TestInspectSheetShape:
    def test_returns_header_and_sample(self, client):
        drifted = ["列 1", "列 2", "列 3", "timestamp", "member_id"]
        sample = ["2026-04-15", "ark", "M001", "ai", "nurse"]

        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [drifted, sample]
            res = client.post(
                "/api/v1/admin/inspect_sheet_shape",
                json={"sheet": "生成ログ"},
            )
        assert res.status_code == 200
        body = res.json()
        assert body["sheet"] == "生成ログ"
        assert body["headers"] == drifted
        assert body["sample_row"] == sample
        assert body["data_rows"] == 1

    def test_with_expected_flags_drift(self, client):
        drifted = ["列 1", "列 2", "timestamp"]
        expected = ["timestamp", "company", "member_id"]

        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [drifted]
            res = client.post(
                "/api/v1/admin/inspect_sheet_shape",
                json={"sheet": "生成ログ", "expected": expected},
            )
        body = res.json()
        assert body["matches_expected"] is False
        assert set(body["missing_expected"]) == {"company", "member_id"}
        assert set(body["extra_headers"]) == {"列 1", "列 2"}

    def test_rejects_missing_sheet_param(self, client):
        res = client.post("/api/v1/admin/inspect_sheet_shape", json={})
        assert res.status_code == 400

    def test_404_when_sheet_unreadable(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.side_effect = Exception("not found")
            res = client.post(
                "/api/v1/admin/inspect_sheet_shape",
                json={"sheet": "no-such-sheet"},
            )
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# POST /admin/normalize_send_sheet
# ---------------------------------------------------------------------------

class TestNormalizeSendSheet:
    def test_rejects_non_send_sheet(self, client):
        res = client.post(
            "/api/v1/admin/normalize_send_sheet",
            json={"sheet": "テンプレート", "dry_run": True},
        )
        assert res.status_code == 400

    def test_rejects_missing_sheet(self, client):
        res = client.post(
            "/api/v1/admin/normalize_send_sheet", json={"dry_run": True}
        )
        assert res.status_code == 400

    def test_dry_run_preview_15col_legacy(self, client):
        """15 列レガシーでは欠落列は空文字に埋められる。"""
        legacy_headers = [
            "日時", "会員番号", "テンプレート種別", "生成パス", "パターン",
            "年齢層", "資格", "経験区分", "希望雇用形態", "就業状況",
            "曜日", "時間帯",
            "返信", "返信日", "返信カテゴリ",
        ]
        row = [
            "2026-04-01 10:00:00", "M001", "パート_初回", "ai", "",
            "30-34歳", "看護師", "4-5年", "パート", "就業中",
            "水", "午前",
            "", "", "",
        ]
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [legacy_headers, row]
            res = client.post(
                "/api/v1/admin/normalize_send_sheet",
                json={"sheet": "送信_legacy", "dry_run": True},
            )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "dry_run"
        assert body["original_header_count"] == 15
        assert body["expected_header_count"] == 21
        assert body["data_rows_output"] == 1
        after = body["preview"][0]["after"]
        assert len(after) == 21
        # 日時 is preserved
        assert after[0] == "2026-04-01 10:00:00"
        # 地域 (EXPECTED[12]) was absent → empty
        assert after[12] == ""
        # 全文 (EXPECTED[15]) was absent → empty
        assert after[15] == ""

    def test_dry_run_does_not_write(self, client):
        headers = [
            "日時", "会員番号", "職種カテゴリ", "テンプレート種別", "テンプレートVer",
            "生成パス", "パターン", "年齢層", "資格", "経験区分",
            "希望雇用形態", "就業状況", "地域", "曜日", "時間帯",
            "全文", "返信", "返信日", "返信カテゴリ",
            "応募", "応募日",
        ]
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [headers, headers]
            res = client.post(
                "/api/v1/admin/normalize_send_sheet",
                json={"sheet": "送信_clean", "dry_run": True},
            )
        assert res.status_code == 200
        mw.append_rows.assert_not_called()
        mw._get_service.assert_not_called()

    def test_empty_rows_skipped(self, client):
        headers = [
            "日時", "会員番号", "職種カテゴリ", "テンプレート種別", "テンプレートVer",
            "生成パス", "パターン", "年齢層", "資格", "経験区分",
            "希望雇用形態", "就業状況", "地域", "曜日", "時間帯",
            "全文", "返信", "返信日", "返信カテゴリ", "応募", "応募日",
        ]
        real_row = ["2026-04-01"] + [""] * 20
        empty_row = [""] * 21
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [headers, real_row, empty_row, empty_row]
            res = client.post(
                "/api/v1/admin/normalize_send_sheet",
                json={"sheet": "送信_clean", "dry_run": True},
            )
        body = res.json()
        assert body["data_rows_input"] == 3
        assert body["data_rows_output"] == 1
        assert body["empty_rows_skipped"] == 2

    def test_real_run_clears_and_writes(self, client):
        headers = [
            "日時", "会員番号", "職種カテゴリ", "テンプレート種別", "テンプレートVer",
            "生成パス", "パターン", "年齢層", "資格", "経験区分",
            "希望雇用形態", "就業状況", "地域", "曜日", "時間帯",
            "全文", "返信", "返信日", "返信カテゴリ", "応募", "応募日",
        ]
        row = ["2026-04-01"] + [""] * 20
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [headers, row]
            service = MagicMock()
            mw._get_service.return_value = service
            res = client.post(
                "/api/v1/admin/normalize_send_sheet",
                json={"sheet": "送信_clean", "dry_run": False},
            )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["written_rows"] == 1
        # clear was invoked with A1:ZZ range
        clear_calls = service.spreadsheets().values().clear.call_args_list
        assert clear_calls, "expected at least one clear call"
        assert any("ZZ" in str(c) for c in clear_calls)
        # header update hit A1
        update_calls = service.spreadsheets().values().update.call_args_list
        assert update_calls, "expected at least one header update"
        # data appended exactly once
        mw.append_rows.assert_called_once()
