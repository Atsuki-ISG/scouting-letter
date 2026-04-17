"""Tests for the knowledge extraction API endpoint.

TDD tests for Part B Step 9.
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
def mock_sheets_writer():
    with patch("api.routes_admin.sheets_writer") as sw:
        sw.ensure_sheet_exists = MagicMock()
        sw.append_rows = MagicMock()
        yield sw


def _mock_ai_extract():
    """Return a patch context for AI extraction."""
    async def fake_generate(system_prompt, user_prompt, **kwargs):
        return GenerationResult(
            text='- [tone] 「感銘を受ける」は経験への使用禁止\n- [expression] 送り手の感情を主語にしない\n- [qualification] 求人職種と同一の資格言及は不要',
            prompt_tokens=100,
            output_tokens=50,
            total_tokens=150,
            model_name="mock",
        )
    return patch(
        "pipeline.ai_generator.generate_personalized_text",
        side_effect=fake_generate,
    )


def test_extract_knowledge_endpoint(client, mock_sheets_writer):
    """POST /admin/extract_knowledge should extract rules and write to knowledge pool."""
    with _mock_ai_extract():
        response = client.post(
            "/api/v1/admin/extract_knowledge",
            json={
                "company": "ark-visiting-nurse",
                "analysis_text": "分析結果テキスト...",
                "source": "分析 2026-04-13",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert len(data["extracted_rules"]) >= 1


def test_extract_knowledge_writes_to_sheet(client, mock_sheets_writer):
    """Extracted rules should be written to the knowledge pool sheet."""
    with _mock_ai_extract():
        client.post(
            "/api/v1/admin/extract_knowledge",
            json={
                "company": "ark-visiting-nurse",
                "analysis_text": "テスト分析",
                "source": "テスト",
            },
        )
    # Should have called ensure_sheet_exists and append_rows
    mock_sheets_writer.ensure_sheet_exists.assert_called_once()
    mock_sheets_writer.append_rows.assert_called_once()
    rows = mock_sheets_writer.append_rows.call_args[0][1]
    assert len(rows) >= 1
    # Each row should have status=pending
    for row in rows:
        assert "pending" in row


def test_extract_knowledge_empty_analysis(client, mock_sheets_writer):
    """Empty analysis text should return error."""
    response = client.post(
        "/api/v1/admin/extract_knowledge",
        json={
            "company": "test",
            "analysis_text": "",
        },
    )
    assert response.status_code == 200
    assert response.json().get("status") == "error"


def _mock_ai_extract_with_template_tip():
    """AI returns a mix of valid categories and the retired template_tip."""
    async def fake_generate(system_prompt, user_prompt, **kwargs):
        return GenerationResult(
            text=(
                "- [tone] 「感銘を受ける」は経験への使用禁止\n"
                "- [template_tip] 東京都指定の教育ステーションを冒頭に\n"  # retired
                "- [expression] 「お持ちとのこと」は回りくどい敬語でNG\n"
                "- [unknown_cat] 何か\n"  # invalid category
            ),
            prompt_tokens=100,
            output_tokens=50,
            total_tokens=150,
            model_name="mock",
        )
    return patch(
        "pipeline.ai_generator.generate_personalized_text",
        side_effect=fake_generate,
    )


def test_extract_knowledge_skips_template_tip_category(client, mock_sheets_writer):
    """template_tip is no longer a valid pool category — must be dropped.

    Previously template_tip was the fallback for unknown categories. Now it
    is removed entirely: template-level hooks go to the improvement flow,
    not the persistent rule pool.
    """
    with _mock_ai_extract_with_template_tip():
        response = client.post(
            "/api/v1/admin/extract_knowledge",
            json={
                "company": "ark-visiting-nurse",
                "analysis_text": "テスト",
            },
        )
    data = response.json()
    assert data["status"] == "ok"
    cats = {r["category"] for r in data["extracted_rules"]}
    assert "template_tip" not in cats
    assert "unknown_cat" not in cats
    # Only the two valid categories should survive
    assert cats == {"tone", "expression"}
