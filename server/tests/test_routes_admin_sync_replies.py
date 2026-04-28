"""sync_replies エンドポイントのテスト

status 別の振り分け、matched/unmatched の返却、直接応募シートへの append を検証。
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


SEND_HEADERS = [
    "日時", "会員番号", "職種カテゴリ", "テンプレート種別", "テンプレートVer",
    "生成パス", "パターン", "年齢層", "資格", "経験区分",
    "希望雇用形態", "就業状況", "地域", "曜日", "時間帯", "全文",
    "返信", "返信日", "返信カテゴリ",
    "応募", "応募日",
]


def _make_send_rows(member_ids: list[str]) -> list[list[str]]:
    """ヘッダー + 指定member_idの行を返す"""
    rows = [SEND_HEADERS]
    for mid in member_ids:
        row = [""] * len(SEND_HEADERS)
        row[1] = mid  # 会員番号
        rows.append(row)
    return rows


class TestSyncRepliesStatusRouting:
    def test_empty_replies_returns_zero(self, client):
        res = client.post("/api/v1/admin/sync_replies", json={"company": "test", "replies": []})
        assert res.status_code == 200
        data = res.json()
        assert data["scout_reply"]["matched"] == []
        assert data["scout_application"]["matched"] == []
        assert data["direct_application"]["appended"] == 0

    def test_scout_reply_updates_matched_only(self, client):
        with patch("api.routes_admin.sheets_writer") as mock_w, \
             patch("pipeline.orchestrator._send_data_sheet_name", return_value="送信_テスト"):
            mock_w.ensure_sheet_exists = MagicMock()
            mock_w.get_all_rows.return_value = _make_send_rows(["100", "200"])
            mock_w.update_cells_by_name = MagicMock()

            res = client.post("/api/v1/admin/sync_replies", json={
                "company": "test",
                "replies": [
                    {"member_id": "100", "replied_at": "2026-04-01", "category": "興味あり", "status": "scout_reply"},
                    {"member_id": "999", "replied_at": "2026-04-02", "category": "興味あり", "status": "scout_reply"},
                ],
            })
            assert res.status_code == 200
            data = res.json()
            assert data["scout_reply"]["matched"] == [{"member_id": "100"}]
            assert data["scout_reply"]["unmatched"] == [{"member_id": "999"}]
            # 100 は更新されたが 999 は触られてない
            mock_w.update_cells_by_name.assert_called_once()
            args, kwargs = mock_w.update_cells_by_name.call_args
            assert "返信" in args[2]
            assert "応募" not in args[2]  # scout_reply なので応募列は触らない

    def test_scout_application_updates_reply_and_application(self, client):
        with patch("api.routes_admin.sheets_writer") as mock_w, \
             patch("pipeline.orchestrator._send_data_sheet_name", return_value="送信_テスト"):
            mock_w.ensure_sheet_exists = MagicMock()
            mock_w.get_all_rows.return_value = _make_send_rows(["100"])
            mock_w.update_cells_by_name = MagicMock()

            res = client.post("/api/v1/admin/sync_replies", json={
                "company": "test",
                "replies": [
                    {
                        "member_id": "100",
                        "replied_at": "2026-04-01",
                        "applied_at": "2026-04-05",
                        "category": "応募",
                        "status": "scout_application",
                    },
                ],
            })
            assert res.status_code == 200
            data = res.json()
            assert data["scout_application"]["matched"] == [{"member_id": "100"}]
            cells = mock_w.update_cells_by_name.call_args[0][2]
            assert cells["返信"] == "有"
            assert cells["応募"] == "有"
            assert cells["応募日"] == "2026-04-05"

    def test_direct_application_appends_to_separate_sheet(self, client):
        with patch("api.routes_admin.sheets_writer") as mock_w, \
             patch("pipeline.orchestrator._send_data_sheet_name", return_value="送信_テスト"), \
             patch("pipeline.orchestrator._direct_application_sheet_name", return_value="直接応募_テスト"):
            mock_w.ensure_sheet_exists = MagicMock()
            # 直接応募シートは空（ヘッダーのみ）
            mock_w.get_all_rows.return_value = [["応募日", "会員番号", "候補者名", "年齢", "性別", "求人タイトル", "返信カテゴリ"]]
            mock_w.append_row = MagicMock()

            res = client.post("/api/v1/admin/sync_replies", json={
                "company": "test",
                "replies": [
                    {
                        "member_id": "500",
                        "replied_at": "2026-04-10",
                        "applied_at": "2026-04-10",
                        "category": "直接応募",
                        "status": "direct_application",
                        "candidate_name": "テスト太郎",
                        "candidate_age": "30歳",
                        "candidate_gender": "男性",
                        "job_title": "テスト求人",
                    },
                ],
            })
            assert res.status_code == 200
            data = res.json()
            assert data["direct_application"]["appended"] == 1
            mock_w.append_row.assert_called_once()
            args = mock_w.append_row.call_args[0]
            assert args[0] == "直接応募_テスト"
            # 会員番号が2番目
            assert args[1][1] == "500"
            assert args[1][2] == "テスト太郎"

    def test_direct_application_dedup(self, client):
        with patch("api.routes_admin.sheets_writer") as mock_w, \
             patch("pipeline.orchestrator._send_data_sheet_name", return_value="送信_テスト"), \
             patch("pipeline.orchestrator._direct_application_sheet_name", return_value="直接応募_テスト"):
            mock_w.ensure_sheet_exists = MagicMock()
            # 既に member_id=500 が登録済み
            mock_w.get_all_rows.return_value = [
                ["応募日", "会員番号", "候補者名", "年齢", "性別", "求人タイトル", "返信カテゴリ"],
                ["2026-04-01", "500", "既存", "", "", "", ""],
            ]
            mock_w.append_row = MagicMock()

            res = client.post("/api/v1/admin/sync_replies", json={
                "company": "test",
                "replies": [
                    {
                        "member_id": "500",
                        "replied_at": "2026-04-10",
                        "category": "直接応募",
                        "status": "direct_application",
                    },
                ],
            })
            assert res.status_code == 200
            assert res.json()["direct_application"]["appended"] == 0
            mock_w.append_row.assert_not_called()

    def test_legacy_request_without_status_is_scout_reply(self, client):
        """status無しリクエスト（旧クライアント）は scout_reply 扱いになる"""
        with patch("api.routes_admin.sheets_writer") as mock_w, \
             patch("pipeline.orchestrator._send_data_sheet_name", return_value="送信_テスト"):
            mock_w.ensure_sheet_exists = MagicMock()
            mock_w.get_all_rows.return_value = _make_send_rows(["100"])
            mock_w.update_cells_by_name = MagicMock()

            res = client.post("/api/v1/admin/sync_replies", json={
                "company": "test",
                "replies": [
                    {"member_id": "100", "replied_at": "2026-04-01", "category": "興味あり"},
                ],
            })
            assert res.status_code == 200
            data = res.json()
            assert data["scout_reply"]["matched"] == [{"member_id": "100"}]
            assert data["scout_application"]["matched"] == []


UNMATCHED_HEADERS = [
    "返信日", "会員番号", "返信カテゴリ", "ステータス",
    "応募日", "候補者名", "年齢", "性別", "求人タイトル", "取り込み日時",
]


class TestSyncRepliesUnmatchedLogging:
    """unmatched 時に未紐付けログシートへ append される挙動の検証。"""

    def _patch_sheet_names(self):
        return [
            patch("pipeline.orchestrator._send_data_sheet_name", return_value="送信_テスト"),
            patch("pipeline.orchestrator._unmatched_reply_sheet_name", return_value="未紐付け返信_テスト"),
        ]

    def test_scout_reply_unmatched_appends_to_unmatched_sheet(self, client):
        """会員番号が send_data に無い scout_reply が未紐付けシートに記録される。"""
        with patch("api.routes_admin.sheets_writer") as mock_w, \
             patch("pipeline.orchestrator._send_data_sheet_name", return_value="送信_テスト"), \
             patch("pipeline.orchestrator._unmatched_reply_sheet_name", return_value="未紐付け返信_テスト"):
            mock_w.ensure_sheet_exists = MagicMock()
            # 1回目: send_data（"100"のみ）, 2回目: 未紐付けシート（空）
            # 呼び出し順: 1) unmatched sheet, 2) send_data sheet
            mock_w.get_all_rows.side_effect = [
                [UNMATCHED_HEADERS],
                _make_send_rows(["100"]),
            ]
            mock_w.update_cells_by_name = MagicMock()
            mock_w.append_row = MagicMock()

            res = client.post("/api/v1/admin/sync_replies", json={
                "company": "test",
                "replies": [
                    {"member_id": "999", "replied_at": "2026-04-02", "category": "興味あり",
                     "status": "scout_reply", "candidate_name": "未紐付太郎",
                     "candidate_age": "30歳", "candidate_gender": "男性",
                     "job_title": "テスト求人"},
                ],
            })
            assert res.status_code == 200
            data = res.json()
            assert data["scout_reply"]["unmatched"] == [{"member_id": "999"}]
            # 未紐付けシートに append された
            mock_w.append_row.assert_called_once()
            args = mock_w.append_row.call_args[0]
            assert args[0] == "未紐付け返信_テスト"
            row = args[1]
            assert row[0] == "2026-04-02"          # 返信日
            assert row[1] == "999"                  # 会員番号
            assert row[2] == "興味あり"             # カテゴリ
            assert row[3] == "scout_reply"          # ステータス
            assert row[4] == ""                     # 応募日（scout_reply なので空）
            assert row[5] == "未紐付太郎"           # 候補者名
            assert row[6] == "30歳"
            assert row[7] == "男性"
            assert row[8] == "テスト求人"

    def test_scout_application_unmatched_records_applied_at(self, client):
        """scout_application の未紐付けは応募日を含めて記録する。"""
        with patch("api.routes_admin.sheets_writer") as mock_w, \
             patch("pipeline.orchestrator._send_data_sheet_name", return_value="送信_テスト"), \
             patch("pipeline.orchestrator._unmatched_reply_sheet_name", return_value="未紐付け返信_テスト"):
            mock_w.ensure_sheet_exists = MagicMock()
            # 呼び出し順: 1) unmatched sheet, 2) send_data sheet
            mock_w.get_all_rows.side_effect = [
                [UNMATCHED_HEADERS],                # 未紐付けシート空
                _make_send_rows([]),                # send_data 空
            ]
            mock_w.append_row = MagicMock()

            res = client.post("/api/v1/admin/sync_replies", json={
                "company": "test",
                "replies": [
                    {"member_id": "777", "replied_at": "2026-04-01",
                     "applied_at": "2026-04-05", "category": "応募",
                     "status": "scout_application"},
                ],
            })
            assert res.status_code == 200
            assert res.json()["scout_application"]["unmatched"] == [{"member_id": "777"}]
            mock_w.append_row.assert_called_once()
            row = mock_w.append_row.call_args[0][1]
            assert row[3] == "scout_application"
            assert row[4] == "2026-04-05"           # 応募日

    def test_unmatched_dedup_by_member_and_replied_at(self, client):
        """同一(会員番号, 返信日)が既に未紐付けシートにあれば append しない。"""
        with patch("api.routes_admin.sheets_writer") as mock_w, \
             patch("pipeline.orchestrator._send_data_sheet_name", return_value="送信_テスト"), \
             patch("pipeline.orchestrator._unmatched_reply_sheet_name", return_value="未紐付け返信_テスト"):
            mock_w.ensure_sheet_exists = MagicMock()
            existing_unmatched = [
                UNMATCHED_HEADERS,
                ["2026-04-02", "999", "興味あり", "scout_reply", "", "既存", "", "", "", "2026-04-03 00:00:00"],
            ]
            # 呼び出し順: 1) unmatched sheet, 2) send_data sheet
            mock_w.get_all_rows.side_effect = [
                existing_unmatched,
                _make_send_rows(["100"]),
            ]
            mock_w.append_row = MagicMock()

            res = client.post("/api/v1/admin/sync_replies", json={
                "company": "test",
                "replies": [
                    {"member_id": "999", "replied_at": "2026-04-02", "category": "興味あり",
                     "status": "scout_reply"},
                ],
            })
            assert res.status_code == 200
            # unmatched に上がるが、シートには append されない（重複）
            assert res.json()["scout_reply"]["unmatched"] == [{"member_id": "999"}]
            mock_w.append_row.assert_not_called()

    def test_matched_does_not_log_to_unmatched(self, client):
        """matched したものは未紐付けシートに append されない。"""
        with patch("api.routes_admin.sheets_writer") as mock_w, \
             patch("pipeline.orchestrator._send_data_sheet_name", return_value="送信_テスト"), \
             patch("pipeline.orchestrator._unmatched_reply_sheet_name", return_value="未紐付け返信_テスト"):
            mock_w.ensure_sheet_exists = MagicMock()
            # 呼び出し順: 1) unmatched sheet, 2) send_data sheet
            mock_w.get_all_rows.side_effect = [
                [UNMATCHED_HEADERS],
                _make_send_rows(["100"]),
            ]
            mock_w.update_cells_by_name = MagicMock()
            mock_w.append_row = MagicMock()

            res = client.post("/api/v1/admin/sync_replies", json={
                "company": "test",
                "replies": [
                    {"member_id": "100", "replied_at": "2026-04-01", "category": "興味あり",
                     "status": "scout_reply"},
                ],
            })
            assert res.status_code == 200
            assert res.json()["scout_reply"]["matched"] == [{"member_id": "100"}]
            mock_w.append_row.assert_not_called()
