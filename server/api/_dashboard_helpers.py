"""Helpers for the send-count dashboard endpoints.

Reads:
- 送信_<会社名> sheets (per-company tool send logs) for category/job-offer/template breakdowns and trends
- 送信目標 sheet for manually-entered monthly targets
- 送信実績 sheet for the JobMedley remaining-count snapshots posted by the Chrome extension
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from db.sheets_writer import sheets_writer
from db.sheets_client import sheets_client
from pipeline.orchestrator import COMPANY_DISPLAY_NAMES, _send_data_sheet_name
from pipeline.job_category_resolver import resolve_job_category

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

TARGETS_SHEET = "送信目標"
TARGETS_HEADERS = ["company", "year_month", "target_count"]

QUOTA_SHEET = "送信実績"
QUOTA_HEADERS = ["company", "year_month", "snapshot_at", "remaining", "quota_hint"]

CATEGORY_DISPLAY = {
    "nurse": "看護師",
    "rehab_pt": "PT",
    "rehab_st": "ST",
    "rehab_ot": "OT",
    "medical_office": "医療事務",
    "care": "介護",
    "counselor": "相談員",
    "dietitian": "管理栄養士",
}


# ---------- shared helpers ----------

def now_jst() -> datetime:
    return datetime.now(JST)


def current_year_month() -> str:
    return now_jst().strftime("%Y-%m")


def month_display(year_month: str) -> str:
    """'2026-04' -> '4月'."""
    try:
        return f"{int(year_month.split('-')[1])}月"
    except (ValueError, IndexError):
        return year_month


def list_companies() -> list[tuple[str, str]]:
    """Return [(company_id, display_name), ...] for all configured companies."""
    return [(cid, name) for cid, name in COMPANY_DISPLAY_NAMES.items()]


def _row_to_dict(headers: list[str], row: list[str]) -> dict[str, str]:
    return {h.strip(): (row[i].strip() if i < len(row) else "") for i, h in enumerate(headers)}


# ---------- send data (tool send log) loader ----------

def load_send_rows(company_id: str) -> tuple[list[str], list[list[str]]]:
    """Read all rows from a company's send data sheet. Returns (headers, data_rows)."""
    sheet_name = _send_data_sheet_name(company_id)
    try:
        all_rows = sheets_writer.get_all_rows(sheet_name)
    except Exception as e:
        logger.warning(f"Failed to read {sheet_name}: {e}")
        return [], []
    if not all_rows or len(all_rows) < 2:
        return (all_rows[0] if all_rows else []), []
    return all_rows[0], all_rows[1:]


# Expected current schema (must match orchestrator.SEND_DATA_HEADERS)
EXPECTED_HEADERS = [
    "日時", "会員番号", "職種カテゴリ", "テンプレート種別", "テンプレートVer",
    "生成パス", "パターン", "年齢層", "資格", "経験区分",
    "希望雇用形態", "就業状況", "地域", "曜日", "時間帯",
    "返信", "返信日", "返信カテゴリ",
]
# Legacy schema used before 職種カテゴリ / テンプレートVer / 地域 were added
LEGACY_HEADERS = [
    "日時", "会員番号", "テンプレート種別", "生成パス", "パターン",
    "年齢層", "資格", "経験区分", "希望雇用形態", "就業状況",
    "曜日", "時間帯",
    "返信", "返信日", "返信カテゴリ",
]


def row_field(row: list[str], headers: list[str], field: str) -> str:
    """Look up a field in a row using header-based mapping, falling back to a best-effort
    match when the header row is out of date (schema drift fallback).

    This mitigates the historical bug where older 送信_* sheets kept their legacy header
    while newer data rows were appended with more columns.
    """
    # Primary: header-based lookup
    for i, h in enumerate(headers):
        if h.strip() == field and i < len(row):
            return row[i].strip()

    # Fallback: if header looks like legacy (15 cols) but row has 18, use expected schema positions
    if len(headers) == len(LEGACY_HEADERS) and len(row) == len(EXPECTED_HEADERS):
        try:
            idx = EXPECTED_HEADERS.index(field)
            return row[idx].strip() if idx < len(row) else ""
        except ValueError:
            return ""

    # Fallback: row is legacy (15 cols) — fields added later don't exist
    if len(row) == len(LEGACY_HEADERS):
        if field in ("職種カテゴリ", "テンプレートVer", "地域"):
            return ""
        try:
            idx = LEGACY_HEADERS.index(field)
            return row[idx].strip() if idx < len(row) else ""
        except ValueError:
            return ""

    return ""


def summarize_company_month(
    company_id: str,
    year_month: str,
) -> dict[str, Any]:
    """Aggregate one company's tool-sent rows for a given YYYY-MM."""
    headers, rows = load_send_rows(company_id)
    if not headers:
        return {"total": 0, "by_category": {}}

    total = 0
    by_category: dict[str, int] = {}
    for row in rows:
        date = row_field(row, headers, "日時")
        if not date or date[:7] != year_month:
            continue
        total += 1
        cat = row_field(row, headers, "職種カテゴリ")
        if not cat:
            qual = row_field(row, headers, "資格")
            cat = resolve_job_category(qual) or "" if qual else ""
        display = CATEGORY_DISPLAY.get(cat, cat) or "不明"
        by_category[display] = by_category.get(display, 0) + 1

    return {"total": total, "by_category": dict(sorted(by_category.items(), key=lambda x: -x[1]))}


def trend_company(
    company_id: str,
    end_year_month: str,
    months: int = 6,
) -> list[dict[str, Any]]:
    """Return last `months` months of tool-sent totals ending at end_year_month (inclusive)."""
    try:
        end_dt = datetime.strptime(end_year_month, "%Y-%m")
    except ValueError:
        end_dt = now_jst().replace(day=1)

    headers, rows = load_send_rows(company_id)
    if not headers:
        return [{"year_month": _shift_month(end_dt, -i).strftime("%Y-%m"), "tool_sent": 0}
                for i in range(months - 1, -1, -1)]

    counts: dict[str, int] = {}
    for row in rows:
        date = row_field(row, headers, "日時")
        if not date:
            continue
        ym = date[:7]
        counts[ym] = counts.get(ym, 0) + 1

    result = []
    for i in range(months - 1, -1, -1):
        ym = _shift_month(end_dt, -i).strftime("%Y-%m")
        result.append({"year_month": ym, "tool_sent": counts.get(ym, 0)})
    return result


def _shift_month(dt: datetime, delta: int) -> datetime:
    year = dt.year
    month = dt.month + delta
    while month <= 0:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return dt.replace(year=year, month=month, day=1)


# ---------- per-company detail (job offer / template breakdown) ----------

def detail_company_month(company_id: str, year_month: str) -> dict[str, Any]:
    """Build job-offer-level and template-level breakdowns for a company in a given month."""
    headers, rows = load_send_rows(company_id)
    if not headers:
        return {"by_job_offer": [], "by_template": []}

    job_offers = sheets_client._get_job_offers(company_id) or []

    def lookup_offer_label(job_category: str, employment_type_hint: str) -> str:
        for offer in job_offers:
            if offer.get("job_category") != job_category:
                continue
            offer_emp = offer.get("employment_type", "")
            if employment_type_hint and offer_emp and employment_type_hint not in offer_emp:
                continue
            return offer.get("label") or offer.get("name") or ""
        for offer in job_offers:
            if offer.get("job_category") == job_category:
                return offer.get("label") or offer.get("name") or ""
        return ""

    job_offer_counts: dict[tuple[str, str], int] = {}
    template_counts: dict[tuple[str, str], int] = {}

    for row in rows:
        date = row_field(row, headers, "日時")
        if not date or date[:7] != year_month:
            continue
        cat = row_field(row, headers, "職種カテゴリ")
        if not cat:
            qual = row_field(row, headers, "資格")
            cat = resolve_job_category(qual) or "" if qual else ""
        ttype = row_field(row, headers, "テンプレート種別")
        tver = row_field(row, headers, "テンプレートVer")

        if not cat and not ttype:
            continue
        key = (cat or "", ttype or "")
        job_offer_counts[key] = job_offer_counts.get(key, 0) + 1
        tkey = (ttype or "", tver or "")
        template_counts[tkey] = template_counts.get(tkey, 0) + 1

    by_job_offer = []
    for (cat, ttype), count in sorted(job_offer_counts.items(), key=lambda x: -x[1]):
        emp_hint = ttype.split("_")[0] if ttype else ""
        label = lookup_offer_label(cat, emp_hint)
        by_job_offer.append({
            "job_category": cat,
            "job_category_display": CATEGORY_DISPLAY.get(cat, cat),
            "template_type": ttype,
            "label": label,
            "count": count,
        })

    by_template = [
        {"template_type": ttype, "version": ver, "count": count}
        for (ttype, ver), count in sorted(template_counts.items(), key=lambda x: -x[1])
    ]

    return {"by_job_offer": by_job_offer, "by_template": by_template}


# ---------- targets sheet ----------

def _ensure_targets_sheet() -> None:
    sheets_writer.ensure_sheet_exists(TARGETS_SHEET, TARGETS_HEADERS)


def load_targets(year_month: str) -> dict[str, int]:
    _ensure_targets_sheet()
    try:
        rows = sheets_writer.get_all_rows(TARGETS_SHEET)
    except Exception as e:
        logger.warning(f"Failed to read {TARGETS_SHEET}: {e}")
        return {}
    if not rows or len(rows) < 2:
        return {}
    headers = rows[0]
    col = {h.strip(): i for i, h in enumerate(headers)}
    c_idx = col.get("company", 0)
    ym_idx = col.get("year_month", 1)
    tc_idx = col.get("target_count", 2)
    result: dict[str, int] = {}
    for row in rows[1:]:
        if len(row) <= max(c_idx, ym_idx, tc_idx):
            continue
        if row[ym_idx].strip() != year_month:
            continue
        try:
            result[row[c_idx].strip()] = int(row[tc_idx].strip() or 0)
        except ValueError:
            continue
    return result


def upsert_targets(year_month: str, targets: list[dict[str, Any]]) -> None:
    """Upsert (company, year_month) -> target_count rows."""
    _ensure_targets_sheet()
    try:
        rows = sheets_writer.get_all_rows(TARGETS_SHEET)
    except Exception:
        rows = []

    headers = rows[0] if rows else TARGETS_HEADERS
    col = {h.strip(): i for i, h in enumerate(headers)}
    c_idx = col.get("company", 0)
    ym_idx = col.get("year_month", 1)
    tc_idx = col.get("target_count", 2)

    # Build index: (company, year_month) -> sheet row number (1-indexed including header)
    index: dict[tuple[str, str], int] = {}
    for i, row in enumerate(rows[1:], start=2):
        if len(row) <= max(c_idx, ym_idx):
            continue
        index[(row[c_idx].strip(), row[ym_idx].strip())] = i

    for target in targets:
        company_id = str(target.get("company_id", "")).strip()
        if not company_id:
            continue
        try:
            count = int(target.get("target_count", 0))
        except (ValueError, TypeError):
            continue
        key = (company_id, year_month)
        if key in index:
            sheets_writer.update_row(TARGETS_SHEET, index[key], [company_id, year_month, str(count)])
        else:
            sheets_writer.append_row(TARGETS_SHEET, [company_id, year_month, str(count)])


# ---------- quota snapshots sheet ----------

def _ensure_quota_sheet() -> None:
    sheets_writer.ensure_sheet_exists(QUOTA_SHEET, QUOTA_HEADERS)


def load_quota_snapshots(year_month: str) -> dict[str, dict[str, Any]]:
    """Return {company_id: {remaining, snapshot_at, quota_hint}}."""
    _ensure_quota_sheet()
    try:
        rows = sheets_writer.get_all_rows(QUOTA_SHEET)
    except Exception as e:
        logger.warning(f"Failed to read {QUOTA_SHEET}: {e}")
        return {}
    if not rows or len(rows) < 2:
        return {}
    headers = rows[0]
    col = {h.strip(): i for i, h in enumerate(headers)}
    c_idx = col.get("company", 0)
    ym_idx = col.get("year_month", 1)
    sa_idx = col.get("snapshot_at", 2)
    rem_idx = col.get("remaining", 3)
    qh_idx = col.get("quota_hint", 4)

    result: dict[str, dict[str, Any]] = {}
    for row in rows[1:]:
        if len(row) <= max(c_idx, ym_idx):
            continue
        if row[ym_idx].strip() != year_month:
            continue
        try:
            remaining = int(row[rem_idx].strip()) if rem_idx < len(row) and row[rem_idx].strip() else None
        except ValueError:
            remaining = None
        try:
            quota_hint = int(row[qh_idx].strip()) if qh_idx < len(row) and row[qh_idx].strip() else None
        except ValueError:
            quota_hint = None
        result[row[c_idx].strip()] = {
            "remaining": remaining,
            "snapshot_at": row[sa_idx].strip() if sa_idx < len(row) else "",
            "quota_hint": quota_hint,
        }
    return result


def upsert_quota_snapshot(company_id: str, remaining: int) -> dict[str, Any]:
    """Upsert (company, current_year_month) with new remaining value.

    On the first snapshot of a month, also store quota_hint = remaining (= the plan quota at month start).
    """
    _ensure_quota_sheet()
    year_month = current_year_month()
    snapshot_at = now_jst().strftime("%Y-%m-%dT%H:%M:%S+09:00")

    try:
        rows = sheets_writer.get_all_rows(QUOTA_SHEET)
    except Exception:
        rows = []

    headers = rows[0] if rows else QUOTA_HEADERS
    col = {h.strip(): i for i, h in enumerate(headers)}
    c_idx = col.get("company", 0)
    ym_idx = col.get("year_month", 1)
    qh_idx = col.get("quota_hint", 4)

    existing_row_idx = None
    existing_quota_hint = ""
    for i, row in enumerate(rows[1:], start=2):
        if len(row) <= max(c_idx, ym_idx):
            continue
        if row[c_idx].strip() == company_id and row[ym_idx].strip() == year_month:
            existing_row_idx = i
            if qh_idx < len(row):
                existing_quota_hint = row[qh_idx].strip()
            break

    # Quota hint policy: keep existing if set; otherwise initialise from this remaining
    quota_hint_value = existing_quota_hint or str(remaining)

    new_row = [company_id, year_month, snapshot_at, str(remaining), quota_hint_value]
    if existing_row_idx is not None:
        sheets_writer.update_row(QUOTA_SHEET, existing_row_idx, new_row)
    else:
        sheets_writer.append_row(QUOTA_SHEET, new_row)

    return {
        "company_id": company_id,
        "year_month": year_month,
        "snapshot_at": snapshot_at,
        "remaining": remaining,
        "quota_hint": int(quota_hint_value) if quota_hint_value else None,
    }
