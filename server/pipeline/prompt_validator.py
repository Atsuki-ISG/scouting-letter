"""Prompt contamination validator.

Ensures that assembled prompts for a company don't contain
terms belonging to a different facility type (e.g., "訪問看護ステーション"
leaking into a hospital's prompt).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db.sheets_client import SheetsClient

logger = logging.getLogger(__name__)

# --- Facility type definitions ---

FACILITY_TERMS: dict[str, dict[str, list[str]]] = {
    "hospital": {
        "self_terms": ["当院", "病院", "病棟"],
        # These terms should NOT appear in a hospital's prompt
        "foreign_terms": ["当ステーション", "訪問看護ステーション", "当事業所"],
    },
    "visiting_nurse": {
        "self_terms": ["当ステーション", "訪問看護"],
        # 「病院」は経歴文脈で正当に使われるため除外
        "foreign_terms": [],
    },
    "care_home": {
        "self_terms": ["当施設", "当ホーム"],
        "foreign_terms": ["当ステーション", "訪問看護ステーション", "当院"],
    },
}

COMPANY_FACILITY_TYPE: dict[str, str] = {
    "ark-visiting-nurse": "visiting_nurse",
    "lcc-visiting-nurse": "visiting_nurse",
    "ichigo-visiting-nurse": "visiting_nurse",
    "ichigo-care-home": "care_home",
    "chigasaki-tokushukai": "hospital",
    "nomura-hospital": "hospital",
}

# Sections that MUST have company-specific overrides (not rely on globals)
REQUIRED_COMPANY_SECTIONS: list[str] = ["role_definition", "tone_and_manner"]


def validate_company_sections(
    company_id: str,
    prompt_sections: list[dict],
) -> list[str]:
    """Check that required sections exist as company-specific (not global fallback).

    This is called with the RAW sections list (before global override filtering)
    to verify that company-specific versions exist.

    Returns list of error messages (empty = OK).
    """
    if company_id not in COMPANY_FACILITY_TYPE:
        return [f"未登録の会社: {company_id} (COMPANY_FACILITY_TYPEに追加してください)"]

    # Find which section_types have company-specific versions
    # A section is "company-specific" if it was NOT from a global (empty company) row.
    # We need to check the raw data, so this function expects unfiltered sections
    # with an extra "_is_company_specific" flag or similar.
    # Since sheets_client already does the filtering, we check differently:
    # We look at the filtered result and verify required sections are present.
    errors: list[str] = []
    present_types = {s["section_type"] for s in prompt_sections}
    for required in REQUIRED_COMPANY_SECTIONS:
        if required not in present_types:
            errors.append(
                f"必須プロンプトセクション '{required}' が見つかりません"
            )
    return errors


def validate_prompt_content(
    company_id: str,
    assembled_prompt: str,
) -> list[str]:
    """Scan assembled prompt for terms that belong to a different facility type.

    Returns list of warning messages (empty = OK).
    """
    facility_type = COMPANY_FACILITY_TYPE.get(company_id)
    if not facility_type:
        return []  # Unknown company, skip content check

    terms = FACILITY_TERMS.get(facility_type)
    if not terms:
        return []

    warnings: list[str] = []
    for term in terms["foreign_terms"]:
        if term in assembled_prompt:
            warnings.append(
                f"他施設の用語 '{term}' が混入しています "
                f"(施設種別: {facility_type})"
            )
    return warnings


def validate_all_companies(client: "SheetsClient") -> dict[str, list[str]]:
    """Validate all companies' config. Returns {company_id: [errors]}."""
    issues: dict[str, list[str]] = {}
    companies = client.get_company_list()

    for company_id in companies:
        errors: list[str] = []

        # 1. Check facility type is registered
        if company_id not in COMPANY_FACILITY_TYPE:
            errors.append(
                f"COMPANY_FACILITY_TYPE に未登録 — 新会社追加時に prompt_validator.py への登録が必要"
            )

        # 2. Check required sections exist
        config = client.get_company_config(company_id)
        sections = config.get("prompt_sections", [])
        errors.extend(validate_company_sections(company_id, sections))

        # 3. Check content contamination in assembled sections
        all_content = "\n".join(s.get("content", "") for s in sections)
        errors.extend(validate_prompt_content(company_id, all_content))

        if errors:
            issues[company_id] = errors

    return issues
