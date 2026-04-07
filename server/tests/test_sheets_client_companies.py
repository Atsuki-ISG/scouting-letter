"""Tests for sheets_client.get_companies_with_keywords with display_name support."""
from __future__ import annotations

import time

from db.sheets_client import (
    SHEET_PROFILES,
    SHEET_TEMPLATES,
    SheetsClient,
)


def _populate(client: SheetsClient, profile_rows, template_rows=None) -> None:
    """Inject fake cache data so the client doesn't hit Sheets."""
    client._cache = {
        SHEET_PROFILES: profile_rows,
        SHEET_TEMPLATES: template_rows or [],
        "パターン": [],
        "プロンプト": [],
        "求人": [],
        "バリデーション": [],
        "職種キーワード": [],
    }
    client._cache_time = time.time()


def test_get_companies_with_keywords_includes_display_name():
    client = SheetsClient()
    _populate(
        client,
        profile_rows=[
            {
                "company": "ark-visiting-nurse",
                "detection_keywords": "アーク,優希",
                "display_name": "アーク訪問看護",
                "content": "...",
            },
            {
                "company": "lcc-visiting-nurse",
                "detection_keywords": "LCC",
                "display_name": "LCC訪問看護",
                "content": "...",
            },
        ],
        template_rows=[
            {"company": "ark-visiting-nurse", "type": "パート_初回", "body": "x"},
            {"company": "lcc-visiting-nurse", "type": "パート_初回", "body": "y"},
        ],
    )
    result = client.get_companies_with_keywords()
    by_id = {c["id"]: c for c in result}
    assert by_id["ark-visiting-nurse"]["display_name"] == "アーク訪問看護"
    assert by_id["lcc-visiting-nurse"]["display_name"] == "LCC訪問看護"
    assert by_id["ark-visiting-nurse"]["detection_keywords"] == ["アーク", "優希"]


def test_get_companies_with_keywords_missing_display_name_falls_back_to_id():
    client = SheetsClient()
    _populate(
        client,
        profile_rows=[
            {
                "company": "ark-visiting-nurse",
                "detection_keywords": "アーク",
                # display_name omitted
                "content": "...",
            },
        ],
        template_rows=[
            {"company": "ark-visiting-nurse", "type": "パート_初回", "body": "x"},
        ],
    )
    result = client.get_companies_with_keywords()
    assert result[0]["id"] == "ark-visiting-nurse"
    # Fallback: use ID when display_name is missing
    assert result[0]["display_name"] == "ark-visiting-nurse"


def test_get_company_config_includes_company_display_name():
    client = SheetsClient()
    _populate(
        client,
        profile_rows=[
            {
                "company": "ark-visiting-nurse",
                "detection_keywords": "アーク",
                "display_name": "アーク訪問看護",
                "content": "...",
            },
        ],
        template_rows=[
            {"company": "ark-visiting-nurse", "type": "パート_初回", "body": "x"},
        ],
    )
    cfg = client.get_company_config("ark-visiting-nurse")
    assert cfg["company_display_name"] == "アーク訪問看護"
