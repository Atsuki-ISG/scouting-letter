"""Tests for the Phase 3 職種解決失敗 aggregation + keyword append endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from auth.api_key import verify_api_key
from main import app


def _fake_operator():
    return {"operator_id": "test", "name": "DirectorBot", "role": "admin"}


@pytest.fixture
def client():
    app.dependency_overrides[verify_api_key] = _fake_operator
    yield TestClient(app)
    app.dependency_overrides.pop(verify_api_key, None)


LOG_HEADERS = [
    "timestamp", "company", "member_id", "job_category", "template_type",
    "generation_path", "pattern_type", "status", "detail", "personalized_text_preview",
    "prompt_tokens", "output_tokens", "estimated_cost",
    "failure_stage", "failure_missing_fields", "failure_searched_text",
    "failure_company_categories", "failure_human_message",
]


def _log_row(
    *,
    company="ark",
    member_id="M001",
    generation_path="filtered_out",
    failure_stage="keyword",
    failure_missing_fields="work_history_summary",
    failure_searched_text="[desired] 看護師 訪問看護 | [experience] 病棟5年",
    failure_company_categories="nurse,rehab_pt",
    failure_human_message="候補者の希望職種から職種を特定できませんでした",
    timestamp=None,
):
    ts = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
    base = {h: "" for h in LOG_HEADERS}
    base.update({
        "timestamp": ts,
        "company": company,
        "member_id": member_id,
        "generation_path": generation_path,
        "failure_stage": failure_stage,
        "failure_missing_fields": failure_missing_fields,
        "failure_searched_text": failure_searched_text,
        "failure_company_categories": failure_company_categories,
        "failure_human_message": failure_human_message,
    })
    return [base[h] for h in LOG_HEADERS]


# ---------------------------------------------------------------------------
# GET /api/v1/admin/job_category_failures
# ---------------------------------------------------------------------------

class TestJobCategoryFailures:
    def test_groups_by_company_stage_and_categories(self, client):
        rows = [
            LOG_HEADERS,
            _log_row(company="ark", member_id="M001"),
            _log_row(company="ark", member_id="M002"),
            _log_row(company="lcc", member_id="M003"),
            _log_row(company="ark", member_id="M004",
                     failure_stage="explicit",
                     failure_company_categories="nurse"),
            # Non-failure row should be ignored
            _log_row(company="ark", member_id="M005",
                     generation_path="ai", failure_stage=""),
        ]
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = rows
            res = client.get("/api/v1/admin/job_category_failures")
        assert res.status_code == 200
        body = res.json()
        groups = body["groups"]
        # Three unique groups: (ark,keyword,[nurse,rehab_pt]), (lcc,keyword,...), (ark,explicit,[nurse])
        assert len(groups) == 3
        assert body["total"] == 4
        # Most-frequent first
        assert groups[0]["count"] == 2
        assert groups[0]["company"] == "ark"
        assert groups[0]["failure_stage"] == "keyword"
        assert "nurse" in groups[0]["company_categories"]
        # Samples are populated
        assert len(groups[0]["samples"]) == 2
        assert groups[0]["samples"][0]["member_id"] in {"M001", "M002"}

    def test_filters_by_company(self, client):
        rows = [
            LOG_HEADERS,
            _log_row(company="ark", member_id="M001"),
            _log_row(company="lcc", member_id="M002"),
        ]
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = rows
            res = client.get("/api/v1/admin/job_category_failures?company=lcc")
        body = res.json()
        assert body["total"] == 1
        assert all(g["company"] == "lcc" for g in body["groups"])

    def test_respects_days_window(self, client):
        recent = datetime.now(timezone.utc).isoformat(timespec="seconds")
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(timespec="seconds")
        rows = [
            LOG_HEADERS,
            _log_row(member_id="recent", timestamp=recent),
            _log_row(member_id="old", timestamp=old),
        ]
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = rows
            res = client.get("/api/v1/admin/job_category_failures?days=30")
        body = res.json()
        assert body["total"] == 1
        assert body["groups"][0]["samples"][0]["member_id"] == "recent"

    def test_handles_empty_logs(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [LOG_HEADERS]
            res = client.get("/api/v1/admin/job_category_failures")
        assert res.status_code == 200
        assert res.json() == {"groups": [], "total": 0}

    def test_handles_sheet_read_failure(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.side_effect = Exception("boom")
            res = client.get("/api/v1/admin/job_category_failures")
        assert res.status_code == 200
        assert res.json()["groups"] == []

    def test_aggregates_missing_fields_counter(self, client):
        rows = [
            LOG_HEADERS,
            _log_row(member_id="M1", failure_missing_fields="work_history_summary,self_pr"),
            _log_row(member_id="M2", failure_missing_fields="work_history_summary"),
        ]
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = rows
            res = client.get("/api/v1/admin/job_category_failures")
        counter = res.json()["groups"][0]["missing_fields_counter"]
        assert counter["work_history_summary"] == 2
        assert counter["self_pr"] == 1


# ---------------------------------------------------------------------------
# POST /api/v1/admin/job_category_keywords/append
# ---------------------------------------------------------------------------

class TestAppendJobCategoryKeyword:
    def test_appends_canonical_row(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            res = client.post(
                "/api/v1/admin/job_category_keywords/append",
                json={
                    "company": "ark",
                    "job_category": "nurse",
                    "keyword": "訪問看護",
                    "source_fields": "experience",
                    "note": "Phase 3 提案",
                },
            )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["appended"]["keyword"] == "訪問看護"
        assert body["appended"]["added_by"] == "DirectorBot"
        mw.append_row.assert_called_once()
        sheet, row = mw.append_row.call_args[0]
        assert sheet == "職種キーワード"
        # Canonical column order
        assert row[0] == "ark"            # company
        assert row[1] == "nurse"          # job_category
        assert row[2] == "訪問看護"        # keyword
        assert row[3] == "experience"     # source_fields
        assert row[5] == "TRUE"           # enabled default
        assert row[7] == "DirectorBot"    # added_by

    def test_rejects_missing_keyword(self, client):
        res = client.post(
            "/api/v1/admin/job_category_keywords/append",
            json={"company": "ark", "job_category": "nurse"},
        )
        assert res.status_code == 400

    def test_rejects_missing_job_category(self, client):
        res = client.post(
            "/api/v1/admin/job_category_keywords/append",
            json={"keyword": "訪問看護"},
        )
        assert res.status_code == 400

    def test_company_can_be_empty_for_global_rule(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            res = client.post(
                "/api/v1/admin/job_category_keywords/append",
                json={"job_category": "nurse", "keyword": "看護師"},
            )
        assert res.status_code == 200
        sheet, row = mw.append_row.call_args[0]
        assert row[0] == ""  # global
