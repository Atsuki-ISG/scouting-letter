"""Google Sheets client for reading company config data.

Reads all config from a single spreadsheet with multiple sheets.
Data is cached in memory and refreshed on demand via reload().

Expected sheets and columns:

  テンプレート: company, job_category, type, body
  パターン: company, job_category, pattern_type, employment_variant, template_text, feature_variations,
            display_name, target_description, match_rules, qualification_combo, replacement_text
            (pattern_type="QUAL" rows are qualification modifiers)
  プロンプト: company, section_type, job_category, order, content
  求人: company, job_category, id, name, label, employment_type, active
  バリデーション: company, age_min, age_max, qualification_rules
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import google.auth
from googleapiclient.discovery import build

from config import SPREADSHEET_ID, CACHE_TTL_SECONDS

logger = logging.getLogger(__name__)


def _safe_int(value: str | None, default: int = 0) -> int:
    """Convert a string to int, returning default on failure."""
    if not value:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


# Sheet names
SHEET_TEMPLATES = "テンプレート"
SHEET_PATTERNS = "パターン"
SHEET_PROMPT_SECTIONS = "プロンプト"
SHEET_JOB_OFFERS = "求人"
SHEET_VALIDATION = "バリデーション"
SHEET_LOGS = "生成ログ"

ALL_SHEETS = [
    SHEET_TEMPLATES,
    SHEET_PATTERNS,
    SHEET_PROMPT_SECTIONS,
    SHEET_JOB_OFFERS,
    SHEET_VALIDATION,
]


def _parse_sheet(rows: list[list[str]]) -> list[dict[str, str]]:
    """Parse sheet rows (first row = header) into list of dicts."""
    if not rows or len(rows) < 2:
        return []
    headers = [h.strip() for h in rows[0]]
    result = []
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue  # skip empty rows
        item = {}
        for i, header in enumerate(headers):
            item[header] = row[i].strip() if i < len(row) else ""
        result.append(item)
    return result


class SheetsClient:
    def __init__(self) -> None:
        self._service = None
        self._cache: dict[str, list[dict[str, str]]] = {}
        self._cache_time: float = 0

    def _get_service(self):
        if self._service is None:
            credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
            )
            self._service = build("sheets", "v4", credentials=credentials)
        return self._service

    def _is_cache_valid(self) -> bool:
        if not self._cache:
            return False
        if CACHE_TTL_SECONDS <= 0:
            return True  # manual reload only
        return (time.time() - self._cache_time) < CACHE_TTL_SECONDS

    def reload(self) -> None:
        """Reload all data from the spreadsheet."""
        if not SPREADSHEET_ID:
            logger.warning("SPREADSHEET_ID not set, using empty config")
            self._cache = {name: [] for name in ALL_SHEETS}
            self._cache_time = time.time()
            return

        service = self._get_service()
        # Batch read all sheets
        ranges = [f"'{name}'!A:Z" for name in ALL_SHEETS]
        result = (
            service.spreadsheets()
            .values()
            .batchGet(spreadsheetId=SPREADSHEET_ID, ranges=ranges)
            .execute()
        )

        value_ranges = result.get("valueRanges", [])
        for i, name in enumerate(ALL_SHEETS):
            rows = value_ranges[i].get("values", []) if i < len(value_ranges) else []
            self._cache[name] = _parse_sheet(rows)

        self._cache_time = time.time()
        total = sum(len(v) for v in self._cache.values())
        logger.info(f"Sheets reloaded: {total} rows from {len(ALL_SHEETS)} sheets")

    def _ensure_cache(self) -> None:
        if not self._is_cache_valid():
            self.reload()

    def get_company_list(self) -> list[str]:
        """Return sorted list of unique company IDs across all sheets."""
        self._ensure_cache()
        companies: set[str] = set()
        for rows in self._cache.values():
            for row in rows:
                c = row.get("company", "").strip()
                if c:
                    companies.add(c)
        return sorted(companies)

    def get_company_config(self, company_id: str) -> dict[str, Any]:
        """Get all config for a company."""
        self._ensure_cache()
        return {
            "templates": self._get_templates(company_id),
            "patterns": self._get_patterns(company_id),
            "qualification_modifiers": self._get_qualification_modifiers(company_id),
            "prompt_sections": self._get_prompt_sections(company_id),
            "job_offers": self._get_job_offers(company_id),
            "validation_config": self._get_validation_config(company_id),
            "examples": [],  # examples are managed via /save-example skill
        }

    def _get_templates(self, company_id: str) -> dict[str, dict]:
        """Return templates keyed by 'job_category:type' (or just 'type' if no job_category)."""
        rows = self._cache.get(SHEET_TEMPLATES, [])
        result = {}
        for row in rows:
            if row.get("company") != company_id:
                continue
            ttype = row.get("type", "")
            jc = row.get("job_category", "").strip()
            # Key with job_category prefix when present
            key = f"{jc}:{ttype}" if jc else ttype
            result[key] = {
                "type": ttype,
                "job_category": jc,
                "body": row.get("body", "").replace("\\n", "\n"),
            }
        return result

    def _get_patterns(self, company_id: str) -> list[dict]:
        rows = self._cache.get(SHEET_PATTERNS, [])
        result = []
        for row in rows:
            if row.get("company") != company_id:
                continue
            if row.get("pattern_type") == "QUAL":
                continue  # qualification modifier rows handled separately
            feature_str = row.get("feature_variations", "")
            features = [f.strip() for f in feature_str.split("|") if f.strip()] if feature_str else []
            item = {
                "pattern_type": row.get("pattern_type", ""),
                "job_category": row.get("job_category", ""),
                "template_text": row.get("template_text", "").replace("\\n", "\n"),
                "feature_variations": features,
                "display_name": row.get("display_name", ""),
                "target_description": row.get("target_description", ""),
            }
            variant = row.get("employment_variant", "")
            if variant:
                item["employment_variant"] = variant
            # Parse match_rules JSON
            rules_str = row.get("match_rules", "")
            if rules_str:
                import json
                try:
                    item["match_rules"] = json.loads(rules_str)
                except (json.JSONDecodeError, TypeError):
                    item["match_rules"] = []
            else:
                item["match_rules"] = []
            result.append(item)
        return result

    def _get_qualification_modifiers(self, company_id: str) -> list[dict]:
        """Get qualification modifiers from QUAL rows in the patterns sheet."""
        rows = self._cache.get(SHEET_PATTERNS, [])
        result = []
        for row in rows:
            if row.get("company") != company_id:
                continue
            if row.get("pattern_type") != "QUAL":
                continue
            combo_str = row.get("qualification_combo", "")
            combo = [q.strip() for q in combo_str.split(",") if q.strip()]
            result.append({
                "qualification_combo": combo,
                "replacement_text": row.get("replacement_text", "").replace("\\n", "\n"),
            })
        return result

    def _get_prompt_sections(self, company_id: str) -> list[dict]:
        rows = self._cache.get(SHEET_PROMPT_SECTIONS, [])
        result = []
        for row in rows:
            company = row.get("company", "")
            # Include global sections (empty company) and company-specific
            if company and company != company_id:
                continue
            result.append({
                "section_type": row.get("section_type", ""),
                "job_category": row.get("job_category", ""),
                "order": _safe_int(row.get("order", "0")),
                "content": row.get("content", "").replace("\\n", "\n"),
            })
        result.sort(key=lambda x: x["order"])
        return result

    def _get_job_offers(self, company_id: str) -> list[dict]:
        rows = self._cache.get(SHEET_JOB_OFFERS, [])
        result = []
        for row in rows:
            if row.get("company") != company_id:
                continue
            if row.get("active", "TRUE").upper() != "TRUE":
                continue
            result.append({
                "id": row.get("id", ""),
                "name": row.get("name", ""),
                "label": row.get("label", ""),
                "job_category": row.get("job_category", ""),
                "employment_type": row.get("employment_type", ""),
            })
        return result

    def _get_validation_config(self, company_id: str) -> dict:
        rows = self._cache.get(SHEET_VALIDATION, [])
        for row in rows:
            if row.get("company") != company_id:
                continue
            config = {}
            age_min = row.get("age_min", "")
            age_max = row.get("age_max", "")
            if age_min or age_max:
                config["age_range"] = {
                    "min": _safe_int(age_min, 0),
                    "max": _safe_int(age_max, 999),
                }
            rules_str = row.get("qualification_rules", "")
            if rules_str:
                try:
                    config["qualification_rules"] = json.loads(rules_str)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid qualification_rules JSON for {company_id}")
            cat_excl_str = row.get("category_exclusions", "")
            if cat_excl_str:
                try:
                    config["category_exclusions"] = json.loads(cat_excl_str)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid category_exclusions JSON for {company_id}")
            cat_config_str = row.get("category_config", "")
            if cat_config_str:
                try:
                    config["category_config"] = json.loads(cat_config_str)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid category_config JSON for {company_id}")
            return config
        return {}


sheets_client = SheetsClient()
