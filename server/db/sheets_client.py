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
  プロフィール: company, content, detection_keywords
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
SHEET_PROFILES = "プロフィール"
SHEET_LOGS = "生成ログ"
SHEET_JOB_CATEGORY_KEYWORDS = "職種キーワード"
SHEET_FIX_FEEDBACK = "修正フィードバック"
SHEET_IMPROVEMENT_PROPOSALS = "改善提案"
SHEET_CONVERSATION_LOGS = "会話ログ"
SHEET_KNOWLEDGE_POOL = "ナレッジプール"

_JOB_CATEGORY_DISPLAY_NAMES: dict[str, str] = {
    "nurse": "看護師",
    "rehab_pt": "理学療法士",
    "rehab_st": "言語聴覚士",
    "rehab_ot": "作業療法士",
    "medical_office": "医療事務",
    "dietitian": "管理栄養士",
    "counselor": "相談支援専門員",
    "sales": "入居相談員",
}


def label_for_category(category_id: str) -> str:
    """Return the Japanese display label for a job category ID.

    Unknown IDs are returned as-is so the caller still gets a non-empty string.
    """
    if not category_id:
        return category_id
    return _JOB_CATEGORY_DISPLAY_NAMES.get(category_id, category_id)


def label_for_categories(category_ids) -> list[str]:
    """Map an iterable of category IDs to their Japanese display labels."""
    return [label_for_category(c) for c in category_ids]

ALL_SHEETS = [
    SHEET_TEMPLATES,
    SHEET_PATTERNS,
    SHEET_PROMPT_SECTIONS,
    SHEET_JOB_OFFERS,
    SHEET_VALIDATION,
    SHEET_PROFILES,
    SHEET_JOB_CATEGORY_KEYWORDS,
    SHEET_FIX_FEEDBACK,
    SHEET_KNOWLEDGE_POOL,
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

        # Discover which sheets actually exist in the spreadsheet
        spreadsheet_meta = service.spreadsheets().get(
            spreadsheetId=SPREADSHEET_ID, fields="sheets.properties.title"
        ).execute()
        existing_sheets = {
            s["properties"]["title"] for s in spreadsheet_meta.get("sheets", [])
        }

        # Only request sheets that exist
        sheets_to_load = [name for name in ALL_SHEETS if name in existing_sheets]
        missing = [name for name in ALL_SHEETS if name not in existing_sheets]
        if missing:
            logger.warning(f"Sheets not found (skipped): {missing}")

        for name in ALL_SHEETS:
            self._cache[name] = []  # default empty

        if sheets_to_load:
            ranges = [f"'{name}'!A:Z" for name in sheets_to_load]
            result = (
                service.spreadsheets()
                .values()
                .batchGet(spreadsheetId=SPREADSHEET_ID, ranges=ranges)
                .execute()
            )
            value_ranges = result.get("valueRanges", [])
            for i, name in enumerate(sheets_to_load):
                rows = value_ranges[i].get("values", []) if i < len(value_ranges) else []
                self._cache[name] = _parse_sheet(rows)

        self._cache_time = time.time()
        total = sum(len(v) for v in self._cache.values())
        logger.info(f"Sheets reloaded: {total} rows from {len(ALL_SHEETS)} sheets")

        # Validate all companies on reload
        try:
            from pipeline.prompt_validator import validate_all_companies
            issues = validate_all_companies(self)
            for company, errors in issues.items():
                for err in errors:
                    logger.error(f"[CONFIG VALIDATION] {company}: {err}")
            if not issues:
                logger.info("[CONFIG VALIDATION] All companies passed validation")
        except Exception as e:
            logger.warning(f"[CONFIG VALIDATION] Validation skipped: {e}")

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

    def get_companies_with_keywords(self) -> list[dict[str, Any]]:
        """Return company list with detection keywords and display name from profile sheet."""
        self._ensure_cache()
        # Build keyword + display_name maps from profiles
        keyword_map: dict[str, list[str]] = {}
        display_name_map: dict[str, str] = {}
        for row in self._cache.get(SHEET_PROFILES, []):
            c = row.get("company", "").strip()
            if not c:
                continue
            kw = row.get("detection_keywords", "").strip()
            if kw:
                keyword_map[c] = [k.strip() for k in kw.split(",") if k.strip()]
            dn = row.get("display_name", "").strip()
            if dn:
                display_name_map[c] = dn

        return [
            {
                "id": c,
                "detection_keywords": keyword_map.get(c, []),
                # Fall back to ID so the UI never shows an empty string
                "display_name": display_name_map.get(c, c),
            }
            for c in self.get_company_list()
        ]

    def get_company_display_name(self, company_id: str) -> str:
        """Return the operator-facing display name for a company, or the ID if missing."""
        self._ensure_cache()
        for row in self._cache.get(SHEET_PROFILES, []):
            if row.get("company", "").strip() == company_id:
                dn = row.get("display_name", "").strip()
                if dn:
                    return dn
        return company_id

    _reload_in_progress: bool = False

    def get_company_config(self, company_id: str) -> dict[str, Any]:
        """Get all config for a company.

        If the cache returns zero templates for the requested company, the
        data may have been added to Sheets after the last cache load (common
        when CACHE_TTL_SECONDS=0). In that case, force ONE reload and retry
        so newly-registered companies are picked up without manual intervention.

        The _reload_in_progress guard prevents infinite recursion when
        validate_all_companies (called inside reload) calls get_company_config.
        """
        self._ensure_cache()
        templates = self._get_templates(company_id)

        if not templates and not self._reload_in_progress:
            logger.info(
                f"[{company_id}] テンプレート0件 — キャッシュをリロードしてリトライします"
            )
            self._reload_in_progress = True
            try:
                self.reload()
            finally:
                self._reload_in_progress = False
            templates = self._get_templates(company_id)

        return {
            "templates": templates,
            "patterns": self._get_patterns(company_id),
            "qualification_modifiers": self._get_qualification_modifiers(company_id),
            "prompt_sections": self._get_prompt_sections(company_id),
            "job_offers": self._get_job_offers(company_id),
            "validation_config": self._get_validation_config(company_id),
            "job_categories": self._get_job_categories(templates),
            "employment_types": self._get_employment_types(templates),
            "job_category_keywords": self._get_job_category_keywords(company_id),
            "company_display_name": self.get_company_display_name(company_id),
            "examples": [],  # examples are managed via /save-example skill
        }

    def _get_job_category_keywords(self, company_id: str) -> list[dict]:
        """Return job category keywords (global + company-specific) for the given company.

        Sheet columns: company, job_category, keyword, source_fields, weight, enabled, added_at, added_by, note

        - company="" rows are global (apply to all companies)
        - company=<id> rows are company-specific overrides (added on top of globals)
        - enabled="FALSE" rows are skipped
        """
        rows = self._cache.get(SHEET_JOB_CATEGORY_KEYWORDS, [])
        result: list[dict] = []
        for row in rows:
            if row.get("enabled", "TRUE").upper() == "FALSE":
                continue
            row_company = row.get("company", "").strip()
            if row_company and row_company != company_id:
                continue
            keyword = row.get("keyword", "").strip()
            job_category = row.get("job_category", "").strip()
            if not keyword or not job_category:
                continue
            source_fields = [
                f.strip() for f in row.get("source_fields", "").split(",") if f.strip()
            ]
            if not source_fields:
                # default: search both qualification and free text fields
                source_fields = ["qualification", "desired", "experience", "pr"]
            result.append({
                "keyword": keyword,
                "job_category": job_category,
                "source_fields": source_fields,
                "weight": _safe_int(row.get("weight", "1"), 1),
                "company": row_company,  # "" for global, company id for override
            })
        return result

    def _get_job_categories(self, templates: dict[str, dict]) -> list[dict[str, str]]:
        """Extract unique job categories from templates with display names."""
        categories: set[str] = set()
        for tpl in templates.values():
            jc = tpl.get("job_category", "")
            if jc:
                categories.add(jc)
        return sorted(
            [{"id": c, "display_name": _JOB_CATEGORY_DISPLAY_NAMES.get(c, c)} for c in categories],
            key=lambda x: list(_JOB_CATEGORY_DISPLAY_NAMES.keys()).index(x["id"])
            if x["id"] in _JOB_CATEGORY_DISPLAY_NAMES else 999,
        )

    _EMPLOYMENT_TYPE_DISPLAY_NAMES: dict[str, str] = {
        "パート": "パート",
        "正社員": "正社員",
        "契約": "契約社員",
    }

    _EMPLOYMENT_TYPE_ORDER = ["パート", "正社員", "契約"]

    def _get_employment_types(self, templates: dict[str, dict]) -> list[dict[str, str]]:
        """Extract unique employment types from template type field (prefix before '_')."""
        types: set[str] = set()
        for tpl in templates.values():
            ttype = tpl.get("type", "")
            if "_" in ttype:
                emp = ttype.split("_")[0]
                if emp:
                    types.add(emp)
        return sorted(
            [{"id": t, "display_name": self._EMPLOYMENT_TYPE_DISPLAY_NAMES.get(t, t)} for t in types],
            key=lambda x: self._EMPLOYMENT_TYPE_ORDER.index(x["id"])
            if x["id"] in self._EMPLOYMENT_TYPE_ORDER else 999,
        )

    def get_knowledge_pool(self, company_id: str) -> list[dict]:
        """Return approved knowledge rules for a company (global + company-specific).

        Sheet columns: id, company, category, rule, source, status, created_at
        Only status='approved' rows are returned.
        Global rules (company='') apply to all companies.
        """
        self._ensure_cache()
        rows = self._cache.get(SHEET_KNOWLEDGE_POOL, [])
        result: list[dict] = []
        for row in rows:
            if (row.get("status") or "").strip().lower() != "approved":
                continue
            row_company = (row.get("company") or "").strip()
            if row_company and row_company != company_id:
                continue
            rule = (row.get("rule") or "").strip()
            if not rule:
                continue
            result.append({
                "company": row_company,
                "category": (row.get("category") or "").strip(),
                "rule": rule,
                "source": (row.get("source") or "").strip(),
            })
        return result

    def get_company_profile(self, company_id: str) -> str:
        """Return the profile markdown text for a company, or empty string if not found."""
        self._ensure_cache()
        rows = self._cache.get(SHEET_PROFILES, [])
        for row in rows:
            if row.get("company") == company_id:
                return row.get("content", "").replace("\\n", "\n")
        return ""

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
                "version": row.get("version", "1"),
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
        global_sections: list[dict] = []
        company_sections: list[dict] = []
        for row in rows:
            company = row.get("company", "")
            if company and company != company_id:
                continue
            item = {
                "section_type": row.get("section_type", ""),
                "job_category": row.get("job_category", ""),
                "order": _safe_int(row.get("order", "0")),
                "content": row.get("content", "").replace("\\n", "\n"),
            }
            if company:
                company_sections.append(item)
            else:
                global_sections.append(item)

        # Company-specific sections override globals with same section_type+job_category
        company_keys = {
            (s["section_type"], s["job_category"]) for s in company_sections
        }
        result = [
            s for s in global_sections
            if (s["section_type"], s["job_category"]) not in company_keys
        ] + company_sections
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
