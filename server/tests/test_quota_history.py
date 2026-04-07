"""Tests for the append-only quota history sheet."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from api._dashboard_helpers import (
    QUOTA_HISTORY_HEADERS,
    QUOTA_HISTORY_SHEET,
    append_quota_history,
    load_quota_history,
)


@pytest.fixture
def mock_writer():
    with patch("api._dashboard_helpers.sheets_writer") as m:
        yield m


class TestAppendQuotaHistory:
    def test_appends_with_generated_id(self, mock_writer):
        mock_writer.get_all_rows.return_value = [QUOTA_HISTORY_HEADERS]
        result = append_quota_history(
            company_id="ark-visiting-nurse",
            year_month="2026-04",
            snapshot_at="2026-04-07T10:00:00+09:00",
            remaining=120,
            quota_hint=200,
            source="extension",
        )
        assert result["id"]
        assert result["id"].startswith("qh_")
        mock_writer.ensure_sheet_exists.assert_called_with(
            QUOTA_HISTORY_SHEET, QUOTA_HISTORY_HEADERS
        )
        mock_writer.append_row.assert_called_once()
        sheet, row = mock_writer.append_row.call_args[0]
        assert sheet == QUOTA_HISTORY_SHEET
        assert len(row) == len(QUOTA_HISTORY_HEADERS)
        # column order: id, company, year_month, snapshot_at, remaining, quota_hint, source
        assert row[QUOTA_HISTORY_HEADERS.index("company")] == "ark-visiting-nurse"
        assert row[QUOTA_HISTORY_HEADERS.index("year_month")] == "2026-04"
        assert row[QUOTA_HISTORY_HEADERS.index("remaining")] == "120"
        assert row[QUOTA_HISTORY_HEADERS.index("quota_hint")] == "200"
        assert row[QUOTA_HISTORY_HEADERS.index("source")] == "extension"

    def test_default_source_is_extension(self, mock_writer):
        mock_writer.get_all_rows.return_value = [QUOTA_HISTORY_HEADERS]
        append_quota_history(
            company_id="x",
            year_month="2026-04",
            snapshot_at="2026-04-07T10:00:00+09:00",
            remaining=10,
            quota_hint=100,
        )
        row = mock_writer.append_row.call_args[0][1]
        assert row[QUOTA_HISTORY_HEADERS.index("source")] == "extension"


class TestLoadQuotaHistory:
    def test_returns_filtered_by_company_and_month_sorted_asc(self, mock_writer):
        rows = [
            QUOTA_HISTORY_HEADERS,
            ["qh_1", "ark-visiting-nurse", "2026-04", "2026-04-07T08:00:00+09:00", "200", "200", "extension"],
            ["qh_2", "ark-visiting-nurse", "2026-04", "2026-04-07T15:00:00+09:00", "180", "200", "extension"],
            ["qh_3", "ark-visiting-nurse", "2026-04", "2026-04-08T09:00:00+09:00", "150", "200", "extension"],
            ["qh_4", "lcc-visiting-nurse", "2026-04", "2026-04-07T10:00:00+09:00", "100", "150", "extension"],
            ["qh_5", "ark-visiting-nurse", "2026-03", "2026-03-31T18:00:00+09:00", "5", "200", "extension"],
        ]
        mock_writer.get_all_rows.return_value = rows
        items = load_quota_history("ark-visiting-nurse", "2026-04")
        assert [i["id"] for i in items] == ["qh_1", "qh_2", "qh_3"]
        # ascending by snapshot_at
        ts = [i["snapshot_at"] for i in items]
        assert ts == sorted(ts)

    def test_returns_empty_when_sheet_missing(self, mock_writer):
        mock_writer.get_all_rows.side_effect = Exception("not found")
        items = load_quota_history("ark-visiting-nurse", "2026-04")
        assert items == []

    def test_returns_all_for_company_when_no_month(self, mock_writer):
        rows = [
            QUOTA_HISTORY_HEADERS,
            ["qh_1", "ark-visiting-nurse", "2026-03", "2026-03-31T18:00:00+09:00", "5", "200", "extension"],
            ["qh_2", "ark-visiting-nurse", "2026-04", "2026-04-01T09:00:00+09:00", "200", "200", "extension"],
        ]
        mock_writer.get_all_rows.return_value = rows
        items = load_quota_history("ark-visiting-nurse", None)
        assert len(items) == 2
