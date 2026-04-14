"""Tests for the customer-facing report export endpoints."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

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
    "全文",
    "返信", "返信日", "返信カテゴリ",
    "応募", "応募日",
]


def _row(replied="", age="30代", area="新宿区", exp="経験浅め", **overrides):
    base = {h: "" for h in SEND_DATA_HEADERS}
    base["日時"] = "2026-04-01T10:00:00"
    base["会員番号"] = "M001"
    base["職種カテゴリ"] = "nurse"
    base["テンプレート種別"] = "パート_初回"
    base["テンプレートVer"] = "3"
    base["生成パス"] = "ai"
    base["パターン"] = "B1"
    base["年齢層"] = age
    base["経験区分"] = exp
    base["希望雇用形態"] = "パート"
    base["就業状況"] = "就業中"
    base["地域"] = area
    base["曜日"] = "水"
    base["時間帯"] = "午前"
    base["返信"] = replied
    base.update(overrides)
    return [base[h] for h in SEND_DATA_HEADERS]


# ---------------------------------------------------------------------------
# POST /api/v1/admin/export_report
# ---------------------------------------------------------------------------

class TestExportReport:
    def test_missing_company_returns_400(self, client):
        res = client.post("/api/v1/admin/export_report", json={})
        assert res.status_code == 400

    def test_cross_company_not_supported(self, client):
        res = client.post("/api/v1/admin/export_report", json={"company": "all"})
        assert res.status_code == 400

    def test_returns_error_when_no_data_in_range(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [SEND_DATA_HEADERS]  # header only
            res = client.post(
                "/api/v1/admin/export_report",
                json={"company": "ark-visiting-nurse", "date_from": "2026-03-01", "date_to": "2026-04-01"},
            )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "error"
        assert "送信データがありません" in body["detail"]

    def test_happy_path_returns_kpi_and_markdown(self, client):
        rows = [
            SEND_DATA_HEADERS,
            _row(replied="有", age="20代", area="新宿区"),
            _row(replied="", age="30代", area="新宿区"),
            _row(replied="有", age="30代", area="渋谷区"),
            _row(replied="", age="40代", area="世田谷区"),
        ]

        fake_narrative = {
            "situation": "今期は4通のスカウトを送信し、2件の返信がございました。返信率は50.0%となっております。",
            "findings": "新宿区と渋谷区の方々から返信をいただいており、23区西部の反応が高めでした。",
            "next_actions": "引き続き23区西部の候補者層への訴求を重点的に進めてまいります。",
        }
        fake_result = MagicMock()
        fake_result.text = json.dumps(fake_narrative, ensure_ascii=False)

        with patch("api.routes_admin.sheets_writer") as mw, \
             patch("pipeline.ai_generator.generate_personalized_text", new=AsyncMock(return_value=fake_result)):
            mw.get_all_rows.return_value = rows
            res = client.post(
                "/api/v1/admin/export_report",
                json={"company": "ark-visiting-nurse", "date_from": "2026-03-01", "date_to": "2026-04-30"},
            )

        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["kpi"]["total"] == 4
        assert body["kpi"]["replied"] == 2
        assert body["kpi"]["reply_rate"] == "50.0%"

        # Customer-facing dimensions should appear; internal ones must not.
        ct = body["cross_tabs"]
        assert "地域" in ct
        assert "年齢層" in ct
        assert "パターン" not in ct
        assert "生成パス" not in ct
        assert "テンプレートVer" not in ct
        assert "曜日" not in ct
        assert "時間帯" not in ct

        # Narrative parsed from JSON response.
        assert body["narrative"]["situation"].startswith("今期は4通")
        assert body["narrative"]["findings"]

        # Markdown should include headers and KPI numbers.
        md = body["markdown"]
        assert "# " in md
        assert "スカウト送信レポート" in md
        assert "送信数: 4通" in md
        assert "返信率: 50.0%" in md
        assert "## 今期の状況" in md
        assert "## 見えてきた傾向" in md
        assert "## 次サイクルの重点" in md

    def test_ai_failure_falls_back_to_kpi_only_markdown(self, client):
        rows = [SEND_DATA_HEADERS, _row(replied="有"), _row(replied="")]

        with patch("api.routes_admin.sheets_writer") as mw, \
             patch("pipeline.ai_generator.generate_personalized_text", new=AsyncMock(side_effect=Exception("gemini down"))):
            mw.get_all_rows.return_value = rows
            res = client.post(
                "/api/v1/admin/export_report",
                json={"company": "ark-visiting-nurse", "date_from": "2026-03-01", "date_to": "2026-04-30"},
            )

        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["ai_error"] == "gemini down"
        # Narrative sections should be absent, but KPI section still renders.
        assert body["narrative"] == {} or all(not v for v in body["narrative"].values())
        assert "送信数: 2通" in body["markdown"]
        assert "## 今期の状況" not in body["markdown"]


# ---------------------------------------------------------------------------
# POST /api/v1/admin/export_report/google_docs
# ---------------------------------------------------------------------------

class TestExportReportGoogleDocs:
    def test_missing_folder_env_returns_500(self, client, monkeypatch):
        monkeypatch.delenv("REPORTS_DRIVE_FOLDER_ID", raising=False)
        res = client.post(
            "/api/v1/admin/export_report/google_docs",
            json={"company": "ark-visiting-nurse", "markdown": "# test"},
        )
        assert res.status_code == 500
        assert "REPORTS_DRIVE_FOLDER_ID" in res.json()["detail"]

    def test_missing_markdown_returns_400(self, client, monkeypatch):
        monkeypatch.setenv("REPORTS_DRIVE_FOLDER_ID", "folder-abc")
        res = client.post(
            "/api/v1/admin/export_report/google_docs",
            json={"company": "ark-visiting-nurse"},
        )
        assert res.status_code == 400

    def test_happy_path_calls_docs_exporter_and_returns_link(self, client, monkeypatch):
        monkeypatch.setenv("REPORTS_DRIVE_FOLDER_ID", "folder-abc")
        fake_file = {
            "id": "doc123",
            "webViewLink": "https://docs.google.com/document/d/doc123/edit",
            "name": "ARK訪問看護_スカウトレポート_2026-03-01_2026-03-31",
        }
        fake_exporter = MagicMock()
        fake_exporter.create_doc_from_markdown.return_value = fake_file

        with patch("db.docs_exporter.docs_exporter", fake_exporter):
            res = client.post(
                "/api/v1/admin/export_report/google_docs",
                json={
                    "company": "ark-visiting-nurse",
                    "markdown": "# ARK訪問看護 スカウト送信レポート\n\n期間: 2026-03-01 〜 2026-03-31\n",
                    "date_from": "2026-03-01",
                    "date_to": "2026-03-31",
                },
            )

        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["doc_id"] == "doc123"
        assert body["web_view_link"].startswith("https://docs.google.com/")
        fake_exporter.create_doc_from_markdown.assert_called_once()
        kwargs = fake_exporter.create_doc_from_markdown.call_args.kwargs
        assert kwargs["parent_folder_id"] == "folder-abc"
        assert "スカウトレポート" in kwargs["title"]
        assert "2026-03-01" in kwargs["title"]
