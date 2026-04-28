"""月次送信数 CRUD エンドポイントのテスト。

GET/POST/DELETE と monthly_stats への統合（scout_send_manual）を検証。
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

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


HEADERS = ["年月", "会社ID", "手動送信", "メモ", "更新日時"]


class TestMonthlySendCountList:
    def test_list_empty(self, client):
        with patch("api.routes_admin.sheets_writer") as mock_w:
            mock_w.ensure_sheet_exists = MagicMock()
            mock_w.get_all_rows.return_value = [HEADERS]
            res = client.get("/api/v1/admin/monthly_send_count")
            assert res.status_code == 200
            assert res.json()["items"] == []

    def test_list_filters_by_company(self, client):
        with patch("api.routes_admin.sheets_writer") as mock_w:
            mock_w.ensure_sheet_exists = MagicMock()
            mock_w.get_all_rows.return_value = [
                HEADERS,
                ["2026-04", "ark-visiting-nurse", "12", "メモA", "2026-04-28"],
                ["2026-04", "lcc-visiting-nurse", "5", "", "2026-04-28"],
                ["2026-03", "ark-visiting-nurse", "8", "", "2026-03-31"],
            ]
            res = client.get("/api/v1/admin/monthly_send_count?company_id=ark-visiting-nurse")
            items = res.json()["items"]
            assert len(items) == 2
            assert all(i["会社ID"] == "ark-visiting-nurse" for i in items)


class TestMonthlySendCountUpsert:
    def _patches(self):
        return [
            patch("api.routes_admin._known_company_ids", return_value={"test-co"}),
        ]

    def test_create_new(self, client):
        ps = self._patches()
        for p in ps: p.start()
        try:
            with patch("api.routes_admin.sheets_writer") as mock_w:
                mock_w.ensure_sheet_exists = MagicMock()
                mock_w.get_all_rows.return_value = [HEADERS]
                mock_w.append_row = MagicMock()

                res = client.post("/api/v1/admin/monthly_send_count", json={
                    "年月": "2026-04", "会社ID": "test-co", "手動送信": 10,
                    "メモ": "test memo",
                })
                assert res.status_code == 200
                assert res.json()["status"] == "created"
                mock_w.append_row.assert_called_once()
                row = mock_w.append_row.call_args[0][1]
                assert row[0] == "2026-04"
                assert row[1] == "test-co"
                assert row[2] == "10"
                assert row[3] == "test memo"
        finally:
            for p in ps: p.stop()

    def test_update_existing(self, client):
        ps = self._patches()
        for p in ps: p.start()
        try:
            with patch("api.routes_admin.sheets_writer") as mock_w:
                mock_w.ensure_sheet_exists = MagicMock()
                mock_w.get_all_rows.return_value = [
                    HEADERS,
                    ["2026-04", "test-co", "5", "old", "2026-04-01"],
                ]
                mock_w.update_cells_by_name = MagicMock()
                mock_w.append_row = MagicMock()

                res = client.post("/api/v1/admin/monthly_send_count", json={
                    "年月": "2026-04", "会社ID": "test-co", "手動送信": 12,
                    "メモ": "updated",
                })
                assert res.status_code == 200
                assert res.json()["status"] == "updated"
                assert res.json()["row_index"] == 2
                mock_w.update_cells_by_name.assert_called_once()
                _, kwargs = mock_w.update_cells_by_name.call_args
                cells = mock_w.update_cells_by_name.call_args[0][2]
                assert cells["手動送信"] == "12"
                assert cells["メモ"] == "updated"
                mock_w.append_row.assert_not_called()
        finally:
            for p in ps: p.stop()

    def test_validation_year_month(self, client):
        ps = self._patches()
        for p in ps: p.start()
        try:
            res = client.post("/api/v1/admin/monthly_send_count", json={
                "年月": "2026/04", "会社ID": "test-co", "手動送信": 1,
            })
            assert res.status_code == 400
        finally:
            for p in ps: p.stop()

    def test_validation_negative(self, client):
        ps = self._patches()
        for p in ps: p.start()
        try:
            res = client.post("/api/v1/admin/monthly_send_count", json={
                "年月": "2026-04", "会社ID": "test-co", "手動送信": -3,
            })
            assert res.status_code == 400
        finally:
            for p in ps: p.stop()

    def test_validation_unknown_company(self, client):
        with patch("api.routes_admin._known_company_ids", return_value=set()):
            res = client.post("/api/v1/admin/monthly_send_count", json={
                "年月": "2026-04", "会社ID": "unknown", "手動送信": 1,
            })
            assert res.status_code == 404


class TestMonthlySendCountDelete:
    def test_delete_row(self, client):
        with patch("api.routes_admin.sheets_writer") as mock_w:
            mock_w.delete_row = MagicMock()
            res = client.delete("/api/v1/admin/monthly_send_count/5")
            assert res.status_code == 200
            assert res.json()["row_index"] == 5
            mock_w.delete_row.assert_called_once()

    def test_delete_header_row_blocked(self, client):
        res = client.delete("/api/v1/admin/monthly_send_count/1")
        assert res.status_code == 400


class TestMonthlyStatsManualIntegration:
    """monthly_stats が月次送信数シートから scout_send_manual を読むことを検証。"""

    def _patches(self):
        return [
            patch("pipeline.orchestrator._send_data_sheet_name", return_value="送信_テスト"),
            patch("pipeline.orchestrator._unmatched_reply_sheet_name", return_value="未紐付け返信_テスト"),
            patch("pipeline.orchestrator._direct_application_sheet_name", return_value="直接応募_テスト"),
            patch("api.routes_admin._known_company_ids", return_value={"test-co"}),
        ]

    def test_manual_count_reflected_in_monthly_stats(self, client):
        ps = self._patches()
        for p in ps: p.start()
        try:
            with patch("api.routes_admin.sheets_writer") as mock_w:
                # send_data に5件のツール送信、月次送信数に手動7件
                send_rows = [[
                    "日時", "会員番号", "職種カテゴリ", "テンプレート種別", "テンプレートVer",
                    "生成パス", "パターン", "年齢層", "資格", "経験区分",
                    "希望雇用形態", "就業状況", "地域", "曜日", "時間帯", "全文",
                    "返信", "返信日", "返信カテゴリ", "応募", "応募日",
                ]]
                for i in range(5):
                    row = [""] * 21
                    row[0] = f"2026-04-{i+1:02d}"
                    row[3] = "正社員_初回"
                    send_rows.append(row)
                monthly_count_rows = [
                    HEADERS,
                    ["2026-04", "test-co", "7", "", "2026-04-28"],
                    ["2026-04", "other-co", "99", "", "2026-04-28"],  # 別会社（無視）
                    ["2026-03", "test-co", "3", "", "2026-03-31"],     # 別月（無視）
                ]
                mock_w.get_all_rows.side_effect = [
                    send_rows, [], [], monthly_count_rows,
                ]

                res = client.get("/api/v1/admin/monthly_stats/test-co?from=2026-04&to=2026-04")
                row = res.json()["rows"][0]
                assert row["scout_send_tool"] == 5
                assert row["scout_send_manual"] == 7
                assert row["scout_send_total"] == 12
        finally:
            for p in ps: p.stop()
