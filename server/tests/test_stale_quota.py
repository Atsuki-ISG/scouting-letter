"""Tests for the stale quota company detection (Phase D)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from api._dashboard_helpers import find_stale_quota_companies, JST


def _hours_ago(hours: float) -> str:
    return (datetime.now(JST) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def test_returns_empty_when_no_companies():
    with patch("api._dashboard_helpers.list_companies", return_value=[]):
        result = find_stale_quota_companies(max_hours=24)
    assert result == []


def test_returns_company_with_stale_snapshot():
    with patch("api._dashboard_helpers.list_companies", return_value=[
        ("ark-visiting-nurse", "アーク訪看"),
    ]), patch("api._dashboard_helpers.load_quota_snapshots", return_value={
        "ark-visiting-nurse": {
            "remaining": 50,
            "snapshot_at": _hours_ago(48),
            "quota_hint": 200,
        },
    }):
        result = find_stale_quota_companies(max_hours=24)
    assert len(result) == 1
    assert result[0]["company_id"] == "ark-visiting-nurse"
    assert result[0]["company_name"] == "アーク訪看"
    assert result[0]["hours_since_update"] >= 48


def test_excludes_fresh_snapshot():
    with patch("api._dashboard_helpers.list_companies", return_value=[
        ("ark-visiting-nurse", "アーク訪看"),
    ]), patch("api._dashboard_helpers.load_quota_snapshots", return_value={
        "ark-visiting-nurse": {
            "remaining": 50,
            "snapshot_at": _hours_ago(2),
            "quota_hint": 200,
        },
    }):
        result = find_stale_quota_companies(max_hours=24)
    assert result == []


def test_includes_company_with_no_snapshot():
    """会社は登録されているがそもそも残数が一度も投稿されていない場合も stale 扱い。"""
    with patch("api._dashboard_helpers.list_companies", return_value=[
        ("ark-visiting-nurse", "アーク訪看"),
    ]), patch("api._dashboard_helpers.load_quota_snapshots", return_value={}):
        result = find_stale_quota_companies(max_hours=24)
    assert len(result) == 1
    assert result[0]["company_id"] == "ark-visiting-nurse"
    assert result[0]["hours_since_update"] is None


def test_returns_only_stale_companies_when_mixed():
    with patch("api._dashboard_helpers.list_companies", return_value=[
        ("ark-visiting-nurse", "アーク訪看"),
        ("lcc-visiting-nurse", "LCC訪看"),
        ("ichigo-visiting-nurse", "いちご訪看"),
    ]), patch("api._dashboard_helpers.load_quota_snapshots", return_value={
        "ark-visiting-nurse": {
            "remaining": 50,
            "snapshot_at": _hours_ago(2),  # fresh
            "quota_hint": 200,
        },
        "lcc-visiting-nurse": {
            "remaining": 30,
            "snapshot_at": _hours_ago(72),  # stale
            "quota_hint": 150,
        },
        # ichigo has no snapshot at all → stale
    }):
        result = find_stale_quota_companies(max_hours=24)
    company_ids = [r["company_id"] for r in result]
    assert "lcc-visiting-nurse" in company_ids
    assert "ichigo-visiting-nurse" in company_ids
    assert "ark-visiting-nurse" not in company_ids
