"""Tests for improve_template with diagnosis parameter (Stage 2).

TDD tests for:
- improve_template accepting diagnosis parameter
- Diagnosis injected into system prompt
- Improvement proposals auto-generated for prompt/recipes targets
"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app
from auth.api_key import verify_api_key
from pipeline.ai_generator import GenerationResult


def _fake_operator():
    return {"operator_id": "t", "name": "tester", "role": "admin"}


# Template sheet data
_TEMPLATE_ROWS = [
    ["company", "job_category", "type", "body", "version"],
    ["ark-visiting-nurse", "看護師", "正社員_default",
     "テンプレート冒頭\\n{personalized_text}\\n会社紹介テキスト", "3"],
]

# Send data (empty, just header)
_SEND_DATA_EMPTY = [
    ["日時", "会員番号", "職種カテゴリ", "テンプレート種別", "テンプレートVer",
     "生成パス", "パターン", "年齢層", "資格", "経験区分", "希望雇用形態",
     "就業状況", "地域", "曜日", "時間帯", "全文", "返信", "返信日", "返信カテゴリ"],
]


def _sheets_writer_get_all_rows(sheet_name):
    if sheet_name == "テンプレート":
        return _TEMPLATE_ROWS
    return _SEND_DATA_EMPTY


IMPROVED_TEMPLATE = "改善された冒頭\\n{personalized_text}\\n改善された会社紹介"

DIAGNOSIS_WITH_PROMPT_TARGET = {
    "gate_scores": {"gate1_open": "C", "gate2_read": "B", "gate3_reply": "B"},
    "weak_principles": [
        {"principle": "返報性", "issue": "具体的評価なし", "severity": "high"}
    ],
    "ai_smell": [
        {"fingerprint": "接続詞偏り", "evidence": "さらに、また連続", "fix_hint": "接続詞を削る"}
    ],
    "structure_issues": [],
    "personalization_issues": [
        {"issue": "具体性不足", "detail": "経験年数への言及がない"}
    ],
    "integration_issues": [],
    "strengths": [],
    "priority_actions": [
        {"action": "冒頭を候補者評価に変更", "impact": "high", "target": "template"},
        {"action": "プロンプトに経験年数の言及を必須指示として追加", "impact": "high", "target": "prompt"},
    ],
    "improvement_targets": {"template": True, "prompt": True, "recipes": False},
}

DIAGNOSIS_TEMPLATE_ONLY = {
    "gate_scores": {"gate1_open": "B", "gate2_read": "A", "gate3_reply": "A"},
    "weak_principles": [],
    "ai_smell": [],
    "structure_issues": [
        {"issue": "会社紹介が長い", "detail": "テンプレの30%が会社紹介", "severity": "medium"}
    ],
    "personalization_issues": [],
    "integration_issues": [],
    "strengths": ["CTAが良い"],
    "priority_actions": [
        {"action": "会社紹介を短縮", "impact": "medium", "target": "template"},
    ],
    "improvement_targets": {"template": True, "prompt": False, "recipes": False},
}


@pytest.fixture
def client():
    app.dependency_overrides[verify_api_key] = _fake_operator
    yield TestClient(app)
    app.dependency_overrides.pop(verify_api_key, None)


@pytest.fixture
def mock_sheets_writer():
    with patch("api.routes_admin.sheets_writer") as sw:
        sw.get_all_rows = MagicMock(side_effect=_sheets_writer_get_all_rows)
        sw.ensure_sheet_exists = MagicMock()
        sw.append_rows = MagicMock()
        yield sw


@pytest.fixture
def mock_sheets_client():
    with patch("api.routes_admin.sheets_client") as sc:
        sc.get_company_profile = MagicMock(return_value="テスト会社プロフィール")
        sc.reload = MagicMock()
        yield sc


def _mock_improve_ai():
    """Mock AI that returns improved template with change reasons."""
    async def fake_generate(system_prompt, user_prompt, **kwargs):
        return GenerationResult(
            text=f"<!-- 変更理由: 冒頭を候補者評価に変更 -->\n{IMPROVED_TEMPLATE}",
            prompt_tokens=4000,
            output_tokens=1000,
            total_tokens=5000,
            model_name="gemini-2.5-pro",
        )
    return patch(
        "pipeline.ai_generator.generate_personalized_text",
        side_effect=fake_generate,
    )


class TestImproveWithDiagnosis:
    """Tests for improve_template with diagnosis parameter."""

    def test_improve_works_without_diagnosis(self, client, mock_sheets_writer, mock_sheets_client):
        """improve_template should still work without diagnosis (backwards compat)."""
        with _mock_improve_ai():
            resp = client.post("/api/v1/admin/improve_template", json={
                "company": "ark-visiting-nurse",
                "template_type": "正社員_default",
                "row_index": 2,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "improved" in data

    def test_improve_with_diagnosis_injects_into_prompt(self, client, mock_sheets_writer, mock_sheets_client):
        """When diagnosis is provided, its findings should be in the system prompt."""
        with _mock_improve_ai() as mock_ai:
            resp = client.post("/api/v1/admin/improve_template", json={
                "company": "ark-visiting-nurse",
                "template_type": "正社員_default",
                "row_index": 2,
                "diagnosis": DIAGNOSIS_WITH_PROMPT_TARGET,
            })
        assert resp.json()["status"] == "ok"

        # Verify system prompt includes diagnosis-derived content
        call_args = mock_ai.call_args
        system_prompt = call_args[0][0]
        assert "診断結果" in system_prompt or "優先改善" in system_prompt

    def test_improve_with_diagnosis_generates_proposals(self, client, mock_sheets_writer, mock_sheets_client):
        """When diagnosis flags prompt target, improvement proposals should be generated."""
        with _mock_improve_ai():
            resp = client.post("/api/v1/admin/improve_template", json={
                "company": "ark-visiting-nurse",
                "template_type": "正社員_default",
                "row_index": 2,
                "diagnosis": DIAGNOSIS_WITH_PROMPT_TARGET,
            })
        data = resp.json()
        assert data["status"] == "ok"
        assert "proposals" in data
        assert len(data["proposals"]) >= 1
        # Check proposal structure
        proposal = data["proposals"][0]
        assert "target_sheet" in proposal
        assert proposal["target_sheet"] in ("prompts", "patterns")

    def test_improve_with_template_only_diagnosis(self, client, mock_sheets_writer, mock_sheets_client):
        """When diagnosis only flags template, no proposals should be generated."""
        with _mock_improve_ai():
            resp = client.post("/api/v1/admin/improve_template", json={
                "company": "ark-visiting-nurse",
                "template_type": "正社員_default",
                "row_index": 2,
                "diagnosis": DIAGNOSIS_TEMPLATE_ONLY,
            })
        data = resp.json()
        assert data["status"] == "ok"
        assert data.get("proposals", []) == []

    def test_improve_proposals_written_to_sheet(self, client, mock_sheets_writer, mock_sheets_client):
        """Proposals should be written to 改善提案 sheet."""
        with _mock_improve_ai():
            client.post("/api/v1/admin/improve_template", json={
                "company": "ark-visiting-nurse",
                "template_type": "正社員_default",
                "row_index": 2,
                "diagnosis": DIAGNOSIS_WITH_PROMPT_TARGET,
            })
        # Check 改善提案 sheet was written to
        append_calls = mock_sheets_writer.append_rows.call_args_list
        proposal_calls = [c for c in append_calls if c[0][0] == "改善提案"]
        assert len(proposal_calls) >= 1

    def test_improve_with_analysis_summary_and_diagnosis(self, client, mock_sheets_writer, mock_sheets_client):
        """Both analysis_summary and diagnosis should be present in the prompt."""
        with _mock_improve_ai() as mock_ai:
            resp = client.post("/api/v1/admin/improve_template", json={
                "company": "ark-visiting-nurse",
                "template_type": "正社員_default",
                "row_index": 2,
                "directive": "冒頭をもっと短く",
                "analysis_summary": "返信率: 正社員_default 6.7%",
                "diagnosis": DIAGNOSIS_WITH_PROMPT_TARGET,
            })
        assert resp.json()["status"] == "ok"
        system_prompt = mock_ai.call_args[0][0]
        # Both analysis and diagnosis should be in prompt
        assert "分析データ" in system_prompt or "返信率" in system_prompt
        assert "診断結果" in system_prompt or "優先改善" in system_prompt
