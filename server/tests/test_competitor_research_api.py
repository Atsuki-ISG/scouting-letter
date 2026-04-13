"""Tests for the competitor research API endpoint.

TDD: Gemini + Google Search grounding で競合調査→ナレッジプール投入。
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app
from auth.api_key import verify_api_key
from pipeline.ai_generator import GenerationResult


def _fake_operator():
    return {"operator_id": "t", "name": "t", "role": "admin"}


@pytest.fixture
def client():
    app.dependency_overrides[verify_api_key] = _fake_operator
    yield TestClient(app)
    app.dependency_overrides.pop(verify_api_key, None)


@pytest.fixture
def mock_sheets_client():
    with patch("api.routes_admin.sheets_client") as sc:
        sc.get_company_profile.return_value = "## ARK訪問看護\n所在地: 北海道札幌市\n訪問看護ステーション"
        sc.get_company_display_name.return_value = "ARK訪問看護"
        sc.get_company_config.return_value = {
            "job_categories": [{"id": "nurse", "display_name": "看護師"}],
            "templates": {},
            "job_offers": [],
        }
        yield sc


@pytest.fixture
def mock_sheets_writer():
    with patch("api.routes_admin.sheets_writer") as sw:
        sw.ensure_sheet_exists = MagicMock()
        sw.append_rows = MagicMock()
        yield sw


def _mock_gemini_search():
    """Mock Gemini with search grounding response."""
    async def fake_generate(system_prompt, user_prompt, **kwargs):
        return GenerationResult(
            text="""## 競合施設一覧
| 施設名 | 給与 | 特色 |
|--------|------|------|
| A訪問看護 | 月給30万 | 教育充実 |
| B訪問看護 | 月給28万 | 24時間対応 |

## 🔍 隠れた強み・差別化の種

### 発見1: 札幌市内で認知症特化は希少
根拠: 競合5施設中、認知症ケアを前面に出しているのは1施設のみ
活用案: 「認知症ケアの経験を活かせる環境」をスカウト文のフックに
確認事項: 実際の認知症利用者比率をクライアントに確認

## スカウト文への活用提案
- 「札幌市内で認知症ケアに特化した訪問看護として」
- 「スタッフあたりの利用者数が少なく、一人ひとりに向き合える環境」

## 💡 ヒアリング提案
- 「競合と比較して御社のスタッフ定着率が高い印象ですが、その要因は何だとお考えですか？」""",
            prompt_tokens=500,
            output_tokens=300,
            total_tokens=800,
            model_name="gemini-2.5-flash",
        )
    return patch(
        "pipeline.ai_generator.generate_personalized_text",
        side_effect=fake_generate,
    )


def test_research_competitors_endpoint(client, mock_sheets_client, mock_sheets_writer):
    """POST /admin/research_competitors should return analysis with hidden strengths."""
    with _mock_gemini_search():
        response = client.post(
            "/api/v1/admin/research_competitors",
            json={"company": "ark-visiting-nurse"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "analysis" in data
    assert "隠れた強み" in data["analysis"]


def test_research_competitors_writes_knowledge(client, mock_sheets_client, mock_sheets_writer):
    """Extracted scout hooks should be written to knowledge pool."""
    with _mock_gemini_search():
        response = client.post(
            "/api/v1/admin/research_competitors",
            json={
                "company": "ark-visiting-nurse",
                "save_to_knowledge": True,
            },
        )
    data = response.json()
    assert data["status"] == "ok"
    assert data.get("knowledge_count", 0) >= 1
    mock_sheets_writer.ensure_sheet_exists.assert_called()
    mock_sheets_writer.append_rows.assert_called()


def test_research_competitors_with_job_category(client, mock_sheets_client, mock_sheets_writer):
    """Should accept optional job_category parameter."""
    with _mock_gemini_search():
        response = client.post(
            "/api/v1/admin/research_competitors",
            json={
                "company": "ark-visiting-nurse",
                "job_category": "nurse",
            },
        )
    assert response.status_code == 200


def test_research_competitors_empty_company(client, mock_sheets_client):
    """Empty company should return error."""
    response = client.post(
        "/api/v1/admin/research_competitors",
        json={"company": ""},
    )
    assert response.status_code == 200
    assert response.json().get("status") == "error"
