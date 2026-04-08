"""Tests for 修正フィードバック Phase B: AI改善提案 → 承認 → Sheets実反映."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

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


FIX_HEADERS = [
    "id", "timestamp", "company", "member_id", "template_type",
    "before", "after", "reason", "status", "actor", "note",
]
PROPOSAL_HEADERS = [
    "id", "created_at", "source_fix_ids", "target_sheet", "operation",
    "scope_company", "payload_json", "rationale", "status", "actor", "decided_at",
]
KEYWORDS_HEADERS = [
    "company", "job_category", "keyword", "source_fields",
    "weight", "enabled", "added_at", "added_by", "note",
]


def _fix_row(*, fix_id="fb_001", company="ark", status="pending",
             before="原文", after="改善後 訪問入浴", reason="訪問入浴を強調"):
    return [
        fix_id,
        "2026-04-08T10:00:00",
        company,
        "M001",
        "パート_初回",
        before,
        after,
        reason,
        status,
        "operator",
        "",
    ]


def _proposal_row(*, prop_id="fbprop_aaa", status="pending",
                  scope="", target="job_category_keywords", op="append",
                  payload=None, rationale="訪問入浴は看護師の主要業務", source_ids="fb_001"):
    payload = payload or {
        "keyword": "訪問入浴",
        "job_category": "nurse",
        "source_fields": "experience,self_pr",
        "note": "AI提案",
    }
    return [
        prop_id,
        "2026-04-08T10:05:00",
        source_ids,
        target,
        op,
        scope,
        json.dumps(payload, ensure_ascii=False),
        rationale,
        status,
        "",
        "",
    ]


# ---------------------------------------------------------------------------
# POST /admin/improvement_proposals/generate
# ---------------------------------------------------------------------------

class TestGenerateProposals:
    @pytest.fixture
    def mock_gemini(self):
        async def fake_call(system, user, *, max_output_tokens=2048, temperature=0.7):
            class R:
                text = json.dumps([
                    {
                        "keyword": "訪問入浴",
                        "job_category": "nurse",
                        "scope_company": "",
                        "source_fields": "experience,self_pr",
                        "rationale": "before/afterで訪問入浴という語が追加されている",
                        "source_fix_ids": ["fb_001"],
                    },
                    {
                        "keyword": "ICU",
                        "job_category": "nurse",
                        "scope_company": "ark",
                        "source_fields": "experience",
                        "rationale": "ICU経験者向けの言及が追加された",
                        "source_fix_ids": ["fb_001"],
                    },
                ])
                model_name = "test-model"
            return R()
        with patch("pipeline.ai_generator.generate_personalized_text", side_effect=fake_call) as m:
            yield m

    def test_generates_and_appends_proposals(self, client, mock_gemini):
        with patch("api.routes_admin.sheets_writer") as mw:
            # Phase A pending row + empty existing keywords
            def get_all_rows(name):
                if name == "修正フィードバック":
                    return [FIX_HEADERS, _fix_row()]
                if name == "職種キーワード":
                    return [KEYWORDS_HEADERS]
                return []
            mw.get_all_rows.side_effect = get_all_rows
            res = client.post("/api/v1/admin/improvement_proposals/generate", json={})
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["appended"] == 2
        assert len(body["proposals"]) == 2
        # Each proposal must have payload_json + status pending
        for p in body["proposals"]:
            assert p["status"] == "pending"
            assert p["target_sheet"] == "job_category_keywords"
            assert p["operation"] == "append"
            payload = json.loads(p["payload_json"])
            assert "keyword" in payload
            assert "job_category" in payload
        # Sheet append called twice
        assert mw.append_row.call_count == 2

    def test_skips_keywords_already_in_sheet(self, client, mock_gemini):
        with patch("api.routes_admin.sheets_writer") as mw:
            def get_all_rows(name):
                if name == "修正フィードバック":
                    return [FIX_HEADERS, _fix_row()]
                if name == "職種キーワード":
                    return [
                        KEYWORDS_HEADERS,
                        ["", "nurse", "訪問入浴", "experience", "1", "TRUE", "", "", ""],
                    ]
                return []
            mw.get_all_rows.side_effect = get_all_rows
            res = client.post("/api/v1/admin/improvement_proposals/generate", json={})
        body = res.json()
        # 訪問入浴は重複なので除外、ICUのみ残る
        assert body["appended"] == 1
        assert body["proposals"][0]["payload_json"].find("ICU") >= 0

    def test_returns_warning_when_no_pending(self, client, mock_gemini):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [FIX_HEADERS, _fix_row(status="adopted")]
            res = client.post("/api/v1/admin/improvement_proposals/generate", json={})
        body = res.json()
        assert body["appended"] == 0
        assert "no pending" in body.get("warning", "").lower()
        # Gemini must NOT be called
        mock_gemini.assert_not_called()

    def test_dry_run_does_not_append(self, client, mock_gemini):
        with patch("api.routes_admin.sheets_writer") as mw:
            def get_all_rows(name):
                if name == "修正フィードバック":
                    return [FIX_HEADERS, _fix_row()]
                if name == "職種キーワード":
                    return [KEYWORDS_HEADERS]
                return []
            mw.get_all_rows.side_effect = get_all_rows
            res = client.post("/api/v1/admin/improvement_proposals/generate", json={"dry_run": True})
        body = res.json()
        assert body["appended"] == 0
        assert len(body["proposals"]) == 2
        mw.append_row.assert_not_called()


# ---------------------------------------------------------------------------
# GET /admin/improvement_proposals
# ---------------------------------------------------------------------------

class TestListProposals:
    def test_lists_with_payload_parsed(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [
                PROPOSAL_HEADERS,
                _proposal_row(prop_id="fbprop_aaa"),
                _proposal_row(prop_id="fbprop_bbb", status="approved"),
            ]
            res = client.get("/api/v1/admin/improvement_proposals?status=pending")
        body = res.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["id"] == "fbprop_aaa"
        # payload_json は items[0].payload に展開される
        assert body["items"][0]["payload"]["keyword"] == "訪問入浴"


# ---------------------------------------------------------------------------
# POST /admin/improvement_proposals/{id}/decide
# ---------------------------------------------------------------------------

class TestDecideProposal:
    def test_approve_appends_keyword_and_marks_fix_adopted(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            def get_all_rows(name):
                if name == "改善提案":
                    return [PROPOSAL_HEADERS, _proposal_row()]
                if name == "修正フィードバック":
                    return [FIX_HEADERS, _fix_row(fix_id="fb_001")]
                return []
            mw.get_all_rows.side_effect = get_all_rows
            res = client.post(
                "/api/v1/admin/improvement_proposals/fbprop_aaa/decide",
                json={"decision": "approve"},
            )
        assert res.status_code == 200
        body = res.json()
        assert body["new_status"] == "approved"
        assert body["appended_keyword"]["keyword"] == "訪問入浴"
        # 1: 職種キーワード append
        assert mw.append_row.call_count == 1
        sheet, row = mw.append_row.call_args[0]
        assert sheet == "職種キーワード"
        # canonical position: company, job_category, keyword, ...
        assert row[0] == ""  # global scope
        assert row[1] == "nurse"
        assert row[2] == "訪問入浴"
        # update_cells_by_name called for proposal status + cascading fix_feedback
        update_calls = mw.update_cells_by_name.call_args_list
        sheets_updated = [c[0][0] for c in update_calls]
        assert "改善提案" in sheets_updated
        assert "修正フィードバック" in sheets_updated
        assert "fb_001" in body["adopted_fix_ids"]

    def test_approve_with_payload_overrides(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            def get_all_rows(name):
                if name == "改善提案":
                    return [PROPOSAL_HEADERS, _proposal_row()]
                if name == "修正フィードバック":
                    return [FIX_HEADERS]
                return []
            mw.get_all_rows.side_effect = get_all_rows
            res = client.post(
                "/api/v1/admin/improvement_proposals/fbprop_aaa/decide",
                json={
                    "decision": "approve",
                    "scope_company": "ark",
                    "payload_overrides": {
                        "keyword": "訪問入浴介助",
                        "job_category": "nurse",
                    },
                },
            )
        assert res.status_code == 200
        sheet, row = mw.append_row.call_args[0]
        assert row[0] == "ark"           # scope override
        assert row[2] == "訪問入浴介助"   # payload override

    def test_reject_marks_status_only(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [PROPOSAL_HEADERS, _proposal_row()]
            res = client.post(
                "/api/v1/admin/improvement_proposals/fbprop_aaa/decide",
                json={"decision": "reject"},
            )
        assert res.status_code == 200
        assert res.json()["new_status"] == "rejected"
        # No keyword append on reject
        mw.append_row.assert_not_called()

    def test_decide_unknown_proposal_returns_404(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [PROPOSAL_HEADERS, _proposal_row(prop_id="fbprop_other")]
            res = client.post(
                "/api/v1/admin/improvement_proposals/fbprop_missing/decide",
                json={"decision": "approve"},
            )
        assert res.status_code == 404

    def test_decide_already_processed_returns_409(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [PROPOSAL_HEADERS, _proposal_row(status="approved")]
            res = client.post(
                "/api/v1/admin/improvement_proposals/fbprop_aaa/decide",
                json={"decision": "reject"},
            )
        assert res.status_code == 409

    def test_decide_invalid_decision_returns_400(self, client):
        res = client.post(
            "/api/v1/admin/improvement_proposals/fbprop_aaa/decide",
            json={"decision": "maybe"},
        )
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# target=prompts (Phase B 第二弾)
# ---------------------------------------------------------------------------

PROMPT_HEADERS = ["company", "section_type", "job_category", "order", "content"]


def _prompt_proposal_row():
    payload = {
        "section_type": "station_features",
        "job_category": "nurse",
        "content": "- 訪問入浴に強い体制\n- 機械浴対応",
        "order": "2",
    }
    return [
        "fbprop_pp1",
        "2026-04-08T11:00:00",
        "fb_001",
        "prompts",
        "append",
        "ark",
        json.dumps(payload, ensure_ascii=False),
        "ark の station_features に訪問入浴の特色が抜けている",
        "pending",
        "",
        "",
    ]


class TestGenerateProposalsPrompts:
    @pytest.fixture
    def mock_gemini_prompts(self):
        async def fake_call(system, user, *, max_output_tokens=2048, temperature=0.7):
            class R:
                text = json.dumps([
                    {
                        "section_type": "station_features",
                        "job_category": "nurse",
                        "scope_company": "ark",
                        "content": "- 訪問入浴の専門ノウハウ\n- 機械浴対応",
                        "rationale": "ark固有の訪問入浴強みが既存promptに無い",
                        "source_fix_ids": ["fb_001"],
                    },
                ])
                model_name = "test-model"
            return R()
        with patch("pipeline.ai_generator.generate_personalized_text", side_effect=fake_call) as m:
            yield m

    def test_generates_prompts_proposal(self, client, mock_gemini_prompts):
        with patch("api.routes_admin.sheets_writer") as mw:
            def get_all_rows(name):
                if name == "修正フィードバック":
                    return [FIX_HEADERS, _fix_row()]
                if name == "プロンプト":
                    return [PROMPT_HEADERS]
                return []
            mw.get_all_rows.side_effect = get_all_rows
            res = client.post(
                "/api/v1/admin/improvement_proposals/generate",
                json={"target": "prompts"},
            )
        assert res.status_code == 200
        body = res.json()
        assert body["target"] == "prompts"
        assert body["appended"] == 1
        p = body["proposals"][0]
        assert p["target_sheet"] == "prompts"
        assert p["operation"] == "append"
        payload = json.loads(p["payload_json"])
        assert payload["section_type"] == "station_features"
        assert payload["order"] == "2"

    def test_skips_invalid_section_type(self, client):
        async def fake_call(*a, **k):
            class R:
                text = json.dumps([
                    {"section_type": "weird_type", "job_category": "nurse",
                     "content": "x", "rationale": "...", "source_fix_ids": []},
                ])
                model_name = ""
            return R()
        with patch("pipeline.ai_generator.generate_personalized_text", side_effect=fake_call):
            with patch("api.routes_admin.sheets_writer") as mw:
                def get_all_rows(name):
                    if name == "修正フィードバック":
                        return [FIX_HEADERS, _fix_row()]
                    return [PROMPT_HEADERS] if name == "プロンプト" else []
                mw.get_all_rows.side_effect = get_all_rows
                res = client.post(
                    "/api/v1/admin/improvement_proposals/generate",
                    json={"target": "prompts"},
                )
        # weird_type はスキップされ、結果ゼロ
        assert res.json()["appended"] == 0

    def test_unsupported_target_returns_400(self, client):
        res = client.post(
            "/api/v1/admin/improvement_proposals/generate",
            json={"target": "unknown"},
        )
        assert res.status_code == 400


class TestDecidePromptsProposal:
    def test_approve_appends_prompt_section(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            def get_all_rows(name):
                if name == "改善提案":
                    return [PROPOSAL_HEADERS, _prompt_proposal_row()]
                if name == "修正フィードバック":
                    return [FIX_HEADERS, _fix_row(fix_id="fb_001")]
                return []
            mw.get_all_rows.side_effect = get_all_rows
            res = client.post(
                "/api/v1/admin/improvement_proposals/fbprop_pp1/decide",
                json={"decision": "approve"},
            )
        assert res.status_code == 200
        body = res.json()
        assert body["new_status"] == "approved"
        assert body["target_sheet"] == "prompts"
        # append_row called once with プロンプト sheet
        assert mw.append_row.call_count == 1
        sheet, row = mw.append_row.call_args[0]
        assert sheet == "プロンプト"
        # column order: company, section_type, job_category, order, content
        assert row[0] == "ark"
        assert row[1] == "station_features"
        assert row[2] == "nurse"
        assert row[3] == "2"
        # Newlines must be escaped to literal \n for sheets
        assert "\\n" in row[4]


# ---------------------------------------------------------------------------
# target=patterns (Phase B 第三弾)
# ---------------------------------------------------------------------------

PATTERN_HEADERS = [
    "company", "job_category", "pattern_type", "employment_variant",
    "template_text", "feature_variations", "display_name", "target_description",
    "match_rules", "qualification_combo", "replacement_text",
]


def _pattern_row(*, company="ark", pattern_type="A", job_category="nurse",
                 employment_variant="", features="経験を活かす|専門スキル"):
    return [
        company, job_category, pattern_type, employment_variant,
        "template body", features, "型A", "ベテラン",
        "[]", "", "",
    ]


def _pattern_proposal_row():
    payload = {
        "pattern_type": "A",
        "job_category": "nurse",
        "employment_variant": "",
        "new_feature": "訪問入浴の現場で活きる",
    }
    return [
        "fbprop_pat1",
        "2026-04-08T11:30:00",
        "fb_002",
        "patterns",
        "update",
        "ark",
        json.dumps(payload, ensure_ascii=False),
        "ark の型A に訪問入浴の文脈を増やしたい",
        "pending",
        "",
        "",
    ]


class TestDecidePatternsProposal:
    def test_approve_appends_feature_to_existing_pattern(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            def get_all_rows(name):
                if name == "改善提案":
                    return [PROPOSAL_HEADERS, _pattern_proposal_row()]
                if name == "パターン":
                    return [PATTERN_HEADERS, _pattern_row()]
                if name == "修正フィードバック":
                    return [FIX_HEADERS]
                return []
            mw.get_all_rows.side_effect = get_all_rows
            res = client.post(
                "/api/v1/admin/improvement_proposals/fbprop_pat1/decide",
                json={"decision": "approve"},
            )
        assert res.status_code == 200
        body = res.json()
        assert body["new_status"] == "approved"
        assert body["target_sheet"] == "patterns"
        # update_cells_by_name called for the pattern row with merged feature_variations
        update_calls = mw.update_cells_by_name.call_args_list
        pattern_updates = [c for c in update_calls if c[0][0] == "パターン"]
        assert len(pattern_updates) == 1
        cells = pattern_updates[0][0][2]
        assert "feature_variations" in cells
        assert "訪問入浴の現場で活きる" in cells["feature_variations"]
        # Original features preserved
        assert "経験を活かす" in cells["feature_variations"]

    def test_approve_rejects_duplicate_feature(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            def get_all_rows(name):
                if name == "改善提案":
                    return [PROPOSAL_HEADERS, _pattern_proposal_row()]
                if name == "パターン":
                    return [PATTERN_HEADERS, _pattern_row(features="訪問入浴の現場で活きる|x")]
                return []
            mw.get_all_rows.side_effect = get_all_rows
            res = client.post(
                "/api/v1/admin/improvement_proposals/fbprop_pat1/decide",
                json={"decision": "approve"},
            )
        assert res.status_code == 409

    def test_approve_404_when_pattern_not_found(self, client):
        with patch("api.routes_admin.sheets_writer") as mw:
            def get_all_rows(name):
                if name == "改善提案":
                    return [PROPOSAL_HEADERS, _pattern_proposal_row()]
                if name == "パターン":
                    return [PATTERN_HEADERS, _pattern_row(company="other")]
                return []
            mw.get_all_rows.side_effect = get_all_rows
            res = client.post(
                "/api/v1/admin/improvement_proposals/fbprop_pat1/decide",
                json={"decision": "approve"},
            )
        assert res.status_code == 404

    def test_approve_400_without_scope_company(self, client):
        # Build proposal with empty scope (illegal for patterns)
        bad_row = _pattern_proposal_row()
        bad_row[5] = ""  # scope_company column
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [PROPOSAL_HEADERS, bad_row]
            res = client.post(
                "/api/v1/admin/improvement_proposals/fbprop_pat1/decide",
                json={"decision": "approve"},
            )
        assert res.status_code == 400
