"""Tests for the knowledge pool feature (Sheets reading + prompt injection).

TDD tests for Part B Steps 6-8.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from db.sheets_client import SheetsClient, _parse_sheet


# ---------------------------------------------------------------------------
# Step 6-7: Knowledge pool reading from sheets_client
# ---------------------------------------------------------------------------

class TestGetKnowledgePool:
    """Verify _get_knowledge_pool filters and returns correct rules."""

    def _make_client_with_cache(self, rows: list[dict]) -> SheetsClient:
        """Create a SheetsClient with pre-populated cache."""
        client = SheetsClient()
        client._cache = {"ナレッジプール": rows}
        client._cache_time = 9999999999.0  # far future, always valid
        return client

    def test_returns_approved_rules_only(self):
        rows = [
            {"company": "", "category": "tone", "rule": "rule1", "status": "approved"},
            {"company": "", "category": "tone", "rule": "rule2", "status": "pending"},
            {"company": "", "category": "tone", "rule": "rule3", "status": "rejected"},
        ]
        client = self._make_client_with_cache(rows)
        rules = client.get_knowledge_pool("test-company")
        assert len(rules) == 1
        assert rules[0]["rule"] == "rule1"

    def test_returns_global_and_company_rules(self):
        rows = [
            {"company": "", "category": "tone", "rule": "global_rule", "status": "approved"},
            {"company": "test-company", "category": "expression", "rule": "company_rule", "status": "approved"},
            {"company": "other-company", "category": "tone", "rule": "other_rule", "status": "approved"},
        ]
        client = self._make_client_with_cache(rows)
        rules = client.get_knowledge_pool("test-company")
        assert len(rules) == 2
        rule_texts = [r["rule"] for r in rules]
        assert "global_rule" in rule_texts
        assert "company_rule" in rule_texts
        assert "other_rule" not in rule_texts

    def test_empty_pool(self):
        client = self._make_client_with_cache([])
        rules = client.get_knowledge_pool("test-company")
        assert rules == []

    def test_preserves_category(self):
        rows = [
            {"company": "", "category": "qualification", "rule": "資格ルール", "status": "approved"},
        ]
        client = self._make_client_with_cache(rows)
        rules = client.get_knowledge_pool("test-company")
        assert rules[0]["category"] == "qualification"


# ---------------------------------------------------------------------------
# Step 8: Knowledge injection into system prompt (already tested in
# test_personalized_scout_prompt.py, but verify the integration path)
# ---------------------------------------------------------------------------

class TestKnowledgePoolIntegration:
    """Verify the pipeline passes knowledge rules to the prompt builder."""

    def test_knowledge_rules_format(self):
        """Knowledge rules should be a list of strings for prompt injection."""
        from pipeline.personalized_scout.prompt import build_system_prompt

        rules = ["NG表現: 「感銘を受ける」", "送り手感情を主語にしない"]
        prompt = build_system_prompt(
            level="L3",
            company_profile="テスト",
            prompt_sections_text="",
            template_body="test",
            knowledge_rules=rules,
        )
        assert "## ナレッジ（蓄積されたルール）" in prompt
        assert "- NG表現: 「感銘を受ける」" in prompt
        assert "- 送り手感情を主語にしない" in prompt
