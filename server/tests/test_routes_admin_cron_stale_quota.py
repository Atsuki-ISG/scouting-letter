"""Tests for Cloud Scheduler daily stale-quota notification endpoint.

送信通数管理 Phase D-2:
- Cloud Scheduler が毎朝 9:00 JST に POST /api/v1/admin/cron/stale-quota を叩く
- 24h 以上残数スナップショットが未更新の会社を Google Chat に通知
- items が空なら通知はしない（朝のノイズ防止）
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from auth.api_key import verify_api_key
from main import app


def _fake_operator():
    return {"operator_id": "scheduler", "name": "CloudScheduler", "role": "admin"}


@pytest.fixture
def client():
    app.dependency_overrides[verify_api_key] = _fake_operator
    yield TestClient(app)
    app.dependency_overrides.pop(verify_api_key, None)


def _stale_item(company_id, company_name, hours, remaining=None, snapshot_at=None):
    return {
        "company_id": company_id,
        "company_name": company_name,
        "snapshot_at": snapshot_at,
        "hours_since_update": hours,
        "remaining": remaining,
    }


class TestCronStaleQuota:
    def test_no_notification_when_all_fresh(self, client):
        """stale が空なら Chat 通知は送らない。"""
        with patch("api.routes_admin.find_stale_quota_companies", return_value=[]), \
             patch("api.routes_admin.notify_google_chat", new_callable=AsyncMock) as mock_notify:
            res = client.post("/api/v1/admin/cron/stale-quota")
        assert res.status_code == 200
        body = res.json()
        assert body["stale_count"] == 0
        assert body["sent"] is False
        mock_notify.assert_not_awaited()

    def test_notification_sent_when_stale_companies_exist(self, client):
        items = [
            _stale_item("ark-visiting-nurse", "ARK訪問看護", 48.0,
                        remaining=128, snapshot_at="2026-04-13T09:15:00+09:00"),
            _stale_item("lcc-visiting-nurse", "LCC訪問看護", None),
        ]
        with patch("api.routes_admin.find_stale_quota_companies", return_value=items), \
             patch("api.routes_admin.notify_google_chat", new_callable=AsyncMock,
                   return_value=True) as mock_notify:
            res = client.post("/api/v1/admin/cron/stale-quota")
        assert res.status_code == 200
        body = res.json()
        assert body["stale_count"] == 2
        assert body["sent"] is True
        mock_notify.assert_awaited_once()

    def test_message_contains_count_and_warning(self, client):
        """メッセージは件数 + 警告ヘッダのみ（会社名などの詳細は管理画面側で確認）。"""
        items = [
            _stale_item("ark-visiting-nurse", "ARK訪問看護", 48.0,
                        remaining=128, snapshot_at="2026-04-13T09:15:00+09:00"),
            _stale_item("lcc-visiting-nurse", "LCC訪問看護", None),
            _stale_item("new-co", "新規会社", None),
        ]
        with patch("api.routes_admin.find_stale_quota_companies", return_value=items), \
             patch("api.routes_admin.notify_google_chat", new_callable=AsyncMock,
                   return_value=True) as mock_notify:
            client.post("/api/v1/admin/cron/stale-quota")
        msg = mock_notify.await_args[0][0]
        # Warning + count
        assert "⚠️" in msg
        assert "3" in msg  # count
        assert "24" in msg  # 24h threshold
        # Detail-level info intentionally omitted
        assert "ARK訪問看護" not in msg
        assert "新規会社" not in msg

    def test_custom_max_hours_query_param(self, client):
        """`?max_hours=48` で閾値を変更できる。"""
        def fake_find(max_hours):
            assert max_hours == 48
            return []
        with patch("api.routes_admin.find_stale_quota_companies", side_effect=fake_find), \
             patch("api.routes_admin.notify_google_chat", new_callable=AsyncMock):
            res = client.post("/api/v1/admin/cron/stale-quota?max_hours=48")
        assert res.status_code == 200

    def test_endpoint_requires_auth(self):
        """X-API-Key 無しは 401。"""
        c = TestClient(app)
        res = c.post("/api/v1/admin/cron/stale-quota")
        assert res.status_code in (401, 403)
