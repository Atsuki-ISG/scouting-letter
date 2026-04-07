"""Tests for SHEET_FIX_FEEDBACK schema and reload integration."""
from __future__ import annotations

import time

from db.sheets_client import (
    ALL_SHEETS,
    SHEET_FIX_FEEDBACK,
    SheetsClient,
)


FIX_FEEDBACK_COLUMNS = [
    "id",
    "timestamp",
    "company",
    "member_id",
    "template_type",
    "before",
    "after",
    "reason",
    "status",
    "actor",
    "note",
]


def test_sheet_constant_defined():
    assert SHEET_FIX_FEEDBACK == "修正フィードバック"


def test_sheet_included_in_all_sheets():
    assert SHEET_FIX_FEEDBACK in ALL_SHEETS


def test_cache_can_hold_fix_feedback_rows():
    client = SheetsClient()
    client._cache = {name: [] for name in ALL_SHEETS}
    client._cache[SHEET_FIX_FEEDBACK] = [
        {col: "" for col in FIX_FEEDBACK_COLUMNS}
        | {
            "id": "fb_abc12345",
            "timestamp": "2026-04-07T10:00:00",
            "company": "ark-visiting-nurse",
            "member_id": "M001",
            "template_type": "パート_初回",
            "before": "before text",
            "after": "after text",
            "reason": "もっと丁寧に",
            "status": "pending",
            "actor": "operator",
            "note": "",
        }
    ]
    client._cache_time = time.time()
    rows = client._cache[SHEET_FIX_FEEDBACK]
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert rows[0]["reason"] == "もっと丁寧に"
