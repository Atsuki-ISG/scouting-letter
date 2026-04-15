"""Tests for テンプレート改善下書き (server-side draft save).

改善提案の編集可能化機能:
- improve_template の diff 承認直前で本文を textarea 編集 → サーバに下書き保存
- 下書きは Sheets 上に `改善下書き` シートとして蓄積
- ブラウザを閉じても復元可能、クロスマシンで共有可能
- status=draft/applied/discarded の soft delete 運用
"""
from __future__ import annotations

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


DRAFT_HEADERS = [
    "id",
    "company",
    "template_row_index",
    "template_type",
    "job_category",
    "original_body",
    "draft_body",
    "directive",
    "analysis_summary",
    "status",
    "created_at",
    "updated_at",
    "created_by",
]


def _draft_row(
    *,
    draft_id="draft_abc123",
    company="ark",
    row_index="42",
    template_type="パート_初回",
    job_category="nurse",
    original_body="原文本文",
    draft_body="編集後\n本文",
    directive="",
    analysis_summary="",
    status="draft",
    created_at="2026-04-15T09:00:00+00:00",
    updated_at="2026-04-15T09:00:00+00:00",
    created_by="DirectorBot",
):
    return [
        draft_id,
        company,
        row_index,
        template_type,
        job_category,
        original_body,
        draft_body,
        directive,
        analysis_summary,
        status,
        created_at,
        updated_at,
        created_by,
    ]


# ---------------------------------------------------------------------------
# POST /api/v1/admin/improvement_drafts  (upsert)
# ---------------------------------------------------------------------------


class TestCreateOrUpdateDraft:
    def test_create_new_draft_returns_generated_id(self, client):
        """id を渡さない POST では新規採番されて append_row される。"""
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [DRAFT_HEADERS]
            res = client.post(
                "/api/v1/admin/improvement_drafts",
                json={
                    "company": "ark",
                    "template_row_index": 42,
                    "template_type": "パート_初回",
                    "job_category": "nurse",
                    "original_body": "原文",
                    "draft_body": "編集後\n本文",
                    "directive": "訪問入浴を強調",
                },
            )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["draft"]["id"].startswith("draft_")
        assert body["draft"]["status"] == "draft"
        assert body["draft"]["company"] == "ark"
        assert body["draft"]["template_row_index"] == 42
        assert body["draft"]["draft_body"] == "編集後\n本文"
        mw.append_row.assert_called_once()
        sheet, row = mw.append_row.call_args[0]
        assert sheet == "改善下書き"
        # created_at == updated_at on new
        col_map = {h: i for i, h in enumerate(DRAFT_HEADERS)}
        assert row[col_map["created_at"]] == row[col_map["updated_at"]]
        assert row[col_map["created_by"]] == "DirectorBot"

    def test_update_existing_draft_preserves_id_and_created_at(self, client):
        """既存 id を渡すと update_cells_by_name で updated_at / draft_body のみ更新。"""
        original_created_at = "2026-04-14T01:00:00+00:00"
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [
                DRAFT_HEADERS,
                _draft_row(
                    draft_id="draft_abc123",
                    draft_body="古い編集",
                    created_at=original_created_at,
                    updated_at=original_created_at,
                ),
            ]
            res = client.post(
                "/api/v1/admin/improvement_drafts",
                json={
                    "id": "draft_abc123",
                    "company": "ark",
                    "template_row_index": 42,
                    "template_type": "パート_初回",
                    "job_category": "nurse",
                    "original_body": "原文",
                    "draft_body": "新しい編集",
                },
            )
        assert res.status_code == 200
        body = res.json()
        assert body["draft"]["id"] == "draft_abc123"
        assert body["draft"]["draft_body"] == "新しい編集"
        assert body["draft"]["created_at"] == original_created_at
        # updated_at は新しい値
        assert body["draft"]["updated_at"] != original_created_at
        # append ではなく update
        mw.append_row.assert_not_called()
        mw.update_cells_by_name.assert_called_once()
        sheet, row_index, cells = mw.update_cells_by_name.call_args[0]
        assert sheet == "改善下書き"
        assert row_index == 2
        assert cells["draft_body"] == "新しい編集"
        assert "updated_at" in cells
        assert "created_at" not in cells

    def test_update_unknown_id_returns_404(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [DRAFT_HEADERS]
            res = client.post(
                "/api/v1/admin/improvement_drafts",
                json={
                    "id": "draft_missing",
                    "company": "ark",
                    "template_row_index": 42,
                    "template_type": "パート_初回",
                    "job_category": "nurse",
                    "original_body": "x",
                    "draft_body": "y",
                },
            )
        assert res.status_code == 404

    def test_missing_required_fields_returns_400(self, client):
        res = client.post(
            "/api/v1/admin/improvement_drafts",
            json={"company": "ark"},  # no row_index / body
        )
        assert res.status_code == 400

    def test_ensures_sheet_exists_on_create(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [DRAFT_HEADERS]
            client.post(
                "/api/v1/admin/improvement_drafts",
                json={
                    "company": "ark",
                    "template_row_index": 1,
                    "template_type": "t",
                    "job_category": "n",
                    "original_body": "o",
                    "draft_body": "d",
                },
            )
        mw.ensure_sheet_exists.assert_called_once()
        call_args = mw.ensure_sheet_exists.call_args[0]
        assert call_args[0] == "改善下書き"
        assert call_args[1] == DRAFT_HEADERS


# ---------------------------------------------------------------------------
# GET /api/v1/admin/improvement_drafts
# ---------------------------------------------------------------------------


class TestListDrafts:
    def test_filters_by_company_and_row_index(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [
                DRAFT_HEADERS,
                _draft_row(draft_id="d1", company="ark", row_index="42"),
                _draft_row(draft_id="d2", company="ark", row_index="99"),
                _draft_row(draft_id="d3", company="lcc", row_index="42"),
            ]
            res = client.get(
                "/api/v1/admin/improvement_drafts",
                params={"company": "ark", "row_index": 42},
            )
        assert res.status_code == 200
        items = res.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == "d1"

    def test_excludes_non_draft_status(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [
                DRAFT_HEADERS,
                _draft_row(draft_id="d1", status="draft"),
                _draft_row(draft_id="d2", status="applied"),
                _draft_row(draft_id="d3", status="discarded"),
            ]
            res = client.get("/api/v1/admin/improvement_drafts")
        items = res.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == "d1"

    def test_list_without_filters_returns_all_drafts(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [
                DRAFT_HEADERS,
                _draft_row(draft_id="d1", company="ark"),
                _draft_row(draft_id="d2", company="lcc"),
            ]
            res = client.get("/api/v1/admin/improvement_drafts")
        items = res.json()["items"]
        assert len(items) == 2

    def test_empty_sheet_returns_empty_list(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.side_effect = Exception("sheet not found")
            res = client.get("/api/v1/admin/improvement_drafts")
        assert res.status_code == 200
        assert res.json()["items"] == []


# ---------------------------------------------------------------------------
# GET /api/v1/admin/improvement_drafts/{id}
# ---------------------------------------------------------------------------


class TestGetDraft:
    def test_returns_full_body_with_real_newlines(self, client):
        """Sheets は `\\n` リテラルで保存、API は実改行で返す想定でも、
        生の draft_body が新規UI入力時からそのまま保持されているかを確認。"""
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [
                DRAFT_HEADERS,
                _draft_row(draft_id="draft_abc", draft_body="1行目\n2行目"),
            ]
            res = client.get("/api/v1/admin/improvement_drafts/draft_abc")
        assert res.status_code == 200
        body = res.json()
        assert body["draft"]["id"] == "draft_abc"
        assert "1行目" in body["draft"]["draft_body"]
        assert "2行目" in body["draft"]["draft_body"]

    def test_get_unknown_returns_404(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [DRAFT_HEADERS]
            res = client.get("/api/v1/admin/improvement_drafts/draft_missing")
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/admin/improvement_drafts/{id}/discard
# ---------------------------------------------------------------------------


class TestDiscardDraft:
    def test_discard_changes_status_to_discarded(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [
                DRAFT_HEADERS,
                _draft_row(draft_id="draft_abc", status="draft"),
            ]
            res = client.post("/api/v1/admin/improvement_drafts/draft_abc/discard")
        assert res.status_code == 200
        assert res.json()["new_status"] == "discarded"
        mw.update_cells_by_name.assert_called_once()
        sheet, row_index, cells = mw.update_cells_by_name.call_args[0]
        assert sheet == "改善下書き"
        assert row_index == 2
        assert cells["status"] == "discarded"
        assert "updated_at" in cells

    def test_discard_accepts_applied_status_param(self, client):
        """apply 成功時に UI が `new_status=applied` を指定して soft delete できる。"""
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [
                DRAFT_HEADERS,
                _draft_row(draft_id="draft_abc", status="draft"),
            ]
            res = client.post(
                "/api/v1/admin/improvement_drafts/draft_abc/discard",
                json={"new_status": "applied"},
            )
        assert res.status_code == 200
        assert res.json()["new_status"] == "applied"
        sheet, row_index, cells = mw.update_cells_by_name.call_args[0]
        assert cells["status"] == "applied"

    def test_discard_rejects_invalid_status(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [
                DRAFT_HEADERS,
                _draft_row(draft_id="draft_abc", status="draft"),
            ]
            res = client.post(
                "/api/v1/admin/improvement_drafts/draft_abc/discard",
                json={"new_status": "draft"},
            )
        assert res.status_code == 400

    def test_discard_already_processed_returns_409(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [
                DRAFT_HEADERS,
                _draft_row(draft_id="draft_abc", status="applied"),
            ]
            res = client.post("/api/v1/admin/improvement_drafts/draft_abc/discard")
        assert res.status_code == 409

    def test_discard_unknown_returns_404(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [DRAFT_HEADERS]
            res = client.post("/api/v1/admin/improvement_drafts/draft_missing/discard")
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


def test_unauthenticated_requests_rejected():
    """verify_api_key 依存関係を override せずに叩くと 401/403。"""
    c = TestClient(app)
    res = c.get("/api/v1/admin/improvement_drafts")
    assert res.status_code in (401, 403)
