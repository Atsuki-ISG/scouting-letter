"""Unit tests for competitor research sheet read/write helpers.

Covers the reader (sheets_client.get_competitor_research) with its
exact-match / empty-category-fallback behavior, plus the writer's
insert-vs-update branching logic.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from db.sheets_client import (
    SHEET_COMPETITOR_RESEARCH,
    COMPETITOR_RESEARCH_HEADERS,
    SheetsClient,
)


def _row(**overrides: str) -> dict[str, str]:
    """Build a full competitor_research row dict with blanks + overrides."""
    base = {h: "" for h in COMPETITOR_RESEARCH_HEADERS}
    base.update(overrides)
    return base


class TestGetCompetitorResearch:
    def _client_with_rows(self, rows: list[dict]) -> SheetsClient:
        c = SheetsClient()
        # Seed cache so _ensure_cache() is a no-op.
        c._cache = {SHEET_COMPETITOR_RESEARCH: rows}
        c._cache_time = 1e18  # far future → cache valid
        return c

    def test_returns_none_when_empty(self):
        c = self._client_with_rows([])
        assert c.get_competitor_research("ark-visiting-nurse") is None

    def test_exact_match_on_company_and_category(self):
        c = self._client_with_rows([
            _row(company="ark-visiting-nurse", job_category="nurse", hooks="a"),
            _row(company="ark-visiting-nurse", job_category="rehab_pt", hooks="b"),
        ])
        result = c.get_competitor_research("ark-visiting-nurse", "rehab_pt")
        assert result is not None
        assert result["hooks"] == "b"

    def test_falls_back_to_empty_category(self):
        c = self._client_with_rows([
            _row(company="ark-visiting-nurse", job_category="", hooks="global"),
            _row(company="other", job_category="nurse", hooks="other"),
        ])
        result = c.get_competitor_research("ark-visiting-nurse", "nurse")
        assert result is not None
        assert result["hooks"] == "global"

    def test_exact_match_preferred_over_fallback(self):
        c = self._client_with_rows([
            _row(company="ark-visiting-nurse", job_category="", hooks="global"),
            _row(company="ark-visiting-nurse", job_category="nurse", hooks="specific"),
        ])
        result = c.get_competitor_research("ark-visiting-nurse", "nurse")
        assert result["hooks"] == "specific"

    def test_parses_json_list_columns(self):
        c = self._client_with_rows([
            _row(
                company="x",
                sources='["https://a.com", "https://b.com"]',
                competitors_list='[{"name": "A"}, {"name": "B"}]',
            ),
        ])
        result = c.get_competitor_research("x")
        assert result["sources"] == ["https://a.com", "https://b.com"]
        assert result["competitors_list"] == [{"name": "A"}, {"name": "B"}]

    def test_parses_newline_delimited_sources_as_fallback(self):
        c = self._client_with_rows([
            _row(company="x", sources="https://a.com\nhttps://b.com"),
        ])
        result = c.get_competitor_research("x")
        assert result["sources"] == ["https://a.com", "https://b.com"]

    def test_restores_newline_escapes(self):
        c = self._client_with_rows([
            _row(company="x", culture_narrative="line1\\nline2"),
        ])
        result = c.get_competitor_research("x")
        assert result["culture_narrative"] == "line1\nline2"


class TestUpsertCompetitorResearch:
    @pytest.fixture
    def writer(self):
        from db.sheets_writer import SheetsWriter
        w = SheetsWriter()
        w._service = MagicMock()
        return w

    def test_insert_when_no_match(self, writer):
        header_row = list(COMPETITOR_RESEARCH_HEADERS)
        with patch.object(writer, "ensure_sheet_exists"), \
             patch.object(writer, "get_all_rows", return_value=[header_row]), \
             patch.object(writer, "append_row") as append_mock, \
             patch.object(writer, "update_cells_by_name") as update_mock:
            result = writer.upsert_competitor_research(
                company="ark-visiting-nurse",
                job_category="nurse",
                data={"hooks": "- hook1"},
                actor="tester",
            )
        assert result["action"] == "insert"
        append_mock.assert_called_once()
        update_mock.assert_not_called()

        sheet_arg, values_arg = append_mock.call_args[0]
        assert sheet_arg == SHEET_COMPETITOR_RESEARCH
        row_dict = dict(zip(header_row, values_arg))
        assert row_dict["company"] == "ark-visiting-nurse"
        assert row_dict["job_category"] == "nurse"
        assert row_dict["hooks"] == "- hook1"
        assert row_dict["updated_by"] == "tester"
        assert row_dict["updated_at"]  # non-empty timestamp

    def test_update_when_match_exists(self, writer):
        header_row = list(COMPETITOR_RESEARCH_HEADERS)
        existing = [""] * len(header_row)
        existing[header_row.index("company")] = "ark-visiting-nurse"
        existing[header_row.index("job_category")] = "nurse"
        existing[header_row.index("hooks")] = "old"

        with patch.object(writer, "ensure_sheet_exists"), \
             patch.object(writer, "get_all_rows", return_value=[header_row, existing]), \
             patch.object(writer, "append_row") as append_mock, \
             patch.object(writer, "update_cells_by_name") as update_mock:
            result = writer.upsert_competitor_research(
                company="ark-visiting-nurse",
                job_category="nurse",
                data={"hooks": "new"},
                actor="tester",
            )
        assert result["action"] == "update"
        assert result["row_index"] == 2
        append_mock.assert_not_called()
        update_mock.assert_called_once()
        call_kwargs = update_mock.call_args
        assert call_kwargs[0][0] == SHEET_COMPETITOR_RESEARCH
        assert call_kwargs[0][1] == 2
        cells = call_kwargs[0][2]
        assert cells["hooks"] == "new"
        assert cells["company"] == "ark-visiting-nurse"
        assert cells["job_category"] == "nurse"

    def test_match_ignores_other_company(self, writer):
        header_row = list(COMPETITOR_RESEARCH_HEADERS)
        other = [""] * len(header_row)
        other[header_row.index("company")] = "other-co"
        other[header_row.index("job_category")] = "nurse"

        with patch.object(writer, "ensure_sheet_exists"), \
             patch.object(writer, "get_all_rows", return_value=[header_row, other]), \
             patch.object(writer, "append_row") as append_mock, \
             patch.object(writer, "update_cells_by_name") as update_mock:
            result = writer.upsert_competitor_research(
                company="ark-visiting-nurse",
                job_category="nurse",
                data={"hooks": "x"},
                actor="tester",
            )
        assert result["action"] == "insert"
        append_mock.assert_called_once()
        update_mock.assert_not_called()
