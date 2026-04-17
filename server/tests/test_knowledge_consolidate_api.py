"""Tests for the knowledge pool consolidation API.

consolidate_knowledge: AI proposes merged/pruned rules, nothing is written.
apply_consolidation: archives old rows (status=archived) + appends new rules.
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


# Realistic pool: 5 approved rows, 2 duplicates + 1 vague
_POOL_ROWS = [
    ["id", "company", "category", "rule", "source", "status", "created_at"],
    # row 2
    ["1", "", "tone", "敬語は丁寧すぎず親しみやすく", "seed", "approved", "2026-01-01"],
    # row 3  — duplicate-ish of row 2
    ["2", "", "tone", "硬すぎない丁寧語を使う", "seed", "approved", "2026-01-02"],
    # row 4
    ["3", "ark-visiting-nurse", "expression", "感銘を受けるは経験への使用禁止", "learnings", "approved", "2026-02-01"],
    # row 5 — vague, should be pruned
    ["4", "", "tone", "適切に対応する", "seed", "approved", "2026-03-01"],
    # row 6 — pending, should be ignored
    ["5", "", "expression", "句点で終わる", "seed", "pending", "2026-04-01"],
]


@pytest.fixture
def mock_sheets_writer():
    with patch("api.routes_admin.sheets_writer") as sw:
        sw.get_all_rows = MagicMock(return_value=_POOL_ROWS)
        sw.update_cells_by_name = MagicMock(return_value={"updated": ["status"], "skipped": []})
        sw.append_rows = MagicMock()
        sw.ensure_sheet_exists = MagicMock()
        yield sw


def _mock_ai_consolidation():
    async def fake_generate(system_prompt, user_prompt, **kwargs):
        # Merges rows 2+3, drops row 5 (vague), AND also tries to archive row
        # 6 (which is pending → not a candidate → must be rejected by the
        # endpoint's safety filter).
        return GenerationResult(
            text=(
                "## 新ルール集\n"
                "- [tone] 敬語は丁寧すぎず親しみやすく（硬すぎない丁寧語）\n"
                "- [expression] 感銘を受けるは経験への使用禁止\n"
                "\n"
                "## 廃止対象の行番号\n"
                "2, 3, 5, 6\n"
                "\n"
                "## 理由\n"
                "1. 行2と行3は同義のためマージ\n"
                "2. 行5は抽象的すぎるため廃止\n"
            ),
            prompt_tokens=200,
            output_tokens=80,
            total_tokens=280,
            model_name="mock",
        )
    return patch(
        "pipeline.ai_generator.generate_personalized_text",
        side_effect=fake_generate,
    )


def test_consolidate_proposes_without_writing(client, mock_sheets_writer):
    """consolidate_knowledge returns a proposal; writes nothing yet."""
    with _mock_ai_consolidation():
        response = client.post(
            "/api/v1/admin/consolidate_knowledge",
            json={"company": "ark-visiting-nurse", "categories": ["tone", "expression"]},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert len(data["proposed_rules"]) == 2
    # Rows 2, 3, 5 are approved candidates → allowed in archive list
    assert 2 in data["archive_row_indexes"]
    assert 3 in data["archive_row_indexes"]
    assert 5 in data["archive_row_indexes"]
    # Row 6 is pending (not a candidate) — AI suggested archiving it, but
    # the endpoint's safety filter must drop it.
    assert 6 not in data["archive_row_indexes"]
    # No writes yet
    mock_sheets_writer.append_rows.assert_not_called()
    mock_sheets_writer.update_cells_by_name.assert_not_called()


def test_consolidate_skips_when_few_candidates(client, mock_sheets_writer):
    """If fewer than 2 rules match the filter, return a no-op proposal."""
    # Override to a pool with just 1 matching row
    mock_sheets_writer.get_all_rows.return_value = [
        _POOL_ROWS[0],
        _POOL_ROWS[1],
    ]
    response = client.post(
        "/api/v1/admin/consolidate_knowledge",
        json={"company": "", "categories": ["tone"]},
    )
    data = response.json()
    assert data["status"] == "ok"
    assert data["archive_row_indexes"] == []
    assert len(data["proposed_rules"]) == 1


def test_apply_consolidation_archives_and_appends(client, mock_sheets_writer):
    """apply_consolidation: archive old rows (status=archived) + append new rules."""
    response = client.post(
        "/api/v1/admin/apply_consolidation",
        json={
            "company": "ark-visiting-nurse",
            "archive_row_indexes": [2, 3, 5],
            "new_rules": [
                {"category": "tone", "rule": "統合された新ルール"},
                {"category": "expression", "rule": "別カテゴリのルール"},
                {"category": "invalid_cat", "rule": "これは弾かれる"},
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    # 3 archive calls (even if row 5 is pending, apply_consolidation trusts the caller)
    assert mock_sheets_writer.update_cells_by_name.call_count == 3
    # Each archive must set status=archived
    for call in mock_sheets_writer.update_cells_by_name.call_args_list:
        _, kwargs = call
        # positional args: (sheet, row_index, cells)
        assert call.args[2] == {"status": "archived"}
    # append_rows called once with 2 valid rules (invalid_cat dropped)
    mock_sheets_writer.append_rows.assert_called_once()
    appended = mock_sheets_writer.append_rows.call_args[0][1]
    assert len(appended) == 2
    # New rules land with status=approved (pre-approved by the consolidation)
    for row in appended:
        assert "approved" in row


def test_apply_consolidation_rejects_bad_input(client, mock_sheets_writer):
    """archive_row_indexes / new_rules must be arrays."""
    response = client.post(
        "/api/v1/admin/apply_consolidation",
        json={
            "archive_row_indexes": "2,3",  # not a list
            "new_rules": [],
        },
    )
    assert response.status_code == 400
