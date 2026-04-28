"""GET /admin/monthly_stats のテスト

会社別月次集計（ツール送信・紐付け/未紐付け返信・応募・直接応募）を検証。
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
UNMATCHED_HEADERS = [
    "返信日", "会員番号", "返信カテゴリ", "ステータス",
    "応募日", "候補者名", "年齢", "性別", "求人タイトル", "取り込み日時",
]
DIRECT_HEADERS = [
    "応募日", "会員番号", "候補者名", "年齢", "性別", "求人タイトル", "返信カテゴリ",
]


def _send_row(date: str, mid: str, template_type: str = "正社員_初回",
              reply: str = "", reply_date: str = "",
              app_flag: str = "", app_date: str = "") -> list[str]:
    row = [""] * len(SEND_HEADERS)
    row[SEND_HEADERS.index("日時")] = date
    row[SEND_HEADERS.index("会員番号")] = mid
    row[SEND_HEADERS.index("テンプレート種別")] = template_type
    row[SEND_HEADERS.index("返信")] = reply
    row[SEND_HEADERS.index("返信日")] = reply_date
    row[SEND_HEADERS.index("応募")] = app_flag
    row[SEND_HEADERS.index("応募日")] = app_date
    return row


def _patch_sheet_names():
    """3つのシート名解決をすべて固定値にパッチ。"""
    return [
        patch("pipeline.orchestrator._send_data_sheet_name", return_value="送信_テスト"),
        patch("pipeline.orchestrator._unmatched_reply_sheet_name", return_value="未紐付け返信_テスト"),
        patch("pipeline.orchestrator._direct_application_sheet_name", return_value="直接応募_テスト"),
        patch("api.routes_admin._known_company_ids", return_value={"test-co"}),
    ]


class TestMonthlyStats:
    def test_unknown_company_returns_404(self, client):
        with patch("api.routes_admin._known_company_ids", return_value={"other"}):
            res = client.get("/api/v1/admin/monthly_stats/test-co")
            assert res.status_code == 404

    def test_empty_sheets_returns_empty_rows(self, client):
        patches = _patch_sheet_names()
        for p in patches:
            p.start()
        try:
            with patch("api.routes_admin.sheets_writer") as mock_w:
                mock_w.get_all_rows.return_value = []
                res = client.get("/api/v1/admin/monthly_stats/test-co")
                assert res.status_code == 200
                data = res.json()
                assert data["company_id"] == "test-co"
                assert data["rows"] == []
        finally:
            for p in patches:
                p.stop()

    def test_aggregates_tool_send_per_month(self, client):
        patches = _patch_sheet_names()
        for p in patches:
            p.start()
        try:
            with patch("api.routes_admin.sheets_writer") as mock_w:
                # send_data: 3月2件、4月3件
                send_rows = [SEND_HEADERS] + [
                    _send_row("2026-03-15 10:00:00", "100"),
                    _send_row("2026-03-20 10:00:00", "101", template_type="パート_初回"),
                    _send_row("2026-04-01 10:00:00", "200"),
                    _send_row("2026-04-10 10:00:00", "201"),
                    _send_row("2026-04-15 10:00:00", "202", template_type="正社員_再送"),  # 再送はカウント外
                ]
                mock_w.get_all_rows.side_effect = [send_rows, [UNMATCHED_HEADERS], [DIRECT_HEADERS]]

                res = client.get("/api/v1/admin/monthly_stats/test-co")
                assert res.status_code == 200
                rows = res.json()["rows"]
                by_ym = {r["year_month"]: r for r in rows}
                assert by_ym["2026-03"]["scout_send_tool"] == 2
                assert by_ym["2026-04"]["scout_send_tool"] == 2  # 再送は除外
        finally:
            for p in patches:
                p.stop()

    def test_aggregates_matched_replies_and_applications(self, client):
        patches = _patch_sheet_names()
        for p in patches:
            p.start()
        try:
            with patch("api.routes_admin.sheets_writer") as mock_w:
                # 送信4件、返信2件 (1つは応募までいった), 4月帰属
                send_rows = [SEND_HEADERS] + [
                    _send_row("2026-04-01", "100", reply="有", reply_date="2026-04-05"),
                    _send_row("2026-04-02", "101", reply="有", reply_date="2026-04-08",
                              app_flag="有", app_date="2026-04-09"),
                    _send_row("2026-04-03", "102"),
                    _send_row("2026-04-04", "103"),
                ]
                mock_w.get_all_rows.side_effect = [send_rows, [UNMATCHED_HEADERS], [DIRECT_HEADERS]]

                res = client.get("/api/v1/admin/monthly_stats/test-co")
                row = res.json()["rows"][0]
                assert row["year_month"] == "2026-04"
                assert row["scout_send_tool"] == 4
                assert row["scout_reply_matched"] == 1     # 応募なし返信
                assert row["scout_application_matched"] == 1  # 応募ありはこっち
        finally:
            for p in patches:
                p.stop()

    def test_aggregates_unmatched_replies(self, client):
        patches = _patch_sheet_names()
        for p in patches:
            p.start()
        try:
            with patch("api.routes_admin.sheets_writer") as mock_w:
                unmatched_rows = [UNMATCHED_HEADERS] + [
                    ["2026-04-05", "999", "興味あり", "scout_reply", "", "A", "", "", "", "ts"],
                    ["2026-04-06", "888", "応募", "scout_application", "2026-04-06", "B", "", "", "", "ts"],
                    ["2026-03-10", "777", "興味あり", "scout_reply", "", "C", "", "", "", "ts"],
                ]
                mock_w.get_all_rows.side_effect = [
                    [SEND_HEADERS], unmatched_rows, [DIRECT_HEADERS],
                ]

                res = client.get("/api/v1/admin/monthly_stats/test-co")
                rows = {r["year_month"]: r for r in res.json()["rows"]}
                assert rows["2026-04"]["scout_reply_unmatched"] == 1
                assert rows["2026-04"]["scout_application_unmatched"] == 1
                assert rows["2026-03"]["scout_reply_unmatched"] == 1
        finally:
            for p in patches:
                p.stop()

    def test_aggregates_direct_applications(self, client):
        patches = _patch_sheet_names()
        for p in patches:
            p.start()
        try:
            with patch("api.routes_admin.sheets_writer") as mock_w:
                direct_rows = [DIRECT_HEADERS] + [
                    ["2026-04-10", "500", "直応募太郎", "30歳", "男性", "求人A", "直接応募"],
                    ["2026-04-15", "501", "B", "", "", "", ""],
                    ["2026-03-20", "502", "C", "", "", "", ""],
                ]
                mock_w.get_all_rows.side_effect = [
                    [SEND_HEADERS], [UNMATCHED_HEADERS], direct_rows,
                ]

                res = client.get("/api/v1/admin/monthly_stats/test-co")
                rows = {r["year_month"]: r for r in res.json()["rows"]}
                assert rows["2026-04"]["direct_application"] == 2
                assert rows["2026-03"]["direct_application"] == 1
        finally:
            for p in patches:
                p.stop()

    def test_reply_rate_calculation(self, client):
        patches = _patch_sheet_names()
        for p in patches:
            p.start()
        try:
            with patch("api.routes_admin.sheets_writer") as mock_w:
                # 送信10件、紐付け返信2件、未紐付け返信3件 → 5/10 = 0.5
                send_rows = [SEND_HEADERS]
                for i in range(10):
                    reply = "有" if i < 2 else ""
                    rd = "2026-04-05" if i < 2 else ""
                    send_rows.append(_send_row(f"2026-04-{i+1:02d}", str(100+i),
                                               reply=reply, reply_date=rd))
                unmatched_rows = [UNMATCHED_HEADERS] + [
                    ["2026-04-05", str(900+i), "興味あり", "scout_reply", "", "", "", "", "", "ts"]
                    for i in range(3)
                ]
                mock_w.get_all_rows.side_effect = [
                    send_rows, unmatched_rows, [DIRECT_HEADERS],
                ]

                res = client.get("/api/v1/admin/monthly_stats/test-co")
                row = res.json()["rows"][0]
                assert row["scout_send_total"] == 10
                assert row["scout_reply_total"] == 5
                assert row["reply_rate"] == 0.5
        finally:
            for p in patches:
                p.stop()

    def test_date_range_filter(self, client):
        patches = _patch_sheet_names()
        for p in patches:
            p.start()
        try:
            with patch("api.routes_admin.sheets_writer") as mock_w:
                send_rows = [SEND_HEADERS] + [
                    _send_row("2026-02-15", "100"),
                    _send_row("2026-03-15", "101"),
                    _send_row("2026-04-15", "102"),
                    _send_row("2026-05-15", "103"),
                ]
                mock_w.get_all_rows.side_effect = [
                    send_rows, [UNMATCHED_HEADERS], [DIRECT_HEADERS],
                ]

                res = client.get("/api/v1/admin/monthly_stats/test-co?from=2026-03&to=2026-04")
                rows = res.json()["rows"]
                yms = sorted(r["year_month"] for r in rows)
                assert yms == ["2026-03", "2026-04"]
        finally:
            for p in patches:
                p.stop()

    def test_manual_send_stays_zero_in_phase1(self, client):
        """Phase 1 では scout_send_manual は常に 0 を返す（Phase 2 で実装予定）。"""
        patches = _patch_sheet_names()
        for p in patches:
            p.start()
        try:
            with patch("api.routes_admin.sheets_writer") as mock_w:
                send_rows = [SEND_HEADERS, _send_row("2026-04-01", "100")]
                mock_w.get_all_rows.side_effect = [
                    send_rows, [UNMATCHED_HEADERS], [DIRECT_HEADERS],
                ]
                res = client.get("/api/v1/admin/monthly_stats/test-co")
                assert res.json()["rows"][0]["scout_send_manual"] == 0
        finally:
            for p in patches:
                p.stop()
