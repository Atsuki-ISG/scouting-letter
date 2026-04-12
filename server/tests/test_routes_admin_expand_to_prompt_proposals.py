"""Tests for POST /admin/expand_template/to_prompt_proposals.

Mode B of the expand UI: approved diffs are repurposed into prompt-sheet
improvement proposals that land in the 改善提案 sheet as pending.

Invariants:
- No template sheet writes ever happen on this path.
- `改善提案` sheet is appended to (once per accepted proposal).
- Existing prompt sections are deduped out.
- An empty Gemini result returns appended=0 without raising.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from auth.api_key import verify_api_key
from main import app


def _fake_operator():
    return {"operator_id": "t", "name": "t", "role": "admin"}


@pytest.fixture
def client():
    app.dependency_overrides[verify_api_key] = _fake_operator
    yield TestClient(app)
    app.dependency_overrides.pop(verify_api_key, None)


PROMPT_HEADERS = ["company", "section_type", "job_category", "order", "content"]


def _sample_diff():
    return {
        "company": "ark",
        "job_category": "nurse",
        "template_type": "パート_初回",
        "original": "訪問看護を募集しています",
        "merged": "訪問看護で在宅ケアに携わる看護師を募集しています。24時間体制のオンコール対応あり",
    }


def _gemini_ok(text: str):
    async def fake(system, user, *, model_name=None, max_output_tokens=2048, temperature=0.3):
        class R:
            def __init__(self):
                self.text = text
                self.model_name = "test"
        return R()
    return fake


class TestExpandToPromptProposals:
    def test_appends_proposals_to_improvement_sheet(self, client):
        gem = _gemini_ok(json.dumps([
            {
                "section_type": "station_features",
                "job_category": "nurse",
                "scope_company": "ark",
                "content": "- 24時間体制のオンコール対応",
                "rationale": "差分から追加された",
                "source_fix_ids": ["expand_0"],
            }
        ]))
        with patch("pipeline.ai_generator.generate_personalized_text", side_effect=gem), \
             patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [PROMPT_HEADERS]  # no existing prompts
            res = client.post(
                "/api/v1/admin/expand_template/to_prompt_proposals",
                json={
                    "company": "ark",
                    "source": {"job_category": "nurse", "template_type": "パート_初回"},
                    "approved_diffs": [_sample_diff()],
                },
            )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["appended"] == 1
        assert len(body["proposal_ids"]) == 1

        # Verify: append_row was called for the 改善提案 sheet
        append_calls = mw.append_row.call_args_list
        sheets_written = [c[0][0] for c in append_calls]
        assert "改善提案" in sheets_written
        # The written row is IMPROVEMENT_PROPOSAL_COLUMNS-ordered
        prop_call = next(c for c in append_calls if c[0][0] == "改善提案")
        row = prop_call[0][1]
        assert row[3] == "prompts"  # target_sheet
        assert row[4] == "append"  # operation
        assert row[5] == "ark"  # scope_company
        payload = json.loads(row[6])
        assert payload["section_type"] == "station_features"
        assert payload["job_category"] == "nurse"
        # NO writes to テンプレート sheet
        template_calls = [c for c in append_calls if c[0][0] == "テンプレート"]
        assert template_calls == []
        mw.update_cells_by_name.assert_not_called()

    def test_dedups_against_existing_prompt_sections(self, client):
        gem = _gemini_ok(json.dumps([
            {
                "section_type": "station_features",
                "job_category": "nurse",
                "scope_company": "ark",
                "content": "- 既に書かれている内容",
                "rationale": "重複なので落ちるはず",
            }
        ]))
        with patch("pipeline.ai_generator.generate_personalized_text", side_effect=gem), \
             patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [
                PROMPT_HEADERS,
                ["ark", "station_features", "nurse", "2", "- 既に書かれている内容"],
            ]
            res = client.post(
                "/api/v1/admin/expand_template/to_prompt_proposals",
                json={
                    "company": "ark",
                    "source": {"job_category": "nurse", "template_type": "パート_初回"},
                    "approved_diffs": [_sample_diff()],
                },
            )
        body = res.json()
        assert body["appended"] == 0
        # No append to 改善提案
        append_targets = [c[0][0] for c in mw.append_row.call_args_list]
        assert "改善提案" not in append_targets

    def test_empty_gemini_array_returns_zero(self, client):
        gem = _gemini_ok("[]")
        with patch("pipeline.ai_generator.generate_personalized_text", side_effect=gem), \
             patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [PROMPT_HEADERS]
            res = client.post(
                "/api/v1/admin/expand_template/to_prompt_proposals",
                json={
                    "company": "ark",
                    "source": {"job_category": "nurse", "template_type": "パート_初回"},
                    "approved_diffs": [_sample_diff()],
                },
            )
        assert res.status_code == 200
        assert res.json()["appended"] == 0

    def test_missing_company_returns_400(self, client):
        res = client.post(
            "/api/v1/admin/expand_template/to_prompt_proposals",
            json={"company": "", "approved_diffs": [_sample_diff()]},
        )
        assert res.status_code == 400

    def test_empty_approved_diffs_returns_400(self, client):
        res = client.post(
            "/api/v1/admin/expand_template/to_prompt_proposals",
            json={"company": "ark", "approved_diffs": []},
        )
        assert res.status_code == 400

    def test_invalid_section_type_filtered(self, client):
        gem = _gemini_ok(json.dumps([
            {
                "section_type": "not_supported",
                "job_category": "nurse",
                "scope_company": "ark",
                "content": "- something",
            },
            {
                "section_type": "education",
                "job_category": "nurse",
                "scope_company": "ark",
                "content": "- プリセプター制度",
            },
        ]))
        with patch("pipeline.ai_generator.generate_personalized_text", side_effect=gem), \
             patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = [PROMPT_HEADERS]
            res = client.post(
                "/api/v1/admin/expand_template/to_prompt_proposals",
                json={
                    "company": "ark",
                    "source": {"job_category": "nurse", "template_type": "パート_初回"},
                    "approved_diffs": [_sample_diff()],
                },
            )
        body = res.json()
        assert body["appended"] == 1
        prop = body["proposals"][0]
        payload = json.loads(prop["payload_json"])
        assert payload["section_type"] == "education"
