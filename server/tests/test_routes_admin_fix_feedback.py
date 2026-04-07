"""Tests for the修正フィードバック admin endpoints."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from auth.api_key import verify_api_key
from main import app


def _fake_operator():
    return {"operator_id": "test", "name": "Test", "role": "admin"}


FIX_FEEDBACK_HEADERS = [
    "id",
    "timestamp",
    "company",
    "member_id",
    "template_type",
    "before",
    "after",
    "reason",
    "status",
    "actor",
    "note",
]


@pytest.fixture
def client():
    app.dependency_overrides[verify_api_key] = _fake_operator
    yield TestClient(app)
    app.dependency_overrides.pop(verify_api_key, None)


@pytest.fixture
def auth_headers():
    return {}


# ---------------------------------------------------------------------------
# POST /api/v1/admin/sync_fixes
# ---------------------------------------------------------------------------

class TestSyncFixes:
    def test_empty_payload_is_noop(self, client, auth_headers):
        with patch("api.routes_admin.sheets_writer") as mock_writer:
            res = client.post(
                "/api/v1/admin/sync_fixes",
                json={"company": "ark-visiting-nurse", "fixes": []},
                headers=auth_headers,
            )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["appended"] == 0
        assert body["skipped_duplicate"] == 0
        mock_writer.append_row.assert_not_called()

    def test_single_fix_appended(self, client, auth_headers):
        with patch("api.routes_admin.sheets_writer") as mock_writer:
            mock_writer.get_all_rows.return_value = [FIX_FEEDBACK_HEADERS]
            res = client.post(
                "/api/v1/admin/sync_fixes",
                json={
                    "company": "ark-visiting-nurse",
                    "fixes": [
                        {
                            "id": "fix_001",
                            "member_id": "M001",
                            "template_type": "パート_初回",
                            "timestamp": "2026-04-07T10:00:00",
                            "before": "old text",
                            "after": "new text",
                            "reason": "もっと丁寧に",
                        }
                    ],
                },
                headers=auth_headers,
            )
        assert res.status_code == 200
        body = res.json()
        assert body["appended"] == 1
        assert body["skipped_duplicate"] == 0
        mock_writer.ensure_sheet_exists.assert_called_once()
        mock_writer.append_row.assert_called_once()
        # Verify the column order matches FIX_FEEDBACK_HEADERS
        sheet_name, row_values = mock_writer.append_row.call_args[0]
        assert sheet_name == "修正フィードバック"
        assert len(row_values) == len(FIX_FEEDBACK_HEADERS)
        # status defaults to pending
        status_idx = FIX_FEEDBACK_HEADERS.index("status")
        assert row_values[status_idx] == "pending"
        id_idx = FIX_FEEDBACK_HEADERS.index("id")
        assert row_values[id_idx] == "fix_001"

    def test_duplicate_id_is_skipped(self, client, auth_headers):
        existing = ["fix_dup", "2026-04-07", "ark-visiting-nurse", "M001",
                    "パート_初回", "x", "y", "", "pending", "operator", ""]
        with patch("api.routes_admin.sheets_writer") as mock_writer:
            mock_writer.get_all_rows.return_value = [FIX_FEEDBACK_HEADERS, existing]
            res = client.post(
                "/api/v1/admin/sync_fixes",
                json={
                    "company": "ark-visiting-nurse",
                    "fixes": [
                        {
                            "id": "fix_dup",
                            "member_id": "M001",
                            "template_type": "パート_初回",
                            "timestamp": "2026-04-07T10:00:00",
                            "before": "x",
                            "after": "y",
                            "reason": "",
                        }
                    ],
                },
                headers=auth_headers,
            )
        assert res.status_code == 200
        body = res.json()
        assert body["appended"] == 0
        assert body["skipped_duplicate"] == 1
        mock_writer.append_row.assert_not_called()

    def test_missing_id_is_auto_generated(self, client, auth_headers):
        with patch("api.routes_admin.sheets_writer") as mock_writer:
            mock_writer.get_all_rows.return_value = [FIX_FEEDBACK_HEADERS]
            res = client.post(
                "/api/v1/admin/sync_fixes",
                json={
                    "company": "ark-visiting-nurse",
                    "fixes": [
                        {
                            "member_id": "M001",
                            "template_type": "パート_初回",
                            "timestamp": "2026-04-07T10:00:00",
                            "before": "a",
                            "after": "b",
                            "reason": "",
                        }
                    ],
                },
                headers=auth_headers,
            )
        assert res.status_code == 200
        assert res.json()["appended"] == 1
        # The generated id should not be empty
        _, row_values = mock_writer.append_row.call_args[0]
        id_idx = FIX_FEEDBACK_HEADERS.index("id")
        assert row_values[id_idx]
        assert row_values[id_idx].startswith("fb_")


# ---------------------------------------------------------------------------
# GET /api/v1/admin/fix_feedback
# ---------------------------------------------------------------------------

def _row(**overrides):
    base = {
        "id": "fb_default",
        "timestamp": "2026-04-01T10:00:00",
        "company": "ark-visiting-nurse",
        "member_id": "M001",
        "template_type": "パート_初回",
        "before": "before",
        "after": "after",
        "reason": "",
        "status": "pending",
        "actor": "operator",
        "note": "",
    }
    base.update(overrides)
    return [base[col] for col in FIX_FEEDBACK_HEADERS]


class TestListFixFeedback:
    def test_returns_all_items_when_no_filter(self, client, auth_headers):
        rows = [
            FIX_FEEDBACK_HEADERS,
            _row(id="fb_001", timestamp="2026-04-01T10:00:00"),
            _row(id="fb_002", timestamp="2026-04-02T10:00:00", status="adopted"),
            _row(id="fb_003", timestamp="2026-04-03T10:00:00", company="lcc-visiting-nurse"),
        ]
        with patch("api.routes_admin.sheets_writer") as mock_writer:
            mock_writer.get_all_rows.return_value = rows
            res = client.get("/api/v1/admin/fix_feedback", headers=auth_headers)
        assert res.status_code == 200
        items = res.json()["items"]
        assert len(items) == 3
        # Sort: timestamp descending
        assert [i["id"] for i in items] == ["fb_003", "fb_002", "fb_001"]

    def test_filter_by_company(self, client, auth_headers):
        rows = [
            FIX_FEEDBACK_HEADERS,
            _row(id="fb_001", company="ark-visiting-nurse"),
            _row(id="fb_002", company="lcc-visiting-nurse"),
        ]
        with patch("api.routes_admin.sheets_writer") as mock_writer:
            mock_writer.get_all_rows.return_value = rows
            res = client.get(
                "/api/v1/admin/fix_feedback?company=lcc-visiting-nurse",
                headers=auth_headers,
            )
        items = res.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == "fb_002"

    def test_filter_by_status(self, client, auth_headers):
        rows = [
            FIX_FEEDBACK_HEADERS,
            _row(id="fb_001", status="pending"),
            _row(id="fb_002", status="adopted"),
            _row(id="fb_003", status="skipped"),
        ]
        with patch("api.routes_admin.sheets_writer") as mock_writer:
            mock_writer.get_all_rows.return_value = rows
            res = client.get(
                "/api/v1/admin/fix_feedback?status=pending", headers=auth_headers
            )
        items = res.json()["items"]
        assert len(items) == 1
        assert items[0]["status"] == "pending"

    def test_returns_empty_when_sheet_missing(self, client, auth_headers):
        with patch("api.routes_admin.sheets_writer") as mock_writer:
            mock_writer.get_all_rows.side_effect = Exception("not found")
            res = client.get("/api/v1/admin/fix_feedback", headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["items"] == []


# ---------------------------------------------------------------------------
# POST /api/v1/admin/fix_feedback/{id}/status
# ---------------------------------------------------------------------------

class TestUpdateFixStatus:
    def test_updates_status_to_adopted(self, client, auth_headers):
        rows = [
            FIX_FEEDBACK_HEADERS,
            _row(id="fb_target", status="pending"),
        ]
        with patch("api.routes_admin.sheets_writer") as mock_writer:
            mock_writer.get_all_rows.return_value = rows
            res = client.post(
                "/api/v1/admin/fix_feedback/fb_target/status",
                json={"status": "adopted"},
                headers=auth_headers,
            )
        assert res.status_code == 200
        assert res.json()["status"] == "ok"
        mock_writer.update_cells_by_name.assert_called_once()
        # Verify it updated row 2 (1-based, after header)
        call_args = mock_writer.update_cells_by_name.call_args
        assert call_args[0][1] == 2  # row_index
        assert call_args[0][2]["status"] == "adopted"

    def test_updates_status_with_note(self, client, auth_headers):
        rows = [
            FIX_FEEDBACK_HEADERS,
            _row(id="fb_target", status="pending"),
        ]
        with patch("api.routes_admin.sheets_writer") as mock_writer:
            mock_writer.get_all_rows.return_value = rows
            res = client.post(
                "/api/v1/admin/fix_feedback/fb_target/status",
                json={"status": "skipped", "note": "重複事例"},
                headers=auth_headers,
            )
        assert res.status_code == 200
        cells = mock_writer.update_cells_by_name.call_args[0][2]
        assert cells["status"] == "skipped"
        assert cells["note"] == "重複事例"

    def test_invalid_status_rejected(self, client, auth_headers):
        with patch("api.routes_admin.sheets_writer") as mock_writer:
            mock_writer.get_all_rows.return_value = [FIX_FEEDBACK_HEADERS]
            res = client.post(
                "/api/v1/admin/fix_feedback/fb_x/status",
                json={"status": "weird"},
                headers=auth_headers,
            )
        assert res.status_code == 400

    def test_id_not_found_returns_404(self, client, auth_headers):
        with patch("api.routes_admin.sheets_writer") as mock_writer:
            mock_writer.get_all_rows.return_value = [FIX_FEEDBACK_HEADERS]
            res = client.post(
                "/api/v1/admin/fix_feedback/fb_missing/status",
                json={"status": "adopted"},
                headers=auth_headers,
            )
        assert res.status_code == 404
