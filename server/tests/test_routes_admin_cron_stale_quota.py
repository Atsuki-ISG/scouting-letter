"""Tests for Cloud Scheduler daily quota status notification endpoint.

送信通数管理 Phase D-2:
- Cloud Scheduler が毎朝 9:00 JST に POST /api/v1/admin/cron/stale-quota を叩く
- 全会社の残数を Google Chat に通知（朝の状況把握も兼ねる）
- 24h 以上未更新の会社は ⚠️ プレフィックスで強調
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from auth.api_key import verify_api_key
from main import app


JST = timezone(timedelta(hours=9))


def _fake_operator():
    return {"operator_id": "scheduler", "name": "CloudScheduler", "role": "admin"}


@pytest.fixture
def client():
    app.dependency_overrides[verify_api_key] = _fake_operator
    yield TestClient(app)
    app.dependency_overrides.pop(verify_api_key, None)


def _hours_ago_iso(hours: float) -> str:
    return (datetime.now(JST) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def _stale_item(company_id, company_name, hours, remaining=None, snapshot_at=None):
    return {
        "company_id": company_id,
        "company_name": company_name,
        "snapshot_at": snapshot_at,
        "hours_since_update": hours,
        "remaining": remaining,
    }


class TestCronStaleQuota:
    @pytest.fixture
    def mock_status(self):
        """list_companies + load_quota_snapshots を 3社モック化。"""
        companies = [
            ("ark-visiting-nurse", "ARK訪問看護"),
            ("lcc-visiting-nurse", "LCC訪問看護"),
            ("new-co", "新規会社"),
        ]
        snapshots = {
            "ark-visiting-nurse": {
                "remaining": 128,
                "snapshot_at": _hours_ago_iso(2),  # fresh
                "quota_hint": 200,
            },
            "lcc-visiting-nurse": {
                "remaining": 45,
                "snapshot_at": _hours_ago_iso(48),  # stale
                "quota_hint": 100,
            },
            # new-co: snapshot 一度も投稿無し → stale
        }
        with patch("api.routes_admin.dh_list_companies", return_value=companies), \
             patch("api.routes_admin.dh_load_quota_snapshots", return_value=snapshots):
            yield {"companies": companies, "snapshots": snapshots}

    def test_always_sends_notification(self, client, mock_status):
        """全社最新でも残数把握のため毎日送る。"""
        with patch("api.routes_admin.find_stale_quota_companies", return_value=[]), \
             patch("api.routes_admin.notify_google_chat", new_callable=AsyncMock,
                   return_value=True) as mock_notify:
            res = client.post("/api/v1/admin/cron/stale-quota")
        assert res.status_code == 200
        body = res.json()
        assert body["sent"] is True
        mock_notify.assert_awaited_once()

    def test_message_lists_all_companies_with_remaining(self, client, mock_status):
        with patch("api.routes_admin.find_stale_quota_companies", return_value=[]), \
             patch("api.routes_admin.notify_google_chat", new_callable=AsyncMock,
                   return_value=True) as mock_notify:
            client.post("/api/v1/admin/cron/stale-quota")
        msg = mock_notify.await_args[0][0]
        # 全会社名が含まれる
        assert "ARK訪問看護" in msg
        assert "LCC訪問看護" in msg
        assert "新規会社" in msg
        # 残数も表示される
        assert "残 128" in msg
        assert "残 45" in msg

    def test_stale_companies_get_warning_prefix(self, client, mock_status):
        with patch("api.routes_admin.find_stale_quota_companies", return_value=[]), \
             patch("api.routes_admin.notify_google_chat", new_callable=AsyncMock,
                   return_value=True) as mock_notify:
            client.post("/api/v1/admin/cron/stale-quota")
        msg = mock_notify.await_args[0][0]
        # stale な会社（48h前 + 未取得）行に ⚠️
        for line in msg.split("\n"):
            if "ARK訪問看護" in line:
                assert "⚠️" not in line, "fresh は ⚠️ なし"
            if "LCC訪問看護" in line:
                assert "⚠️" in line, "48h前は ⚠️ あり"
            if "新規会社" in line:
                assert "⚠️" in line, "未取得は ⚠️ あり"
                assert "未取得" in line

    def test_message_includes_threshold_explanation_when_stale(self, client, mock_status):
        with patch("api.routes_admin.find_stale_quota_companies", return_value=[]), \
             patch("api.routes_admin.notify_google_chat", new_callable=AsyncMock,
                   return_value=True) as mock_notify:
            client.post("/api/v1/admin/cron/stale-quota")
        msg = mock_notify.await_args[0][0]
        # フッターで「⚠️ のついたものは ... 時間以上前」と説明
        assert "⚠️" in msg
        assert "24" in msg
        assert "時間以上前" in msg

    def test_message_says_all_fresh_when_none_stale(self, client):
        """全社最新なら ⚠️ なしで「全社最新です」と表示。"""
        companies = [("ark", "ARK")]
        snapshots = {"ark": {"remaining": 100, "snapshot_at": _hours_ago_iso(1)}}
        with patch("api.routes_admin.dh_list_companies", return_value=companies), \
             patch("api.routes_admin.dh_load_quota_snapshots", return_value=snapshots), \
             patch("api.routes_admin.find_stale_quota_companies", return_value=[]), \
             patch("api.routes_admin.notify_google_chat", new_callable=AsyncMock,
                   return_value=True) as mock_notify:
            client.post("/api/v1/admin/cron/stale-quota")
        msg = mock_notify.await_args[0][0]
        assert "⚠️" not in msg
        assert "全社最新" in msg

    def test_response_includes_stale_count(self, client, mock_status):
        items = [_stale_item("lcc-visiting-nurse", "LCC訪問看護", 48.0, remaining=45)]
        with patch("api.routes_admin.find_stale_quota_companies", return_value=items), \
             patch("api.routes_admin.notify_google_chat", new_callable=AsyncMock,
                   return_value=True):
            res = client.post("/api/v1/admin/cron/stale-quota")
        assert res.json()["stale_count"] == 1

    def test_custom_max_hours_query_param(self, client, mock_status):
        captured = {}
        def fake_find(max_hours):
            captured["max_hours"] = max_hours
            return []
        with patch("api.routes_admin.find_stale_quota_companies", side_effect=fake_find), \
             patch("api.routes_admin.notify_google_chat", new_callable=AsyncMock,
                   return_value=True):
            res = client.post("/api/v1/admin/cron/stale-quota?max_hours=48")
        assert res.status_code == 200
        assert captured["max_hours"] == 48

    def test_endpoint_requires_auth(self):
        c = TestClient(app)
        res = c.post("/api/v1/admin/cron/stale-quota")
        assert res.status_code in (401, 403)
