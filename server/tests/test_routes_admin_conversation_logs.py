"""Tests for POST /api/v1/admin/conversation_logs."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from auth.api_key import verify_api_key
from main import app


def _fake_operator():
    return {"operator_id": "t", "name": "TesterBot", "role": "admin"}


@pytest.fixture
def client():
    app.dependency_overrides[verify_api_key] = _fake_operator
    yield TestClient(app)
    app.dependency_overrides.pop(verify_api_key, None)


CONV_HEADERS = [
    "timestamp", "company", "member_id", "candidate_name",
    "candidate_age", "candidate_gender", "job_title",
    "started", "message_count", "messages_json", "source", "actor",
]


def _thread(member_id="M001", started="2026-04-04"):
    return {
        "member_id": member_id,
        "candidate_name": "平 沙季",
        "candidate_age": "39歳",
        "candidate_gender": "女性",
        "job_title": "訪問看護師 求人",
        "started": started,
        "messages": [
            {"date": started, "role": "company", "text": "はじめまして..."},
            {"date": started, "role": "candidate", "text": "ありがとうございます..."},
        ],
    }


class TestPostConversationLogs:
    def test_appends_new_thread(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [CONV_HEADERS]  # empty
            res = client.post(
                "/api/v1/admin/conversation_logs",
                json={
                    "company": "ichigo-visiting-nurse",
                    "threads": [_thread()],
                    "source": "extension_auto",
                },
            )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["appended"] == 1
        assert body["updated"] == 0

        # append_row was called with the thread row
        mw.ensure_sheet_exists.assert_called_once()
        append_calls = mw.append_row.call_args_list
        conv_calls = [c for c in append_calls if c[0][0] == "会話ログ"]
        assert len(conv_calls) == 1
        row = conv_calls[0][0][1]
        # Columns are in the expected order
        assert row[1] == "ichigo-visiting-nurse"  # company
        assert row[2] == "M001"  # member_id
        assert row[7] == "2026-04-04"  # started
        assert row[8] == "2"  # message_count
        messages = json.loads(row[9])
        assert len(messages) == 2
        assert row[10] == "extension_auto"

    def test_dedup_overwrites_existing(self, client):
        """A second ingestion for the same (company, member_id, started)
        should overwrite (update) the existing row, not duplicate it."""
        existing_row = [
            "2026-04-04 10:00:00",
            "ichigo-visiting-nurse",
            "M001",
            "平 沙季",
            "39歳",
            "女性",
            "訪問看護師 求人",
            "2026-04-04",
            "1",
            json.dumps([{"date": "2026-04-04", "role": "company", "text": "prev"}]),
            "extension_manual",
            "tester",
        ]
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [CONV_HEADERS, existing_row]
            res = client.post(
                "/api/v1/admin/conversation_logs",
                json={
                    "company": "ichigo-visiting-nurse",
                    "threads": [_thread()],
                    "source": "extension_auto",
                },
            )
        body = res.json()
        assert body["appended"] == 0
        assert body["updated"] == 1
        # update_cells_by_name was invoked, not append_row for the conv sheet
        conv_appends = [
            c for c in mw.append_row.call_args_list if c[0][0] == "会話ログ"
        ]
        assert conv_appends == []
        mw.update_cells_by_name.assert_called_once()

    def test_missing_company_400(self, client):
        res = client.post(
            "/api/v1/admin/conversation_logs",
            json={"threads": [_thread()]},
        )
        assert res.status_code == 400

    def test_empty_threads_400(self, client):
        res = client.post(
            "/api/v1/admin/conversation_logs",
            json={"company": "ark", "threads": []},
        )
        assert res.status_code == 400

    def test_skips_thread_without_member_id(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [CONV_HEADERS]
            bad = _thread()
            bad["member_id"] = ""
            res = client.post(
                "/api/v1/admin/conversation_logs",
                json={
                    "company": "ichigo-visiting-nurse",
                    "threads": [bad, _thread(member_id="M002")],
                },
            )
        body = res.json()
        assert body["appended"] == 1
