"""Tests for template history view + revert endpoints.

Covers:
1. GET /admin/templates/{row_index}/history returns current + history rows
   filtered by company/job_category/type
2. Unrelated history rows are filtered out
3. POST /admin/templates/{row_index}/revert restores the old_body for the
   target version as a NEW version (history-preserving)
4. Revert to non-existent version → 404
5. Reverting repeatedly picks the most recent matching history entry
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from auth.api_key import verify_api_key
from main import app

from tests.test_template_version_bump import FakeSheets, TEMPLATE_HEADERS, _install


def _fake_operator():
    return {"operator_id": "test", "name": "tester", "role": "admin"}


@pytest.fixture
def client():
    app.dependency_overrides[verify_api_key] = _fake_operator
    yield TestClient(app)
    app.dependency_overrides.pop(verify_api_key, None)


HISTORY_HEADERS = [
    "timestamp", "company", "job_category", "type",
    "old_version", "new_version", "reason", "old_body",
]


class TestGetTemplateHistory:
    def test_returns_current_and_filtered_history(self, client, monkeypatch):
        fake = FakeSheets({
            "テンプレート": [
                TEMPLATE_HEADERS,
                ["ark", "nurse", "パート_初回", "現在の本文", "3"],
                ["lcc", "nurse", "パート_初回", "別会社", "1"],
            ],
            "テンプレート変更履歴": [
                HISTORY_HEADERS,
                ["2026-04-10 10:00", "ark", "nurse", "パート_初回",
                 "1", "2", "初回改善", "v1の本文"],
                ["2026-04-12 15:00", "ark", "nurse", "パート_初回",
                 "2", "3", "二回目", "v2の本文"],
                # 別会社の履歴は除外されるべき
                ["2026-04-11 12:00", "lcc", "nurse", "パート_初回",
                 "1", "2", "別会社の変更", "lcc v1本文"],
            ],
        })
        _install(monkeypatch, fake)

        res = client.get("/api/v1/admin/templates/2/history")
        assert res.status_code == 200
        data = res.json()
        assert data["current"]["version"] == "3"
        assert data["current"]["body"] == "現在の本文"
        assert len(data["history"]) == 2
        # 新しい順
        assert data["history"][0]["old_version"] == "2"
        assert data["history"][1]["old_version"] == "1"
        # 別会社は含まれない
        companies = {h["company"] for h in data["history"]}
        assert companies == {"ark"}

    def test_decodes_literal_newlines(self, client, monkeypatch):
        fake = FakeSheets({
            "テンプレート": [
                TEMPLATE_HEADERS,
                ["ark", "nurse", "パート_初回", "行1\\n行2", "2"],
            ],
            "テンプレート変更履歴": [
                HISTORY_HEADERS,
                ["2026-04-10 10:00", "ark", "nurse", "パート_初回",
                 "1", "2", "初版から", "旧1\\n旧2"],
            ],
        })
        _install(monkeypatch, fake)

        res = client.get("/api/v1/admin/templates/2/history")
        assert res.status_code == 200
        data = res.json()
        assert data["current"]["body"] == "行1\n行2"
        assert data["history"][0]["old_body"] == "旧1\n旧2"

    def test_empty_history(self, client, monkeypatch):
        fake = FakeSheets({
            "テンプレート": [
                TEMPLATE_HEADERS,
                ["ark", "nurse", "パート_初回", "本文", "1"],
            ],
        })
        _install(monkeypatch, fake)

        res = client.get("/api/v1/admin/templates/2/history")
        assert res.status_code == 200
        assert res.json()["history"] == []


class TestRevertTemplate:
    def test_revert_creates_new_version_with_old_body(self, client, monkeypatch):
        fake = FakeSheets({
            "テンプレート": [
                TEMPLATE_HEADERS,
                ["ark", "nurse", "パート_初回", "v3の本文（現在）", "3"],
            ],
            "テンプレート変更履歴": [
                HISTORY_HEADERS,
                ["2026-04-10 10:00", "ark", "nurse", "パート_初回",
                 "1", "2", "一回目", "v1の本文"],
                ["2026-04-12 15:00", "ark", "nurse", "パート_初回",
                 "2", "3", "二回目", "v2の本文"],
            ],
        })
        _install(monkeypatch, fake)

        res = client.post(
            "/api/v1/admin/templates/2/revert",
            json={"target_version": "1", "reason": "元に戻したい"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["restored_from"] == "1"
        assert body["new_version"] == "4"
        # 実際にテンプレートが更新されている
        assert fake.data["テンプレート"][1][3] == "v1の本文"
        assert fake.data["テンプレート"][1][4] == "4"
        # 履歴にrevertの記録も追加されている（v3→v4）
        hist = fake.data["テンプレート変更履歴"]
        assert len(hist) == 4  # header + 2 original + 1 revert log
        revert_row = hist[-1]
        assert revert_row[4] == "3"  # old_version (revert前のcurrent)
        assert revert_row[5] == "4"  # new_version
        assert "v1に復元" in revert_row[6]
        assert "元に戻したい" in revert_row[6]

    def test_revert_without_reason_uses_default(self, client, monkeypatch):
        fake = FakeSheets({
            "テンプレート": [
                TEMPLATE_HEADERS,
                ["ark", "nurse", "パート_初回", "現在", "2"],
            ],
            "テンプレート変更履歴": [
                HISTORY_HEADERS,
                ["2026-04-10 10:00", "ark", "nurse", "パート_初回",
                 "1", "2", "初回変更", "v1本文"],
            ],
        })
        _install(monkeypatch, fake)

        res = client.post(
            "/api/v1/admin/templates/2/revert",
            json={"target_version": "1"},
        )
        assert res.status_code == 200
        hist = fake.data["テンプレート変更履歴"]
        revert_reason = hist[-1][6]
        assert revert_reason == "v1に復元"

    def test_revert_target_not_found(self, client, monkeypatch):
        fake = FakeSheets({
            "テンプレート": [
                TEMPLATE_HEADERS,
                ["ark", "nurse", "パート_初回", "現在", "2"],
            ],
            "テンプレート変更履歴": [
                HISTORY_HEADERS,
                ["2026-04-10 10:00", "ark", "nurse", "パート_初回",
                 "1", "2", "初回", "v1本文"],
            ],
        })
        _install(monkeypatch, fake)

        res = client.post(
            "/api/v1/admin/templates/2/revert",
            json={"target_version": "99"},
        )
        assert res.status_code == 404

    def test_revert_missing_target_version(self, client, monkeypatch):
        fake = FakeSheets({
            "テンプレート": [
                TEMPLATE_HEADERS,
                ["ark", "nurse", "パート_初回", "本文", "1"],
            ],
        })
        _install(monkeypatch, fake)

        res = client.post("/api/v1/admin/templates/2/revert", json={})
        assert res.status_code == 400

    def test_revert_picks_most_recent_match_for_duplicate_version(
        self, client, monkeypatch
    ):
        """Same old_version may appear twice if user reverts then edits back.
        The revert endpoint should pick the MOST RECENT matching entry so the
        restored body reflects the latest snapshot the user saw as vN."""
        fake = FakeSheets({
            "テンプレート": [
                TEMPLATE_HEADERS,
                ["ark", "nurse", "パート_初回", "現在v5", "5"],
            ],
            "テンプレート変更履歴": [
                HISTORY_HEADERS,
                ["2026-04-10 10:00", "ark", "nurse", "パート_初回",
                 "2", "3", "初回", "古いv2"],
                ["2026-04-12 15:00", "ark", "nurse", "パート_初回",
                 "2", "4", "revert後にまたv2になった", "新しいv2"],
            ],
        })
        _install(monkeypatch, fake)

        res = client.post(
            "/api/v1/admin/templates/2/revert",
            json={"target_version": "2"},
        )
        assert res.status_code == 200
        assert fake.data["テンプレート"][1][3] == "新しいv2"
