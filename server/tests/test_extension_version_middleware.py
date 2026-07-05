"""Tests for the extension-version detection middleware in main.py.

拡張が X-Extension-Version を送ってきたとき、旧版をレスポンスヘッダーで
知らせ、ヘッダー未送信（管理画面・curl 等）は判定対象外にすることを確認する。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import main
from main import app

client = TestClient(app)


def test_current_version_not_flagged():
    res = client.get("/health", headers={"X-Extension-Version": main.LATEST_EXTENSION_VERSION})
    assert res.status_code == 200
    assert res.headers.get("X-Extension-Outdated") == "false"
    assert res.headers.get("X-Latest-Extension-Version") == main.LATEST_EXTENSION_VERSION


def test_old_version_flagged_outdated():
    res = client.get("/health", headers={"X-Extension-Version": "0.0.1"})
    assert res.status_code == 200
    assert res.headers.get("X-Extension-Outdated") == "true"
    assert res.headers.get("X-Latest-Extension-Version") == main.LATEST_EXTENSION_VERSION


def test_missing_header_not_evaluated():
    """管理画面・curl 等はバージョンヘッダーを送らない → 判定ヘッダーを付けない。"""
    res = client.get("/health")
    assert res.status_code == 200
    assert "X-Extension-Outdated" not in res.headers


def test_version_parse_handles_garbage():
    assert main._parse_version("1.2.3") == (1, 2, 3)
    assert main._parse_version("1.x.0") == (1, 0, 0)
    assert main._parse_version("") == (0,)
    assert main._parse_version("1.0.0") < main._parse_version("1.1.0")
