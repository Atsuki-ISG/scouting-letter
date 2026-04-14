"""Admin CRUD routes for Google Sheets data management."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

from db.sheets_writer import sheets_writer
from db.sheets_client import sheets_client, SHEET_FIX_FEEDBACK, SHEET_CONVERSATION_LOGS
from auth.api_key import verify_api_key

router = APIRouter(prefix="/admin", tags=["admin"])

# Slug to Japanese sheet name mapping
SHEET_MAP = {
    "templates": "テンプレート",
    "patterns": "パターン",
    "qualifiers": "パターン",  # QUAL rows in patterns sheet
    "prompts": "プロンプト",
    "job_offers": "求人",
    "validation": "バリデーション",
    "logs": "生成ログ",
    "profiles": "プロフィール",
    "job_category_keywords": "職種キーワード",
    "knowledge_pool": "ナレッジプール",
}

# Column order for each sheet (must match header row)
COLUMNS = {
    "templates": ["company", "job_category", "type", "body", "version"],
    "patterns": ["company", "job_category", "pattern_type", "employment_variant", "template_text", "feature_variations", "display_name", "target_description", "match_rules", "qualification_combo", "replacement_text"],
    "qualifiers": ["company", "job_category", "pattern_type", "employment_variant", "template_text", "feature_variations", "display_name", "target_description", "match_rules", "qualification_combo", "replacement_text"],
    "prompts": ["company", "section_type", "job_category", "order", "content"],
    "job_offers": ["company", "job_category", "id", "name", "label", "employment_type", "active"],
    "validation": ["company", "age_min", "age_max", "qualification_rules", "category_exclusions", "category_config"],
    "logs": ["timestamp", "company", "member_id", "job_category", "template_type", "generation_path", "pattern_type", "status", "detail", "personalized_text_preview", "prompt_tokens", "output_tokens", "estimated_cost", "failure_stage", "failure_missing_fields", "failure_searched_text", "failure_company_categories", "failure_human_message"],
    "profiles": ["company", "content", "detection_keywords"],
    "job_category_keywords": ["company", "job_category", "keyword", "source_fields", "weight", "enabled", "added_at", "added_by", "note"],
    "knowledge_pool": ["id", "company", "category", "rule", "source", "status", "created_at"],
}


DASHBOARD_SPREADSHEET_ID = "1a3XE212nZgsQP-93phk22VlSSZ5aD1ig72M4A6p2awE"


# ---------------------------------------------------------------------------
# Template body version-bump helper.
#
# Used by both the single-row PUT endpoint and batch_update_templates so
# the version increment / history logging / no-op detection are defined
# in exactly one place.
# ---------------------------------------------------------------------------

def _normalize_body(value: str) -> str:
    """Canonicalize template body for equality comparison.

    The sheet stores bodies with literal backslash-n sequences; the admin
    UI and AI generator sometimes round-trip through real newlines. Treat
    both forms as the same content when deciding if a change happened.
    """
    return (value or "").replace("\r\n", "\n").replace("\\n", "\n")


def _escape_body_for_sheets(value: str) -> str:
    """Escape real newlines to literal \\n for Sheets storage.

    The convention is that template body cells in Google Sheets use
    literal two-character ``\\n`` sequences instead of real newlines.
    The reader (sheets_client) converts them back on load.
    """
    return (value or "").replace("\r\n", "\\n").replace("\n", "\\n")


def _bump_template_body(
    row_index: int,
    new_body: str,
    *,
    reason: str,
    actor: str,
    expected_company: Optional[str] = None,
) -> dict:
    """Apply a template body update with version increment + change history.

    Returns a dict describing what happened:
        {
          "status": "updated" | "no-op" | "skipped",
          "row_index": int,
          "old_version": str,
          "new_version": str,
          "reason": <reason if skipped>,
        }

    Guarantees:
    - Header cells are always stripped before lookup, so whitespace in the
      sheet header never desyncs version tracking.
    - Body equality is checked on normalized (real-newline) form.
    - When `expected_company` is given, the row must match that company
      or the update is skipped (returns status="skipped").
    - `update_cells_by_name` is called with `strict_columns=["body", "version"]`
      so a missing version column surfaces as a loud error rather than a
      silent skip.

    Raises ValueError for bad row_index, missing required columns, etc.
    Callers should translate to HTTP responses as appropriate.
    """
    from datetime import timedelta, timezone
    JST = timezone(timedelta(hours=9))

    all_rows = sheets_writer.get_all_rows("テンプレート")
    if not all_rows:
        raise ValueError("テンプレートシートが空です")
    if row_index < 2 or row_index > len(all_rows):
        raise ValueError(
            f"row_index {row_index} out of range (valid: 2..{len(all_rows)})"
        )

    headers = [h.strip() for h in all_rows[0]]
    required = {"company", "body", "version"}
    missing = [c for c in required if c not in headers]
    if missing:
        raise ValueError(
            f"テンプレートシートに必須列がありません: {missing} (headers={headers})"
        )

    existing_row = list(all_rows[row_index - 1])
    existing_row += [""] * (len(headers) - len(existing_row))
    existing = {headers[i]: existing_row[i] for i in range(len(headers))}

    row_company = (existing.get("company", "") or "").strip()
    if expected_company is not None and row_company != expected_company:
        return {
            "status": "skipped",
            "row_index": row_index,
            "reason": f"company mismatch: row={row_company} expected={expected_company}",
            "old_version": existing.get("version", ""),
            "new_version": existing.get("version", ""),
        }

    old_body_norm = _normalize_body(existing.get("body", ""))
    new_body_norm = _normalize_body(new_body)
    if old_body_norm == new_body_norm:
        return {
            "status": "no-op",
            "row_index": row_index,
            "old_version": existing.get("version", ""),
            "new_version": existing.get("version", ""),
        }

    old_version_raw = (existing.get("version", "") or "").strip()
    try:
        new_version = str(int(old_version_raw or "1") + 1)
    except (ValueError, TypeError):
        new_version = "2"
    # If the existing cell was blank, treat the bump as going from
    # an implicit "1" so the new value is "2".
    old_version_display = old_version_raw or "1"

    # Log history FIRST (so we always have the pre-change snapshot even
    # if the cell update fails part-way).
    try:
        sheets_writer.ensure_sheet_exists("テンプレート変更履歴", [
            "timestamp", "company", "job_category", "type",
            "old_version", "new_version", "reason", "old_body",
        ])
        sheets_writer.append_row("テンプレート変更履歴", [
            datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
            existing.get("company", ""),
            existing.get("job_category", ""),
            existing.get("type", ""),
            old_version_display,
            new_version,
            reason,
            existing.get("body", ""),
        ])
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to log template history: {e}")

    # Strict column mode: body and version MUST be present. Missing
    # columns raise so we never bump silently without a version record.
    # Always escape real newlines to literal \n for Sheets storage.
    sheets_writer.update_cells_by_name(
        "テンプレート",
        row_index,
        {"body": _escape_body_for_sheets(new_body), "version": new_version},
        actor=actor,
        strict_columns=["body", "version"],
    )
    return {
        "status": "updated",
        "row_index": row_index,
        "old_version": old_version_display,
        "new_version": new_version,
    }


@router.get("/server_info")
async def server_info(operator=Depends(verify_api_key)):
    """Return server metadata for admin help page."""
    from config import SPREADSHEET_ID
    result = {}
    if SPREADSHEET_ID:
        result["spreadsheet_url"] = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"
    result["dashboard_url"] = f"https://docs.google.com/spreadsheets/d/{DASHBOARD_SPREADSHEET_ID}/edit"
    return result


@router.get("/prompt_preview")
async def prompt_preview(company: str, operator=Depends(verify_api_key)):
    """Preview how the system prompt is assembled for a company."""
    from pipeline.prompt_builder import build_system_prompt, build_user_prompt
    from models.profile import CandidateProfile

    config = sheets_client.get_company_config(company)

    # Use a sample template (パート_初回) - try first available
    template_data = None
    for key in config["templates"]:
        if key.endswith("パート_初回") or key == "パート_初回":
            template_data = config["templates"][key]
            break
    template_data = template_data or {}
    template_body = template_data.get("body", "(テンプレート未設定)")

    system_prompt = build_system_prompt(
        config["prompt_sections"],
        template_body,
        config.get("examples"),
    )

    # Build a dummy user prompt to show format
    dummy = CandidateProfile(
        member_id="SAMPLE",
        qualifications="看護師",
        experience_type="病棟看護",
        experience_years="5年",
        employment_status="就業中",
        age="35歳",
        self_pr="患者様一人ひとりに寄り添った看護を心がけてきました。",
        work_history_summary="急性期病棟3年、回復期病棟2年",
    )
    user_prompt = build_user_prompt(dummy, "nurse")

    # Build section breakdown
    sections = []
    for sec in config.get("prompt_sections", []):
        content = sec.get("content", "")
        if content and content.strip():
            sections.append({
                "section_type": sec.get("section_type", ""),
                "content": content.strip()[:200],
            })

    return {
        "system_prompt": system_prompt,
        "user_prompt_example": user_prompt,
        "sections": sections,
        "template_used": "パート_初回",
        "flow": [
            "1. プロフィール受信",
            "2. 職種カテゴリ判定（資格から自動）",
            "3. テンプレート種別判定（パート/正社員 × 初回/再送）",
            "4. バリデーション（年齢・資格・AI条件）",
            "5a. 経歴あり → AI生成（system prompt + user prompt）",
            "5b. 経歴なし → 型はめ（パターンマッチング）",
            "6. テンプレートにパーソナライズ文を挿入",
            "7. 求人ID解決 → 完成",
        ],
    }


@router.get("/validate")
async def validate_config(
    company: Optional[str] = None,
    operator=Depends(verify_api_key),
):
    """Validate company config for prompt contamination and missing sections."""
    from pipeline.prompt_validator import (
        validate_all_companies,
        validate_company_sections,
        validate_prompt_content,
    )

    if company:
        config = sheets_client.get_company_config(company)
        sections = config.get("prompt_sections", [])
        errors = validate_company_sections(company, sections)
        all_content = "\n".join(s.get("content", "") for s in sections)
        errors.extend(validate_prompt_content(company, all_content))
        return {"company": company, "errors": errors, "ok": len(errors) == 0}

    issues = validate_all_companies(sheets_client)
    companies = sheets_client.get_company_list()
    results = {}
    for c in companies:
        errors = issues.get(c, [])
        results[c] = {"errors": errors, "ok": len(errors) == 0}
    all_ok = all(r["ok"] for r in results.values())
    return {"results": results, "all_ok": all_ok}


# --- Send summary endpoint ---

@router.get("/send_summary")
async def send_summary(
    company: Optional[str] = None,
    operator: dict = Depends(verify_api_key),
):
    """今月の送信数サマリー（職種カテゴリ別）を返す。"""
    from datetime import datetime, timedelta, timezone
    from pipeline.orchestrator import _send_data_sheet_name, COMPANY_DISPLAY_NAMES
    from pipeline.job_category_resolver import resolve_qualification_only

    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    current_month = now.strftime("%Y-%m")

    # カテゴリ表示名
    CATEGORY_DISPLAY = {
        "nurse": "看護師",
        "rehab_pt": "PT",
        "rehab_st": "ST",
        "rehab_ot": "OT",
        "medical_office": "医療事務",
        "care": "介護",
        "counselor": "相談員",
    }

    companies_to_scan = [company] if company else list(COMPANY_DISPLAY_NAMES.keys())
    total = 0
    by_category: dict[str, int] = {}

    for cid in companies_to_scan:
        sheet_name = _send_data_sheet_name(cid)
        try:
            all_rows = sheets_writer.get_all_rows(sheet_name)
        except Exception:
            continue
        if len(all_rows) < 2:
            continue

        headers = all_rows[0]
        col_map = {h.strip(): i for i, h in enumerate(headers)}
        date_idx = col_map.get("日時", 0)
        cat_idx = col_map.get("職種カテゴリ")
        qual_idx = col_map.get("資格")

        for row in all_rows[1:]:
            if len(row) <= date_idx:
                continue
            row_date = row[date_idx][:7]  # YYYY-MM
            if row_date != current_month:
                continue
            total += 1

            # 職種カテゴリ取得（列があれば使う、なければ資格から推定）
            cat = ""
            if cat_idx is not None and cat_idx < len(row):
                cat = row[cat_idx].strip()
            if not cat and qual_idx is not None and qual_idx < len(row):
                cat = resolve_qualification_only(row[qual_idx]) or ""

            display = CATEGORY_DISPLAY.get(cat, cat) or "不明"
            by_category[display] = by_category.get(display, 0) + 1

    # 件数降順でソート
    by_category_sorted = dict(sorted(by_category.items(), key=lambda x: -x[1]))

    return {
        "month": current_month,
        "month_display": f"{now.month}月",
        "total": total,
        "by_category": by_category_sorted,
    }


# --- Send dashboard endpoints ---

@router.get("/send_dashboard")
async def send_dashboard(
    year_month: Optional[str] = None,
    operator: dict = Depends(verify_api_key),
):
    """Return per-company send-count dashboard data for a given month."""
    from api import _dashboard_helpers as dh

    ym = year_month or dh.current_year_month()
    targets = dh.load_targets(ym)
    snapshots = dh.load_quota_snapshots(ym)

    companies = []
    for cid, name in dh.list_companies():
        summary = dh.summarize_company_month(cid, ym)
        snap = snapshots.get(cid, {}) or {}
        remaining = snap.get("remaining")
        quota_hint = snap.get("quota_hint")
        used = (quota_hint - remaining) if (remaining is not None and quota_hint is not None) else None
        companies.append({
            "company_id": cid,
            "company_name": name,
            "remaining": remaining,
            "quota_hint": quota_hint,
            "used": used,
            "snapshot_at": snap.get("snapshot_at", ""),
            "target": targets.get(cid),
            "tool_sent_total": summary["total"],
            "by_category": summary["by_category"],
            "trend": dh.trend_company(cid, ym, months=6),
        })

    return {
        "year_month": ym,
        "month_display": dh.month_display(ym),
        "companies": companies,
    }


@router.get("/send_dashboard/company")
async def send_dashboard_company(
    company_id: str,
    year_month: Optional[str] = None,
    operator: dict = Depends(verify_api_key),
):
    """Return job-offer-level and template-level breakdowns for one company."""
    from api import _dashboard_helpers as dh

    ym = year_month or dh.current_year_month()
    detail = dh.detail_company_month(company_id, ym)
    return {
        "company_id": company_id,
        "year_month": ym,
        **detail,
    }


@router.post("/scout_quota_snapshot")
async def post_scout_quota_snapshot(
    data: dict,
    operator: dict = Depends(verify_api_key),
):
    """Receive a scout-remaining snapshot from the Chrome extension."""
    from api import _dashboard_helpers as dh

    company_id = str(data.get("company_id", "")).strip()
    if not company_id:
        raise HTTPException(400, "company_id is required")
    raw_remaining = data.get("remaining")
    if raw_remaining is None:
        raise HTTPException(400, "remaining is required")
    try:
        remaining = int(raw_remaining)
    except (ValueError, TypeError):
        raise HTTPException(400, "remaining must be an integer")
    if remaining < 0:
        raise HTTPException(400, "remaining must be >= 0")

    return dh.upsert_quota_snapshot(company_id, remaining)




@router.get("/send_targets")
async def get_send_targets(
    year_month: Optional[str] = None,
    operator: dict = Depends(verify_api_key),
):
    from api import _dashboard_helpers as dh
    ym = year_month or dh.current_year_month()
    return {"year_month": ym, "targets": dh.load_targets(ym)}


@router.post("/send_targets")
async def post_send_targets(
    data: dict,
    operator: dict = Depends(verify_api_key),
):
    from api import _dashboard_helpers as dh
    ym = str(data.get("year_month", "")).strip() or dh.current_year_month()
    targets = data.get("targets") or []
    if not isinstance(targets, list):
        raise HTTPException(400, "targets must be a list")
    dh.upsert_targets(ym, targets)
    return {"year_month": ym, "targets": dh.load_targets(ym)}


# Specific routes — must be defined BEFORE the /{sheet_slug} catch-all
# below or they will be shadowed.

@router.get("/send_data/{company_id}")
async def list_send_data(
    company_id: str,
    operator: dict = Depends(verify_api_key),
):
    """Return all rows from the per-company 送信_<会社名> sheet, with row indices.

    Schema drift handling: production sheets exist in three forms:
    (1) legacy 15-col headers + legacy 15-col rows
    (2) headers extended (18 cols) but with new fields appended at the END,
        while data rows are written by orchestrator in CANONICAL EXPECTED_HEADERS
        order — header positions don't match row positions
    (3) clean current schema in canonical order

    Detection: if a row's column count matches EXPECTED_HEADERS (18), trust the
    canonical positional order regardless of what the header row says. Otherwise
    fall back to `row_field`'s legacy logic.
    """
    from pipeline.orchestrator import _send_data_sheet_name, COMPANY_DISPLAY_NAMES
    from api._dashboard_helpers import EXPECTED_HEADERS, row_field
    if company_id not in COMPANY_DISPLAY_NAMES:
        raise HTTPException(404, f"Unknown company: {company_id}")
    sheet_name = _send_data_sheet_name(company_id)
    try:
        rows = sheets_writer.get_all_rows(sheet_name)
    except Exception:
        return {"items": [], "headers": list(EXPECTED_HEADERS)}
    if not rows or len(rows) < 2:
        return {"items": [], "headers": rows[0] if rows else list(EXPECTED_HEADERS)}
    raw_headers = [h.strip() for h in rows[0]]
    # Detect drift: if the header row matches EXPECTED set but in a different
    # order, OR if it has 18 cols already, the data was likely written by
    # orchestrator using EXPECTED_HEADERS positional order. In all such cases,
    # we trust EXPECTED_HEADERS as the canonical positional source of truth.
    use_canonical_positional = (
        set(raw_headers) == set(EXPECTED_HEADERS)
        or len(raw_headers) >= len(EXPECTED_HEADERS)
    )
    items = []
    for i, row in enumerate(rows[1:], start=2):
        if use_canonical_positional:
            # Pad short rows (Google Sheets API trims trailing empties)
            padded = list(row) + [""] * (len(EXPECTED_HEADERS) - len(row))
            item = {
                field: padded[idx].strip() if idx < len(padded) else ""
                for idx, field in enumerate(EXPECTED_HEADERS)
            }
        else:
            # Legacy short headers AND short rows — use row_field's fallback chain
            item = {field: row_field(row, raw_headers, field) for field in EXPECTED_HEADERS}
        item["_row_index"] = i
        items.append(item)
    return {"headers": list(EXPECTED_HEADERS), "items": items}


@router.post("/record_manual_send")
async def record_manual_send(
    data: dict,
    operator: dict = Depends(verify_api_key),
):
    """Record a scout that was sent manually in JOBMEDLEY (without going through
    the orchestrator generate API).

    Called by the Chrome extension's single-send-tracker when it detects a
    manual send completion AND the candidate is not already in the side panel's
    local list (i.e. wasn't generated via tool).

    Idempotency: same (company_id, member_id, YYYY-MM-DD) is treated as duplicate.
    """
    from pipeline.orchestrator import (
        _send_data_sheet_name,
        COMPANY_DISPLAY_NAMES,
        SEND_DATA_HEADERS,
    )
    from api._dashboard_helpers import EXPECTED_HEADERS

    company_id = (data.get("company_id") or "").strip()
    member_id = (data.get("member_id") or "").strip()
    sent_at = (data.get("sent_at") or "").strip()
    if not member_id:
        raise HTTPException(400, "member_id is required")
    if company_id not in COMPANY_DISPLAY_NAMES:
        raise HTTPException(404, f"Unknown company: {company_id}")

    sheet_name = _send_data_sheet_name(company_id)
    sheets_writer.ensure_sheet_exists(sheet_name, SEND_DATA_HEADERS)

    # Dedup: skip if same member_id was already recorded as a manual send today
    sent_day = sent_at[:10] if sent_at else ""
    try:
        existing_rows = sheets_writer.get_all_rows(sheet_name)
    except Exception:
        existing_rows = []
    if existing_rows and len(existing_rows) >= 2:
        member_idx = SEND_DATA_HEADERS.index("会員番号")
        date_idx = SEND_DATA_HEADERS.index("日時")
        path_idx = SEND_DATA_HEADERS.index("生成パス")
        for row in existing_rows[1:]:
            if (
                len(row) > member_idx
                and row[member_idx].strip() == member_id
                and len(row) > date_idx
                and row[date_idx].strip()[:10] == sent_day
                and len(row) > path_idx
                and row[path_idx].strip() == "manual"
            ):
                return {
                    "status": "ok",
                    "recorded": False,
                    "reason": "duplicate",
                    "company_id": company_id,
                    "member_id": member_id,
                }

    # Build a row in canonical positional order. Most fields are empty for
    # manual sends — we only know what JOBMEDLEY's overlay exposed.
    row_values = [""] * len(EXPECTED_HEADERS)
    row_values[EXPECTED_HEADERS.index("日時")] = sent_at
    row_values[EXPECTED_HEADERS.index("会員番号")] = member_id
    row_values[EXPECTED_HEADERS.index("生成パス")] = "manual"
    row_values[EXPECTED_HEADERS.index("テンプレート種別")] = "(手動)"
    # Optional profile snapshot fields
    if data.get("qualifications"):
        row_values[EXPECTED_HEADERS.index("資格")] = str(data["qualifications"])
    if data.get("age"):
        row_values[EXPECTED_HEADERS.index("年齢層")] = str(data["age"])
    if data.get("desired_employment_type"):
        row_values[EXPECTED_HEADERS.index("希望雇用形態")] = str(data["desired_employment_type"])
    if data.get("area"):
        row_values[EXPECTED_HEADERS.index("地域")] = str(data["area"])

    sheets_writer.append_row(sheet_name, row_values)
    return {
        "status": "ok",
        "recorded": True,
        "company_id": company_id,
        "member_id": member_id,
    }


@router.delete("/send_data/{company_id}/{row_index}")
async def delete_send_data_row(
    company_id: str,
    row_index: int,
    operator: dict = Depends(verify_api_key),
):
    """Delete a single row from a per-company 送信_<会社名> sheet.

    The deletion is recorded in the audit log via sheets_writer.delete_row.
    Row index 1 is the header row and is never deletable.
    """
    from pipeline.orchestrator import _send_data_sheet_name, COMPANY_DISPLAY_NAMES
    if company_id not in COMPANY_DISPLAY_NAMES:
        raise HTTPException(404, f"Unknown company: {company_id}")
    if row_index < 2:
        raise HTTPException(400, f"row_index must be >= 2 (header is row 1)")
    sheet_name = _send_data_sheet_name(company_id)
    actor_name = operator.get("name") or operator.get("operator_id") or "operator"
    sheets_writer.delete_row(sheet_name, row_index, actor=f"delete_send_data:{actor_name}")
    return {"status": "deleted", "company_id": company_id, "row_index": row_index}


# Fields the operator may edit on a 送信_<会社名> row. 日時 is intentionally
# excluded so the audit timeline stays trustworthy.
SEND_DATA_EDITABLE_FIELDS = {
    "会員番号", "職種カテゴリ", "テンプレート種別", "テンプレートVer",
    "生成パス", "パターン", "年齢層", "資格", "経験区分",
    "希望雇用形態", "就業状況", "地域", "曜日", "時間帯",
    "返信", "返信日", "返信カテゴリ",
}


@router.patch("/send_data/{company_id}/{row_index}")
async def patch_send_data_row(
    company_id: str,
    row_index: int,
    data: dict,
    operator: dict = Depends(verify_api_key),
):
    """Edit individual cells of a row in 送信_<会社名>.

    Body: ``{"cells": {"会員番号": "123", "テンプレート種別": "_初回", ...}}``

    Only fields in ``SEND_DATA_EDITABLE_FIELDS`` are accepted; the timestamp
    column 日時 is immutable to keep the audit trail trustworthy. The previous
    row contents are snapshotted to the audit log via
    ``sheets_writer.update_cells_by_name`` before the write happens, so the
    edit is recoverable.

    Refuses if the sheet header has drifted from the canonical schema, since
    update_cells_by_name maps by header NAME and a drifted header would cause
    silent miswrites.
    """
    from pipeline.orchestrator import _send_data_sheet_name, COMPANY_DISPLAY_NAMES
    from api._dashboard_helpers import EXPECTED_HEADERS

    if company_id not in COMPANY_DISPLAY_NAMES:
        raise HTTPException(404, f"Unknown company: {company_id}")
    if row_index < 2:
        raise HTTPException(400, "row_index must be >= 2 (header is row 1)")

    cells_in = data.get("cells") or {}
    if not isinstance(cells_in, dict) or not cells_in:
        raise HTTPException(400, "cells must be a non-empty object")

    unknown = [k for k in cells_in.keys() if k not in SEND_DATA_EDITABLE_FIELDS]
    if unknown:
        raise HTTPException(400, f"Non-editable fields rejected: {unknown}")

    sheet_name = _send_data_sheet_name(company_id)

    # Drift guard: refuse if the sheet header isn't the canonical schema in
    # canonical order. update_cells_by_name resolves columns by header name,
    # so a drifted header (e.g. legacy 15-col) would write to the wrong column.
    try:
        rows = sheets_writer.get_all_rows(sheet_name)
    except Exception as e:
        raise HTTPException(500, f"Failed to read sheet: {e}")
    if not rows:
        raise HTTPException(404, f"Sheet '{sheet_name}' is empty")
    raw_headers = [h.strip() for h in rows[0]]
    if raw_headers != list(EXPECTED_HEADERS):
        raise HTTPException(
            409,
            "Sheet header has drifted from the canonical schema; "
            "row edit is disabled to prevent miswrites. "
            "Header must match EXPECTED_HEADERS exactly.",
        )

    # Coerce all values to strings (Sheets RAW write expects str)
    cells = {k: ("" if v is None else str(v)) for k, v in cells_in.items()}

    actor_name = operator.get("name") or operator.get("operator_id") or "operator"
    result = sheets_writer.update_cells_by_name(
        sheet_name,
        row_index,
        cells,
        actor=f"edit_send_data:{actor_name}",
    )
    return {
        "status": "ok",
        "company_id": company_id,
        "row_index": row_index,
        "updated": result.get("updated", []),
        "skipped": result.get("skipped", []),
    }


@router.get("/job_category_failures")
async def list_job_category_failures(
    company: Optional[str] = None,
    days: int = 30,
    operator: dict = Depends(verify_api_key),
):
    """Aggregate `failure_*` rows from the 生成ログ sheet for the keyword
    proposal workflow (BACKLOG: Phase 3 — 職種解決ワークフロー).

    Reads recent rows from 生成ログ where `generation_path == "filtered_out"`
    and `failure_stage` is populated, groups them by (company, failure_stage,
    company_categories) and exposes the searched_text snippets so a director
    can decide which keywords are worth promoting to the 職種キーワード sheet.

    Params:
      - company: optional company filter
      - days: lookback window (default 30; the resolver writes ISO timestamps)
    """
    from datetime import datetime, timedelta, timezone

    sheet_name = SHEET_MAP.get("logs")  # "生成ログ"
    try:
        rows = sheets_writer.get_all_rows(sheet_name)
    except Exception:
        return {"groups": [], "total": 0}
    if not rows or len(rows) < 2:
        return {"groups": [], "total": 0}

    headers = [h.strip() for h in rows[0]]

    def col(name: str) -> int:
        try:
            return headers.index(name)
        except ValueError:
            return -1

    idx_ts = col("timestamp")
    idx_company = col("company")
    idx_member = col("member_id")
    idx_path = col("generation_path")
    idx_stage = col("failure_stage")
    idx_missing = col("failure_missing_fields")
    idx_searched = col("failure_searched_text")
    idx_company_cats = col("failure_company_categories")
    idx_human = col("failure_human_message")

    if idx_stage < 0 or idx_path < 0:
        return {"groups": [], "total": 0, "warning": "logs sheet missing failure_* columns"}

    # Time cutoff (best effort — accept rows whose timestamp is unparseable)
    cutoff: Optional[datetime] = None
    if days and days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    def cell(row: list, idx: int) -> str:
        if idx < 0 or idx >= len(row):
            return ""
        return (row[idx] or "").strip()

    def parse_ts(s: str) -> Optional[datetime]:
        if not s:
            return None
        try:
            # ISO 8601, may or may not have a tz suffix
            ts = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts
        except Exception:
            return None

    # group key → aggregated dict
    groups: dict[tuple, dict] = {}
    total = 0

    for row in rows[1:]:
        path = cell(row, idx_path)
        stage = cell(row, idx_stage)
        if path != "filtered_out" or not stage:
            continue
        row_company = cell(row, idx_company)
        if company and row_company != company:
            continue
        ts_str = cell(row, idx_ts)
        if cutoff is not None:
            ts = parse_ts(ts_str)
            if ts is not None and ts < cutoff:
                continue

        company_cats_raw = cell(row, idx_company_cats)
        # Stored as comma-separated. Normalize for stable grouping.
        company_cats = tuple(
            sorted(c.strip() for c in company_cats_raw.split(",") if c.strip())
        )
        key = (row_company, stage, company_cats)
        bucket = groups.get(key)
        if bucket is None:
            bucket = {
                "company": row_company,
                "failure_stage": stage,
                "company_categories": list(company_cats),
                "count": 0,
                "samples": [],  # most recent up to 10
                "missing_fields_counter": {},
                "human_message": cell(row, idx_human),  # last seen
            }
            groups[key] = bucket
        bucket["count"] += 1
        total += 1

        # Track which fields were missing across the group
        missing_raw = cell(row, idx_missing)
        for f in (m.strip() for m in missing_raw.split(",")):
            if f:
                bucket["missing_fields_counter"][f] = (
                    bucket["missing_fields_counter"].get(f, 0) + 1
                )

        if len(bucket["samples"]) < 10:
            bucket["samples"].append({
                "timestamp": ts_str,
                "member_id": cell(row, idx_member),
                "searched_text": cell(row, idx_searched),
                "missing_fields": [
                    f.strip() for f in missing_raw.split(",") if f.strip()
                ],
            })

    # Sort: most-frequent first
    out = sorted(groups.values(), key=lambda g: g["count"], reverse=True)
    return {"groups": out, "total": total, "days": days}


@router.post("/job_category_keywords/append")
async def append_job_category_keyword(
    data: dict,
    operator: dict = Depends(verify_api_key),
):
    """Append a single row to the 職種キーワード sheet.

    Used by the Phase 3 admin UI to promote a director-approved keyword
    suggestion into the live dictionary. Always uses the canonical column
    order from `COLUMNS["job_category_keywords"]`.

    Body:
      {
        "company": "" | company_id,    # "" = global rule
        "job_category": "nurse",        # required
        "keyword": "訪問看護",          # required
        "source_fields": "qualification",  # CSV or single
        "weight": "1",                  # optional
        "enabled": "TRUE",              # default TRUE
        "note": "Phase 3 自動提案 from 生成ログ"
      }
    """
    from datetime import datetime, timezone

    job_category = (data.get("job_category") or "").strip()
    keyword = (data.get("keyword") or "").strip()
    if not job_category or not keyword:
        raise HTTPException(400, "job_category and keyword are required")

    sheet_name = SHEET_MAP["job_category_keywords"]
    columns = COLUMNS["job_category_keywords"]

    actor_name = operator.get("name") or operator.get("operator_id") or "operator"
    row_dict = {
        "company": (data.get("company") or "").strip(),
        "job_category": job_category,
        "keyword": keyword,
        "source_fields": (data.get("source_fields") or "qualification").strip(),
        "weight": (data.get("weight") or "1").strip(),
        "enabled": (data.get("enabled") or "TRUE").strip(),
        "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "added_by": actor_name,
        "note": (data.get("note") or "").strip(),
    }
    row_values = [row_dict.get(c, "") for c in columns]
    sheets_writer.append_row(sheet_name, row_values)
    return {"status": "ok", "appended": row_dict}


@router.get("/stale_quota_companies")
async def get_stale_quota_companies(
    max_hours: float = 24,
    operator: dict = Depends(verify_api_key),
):
    """Return companies whose quota snapshot is older than `max_hours` (default 24).

    Used by the dashboard to highlight stale rows and (later) by Cloud Scheduler
    to fire alerts.
    """
    from api import _dashboard_helpers as dh
    items = dh.find_stale_quota_companies(max_hours=max_hours)
    return {"max_hours": max_hours, "items": items, "count": len(items)}


@router.get("/quota_history")
async def get_quota_history(
    company: str,
    year_month: Optional[str] = None,
    operator: dict = Depends(verify_api_key),
):
    """Return the append-only history of quota snapshots for a company.

    Used by the dashboard to chart the remaining-count trajectory across
    a month.
    """
    from api import _dashboard_helpers as dh
    items = dh.load_quota_history(company, year_month)
    return {"items": items}


@router.get("/fix_feedback")
async def list_fix_feedback(
    company: Optional[str] = None,
    status: Optional[str] = None,
    operator: dict = Depends(verify_api_key),
):
    """修正フィードバック一覧。company / status でフィルタ可能。timestamp降順。"""
    try:
        all_rows = sheets_writer.get_all_rows(SHEET_FIX_FEEDBACK)
    except Exception:
        return {"items": []}
    if not all_rows or len(all_rows) < 2:
        return {"items": []}

    headers = all_rows[0]
    items: list[dict] = []
    for row in all_rows[1:]:
        item = {col: (row[i] if i < len(row) else "") for i, col in enumerate(headers)}
        if company and item.get("company", "") != company:
            continue
        if status and item.get("status", "") != status:
            continue
        items.append(item)

    items.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return {"items": items}


@router.get("/improvement_proposals")
async def list_improvement_proposals(
    status: Optional[str] = None,
    operator=Depends(verify_api_key),
):
    """改善提案一覧を返す。created_at降順。status でフィルタ可能。

    NOTE: 必ず `@router.get("/{sheet_slug}")` より前に登録すること。
    そうしないと catchall に飲まれて 404 になる。
    """
    import json
    from db.sheets_client import SHEET_IMPROVEMENT_PROPOSALS

    try:
        all_rows = sheets_writer.get_all_rows(SHEET_IMPROVEMENT_PROPOSALS)
    except Exception:
        return {"items": []}
    if not all_rows or len(all_rows) < 2:
        return {"items": []}

    headers = [h.strip() for h in all_rows[0]]
    items: list[dict] = []
    for row in all_rows[1:]:
        item = {h: (row[i].strip() if i < len(row) else "") for i, h in enumerate(headers)}
        if status and item.get("status", "") != status:
            continue
        try:
            item["payload"] = json.loads(item.get("payload_json", "") or "{}")
        except Exception:
            item["payload"] = {}
        items.append(item)
    items.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return {"items": items}


@router.get("/{sheet_slug}")
async def list_rows(sheet_slug: str, company: Optional[str] = None, operator=Depends(verify_api_key)):
    sheet_name = SHEET_MAP.get(sheet_slug)
    if not sheet_name:
        raise HTTPException(404, f"Unknown sheet: {sheet_slug}")

    try:
        rows = sheets_writer.get_all_rows(sheet_name)
    except Exception:
        rows = []
    if not rows:
        return {"headers": COLUMNS.get(sheet_slug, []), "rows": []}

    headers = rows[0]
    # Determine pattern_type column index for QUAL filtering
    pt_col_idx = None
    for j, h in enumerate(headers):
        if h.strip() == "pattern_type":
            pt_col_idx = j
            break

    data_rows = []
    for i, row in enumerate(rows[1:], start=2):  # row 2 = first data row in sheet
        item = {}
        for j, h in enumerate(headers):
            item[h.strip()] = row[j].strip() if j < len(row) else ""
        item_company = item.get("company", "")
        if company and item_company and item_company != company:
            continue
        # Filter by pattern_type for qualifiers vs patterns
        pt_value = item.get("pattern_type", "")
        if sheet_slug == "qualifiers" and pt_value != "QUAL":
            continue
        if sheet_slug == "patterns" and pt_value == "QUAL":
            continue
        # Normalize body/template_text: ensure real newlines are stored as
        # literal \n so the admin UI's formatCellText() renders them as <br>.
        for col in ("body", "template_text"):
            if col in item and "\n" in item[col]:
                item[col] = item[col].replace("\r\n", "\\n").replace("\n", "\\n")

        item["_row_index"] = i  # actual sheet row number
        data_rows.append(item)

    # Logs: newest first, limit to 200 rows
    if sheet_slug == "logs":
        data_rows = list(reversed(data_rows))[:200]

    return {"headers": [h.strip() for h in headers], "rows": data_rows}


@router.post("/init_company")
async def init_company(data: dict, operator=Depends(verify_api_key)):
    """Create empty scaffold rows for a new company."""
    company_id = data.get("company_id", "").strip()
    if not company_id:
        raise HTTPException(400, "company_id is required")

    # Check if company already exists
    existing = sheets_client.get_company_list()
    if company_id in existing:
        raise HTTPException(409, f"Company '{company_id}' already exists")

    total = 0

    # Templates: 4 empty rows (パート初回/再送, 正社員初回/再送)
    template_types = ["パート_初回", "パート_再送", "正社員_初回", "正社員_再送"]
    for tt in template_types:
        # columns: company, job_category, type, body
        sheets_writer.append_row("テンプレート", [company_id, "nurse", tt, ""])
        total += 1

    # Patterns: 型A〜G with default matching rules
    import json
    default_patterns = [
        ("A", "", "豊富な経験への期待", "経験10年+ / 40代〜×経験6年+",
         json.dumps([{"exp_min":10,"age_group":"40s+"},{"exp_min":6,"age_group":"late_30s"}])),
        ("B1", "", "確かな経験×特色", "経験6〜9年",
         json.dumps([{"exp_min":10,"age_group":"young"},{"exp_min":6,"exp_max":9}])),
        ("B2", "", "経験×特色", "経験3〜5年",
         json.dumps([{"exp_min":3,"exp_max":5}])),
        ("C", "", "経験とのフィット", "40代〜 × 経験1〜2年",
         json.dumps([{"exp_min":1,"exp_max":2,"age_group":"40s+"},{"exp_min":1,"exp_max":2,"age_group":"late_30s"}])),
        ("D", "就業中", "経験ある前提で評価", "40代〜 × 経験未入力",
         json.dumps([{"exp_max":0,"age_group":"40s+"},{"exp_max":0,"age_group":"late_30s"},{"exp_min":None,"age_group":"40s+"},{"exp_min":None,"age_group":"late_30s"}])),
        ("D", "離職中", "経験ある前提で評価", "40代〜 × 経験未入力",
         json.dumps([{"exp_max":0,"age_group":"40s+"},{"exp_max":0,"age_group":"late_30s"},{"exp_min":None,"age_group":"40s+"},{"exp_min":None,"age_group":"late_30s"}])),
        ("E", "", "ポテンシャル+教育体制", "20〜30代 × 経験1〜2年",
         json.dumps([{"exp_min":1,"exp_max":2,"age_group":"young"}])),
        ("F", "就業中", "教育体制+成長環境", "20〜30代 × 経験未入力",
         json.dumps([{"exp_max":0,"age_group":"young"},{"exp_min":None,"age_group":"young"}])),
        ("F", "離職中", "教育体制+成長環境", "20〜30代 × 経験未入力",
         json.dumps([{"exp_max":0,"age_group":"young"},{"exp_min":None,"age_group":"young"}])),
        ("G", "", "教育体制メイン", "在学中",
         json.dumps([{"employment":"在学中"}])),
    ]
    for pt, emp_var, disp_name, target_desc, rules in default_patterns:
        # columns: company, job_category, pattern_type, employment_variant, template_text, feature_variations, display_name, target_description, match_rules
        sheets_writer.append_row("パターン", [company_id, "nurse", pt, emp_var, "", "", disp_name, target_desc, rules])
        total += 1

    # Validation: 1 empty row
    # columns: company, age_min, age_max, qualification_rules
    sheets_writer.append_row("バリデーション", [company_id, "", "", ""])
    total += 1

    # Profile: 1 empty row
    # columns: company, content
    sheets_writer.append_row("プロフィール", [company_id, ""])
    total += 1

    sheets_client.reload()
    return {"status": "created", "company_id": company_id, "total_rows": total}


@router.post("/generate_company")
async def generate_company(data: dict, operator=Depends(verify_api_key)):
    """Generate company config from free-text company info using AI.

    Creates empty template scaffolds, then AI-generates patterns, prompts,
    validation, and qualification modifiers, writing them to Google Sheets.
    """
    import json as _json
    from pipeline.ai_generator import generate_personalized_text

    company_id = data.get("company_id", "").strip()
    company_info = data.get("company_info", "").strip()
    template_text = data.get("template_text", "").strip()
    generate_templates = data.get("generate_templates", not template_text)
    if not company_id:
        raise HTTPException(400, "company_id is required")
    if not company_info:
        raise HTTPException(400, "company_info is required")

    # Check if company already exists
    existing = sheets_client.get_company_list()
    if company_id in existing:
        raise HTTPException(409, f"Company '{company_id}' already exists")

    # --- Build the mega-prompt ---
    # Load ALL existing companies as reference examples
    import json as _json_ref
    ref_configs = {}
    try:
        all_companies = sheets_client.get_company_list()
        for cid in all_companies:
            if cid == company_id:
                continue  # Skip the company being created
            try:
                ref_configs[cid] = sheets_client.get_company_config(cid)
            except Exception:
                pass
    except Exception:
        pass

    # Build reference pattern examples from multiple companies
    ref_pattern_examples = ""
    target_types_per_company = {"A": "ベテラン向け", "E": "若手向け", "G": "在学中向け"}
    for cid, cfg in ref_configs.items():
        patterns = cfg.get("patterns", [])
        if not patterns:
            continue
        ref_pattern_examples += f"\n【{cid}】\n"
        for p in patterns:
            pt = p.get("pattern_type", "")
            if pt in target_types_per_company:
                emp = p.get("employment_variant", "")
                label = f"型{pt}" + (f"_{emp}" if emp else "")
                features = p.get("feature_variations", [])
                ref_pattern_examples += f"- {label}: template_text=\"{p.get('template_text','')}\", feature_variations={features}\n"
        if len(ref_configs) > 2:
            break  # Show max 2 companies to avoid prompt bloat

    # Build reference prompt sections from multiple companies (company-specific only)
    ref_prompt_example = ""
    company_specific_types = {"station_features", "education", "ai_guide"}
    for cid, cfg in ref_configs.items():
        prompts = cfg.get("prompt_sections", [])
        relevant = [s for s in prompts if s.get("content") and s.get("section_type") in company_specific_types]
        if not relevant:
            continue
        ref_prompt_example += f"\n【{cid}】\n"
        for sec in relevant:
            ref_prompt_example += f"- section_type: \"{sec.get('section_type','')}\", job_category: \"{sec.get('job_category','')}\", order: {sec.get('order','')}, content: \"{sec.get('content','')}\"\n"
        if len(ref_configs) > 2:
            break

    # Build reference validation example (pick first company that has it)
    ref_validation_example = ""
    for cid, cfg in ref_configs.items():
        val = cfg.get("validation_config", {})
        if val:
            age_range = val.get("age_range", {})
            qual_rules = val.get("qualification_rules", {})
            ref_validation_example = f"\n参考例（{cid}）:\n- age_min: {age_range.get('min','')}, age_max: {age_range.get('max','')}\n- qualification_rules: {_json_ref.dumps(qual_rules, ensure_ascii=False)}\n"
            break

    # Build reference qualifier examples from multiple companies
    ref_qualifier_example = ""
    for cid, cfg in ref_configs.items():
        qualifiers = cfg.get("qualification_modifiers", [])
        if not qualifiers:
            continue
        ref_qualifier_example += f"\n【{cid}】\n"
        for q in qualifiers[:3]:
            combo = q.get("qualification_combo", [])
            combo_str = ",".join(combo) if isinstance(combo, list) else combo
            ref_qualifier_example += f"- combo: \"{combo_str}\", text: \"{q.get('replacement_text','')}\"\n"
        if len(ref_configs) > 2:
            break

    # Build reference template examples if generating templates
    ref_template_section = ""
    template_output_schema = ""
    if generate_templates:
        # Show 初回 and 再送 from first company that has both
        for cid, cfg in ref_configs.items():
            templates = cfg.get("templates", {})
            found_initial = found_resend = ""
            for key, t in templates.items():
                ttype = t.get("type", "")
                body = t.get("body", "")
                if not body:
                    continue
                if "初回" in ttype and not found_initial:
                    found_initial = f"\n#### {ttype} の例（{cid}、冒頭300文字）:\n{body[:300]}...\n"
                elif "再送" in ttype and not found_resend:
                    found_resend = f"\n#### {ttype} の例（{cid}、冒頭300文字）:\n{body[:300]}...\n"
            if found_initial and found_resend:
                ref_template_section = found_initial + found_resend
                break

        template_instructions = f"""### 0. テンプレート（4種類）
スカウトメールの本文テンプレート。以下の4種を生成:
- パート_初回: パートタイム向け初回スカウト
- パート_再送: パートタイム向け再送スカウト（2回目以降）
- 正社員_初回: 正社員向け初回スカウト
- 正社員_再送: 正社員向け再送スカウト

各テンプレートのルール:
- **必ず `{{ここに生成した文章を挿入}}` プレースホルダーを1箇所含める**（AIが候補者ごとのパーソナライズ文を挿入する位置）
- プレースホルダーの前後に、会社の特色や共通メッセージを配置
- 末尾は応募を促す文言で締める
- ですます調、自然な日本語
- 正社員テンプレートは給与・待遇情報を含める
- 全体で300〜500文字程度

初回 vs 再送の違い:
- **初回**: 冒頭「はじめまして。突然のご連絡大変失礼いたします、[会社名]の[担当者名]と申します。」
- **再送**: 冒頭を「度々のご連絡大変申し訳ございません。諦めきれず、ご連絡させていただきます、[会社名]の[担当者名]と申します。」のように、再度連絡している旨に変える。「はじめまして」は使わない
- 本文の構成は同じでよいが、冒頭の挨拶文は必ず変えること
{ref_template_section}

"""
        template_output_schema = """  "templates": [
    {{"type": "パート_初回", "job_category": "nurse", "body": "テンプレート本文..."}},
    {{"type": "パート_再送", "job_category": "nurse", "body": "テンプレート本文..."}},
    {{"type": "正社員_初回", "job_category": "nurse", "body": "テンプレート本文..."}},
    {{"type": "正社員_再送", "job_category": "nurse", "body": "テンプレート本文..."}}
  ],
"""
    else:
        template_instructions = ""
        template_output_schema = ""

    system_prompt = f"""あなたは訪問看護・介護系のスカウト文生成システムの設定エキスパートです。
会社情報のフリーテキストから、スカウト文生成に必要な設定を一括生成してください。

## 生成する設定
{template_instructions}
### 1. パターン（10種類）
経歴が少ない候補者に使う型はめパターン。候補者の経験年数・年齢帯に応じて使い分ける。

| 型 | 対象 | 特徴 |
|----|------|------|
| A | 経験10年+のベテラン | 豊富な経験への期待・敬意を表現 |
| B1 | 経験6〜9年の中堅 | 確かな経験×会社の特色 |
| B2 | 経験3〜5年 | 経験×会社の特色 |
| C | 40代〜×経験1〜2年 | 経験とのフィット |
| D | 40代〜×経験未入力（就業中/離職中の2バリエーション） | 経験ある前提で評価 |
| E | 20〜30代×経験1〜2年 | ポテンシャル+教育体制 |
| F | 20〜30代×経験未入力（就業中/離職中の2バリエーション） | 教育体制+成長環境 |
| G | 在学中 | 教育体制メイン |

パターンのルール:
- template_text: 2〜3文、句点で終わる。ですます調
- `{{特色}}` プレースホルダーを1箇所含める（特色バリエーションが挿入される）
- 型A・B1・B2: `{{N}}` プレースホルダー可（経験年数が入る）
- 上から目線にならない（「フォローします」「安心してスタートいただけます」等は厳禁）
- feature_variations: 3つ、各バリエーションは会社の特色を短く表現（連体修飾形「〜する」「〜な」で終わる）
- 型E・F・G: **その会社固有の**教育体制を具体的に記載すること（他社の制度を混ぜない）

参考例（他社）:
{ref_pattern_examples}

### 2. プロンプトセクション（会社固有の3セクション）
AI生成時のシステムプロンプトの構成パーツ。section_type と content を設定。
トーン・共通ルール・NG表現は全社共通で登録済みのため、**会社固有の情報のみ**を生成する。
候補者の経歴が豊富な場合にAIが使う生成ガイドになるため、**具体的で実用的な内容**にすること。

必須セクション（section_type名を正確に使うこと）:
1. **station_features**（会社特色）order=2: AIが接点を見つけるための会社の強み・特色リスト。箇条書きで5〜8項目。各項目に（カッコ内で候補者のどんな経験が活きるか）を添える
2. **education**（教育体制）order=3: **その会社固有の**研修・サポート体制。他社の制度を混ぜないよう注意。制度がない場合は「現場のスタッフと協力しながら業務を覚えられる体制」等の事実のみ記載
3. **ai_guide**（AI生成ガイド）order=8: 以下の2つを含めること:
   a. 経歴別の接点対応表: 候補者の経験パターン → 会社の強み → 接点の表現方向。5〜8パターン
   b. NGパターン: やってはいけない接点の作り方（弱い接点、会社情報の羅列、地理的要素のみ等）

以下は全社共通で既に登録済み（生成不要）:
- role_definition（order=1）: パーソナライズ文の基本指示
- tone_and_manner（order=4）: トーン・マナールール
- common_rules（order=5）: 文字数・書き出し・経験年数記載等の共通ルール
- ng_expressions（order=9）: NG表現リスト

つまり、会社固有で生成するのは **station_features, education, ai_guide** の3セクションのみ。
各セクションは200〜800文字。job_category は会社情報から推測（看護系なら"nurse"等）。

参考例（他社）:
{ref_prompt_example}

### 3. バリデーション（1件）
スカウト対象のフィルタリング条件。JSON形式。
- age_min, age_max: 年齢範囲（空欄なら制限なし）
- qualification_rules: JSON。必須資格、除外条件等
{ref_validation_example}

### 4. 資格修飾（5〜10件）
複数資格保持者への修飾テキスト。型はめパターンの冒頭を差し替える文。
- qualification_combo: 資格の組み合わせ（カンマ区切り）
- replacement_text: その資格の組み合わせが**なぜこの会社で活きるのか**を具体的に書いた1〜2文
  - 悪い例: 「看護師・介護福祉士の両方の資格をお持ちとのこと、」（接点がない）
  - 良い例: 「看護師の資格に加え、ケアマネージャーの資格もお持ちとのこと、医療と介護の両面から患者様を支える視点は、地域に根差した精神科医療を提供する当院で大きな力になると考えております。」（資格×会社の特色の接点がある）
{ref_qualifier_example}

## 出力形式
以下のJSON1つで返してください。他のテキストは不要です。
```json
{{
{template_output_schema}  "patterns": [
    {{"pattern_type": "A", "employment_variant": "", "template_text": "...", "feature_variations": ["...", "...", "..."]}},
    ... (10件: A, B1, B2, C, D就業中, D離職中, E, F就業中, F離職中, G)
  ],
  "prompts": [
    {{"section_type": "station_features", "job_category": "nurse", "order": 2, "content": "- 特色1（どんな経験が活きるか）\\n- 特色2..."}},
    {{"section_type": "education", "job_category": "nurse", "order": 3, "content": "- 研修制度1\\n- 研修制度2..."}},
    {{"section_type": "ai_guide", "job_category": "nurse", "order": 8, "content": "経歴別の接点対応表:\\n- 〇〇経験 → 会社の強み → 接点表現\\n...\\n\\nNGパターン:\\n- ..."}}
  ],
  "validation": {{
    "age_min": "",
    "age_max": "",
    "qualification_rules": "{{...JSON文字列...}}"
  }},
  "qualifiers": [
    {{"qualification_combo": "看護師,介護福祉士", "replacement_text": "..."}},
    ...
  ]
}}
```"""

    try:
        gen_result = await generate_personalized_text(
            system_prompt=system_prompt,
            user_prompt=f"以下の会社情報から、スカウト文生成の全設定を生成してください。\n\n{company_info}",
            model_name=None,
            max_output_tokens=8192,
            temperature=0.5,
        )
        result_text = gen_result.text

        # Extract JSON from response
        import re
        json_match = re.search(r'\{[\s\S]*\}', result_text)
        if not json_match:
            raise ValueError("AI応答からJSONを抽出できませんでした")

        generated = _json.loads(json_match.group(0))

        # --- Write to Sheets ---
        total = 0

        # 1. Templates
        template_types = ["パート_初回", "パート_再送", "正社員_初回", "正社員_再送"]
        if template_text:
            # User provided a template base — use it for all 4 types
            body_escaped = template_text.replace("\n", "\\n")
            for tt in template_types:
                sheets_writer.append_row("テンプレート", [company_id, "nurse", tt, body_escaped])
                total += 1
            generated["templates"] = [{"type": tt, "body": template_text} for tt in template_types]
        elif generate_templates and generated.get("templates"):
            # AI-generated templates
            for t in generated["templates"]:
                body = t.get("body", "").replace("\n", "\\n")
                sheets_writer.append_row("テンプレート", [
                    company_id,
                    t.get("job_category", "nurse"),
                    t.get("type", ""),
                    body,
                ])
                total += 1
        else:
            # Empty scaffolds (user fills in manually)
            for tt in template_types:
                sheets_writer.append_row("テンプレート", [company_id, "nurse", tt, ""])
                total += 1

        # 2. Patterns (with default match_rules)
        default_match_rules = {
            "A": _json.dumps([{"exp_min":10,"age_group":"40s+"},{"exp_min":6,"age_group":"late_30s"}]),
            "B1": _json.dumps([{"exp_min":10,"age_group":"young"},{"exp_min":6,"exp_max":9}]),
            "B2": _json.dumps([{"exp_min":3,"exp_max":5}]),
            "C": _json.dumps([{"exp_min":1,"exp_max":2,"age_group":"40s+"},{"exp_min":1,"exp_max":2,"age_group":"late_30s"}]),
            "D_就業中": _json.dumps([{"exp_max":0,"age_group":"40s+"},{"exp_max":0,"age_group":"late_30s"},{"exp_min":None,"age_group":"40s+"},{"exp_min":None,"age_group":"late_30s"}]),
            "D_離職中": _json.dumps([{"exp_max":0,"age_group":"40s+"},{"exp_max":0,"age_group":"late_30s"},{"exp_min":None,"age_group":"40s+"},{"exp_min":None,"age_group":"late_30s"}]),
            "E": _json.dumps([{"exp_min":1,"exp_max":2,"age_group":"young"}]),
            "F_就業中": _json.dumps([{"exp_max":0,"age_group":"young"},{"exp_min":None,"age_group":"young"}]),
            "F_離職中": _json.dumps([{"exp_max":0,"age_group":"young"},{"exp_min":None,"age_group":"young"}]),
            "G": _json.dumps([{"employment":"在学中"}]),
        }
        display_names = {
            "A": "豊富な経験への期待", "B1": "確かな経験×特色", "B2": "経験×特色",
            "C": "経験とのフィット", "D": "経験ある前提で評価", "E": "ポテンシャル+教育体制",
            "F": "教育体制+成長環境", "G": "教育体制メイン",
        }
        target_descs = {
            "A": "経験10年+ / 40代〜×経験6年+", "B1": "経験6〜9年", "B2": "経験3〜5年",
            "C": "40代〜 × 経験1〜2年", "D": "40代〜 × 経験未入力",
            "E": "20〜30代 × 経験1〜2年", "F": "20〜30代 × 経験未入力", "G": "在学中",
        }

        patterns = generated.get("patterns", [])
        for p in patterns:
            pt = p.get("pattern_type", "")
            emp_var = p.get("employment_variant", "")
            features = "|".join(p.get("feature_variations", []))
            rules_key = f"{pt}_{emp_var}" if emp_var else pt
            rules = default_match_rules.get(rules_key, "[]")
            sheets_writer.append_row("パターン", [
                company_id,
                "nurse",
                pt,
                emp_var,
                p.get("template_text", ""),
                features,
                display_names.get(pt, ""),
                target_descs.get(pt, ""),
                rules,
            ])
            total += 1

        # 3. Prompts
        prompts = generated.get("prompts", [])
        for sec in prompts:
            content = sec.get("content", "").replace("\n", "\\n")
            sheets_writer.append_row("プロンプト", [
                company_id,
                sec.get("section_type", ""),
                sec.get("job_category", ""),
                str(sec.get("order", 1)),
                content,
            ])
            total += 1

        # 4. Validation
        validation = generated.get("validation", {})
        qual_rules = validation.get("qualification_rules", "")
        if isinstance(qual_rules, dict):
            qual_rules = _json.dumps(qual_rules, ensure_ascii=False)
        cat_excl = validation.get("category_exclusions", "")
        if isinstance(cat_excl, dict):
            cat_excl = _json.dumps(cat_excl, ensure_ascii=False)
        sheets_writer.append_row("バリデーション", [
            company_id,
            str(validation.get("age_min", "")),
            str(validation.get("age_max", "")),
            qual_rules,
            cat_excl,
        ])
        total += 1

        # 5. Qualification modifiers (as QUAL rows in patterns sheet)
        qualifiers = generated.get("qualifiers", [])
        for q in qualifiers:
            # columns: company, job_category, pattern_type, employment_variant, template_text,
            #          feature_variations, display_name, target_description, match_rules,
            #          qualification_combo, replacement_text
            sheets_writer.append_row("パターン", [
                company_id, "nurse", "QUAL", "", "", "", "", "", "",
                q.get("qualification_combo", ""),
                q.get("replacement_text", ""),
            ])
            total += 1

        sheets_client.reload()

        # Add template info to response for UI preview
        if not generated.get("templates"):
            generated["templates"] = [{"type": tt, "body": "（手動入力）"} for tt in template_types]

        return {
            "status": "created",
            "company_id": company_id,
            "generated": generated,
            "total_rows": total,
        }

    except _json.JSONDecodeError as e:
        raise HTTPException(500, f"AI応答のJSON解析エラー: {str(e)}")
    except Exception as e:
        raise HTTPException(500, f"会社設定生成エラー: {str(e)}")


@router.post("/generate_patterns")
async def generate_patterns(data: dict, operator=Depends(verify_api_key)):
    """Generate pattern texts for all types using AI based on company info."""
    import json as _json
    from pipeline.ai_generator import generate_personalized_text

    company_id = data.get("company_id", "").strip()
    company_info = data.get("company_info", "").strip()
    if not company_info:
        raise HTTPException(400, "company_info is required")

    # Load company-specific prompt sections for pattern generation
    prompt_sections = sheets_client.get_company_config(company_id).get("prompt_sections", []) if company_id else []
    custom_prompt = ""
    for sec in prompt_sections:
        if sec.get("section_type") == "pattern_generation":
            custom_prompt += sec.get("content", "") + "\n"

    # Build system prompt
    system_prompt = custom_prompt if custom_prompt.strip() else """あなたは訪問看護・介護系のスカウト文ライターです。
以下の会社情報をもとに、8つのパターン型のスカウト文（template_text）と特色バリエーション（feature_variations）を生成してください。

## 型の構造
各型は「経歴が少ない候補者」に使う型はめパターンです。候補者の経験年数・年齢帯に応じて使い分けます。

| 型 | 対象 | 特徴 |
|----|------|------|
| A | 経験10年+のベテラン | 豊富な経験への期待・敬意を表現 |
| B1 | 経験6〜9年の中堅 | 確かな経験×会社の特色 |
| B2 | 経験3〜5年 | 経験×会社の特色 |
| C | 40代〜×経験1〜2年 | 経験とのフィット |
| D | 40代〜×経験未入力 | 経験ある前提で評価（就業中/離職中の2バリエーション） |
| E | 20〜30代×経験1〜2年 | ポテンシャル+教育体制 |
| F | 20〜30代×経験未入力 | 教育体制+成長環境（就業中/離職中の2バリエーション） |
| G | 在学中 | 教育体制メイン |

## ルール
- template_text: 2〜3文、句点で終わる。ですます調
- {特色} プレースホルダーを1箇所含める（特色バリエーションが挿入される位置）
- 型A・B1・B2: {N} プレースホルダー可（経験年数が入る）
- 型D・F: 就業中/離職中の2バリエーションを生成
- 型E・F・G: 教育体制を具体的に記載（会社情報から取得）
- 上から目線にならない（「フォローします」「安心してください」等は不可）
- feature_variations: 3つ、各バリエーションは会社の特色を短く表現（「〜する」「〜な」で終わる連体修飾形）

## 出力形式
以下のJSON配列で返してください。他のテキストは不要です。
```json
[
  {"pattern_type": "A", "employment_variant": "", "template_text": "...", "feature_variations": ["...", "...", "..."]},
  {"pattern_type": "B1", "employment_variant": "", "template_text": "...", "feature_variations": ["...", "...", "..."]},
  {"pattern_type": "B2", "employment_variant": "", "template_text": "...", "feature_variations": ["...", "...", "..."]},
  {"pattern_type": "C", "employment_variant": "", "template_text": "...", "feature_variations": ["...", "...", "..."]},
  {"pattern_type": "D", "employment_variant": "就業中", "template_text": "...", "feature_variations": ["...", "...", "..."]},
  {"pattern_type": "D", "employment_variant": "離職中", "template_text": "...", "feature_variations": ["...", "...", "..."]},
  {"pattern_type": "E", "employment_variant": "", "template_text": "...", "feature_variations": ["...", "...", "..."]},
  {"pattern_type": "F", "employment_variant": "就業中", "template_text": "...", "feature_variations": ["...", "...", "..."]},
  {"pattern_type": "F", "employment_variant": "離職中", "template_text": "...", "feature_variations": ["...", "...", "..."]},
  {"pattern_type": "G", "employment_variant": "", "template_text": "...", "feature_variations": ["...", "...", "..."]}
]
```"""

    try:
        gen_result = await generate_personalized_text(
            system_prompt=system_prompt,
            user_prompt=f"以下の会社情報をもとに、10パターンのスカウト文を生成してください。\n\n{company_info}",
            model_name=None,
        )
        result_text = gen_result.text

        # Extract JSON from response (may be wrapped in markdown code blocks)
        import re
        json_match = re.search(r'\[[\s\S]*\]', result_text)
        if not json_match:
            raise ValueError("AI応答からJSONを抽出できませんでした")

        patterns = _json.loads(json_match.group(0))
        return {"patterns": patterns}
    except Exception as e:
        raise HTTPException(500, f"AI生成エラー: {str(e)}")


@router.post("/sync_replies")
async def sync_replies(
    data: dict,
    operator=Depends(verify_api_key),
):
    """Chrome拡張から返信データを受け取り、送信データシートを更新する。"""
    company = data.get("company", "")
    replies = data.get("replies", [])
    if not replies:
        return {"status": "ok", "updated": 0}

    from pipeline.orchestrator import _send_data_sheet_name
    sheet_name = _send_data_sheet_name(company)

    try:
        all_rows = sheets_writer.get_all_rows(sheet_name)
    except Exception:
        return {"status": "error", "detail": f"送信データシート '{sheet_name}' が存在しません"}
    if len(all_rows) < 2:
        return {"status": "ok", "updated": 0}

    headers = all_rows[0]
    try:
        col_member = headers.index("会員番号")
        col_reply = headers.index("返信")
        col_reply_date = headers.index("返信日")
        col_reply_cat = headers.index("返信カテゴリ")
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"シートヘッダー不正: {e}")

    reply_map = {r["member_id"]: r for r in replies}

    updated = 0
    for row_idx, row in enumerate(all_rows[1:], start=2):
        if len(row) <= col_member:
            continue
        member_id = row[col_member]
        if member_id not in reply_map:
            continue

        reply = reply_map[member_id]
        # Write only the 3 reply cells by name — never touches other columns
        sheets_writer.update_cells_by_name(
            sheet_name,
            row_idx,
            {
                "返信": "有",
                "返信日": reply.get("replied_at", ""),
                "返信カテゴリ": reply.get("category", ""),
            },
            actor="sync_replies",
        )
        updated += 1

    return {"status": "ok", "updated": updated}


# ---------------------------------------------------------------------------
# 会話ログ蓄積 (Chrome拡張 / yaml import 両対応)
# ---------------------------------------------------------------------------

CONVERSATION_LOGS_COLUMNS = [
    "timestamp",      # ingestion time (ISO 8601)
    "company",        # company_id
    "member_id",
    "candidate_name",
    "candidate_age",
    "candidate_gender",
    "job_title",
    "started",        # date of first message in the thread
    "message_count",
    "messages_json",  # full [{date, role, text}, ...] as JSON
    "source",         # "extension_auto" | "extension_manual" | "yaml_import"
    "actor",
]


@router.post("/conversation_logs")
async def post_conversation_logs(
    data: dict,
    operator=Depends(verify_api_key),
):
    """Receive conversation threads from the Chrome extension (dev
    mode) and append them to the `会話ログ` sheet.

    Body:
      - company (str, required)
      - threads (list[dict], required): each thread has
          { member_id, candidate_name?, candidate_age?, candidate_gender?,
            job_title?, started?, messages: [{date, role, text}, ...] }
      - source (str, optional): defaults to "extension_manual"

    Dedup behaviour: same (company, member_id, started) as an existing
    row is replaced by overwriting `messages_json` + bumping timestamp.
    This lets the extension re-sync a conversation and pick up new
    messages without creating duplicates.
    """
    import json
    from datetime import datetime, timedelta, timezone

    JST = timezone(timedelta(hours=9))

    company = (data.get("company") or "").strip()
    threads = data.get("threads") or []
    source = (data.get("source") or "extension_manual").strip()
    if not company:
        raise HTTPException(400, "company is required")
    if not isinstance(threads, list) or not threads:
        raise HTTPException(400, "threads must be a non-empty list")

    sheets_writer.ensure_sheet_exists(
        SHEET_CONVERSATION_LOGS, CONVERSATION_LOGS_COLUMNS
    )

    # Preload existing rows so we can dedup by (company, member_id, started).
    try:
        all_rows = sheets_writer.get_all_rows(SHEET_CONVERSATION_LOGS)
    except Exception:
        all_rows = [list(CONVERSATION_LOGS_COLUMNS)]
    if not all_rows:
        all_rows = [list(CONVERSATION_LOGS_COLUMNS)]

    headers = [h.strip() for h in all_rows[0]]
    col = {h: headers.index(h) for h in CONVERSATION_LOGS_COLUMNS if h in headers}

    existing_key_to_row: dict[tuple[str, str, str], int] = {}
    for i, row in enumerate(all_rows[1:], start=2):
        def _get(name: str) -> str:
            idx = col.get(name)
            if idx is None or idx >= len(row):
                return ""
            return row[idx].strip()
        key = (_get("company"), _get("member_id"), _get("started"))
        if all(key):
            existing_key_to_row[key] = i

    actor_name = operator.get("name") or operator.get("operator_id") or "operator"
    now_iso = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")

    appended = 0
    updated = 0
    for thread in threads:
        member_id = (thread.get("member_id") or "").strip()
        if not member_id:
            continue
        messages = thread.get("messages") or []
        if not isinstance(messages, list):
            continue
        started = (thread.get("started") or "").strip()
        if not started and messages:
            started = str(messages[0].get("date") or "")

        row_values = [
            now_iso,
            company,
            member_id,
            (thread.get("candidate_name") or "").strip(),
            (thread.get("candidate_age") or "").strip(),
            (thread.get("candidate_gender") or "").strip(),
            (thread.get("job_title") or "").strip(),
            started,
            str(len(messages)),
            json.dumps(messages, ensure_ascii=False),
            source,
            actor_name,
        ]

        key = (company, member_id, started)
        existing_row = existing_key_to_row.get(key)
        if existing_row is not None:
            cells = {CONVERSATION_LOGS_COLUMNS[i]: row_values[i] for i in range(len(CONVERSATION_LOGS_COLUMNS))}
            sheets_writer.update_cells_by_name(
                SHEET_CONVERSATION_LOGS,
                existing_row,
                cells,
                actor=f"conversation_logs:{actor_name}",
            )
            updated += 1
        else:
            sheets_writer.append_row(SHEET_CONVERSATION_LOGS, row_values)
            appended += 1

    return {"status": "ok", "appended": appended, "updated": updated}


# ---------------------------------------------------------------------------
# 修正フィードバック (Phase A: 蓄積 + 一覧 + status更新)
# ---------------------------------------------------------------------------

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


def _gen_fix_id() -> str:
    return f"fb_{uuid.uuid4().hex[:8]}"


@router.post("/sync_fixes")
async def sync_fixes(
    data: dict,
    operator: dict = Depends(verify_api_key),
):
    """Chrome拡張から修正diff(FixRecord[])を受け取り、修正フィードバックシートに追記する。

    冪等性: クライアントが id を送ってきた場合、既存行と重複していたらスキップ。
    """
    company = (data.get("company") or "").strip()
    fixes = data.get("fixes") or []
    if not fixes:
        return {"status": "ok", "appended": 0, "skipped_duplicate": 0}

    # 1. シートが無ければ作成
    sheets_writer.ensure_sheet_exists(SHEET_FIX_FEEDBACK, FIX_FEEDBACK_COLUMNS)

    # 2. 既存IDセットを取得（重複防止）
    try:
        all_rows = sheets_writer.get_all_rows(SHEET_FIX_FEEDBACK)
    except Exception:
        all_rows = [FIX_FEEDBACK_COLUMNS]
    headers = all_rows[0] if all_rows else FIX_FEEDBACK_COLUMNS
    try:
        id_idx = headers.index("id")
    except ValueError:
        id_idx = 0
    existing_ids = {
        row[id_idx].strip()
        for row in all_rows[1:]
        if len(row) > id_idx and row[id_idx].strip()
    }

    actor_name = operator.get("name") or operator.get("operator_id") or "operator"
    appended = 0
    skipped_duplicate = 0

    for fix in fixes:
        fix_id = (fix.get("id") or "").strip() or _gen_fix_id()
        if fix_id in existing_ids:
            skipped_duplicate += 1
            continue
        row = {
            "id": fix_id,
            "timestamp": fix.get("timestamp") or datetime.utcnow().isoformat(timespec="seconds"),
            "company": company,
            "member_id": fix.get("member_id", ""),
            "template_type": fix.get("template_type", ""),
            "before": fix.get("before", ""),
            "after": fix.get("after", ""),
            "reason": fix.get("reason", ""),
            "status": "pending",
            "actor": actor_name,
            "note": "",
        }
        sheets_writer.append_row(
            SHEET_FIX_FEEDBACK,
            [row[col] for col in FIX_FEEDBACK_COLUMNS],
        )
        existing_ids.add(fix_id)
        appended += 1

    return {"status": "ok", "appended": appended, "skipped_duplicate": skipped_duplicate}


@router.post("/fix_feedback/{fix_id}/status")
async def update_fix_status(
    fix_id: str,
    data: dict,
    operator: dict = Depends(verify_api_key),
):
    """個別の修正フィードバックの status / note を更新する。"""
    new_status = (data.get("status") or "").strip()
    if new_status not in ("pending", "adopted", "skipped"):
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of pending/adopted/skipped (got: {new_status!r})",
        )

    try:
        all_rows = sheets_writer.get_all_rows(SHEET_FIX_FEEDBACK)
    except Exception:
        raise HTTPException(status_code=404, detail="修正フィードバックシートが存在しません")
    if not all_rows or len(all_rows) < 2:
        raise HTTPException(status_code=404, detail=f"id '{fix_id}' が見つかりません")

    headers = all_rows[0]
    try:
        id_idx = headers.index("id")
    except ValueError:
        raise HTTPException(status_code=500, detail="シートヘッダー不正: id 列なし")

    target_row: int | None = None
    for i, row in enumerate(all_rows[1:], start=2):
        if len(row) > id_idx and row[id_idx].strip() == fix_id:
            target_row = i
            break
    if target_row is None:
        raise HTTPException(status_code=404, detail=f"id '{fix_id}' が見つかりません")

    cells: dict[str, str] = {"status": new_status}
    if "note" in data:
        cells["note"] = data.get("note") or ""

    actor_name = operator.get("name") or operator.get("operator_id") or "operator"
    sheets_writer.update_cells_by_name(
        SHEET_FIX_FEEDBACK,
        target_row,
        cells,
        actor=f"update_fix_status:{actor_name}",
    )
    return {"status": "ok", "id": fix_id, "new_status": new_status}


# ---------------------------------------------------------------------------
# 修正フィードバック Phase B: AI改善提案 → 承認 → Sheets実反映
# 第一弾: 職種キーワードへの追加提案（append-only）
# 第二弾: プロンプトシートへの新規 section 追加（append-only）
# patterns / 既存行 update は次フェーズ。
# ---------------------------------------------------------------------------

IMPROVEMENT_PROPOSAL_COLUMNS = [
    "id",                 # fbprop_xxxxxxxx
    "created_at",         # ISO 8601
    "source_fix_ids",     # comma-separated fix_feedback ids that prompted this proposal
    "target_sheet",       # "job_category_keywords" | "prompts"
    "operation",          # "append" 固定（次フェーズで update/delete を追加）
    "scope_company",      # "" = 全社共通 / company_id = 会社別
    "payload_json",       # 追加内容を JSON dict
    "rationale",          # AIが書いた根拠
    "status",             # "pending" | "approved" | "rejected"
    "actor",              # 承認/却下した人
    "decided_at",         # ISO 8601
]

# Phase B でサポートする target_sheet と operation の組み合わせ
SUPPORTED_PROPOSAL_TARGETS = {
    "job_category_keywords": {"append"},
    "prompts": {"append"},
    "patterns": {"update"},
}

# プロンプトシートで会社固有に上書き可能な section_type（routes_admin.py 1029行に既出）
PROMPT_COMPANY_SECTION_TYPES = {"station_features", "education", "ai_guide"}


def _gen_proposal_id() -> str:
    return f"fbprop_{uuid.uuid4().hex[:8]}"


def _build_keyword_proposal_inputs(pending: list[dict]) -> tuple[str, str, set]:
    """target=job_category_keywords 用: (system_prompt, user_prompt, dedup_keys)"""
    import json as _json
    try:
        kw_rows = sheets_writer.get_all_rows("職種キーワード")
    except Exception:
        kw_rows = []
    existing_keywords: list[dict] = []
    if kw_rows and len(kw_rows) >= 2:
        kw_headers = [h.strip() for h in kw_rows[0]]
        for row in kw_rows[1:]:
            item = {h: (row[i].strip() if i < len(row) else "") for i, h in enumerate(kw_headers)}
            if item.get("enabled", "TRUE").upper() == "FALSE":
                continue
            existing_keywords.append({
                "company": item.get("company", ""),
                "job_category": item.get("job_category", ""),
                "keyword": item.get("keyword", ""),
            })

    system_prompt = """あなたはスカウト文生成システムの「職種キーワード辞書」を改善するアシスタントです。

ディレクターが手動で修正したスカウト文の差分（before/after/reason）を読み、職種カテゴリの自動判定が外れた原因が「辞書に未登録のキーワード」であるケースを特定し、職種キーワードシートへの追加提案をJSON配列で返してください。

# 判断基準
- after で追加された語句、reason で言及されている語句のうち、職種の特定に効きそうな名詞・職種名・資格名・施設名（例: "訪問看護", "通所リハビリ", "ICU", "PT"）に注目する
- before/after が同じ会社の同じ職種カテゴリでも、地名・氏名・候補者固有の経験は提案しない
- 既存キーワードリスト（既に登録済み）と重複するものは提案しない
- 1つのキーワードは1〜20文字、過度に一般的な語（"看護"単独など）は避ける

# scope_company の決め方
- 会社固有の施設名・部署名・サービス名 → scope_company を会社IDに
- 一般的な職種名・資格名・業務名 → scope_company を空文字（全社共通）に

# 出力フォーマット（厳守）
JSON配列のみを出力すること。説明文や ``` などのマークダウンは禁止。
各要素は次のキーを持つ:
- "keyword": 追加するキーワード文字列
- "job_category": 推定する職種カテゴリ（既存の職種ID: nurse / rehab_pt / rehab_st / rehab_ot / dietitian / counselor / medical_office）
- "scope_company": "" または会社ID
- "source_fields": "qualification" | "desired_job" | "experience" | "self_pr" のいずれか、または複数をカンマ区切り
- "rationale": なぜこのキーワードが必要か（30〜80文字）
- "source_fix_ids": この提案の根拠になった fix_feedback の id 配列

提案は最大10件まで。提案がない場合は空配列 [] を返す。"""

    fixes_for_prompt = [
        {
            "id": f["id"],
            "company": f.get("company", ""),
            "template_type": f.get("template_type", ""),
            "before": (f.get("before") or "")[:600],
            "after": (f.get("after") or "")[:600],
            "reason": (f.get("reason") or "")[:300],
        }
        for f in pending
    ]
    user_prompt = (
        "## 既存の職種キーワード（追加提案で重複を避けるため）\n"
        + _json.dumps(existing_keywords[:200], ensure_ascii=False, indent=2)
        + "\n\n## ディレクターによる修正フィードバック (pending)\n"
        + _json.dumps(fixes_for_prompt, ensure_ascii=False, indent=2)
        + "\n\nこれらの修正から、職種キーワードシートに追加すべき項目を JSON 配列で出力してください。"
    )
    dedup_keys = {(k["company"], k["job_category"], k["keyword"]) for k in existing_keywords}
    return system_prompt, user_prompt, dedup_keys


def _build_prompt_proposal_inputs(pending: list[dict]) -> tuple[str, str, set]:
    """target=prompts 用: (system_prompt, user_prompt, dedup_keys)"""
    import json as _json
    try:
        prompt_rows = sheets_writer.get_all_rows("プロンプト")
    except Exception:
        prompt_rows = []
    existing_prompts: list[dict] = []
    if prompt_rows and len(prompt_rows) >= 2:
        ph = [h.strip() for h in prompt_rows[0]]
        for row in prompt_rows[1:]:
            item = {h: (row[i].strip() if i < len(row) else "") for i, h in enumerate(ph)}
            section_type = item.get("section_type", "")
            if section_type not in PROMPT_COMPANY_SECTION_TYPES:
                continue
            existing_prompts.append({
                "company": item.get("company", ""),
                "section_type": section_type,
                "job_category": item.get("job_category", ""),
                "order": item.get("order", ""),
                "content_excerpt": (item.get("content", "") or "")[:200],
            })

    system_prompt = """あなたはスカウト文生成パイプラインの「プロンプトシート」を改善するアシスタントです。

ディレクターが手動で修正したスカウト文の差分から、AIが生成時に参照する「会社の特色 / 教育体制 / 経験別の接点ガイド」セクションに不足している情報を特定し、プロンプトシートへの追加提案をJSON配列で返してください。

# 対象 section_type（厳守、これ以外は出力しない）
- station_features: 施設の特色・どんな経験が活きるか（order=2）
- education: 教育体制・研修制度（order=3）
- ai_guide: 経歴別の接点対応表 + NGパターン（order=8）

# 判断基準
- after や reason に出てきた「会社の強み・サービス内容・教育制度・接点パターン」のうち、既存の同 (company, section_type, job_category) 行に書かれていないものに限る
- 候補者個別の事情・地名・氏名などは追加しない
- 既存 content と重複する提案はしない
- scope_company は基本的に対象会社IDを指定する。全社共通として汎用化できる場合のみ空文字を返す

# 出力フォーマット（厳守）
JSON配列のみ。説明文や ``` などのマークダウンは禁止。
各要素のキー:
- "section_type": "station_features" | "education" | "ai_guide"
- "job_category": "nurse" / "rehab_pt" / "rehab_st" / "rehab_ot" / "dietitian" / "counselor" / "medical_office"
- "scope_company": "" または対象会社ID
- "content": 追加する markdown 箇条書き（- で始まる行を1〜3行）
- "rationale": なぜ追加するか（30〜80文字）
- "source_fix_ids": fix_feedback id の配列

提案は最大8件まで。なければ []。"""

    fixes_for_prompt = [
        {
            "id": f["id"],
            "company": f.get("company", ""),
            "template_type": f.get("template_type", ""),
            "before": (f.get("before") or "")[:600],
            "after": (f.get("after") or "")[:600],
            "reason": (f.get("reason") or "")[:300],
        }
        for f in pending
    ]
    user_prompt = (
        "## 既存のプロンプトセクション（重複を避けるため）\n"
        + _json.dumps(existing_prompts[:120], ensure_ascii=False, indent=2)
        + "\n\n## ディレクターによる修正フィードバック (pending)\n"
        + _json.dumps(fixes_for_prompt, ensure_ascii=False, indent=2)
        + "\n\nこれらから、プロンプトシートに追加すべき section を JSON 配列で出力してください。"
    )
    dedup_keys = {
        (p["company"], p["section_type"], p["job_category"], p["content_excerpt"][:80])
        for p in existing_prompts
    }
    return system_prompt, user_prompt, dedup_keys


def _build_pattern_proposal_inputs(pending: list[dict]) -> tuple[str, str, set]:
    """target=patterns 用: (system_prompt, user_prompt, dedup_keys)

    patterns シートは型ごとの template_text + feature_variations + match_rules で構成され、
    完全な append は型システム上難しい。Phase B 第3弾では feature_variations への
    語句追加（同じ型の特色バリエーションを増やす）に絞る。
    """
    import json as _json
    try:
        pattern_rows = sheets_writer.get_all_rows("パターン")
    except Exception:
        pattern_rows = []
    existing_patterns: list[dict] = []
    if pattern_rows and len(pattern_rows) >= 2:
        ph = [h.strip() for h in pattern_rows[0]]
        for row in pattern_rows[1:]:
            item = {h: (row[i].strip() if i < len(row) else "") for i, h in enumerate(ph)}
            if item.get("pattern_type", "") == "QUAL":
                continue
            features = [f.strip() for f in (item.get("feature_variations") or "").split("|") if f.strip()]
            existing_patterns.append({
                "company": item.get("company", ""),
                "job_category": item.get("job_category", ""),
                "pattern_type": item.get("pattern_type", ""),
                "employment_variant": item.get("employment_variant", ""),
                "feature_variations": features,
                "template_text_excerpt": (item.get("template_text", "") or "")[:120],
            })

    system_prompt = """あなたはスカウト文生成パイプラインの「型はめパターン」を改善するアシスタントです。

ディレクターが手動修正したスカウト文の差分から、既存の型はめパターンの「特色バリエーション」(feature_variations) に追加すべき語句・短文を特定し、JSON配列で返してください。

# 前提
- パターン (型A〜G) は経験年数 × 年齢のマトリクスで選ばれる、骨格は固定の型です
- feature_variations は型のテキスト中で差し替え可能な特色バリエーション（| 区切り）
- 既存パターン一覧をユーザープロンプトに渡します。company / pattern_type / job_category がマッチするものに対してのみ提案してください

# 判断基準
- after や reason から、その会社の強みや業務特色を表す短い表現（10〜30文字）を抽出
- 既に feature_variations に含まれているものは提案しない
- 候補者個別の事情ではなく、その会社の他候補者にも使い回せる語句に限る
- scope_company は基本的に対象会社IDを指定する

# 出力フォーマット（厳守）
JSON配列のみ。説明文や ``` 禁止。
各要素のキー:
- "company": 対象会社ID（必須、scope_company と同じ値）
- "scope_company": 対象会社ID
- "pattern_type": "A" / "B1" / "B2" / "C" / "D" / "E" / "F" / "G"
- "job_category": "nurse" など
- "employment_variant": "" / "就業中" / "離職中"
- "new_feature": 追加する特色バリエーション文字列
- "rationale": なぜ追加するか（30〜80文字）
- "source_fix_ids": fix_feedback id 配列

提案は最大6件。なければ []。"""

    fixes_for_prompt = [
        {
            "id": f["id"],
            "company": f.get("company", ""),
            "template_type": f.get("template_type", ""),
            "before": (f.get("before") or "")[:600],
            "after": (f.get("after") or "")[:600],
            "reason": (f.get("reason") or "")[:300],
        }
        for f in pending
    ]
    user_prompt = (
        "## 既存の型はめパターン（提案先を選ぶための一覧）\n"
        + _json.dumps(existing_patterns[:80], ensure_ascii=False, indent=2)
        + "\n\n## ディレクターによる修正フィードバック (pending)\n"
        + _json.dumps(fixes_for_prompt, ensure_ascii=False, indent=2)
        + "\n\n適切な既存パターンに追加すべき特色バリエーションを JSON 配列で出力してください。"
    )
    # dedup: (company, pattern_type, job_category, employment_variant, feature)
    dedup_keys = set()
    for p in existing_patterns:
        for feat in p["feature_variations"]:
            dedup_keys.add((
                p["company"], p["pattern_type"], p["job_category"],
                p["employment_variant"], feat,
            ))
    return system_prompt, user_prompt, dedup_keys


@router.post("/improvement_proposals/generate")
async def generate_improvement_proposals(
    data: dict,
    operator=Depends(verify_api_key),
):
    """pending な fix_feedback を集約して Gemini に渡し、改善提案を生成する。

    Body:
      - target (optional, default "job_category_keywords"):
        "job_category_keywords" | "prompts" | "patterns"
      - company (optional)
      - max_fixes (optional, default 50)
      - dry_run (optional, default False)
    """
    import json
    import re as _re
    from datetime import datetime as _dt
    from pipeline.ai_generator import generate_personalized_text
    from db.sheets_client import SHEET_IMPROVEMENT_PROPOSALS

    target = (data.get("target") or "job_category_keywords").strip()
    if target not in SUPPORTED_PROPOSAL_TARGETS:
        raise HTTPException(400, f"Unsupported target: {target}")
    company_filter = (data.get("company") or "").strip()
    max_fixes = int(data.get("max_fixes") or 50)
    dry_run = bool(data.get("dry_run") or False)

    # 1. pending な fix_feedback を取得
    try:
        all_rows = sheets_writer.get_all_rows(SHEET_FIX_FEEDBACK)
    except Exception:
        return {"status": "ok", "appended": 0, "proposals": [], "warning": "no fix_feedback sheet"}
    if not all_rows or len(all_rows) < 2:
        return {"status": "ok", "appended": 0, "proposals": [], "warning": "no fixes"}

    headers = [h.strip() for h in all_rows[0]]
    pending: list[dict] = []
    for row in all_rows[1:]:
        item = {h: (row[i].strip() if i < len(row) else "") for i, h in enumerate(headers)}
        if item.get("status", "") != "pending":
            continue
        if company_filter and item.get("company", "") != company_filter:
            continue
        pending.append(item)
        if len(pending) >= max_fixes:
            break

    if not pending:
        return {"status": "ok", "appended": 0, "proposals": [], "warning": "no pending fixes"}

    # 2. target ごとに system/user prompt + dedup_keys を組み立てる
    if target == "job_category_keywords":
        system_prompt, user_prompt, dedup_keys = _build_keyword_proposal_inputs(pending)
    elif target == "prompts":
        system_prompt, user_prompt, dedup_keys = _build_prompt_proposal_inputs(pending)
    elif target == "patterns":
        system_prompt, user_prompt, dedup_keys = _build_pattern_proposal_inputs(pending)
    else:
        raise HTTPException(400, f"Unsupported target: {target}")

    # 3. Gemini 呼び出し
    from config import GEMINI_PRO_MODEL
    try:
        result = await generate_personalized_text(
            system_prompt,
            user_prompt,
            model_name=GEMINI_PRO_MODEL,
            max_output_tokens=4096,
            temperature=0.3,
        )
        raw = result.text or ""
    except Exception as e:
        raise HTTPException(500, f"AI生成エラー: {e}")

    raw = _re.sub(r"^```[^\n]*\n", "", raw.strip())
    raw = _re.sub(r"\n```$", "", raw.strip())
    try:
        suggestions = json.loads(raw)
        if not isinstance(suggestions, list):
            raise ValueError("Gemini did not return a list")
    except Exception as e:
        raise HTTPException(500, f"Gemini出力のJSONパース失敗: {e} / raw={raw[:300]}")

    # 4. target ごとに proposal dict を組み立てる
    proposals_out: list[dict] = []
    actor_name = operator.get("name") or operator.get("operator_id") or "operator"
    now_iso = _dt.utcnow().isoformat(timespec="seconds")

    for s in suggestions:
        scope_company = (s.get("scope_company") or "").strip()

        if target == "job_category_keywords":
            keyword = (s.get("keyword") or "").strip()
            job_category = (s.get("job_category") or "").strip()
            if not keyword or not job_category:
                continue
            if (scope_company, job_category, keyword) in dedup_keys:
                continue
            payload = {
                "keyword": keyword,
                "job_category": job_category,
                "source_fields": (s.get("source_fields") or "desired_job,experience,self_pr").strip(),
                "note": f"Phase B AI提案 / {(s.get('rationale') or '')[:60]}",
            }

        elif target == "prompts":
            section_type = (s.get("section_type") or "").strip()
            job_category = (s.get("job_category") or "").strip()
            content = (s.get("content") or "").strip()
            if section_type not in PROMPT_COMPANY_SECTION_TYPES:
                continue
            if not job_category or not content:
                continue
            if (scope_company, section_type, job_category, content[:80]) in dedup_keys:
                continue
            order_default = "2" if section_type == "station_features" else ("3" if section_type == "education" else "8")
            payload = {
                "section_type": section_type,
                "job_category": job_category,
                "content": content,
                "order": order_default,
            }

        else:  # patterns
            pattern_type = (s.get("pattern_type") or "").strip()
            job_category = (s.get("job_category") or "").strip()
            new_feature = (s.get("new_feature") or "").strip()
            employment_variant = (s.get("employment_variant") or "").strip()
            target_company = (s.get("company") or scope_company or "").strip()
            if not pattern_type or not job_category or not new_feature or not target_company:
                continue
            if (target_company, pattern_type, job_category, employment_variant, new_feature) in dedup_keys:
                continue
            scope_company = target_company  # patterns は会社固有が前提
            payload = {
                "pattern_type": pattern_type,
                "job_category": job_category,
                "employment_variant": employment_variant,
                "new_feature": new_feature,
            }

        proposal = {
            "id": _gen_proposal_id(),
            "created_at": now_iso,
            "source_fix_ids": ",".join(s.get("source_fix_ids") or []),
            "target_sheet": target,
            "operation": "append" if target != "patterns" else "update",
            "scope_company": scope_company,
            "payload_json": json.dumps(payload, ensure_ascii=False),
            "rationale": (s.get("rationale") or "").strip()[:300],
            "status": "pending",
            "actor": "",
            "decided_at": "",
        }
        proposals_out.append(proposal)

    if not proposals_out:
        return {"status": "ok", "appended": 0, "proposals": [], "warning": "AIから新規提案なし"}

    if not dry_run:
        sheets_writer.ensure_sheet_exists(SHEET_IMPROVEMENT_PROPOSALS, IMPROVEMENT_PROPOSAL_COLUMNS)
        for p in proposals_out:
            sheets_writer.append_row(
                SHEET_IMPROVEMENT_PROPOSALS,
                [p[c] for c in IMPROVEMENT_PROPOSAL_COLUMNS],
            )

    return {
        "status": "ok",
        "target": target,
        "appended": 0 if dry_run else len(proposals_out),
        "proposals": proposals_out,
        "model": result.model_name if hasattr(result, "model_name") else "",
        "actor": actor_name,
    }


@router.post("/improvement_proposals/{proposal_id}/decide")
async def decide_improvement_proposal(
    proposal_id: str,
    data: dict,
    operator=Depends(verify_api_key),
):
    """改善提案の承認/却下。

    Body:
      - decision: "approve" | "reject"
      - scope_company (optional): 承認時に scope を上書きしたい場合
      - payload_overrides (optional dict): keyword/job_category/source_fields/note を上書き

    approve の場合、target_sheet (=職種キーワード) に append し、proposal の
    status=approved にし、紐付く fix_feedback も adopted にする。
    """
    import json
    from datetime import datetime as _dt
    from db.sheets_client import SHEET_IMPROVEMENT_PROPOSALS

    decision = (data.get("decision") or "").strip()
    if decision not in ("approve", "reject"):
        raise HTTPException(400, "decision must be 'approve' or 'reject'")

    try:
        all_rows = sheets_writer.get_all_rows(SHEET_IMPROVEMENT_PROPOSALS)
    except Exception:
        raise HTTPException(404, "改善提案シートが存在しません")
    if not all_rows or len(all_rows) < 2:
        raise HTTPException(404, "改善提案がありません")

    headers = [h.strip() for h in all_rows[0]]
    try:
        id_idx = headers.index("id")
    except ValueError:
        raise HTTPException(500, "改善提案シートのヘッダー不正")

    target_row_idx: int | None = None
    target_row: dict = {}
    for i, row in enumerate(all_rows[1:], start=2):
        if len(row) > id_idx and row[id_idx].strip() == proposal_id:
            target_row_idx = i
            target_row = {h: (row[j].strip() if j < len(row) else "") for j, h in enumerate(headers)}
            break
    if target_row_idx is None:
        raise HTTPException(404, f"提案 '{proposal_id}' が見つかりません")
    if target_row.get("status", "") != "pending":
        raise HTTPException(
            409,
            f"提案 '{proposal_id}' は既に処理済みです (status={target_row.get('status')})",
        )

    actor_name = operator.get("name") or operator.get("operator_id") or "operator"
    now_iso = _dt.utcnow().isoformat(timespec="seconds")

    if decision == "reject":
        sheets_writer.update_cells_by_name(
            SHEET_IMPROVEMENT_PROPOSALS,
            target_row_idx,
            {"status": "rejected", "actor": actor_name, "decided_at": now_iso},
            actor=f"reject_proposal:{actor_name}",
        )
        return {"status": "ok", "id": proposal_id, "new_status": "rejected"}

    # === approve ===
    target_sheet = target_row.get("target_sheet", "")
    operation = target_row.get("operation", "")
    allowed_ops = SUPPORTED_PROPOSAL_TARGETS.get(target_sheet, set())
    if operation not in allowed_ops:
        raise HTTPException(
            400,
            f"未対応の target/operation: {target_sheet}/{operation}",
        )

    try:
        payload = json.loads(target_row.get("payload_json", "") or "{}")
    except Exception as e:
        raise HTTPException(400, f"payload_json パース失敗: {e}")

    overrides = data.get("payload_overrides") or {}
    scope_company = data.get("scope_company")
    if scope_company is None:
        scope_company = target_row.get("scope_company", "")
    scope_company = (scope_company or "").strip()

    appended_row: dict = {}

    if target_sheet == "job_category_keywords":
        for k in ("keyword", "job_category", "source_fields", "note"):
            if k in overrides and overrides[k] is not None:
                payload[k] = str(overrides[k]).strip()
        keyword = payload.get("keyword", "").strip()
        job_category = payload.get("job_category", "").strip()
        if not keyword or not job_category:
            raise HTTPException(400, "keyword/job_category は必須です")
        sheet_name = SHEET_MAP["job_category_keywords"]
        columns = COLUMNS["job_category_keywords"]
        row_dict = {
            "company": scope_company,
            "job_category": job_category,
            "keyword": keyword,
            "source_fields": payload.get("source_fields", "desired_job,experience,self_pr"),
            "weight": "1",
            "enabled": "TRUE",
            "added_at": now_iso,
            "added_by": actor_name,
            "note": payload.get("note", ""),
        }
        sheets_writer.append_row(sheet_name, [row_dict.get(c, "") for c in columns])
        appended_row = row_dict

    elif target_sheet == "prompts":
        for k in ("section_type", "job_category", "content", "order"):
            if k in overrides and overrides[k] is not None:
                payload[k] = str(overrides[k]).strip()
        section_type = payload.get("section_type", "").strip()
        job_category = payload.get("job_category", "").strip()
        content = payload.get("content", "").strip()
        if section_type not in PROMPT_COMPANY_SECTION_TYPES:
            raise HTTPException(400, f"section_type は {PROMPT_COMPANY_SECTION_TYPES} のいずれかである必要があります")
        if not job_category or not content:
            raise HTTPException(400, "job_category / content は必須です")
        sheet_name = SHEET_MAP["prompts"]
        columns = COLUMNS["prompts"]
        # content の改行を Sheets 用に \n リテラル化（既存運用に合わせる）
        content_for_sheet = content.replace("\n", "\\n")
        row_dict = {
            "company": scope_company,
            "section_type": section_type,
            "job_category": job_category,
            "order": str(payload.get("order", "")),
            "content": content_for_sheet,
        }
        sheets_writer.append_row(sheet_name, [row_dict.get(c, "") for c in columns])
        appended_row = row_dict

    elif target_sheet == "patterns" and operation == "update":
        # patterns の場合: 既存行の feature_variations に new_feature を append する
        for k in ("pattern_type", "job_category", "employment_variant", "new_feature"):
            if k in overrides and overrides[k] is not None:
                payload[k] = str(overrides[k]).strip()
        pattern_type = payload.get("pattern_type", "").strip()
        job_category = payload.get("job_category", "").strip()
        employment_variant = payload.get("employment_variant", "").strip()
        new_feature = payload.get("new_feature", "").strip()
        if not pattern_type or not job_category or not new_feature:
            raise HTTPException(400, "pattern_type / job_category / new_feature は必須です")
        if not scope_company:
            raise HTTPException(400, "patterns の承認には scope_company（対象会社ID）が必須です")

        # 該当する pattern 行を探す
        sheet_name = SHEET_MAP["patterns"]
        try:
            pattern_rows = sheets_writer.get_all_rows(sheet_name)
        except Exception as e:
            raise HTTPException(500, f"パターンシート読み込み失敗: {e}")
        if not pattern_rows or len(pattern_rows) < 2:
            raise HTTPException(404, "パターンシートが空です")
        pat_headers = [h.strip() for h in pattern_rows[0]]
        try:
            ic = pat_headers.index("company")
            ipt = pat_headers.index("pattern_type")
            ijc = pat_headers.index("job_category")
            iev = pat_headers.index("employment_variant")
            ifv = pat_headers.index("feature_variations")
        except ValueError as e:
            raise HTTPException(500, f"パターンシートヘッダー不正: {e}")

        pattern_row_idx: int | None = None
        existing_features: list[str] = []
        for i, row in enumerate(pattern_rows[1:], start=2):
            if (
                len(row) > max(ic, ipt, ijc, iev, ifv)
                and row[ic].strip() == scope_company
                and row[ipt].strip() == pattern_type
                and row[ijc].strip() == job_category
                and row[iev].strip() == employment_variant
                and row[ipt].strip() != "QUAL"
            ):
                pattern_row_idx = i
                existing_features = [
                    f.strip() for f in (row[ifv].strip() or "").split("|") if f.strip()
                ]
                break
        if pattern_row_idx is None:
            raise HTTPException(
                404,
                f"対象パターンが見つかりません: company={scope_company} type={pattern_type} jc={job_category} ev={employment_variant}",
            )
        if new_feature in existing_features:
            raise HTTPException(409, f"feature '{new_feature}' は既に登録済みです")
        merged = existing_features + [new_feature]
        sheets_writer.update_cells_by_name(
            sheet_name,
            pattern_row_idx,
            {"feature_variations": "|".join(merged)},
            actor=f"approve_proposal_pattern:{actor_name}",
        )
        appended_row = {
            "company": scope_company,
            "pattern_type": pattern_type,
            "job_category": job_category,
            "employment_variant": employment_variant,
            "feature_variations": "|".join(merged),
            "added_feature": new_feature,
            "_row_index": pattern_row_idx,
        }

    else:
        raise HTTPException(400, f"未対応の target/operation: {target_sheet}/{operation}")

    # 提案を approved に
    sheets_writer.update_cells_by_name(
        SHEET_IMPROVEMENT_PROPOSALS,
        target_row_idx,
        {"status": "approved", "actor": actor_name, "decided_at": now_iso, "scope_company": scope_company},
        actor=f"approve_proposal:{actor_name}",
    )

    # 紐付く fix_feedback も adopted にする（best-effort）
    adopted_fix_ids: list[str] = []
    source_ids = (target_row.get("source_fix_ids") or "").split(",")
    source_ids = [s.strip() for s in source_ids if s.strip()]
    if source_ids:
        try:
            fix_rows = sheets_writer.get_all_rows(SHEET_FIX_FEEDBACK)
            fix_headers = [h.strip() for h in fix_rows[0]]
            id_col = fix_headers.index("id")
            for i, row in enumerate(fix_rows[1:], start=2):
                if len(row) > id_col and row[id_col].strip() in source_ids:
                    sheets_writer.update_cells_by_name(
                        SHEET_FIX_FEEDBACK,
                        i,
                        {"status": "adopted", "note": f"Phase B 提案 {proposal_id} 経由"},
                        actor=f"approve_proposal_cascade:{actor_name}",
                    )
                    adopted_fix_ids.append(row[id_col].strip())
        except Exception:
            pass

    return {
        "status": "ok",
        "id": proposal_id,
        "new_status": "approved",
        "target_sheet": target_sheet,
        "appended_row": appended_row,
        "appended_keyword": appended_row,  # 後方互換: 既存テスト名
        "adopted_fix_ids": adopted_fix_ids,
    }


# ---------------------------------------------------------------------------
# Diagnosis system constants
# ---------------------------------------------------------------------------

DIAGNOSIS_HISTORY_SHEET = "診断履歴"
DIAGNOSIS_HISTORY_HEADERS = [
    "id", "created_at", "company", "template_type", "job_category",
    "row_index", "gate1_score", "gate2_score", "gate3_score",
    "weak_principles", "ai_smell_count", "priority_actions",
    "improvement_targets_json", "actor",
]

VALID_KNOWLEDGE_CATEGORIES = {"tone", "expression", "profile_handling", "template_tip", "qualification"}


@router.post("/diagnose_template")
async def diagnose_template(
    data: dict,
    operator=Depends(verify_api_key),
):
    """スカウト文全体を good-scout-pro.md の知見で診断し、構造化された結果を返す。"""
    import json as _json
    import os
    from pipeline.orchestrator import _send_data_sheet_name, COMPANY_DISPLAY_NAMES
    from pipeline.ai_generator import generate_personalized_text
    from config import GEMINI_PRO_MODEL

    company = data.get("company", "")
    template_type = data.get("template_type", "")
    job_category = data.get("job_category", "")
    requested_row_index = data.get("row_index")

    if not company:
        return {"status": "error", "detail": "company は必須です"}

    # 1. Get template body
    all_template_rows = sheets_writer.get_all_rows("テンプレート")
    row_index = None
    original_body = ""

    if requested_row_index:
        row_index = int(requested_row_index)
        if 2 <= row_index <= len(all_template_rows):
            row = all_template_rows[row_index - 1]
            original_body = row[3].replace("\\n", "\n") if len(row) > 3 else ""
            if not template_type and len(row) > 2:
                template_type = row[2]
            if not job_category and len(row) > 1:
                job_category = row[1]
        else:
            return {"status": "error", "detail": f"Row {row_index} not found"}
    else:
        for idx, row in enumerate(all_template_rows[1:], start=2):
            if len(row) >= 4 and row[0] == company and row[2] == template_type:
                if not job_category or row[1] == job_category:
                    row_index = idx
                    original_body = row[3].replace("\\n", "\n") if len(row) > 3 else ""
                    break

    if row_index is None or not original_body:
        return {"status": "error", "detail": "テンプレートが見つかりません"}

    # 2. Load company profile
    company_profile = sheets_client.get_company_profile(company)

    # 3. Get send data stats + full_text samples
    from datetime import datetime, timedelta, timezone
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    date_from = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    stats_text = ""
    full_text_samples = []
    sheet_name = _send_data_sheet_name(company)
    try:
        all_rows = sheets_writer.get_all_rows(sheet_name)
        if len(all_rows) >= 2:
            headers = all_rows[0]
            col_map = {h: i for i, h in enumerate(headers)}
            total = 0
            replied = 0
            full_text_col = col_map.get("全文")
            type_col = col_map.get("テンプレート種別")

            for row in all_rows[1:]:
                row_date = row[col_map.get("日時", 0)][:10] if col_map.get("日時") is not None and len(row) > col_map["日時"] and row[col_map["日時"]] else ""
                if row_date >= date_from:
                    total += 1
                    if col_map.get("返信") is not None and len(row) > col_map["返信"] and row[col_map["返信"]] == "有":
                        replied += 1
                    # Collect full_text samples for matching template type
                    if (full_text_col is not None
                            and len(row) > full_text_col
                            and row[full_text_col]
                            and (not type_col or len(row) <= type_col or row[type_col] == template_type)):
                        full_text_samples.append(row[full_text_col])

            if total > 0:
                stats_text = f"直近30日: 送信{total}通, 返信{replied}件, 返信率{replied/total*100:.1f}%"
    except Exception:
        pass

    # Keep newest 3 samples
    full_text_samples = full_text_samples[-3:]

    # 4. Load diagnosis prompt
    prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts", "diagnose_scout.md")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            system_prompt = f.read()
    except FileNotFoundError:
        return {"status": "error", "detail": "diagnose_scout.md が見つかりません"}

    # 5. Build user prompt
    display_name = COMPANY_DISPLAY_NAMES.get(company, company)
    profile_text = company_profile if company_profile else f"(会社プロフィール未登録: {display_name})"

    user_parts = [
        f"## 診断対象テンプレート\n\n会社: {display_name}\nテンプレート種別: {template_type}\n職種カテゴリ: {job_category or '(未指定)'}\n\n```\n{original_body}\n```",
    ]

    if full_text_samples:
        user_parts.append(f"\n\n## 送信済みスカウト文サンプル（完成形: テンプレート+パーソナライズ文）\n\n以下は実際に送信されたスカウト文の完成形です。テンプレートとパーソナライズ文の統合品質を評価してください。\n")
        for i, sample in enumerate(full_text_samples, 1):
            user_parts.append(f"### サンプル{i}\n```\n{sample}\n```\n")
    else:
        user_parts.append("\n\n（送信済みスカウト文のサンプルはありません。テンプレートのみで診断してください。personalization_issues と integration_issues は空配列にしてください。）")

    user_parts.append(f"\n\n## 会社プロフィール\n\n{profile_text}")

    if stats_text:
        user_parts.append(f"\n\n## 送信実績\n\n{stats_text}")

    user_prompt = "\n".join(user_parts)

    # 6. Call AI
    try:
        result = await generate_personalized_text(
            system_prompt,
            user_prompt,
            model_name=GEMINI_PRO_MODEL,
            max_output_tokens=4096,
            temperature=0.3,
        )
        raw_text = result.text
    except Exception as e:
        return {"status": "error", "detail": f"AI呼び出しエラー: {str(e)}"}

    # 7. Parse JSON response
    # Strip markdown fences if present
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]  # remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    try:
        diagnosis = _json.loads(cleaned)
    except _json.JSONDecodeError:
        return {"status": "error", "detail": f"AIの出力をJSON解析できませんでした。出力の先頭: {raw_text[:200]}"}

    # 8. Validate/normalize required fields
    gate_scores = diagnosis.get("gate_scores", {})
    for gate_key in ("gate1_open", "gate2_read", "gate3_reply"):
        if gate_key not in gate_scores or gate_scores[gate_key] not in ("A", "B", "C"):
            gate_scores[gate_key] = "B"  # default
    diagnosis["gate_scores"] = gate_scores
    diagnosis.setdefault("weak_principles", [])
    diagnosis.setdefault("ai_smell", [])
    diagnosis.setdefault("structure_issues", [])
    diagnosis.setdefault("personalization_issues", [])
    diagnosis.setdefault("integration_issues", [])
    diagnosis.setdefault("strengths", [])
    diagnosis.setdefault("priority_actions", [])
    diagnosis.setdefault("improvement_targets", {"template": False, "prompt": False, "recipes": False})

    # 9. Generate diagnosis ID and write history
    diagnosis_id = f"diag_{uuid.uuid4().hex[:8]}"

    try:
        sheets_writer.ensure_sheet_exists(DIAGNOSIS_HISTORY_SHEET, DIAGNOSIS_HISTORY_HEADERS)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        history_row = [
            diagnosis_id,
            now_str,
            company,
            template_type,
            job_category or "",
            str(row_index),
            gate_scores.get("gate1_open", ""),
            gate_scores.get("gate2_read", ""),
            gate_scores.get("gate3_reply", ""),
            "; ".join(wp.get("principle", "") for wp in diagnosis.get("weak_principles", [])),
            str(len(diagnosis.get("ai_smell", []))),
            "; ".join(pa.get("action", "") for pa in diagnosis.get("priority_actions", [])),
            _json.dumps(diagnosis.get("improvement_targets", {}), ensure_ascii=False),
            operator.get("name", "") if isinstance(operator, dict) else "",
        ]
        sheets_writer.append_rows(DIAGNOSIS_HISTORY_SHEET, [history_row])
    except Exception:
        pass  # History write failure should not block diagnosis

    # 10. Return response
    return {
        "status": "ok",
        "diagnosis": diagnosis,
        "context": {
            "company": company,
            "template_type": template_type,
            "job_category": job_category or "",
            "row_index": row_index,
            "sample_count": len(full_text_samples),
            "stats_summary": stats_text,
        },
        "diagnosis_id": diagnosis_id,
        "model": result.model_name,
    }


@router.post("/save_diagnosis_knowledge")
async def save_diagnosis_knowledge(
    data: dict,
    operator=Depends(verify_api_key),
):
    """診断で見つかった知見をナレッジプールに直接保存する（AI呼び出しなし）。"""
    company = data.get("company", "")  # 空文字 = 全社共通ルール
    category = data.get("category", "")
    rule = data.get("rule", "").strip()
    source = data.get("source", "診断")
    diagnosis_id = data.get("diagnosis_id", "")

    if category not in VALID_KNOWLEDGE_CATEGORIES:
        return {"status": "error", "detail": f"category は {', '.join(sorted(VALID_KNOWLEDGE_CATEGORIES))} のいずれかを指定してください"}

    if not rule:
        return {"status": "error", "detail": "rule は空にできません"}

    from datetime import datetime, timedelta, timezone
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)

    rule_id = str(int(now.timestamp()))
    source_with_id = f"{source} ({diagnosis_id})" if diagnosis_id else source

    sheet_name = SHEET_MAP["knowledge_pool"]
    columns = COLUMNS["knowledge_pool"]
    sheets_writer.ensure_sheet_exists(sheet_name, columns)

    row = [rule_id, company, category, rule, source_with_id, "pending", now.strftime("%Y-%m-%d %H:%M:%S")]
    sheets_writer.append_rows(sheet_name, [row])

    return {"status": "ok", "id": rule_id}


@router.post("/improve_template")
async def improve_template(
    data: dict,
    operator=Depends(verify_api_key),
):
    """AIがテンプレートを改善し、変更理由付きの改善版を返す。"""
    import re
    from pipeline.orchestrator import _send_data_sheet_name, COMPANY_DISPLAY_NAMES
    from pipeline.ai_generator import generate_personalized_text

    company = data.get("company", "")
    template_type = data.get("template_type", "")
    job_category = data.get("job_category", "")
    directive = data.get("directive", "")  # ユーザーの改善指示
    analysis_summary = data.get("analysis_summary", "")  # 分析タブからの連携データ
    requested_row_index = data.get("row_index")  # 管理画面から直接渡されるrow_index
    diagnosis = data.get("diagnosis")  # Stage 1 診断結果（任意）

    if not company or not template_type:
        raise HTTPException(400, "company and template_type are required")

    # 1. Get current template body
    all_template_rows = sheets_writer.get_all_rows("テンプレート")
    row_index = None
    original_body = ""

    if requested_row_index:
        # row_indexが直接指定されている場合はそれを使用（Sheet行番号: 1-based）
        row_index = int(requested_row_index)
        if row_index >= 2 and row_index <= len(all_template_rows):
            row = all_template_rows[row_index - 1]
            original_body = row[3].replace("\\n", "\n") if len(row) > 3 else ""
        else:
            raise HTTPException(404, f"Row {row_index} not found")
    else:
        # row_indexが指定されていない場合は検索
        for idx, row in enumerate(all_template_rows[1:], start=2):
            if len(row) >= 4 and row[0] == company and row[2] == template_type:
                if not job_category or row[1] == job_category:
                    row_index = idx
                    original_body = row[3].replace("\\n", "\n") if len(row) > 3 else ""
                    break

    if row_index is None or not original_body:
        raise HTTPException(404, "テンプレートの行が見つかりません")

    # 2. Load company profile from Sheets
    company_profile = sheets_client.get_company_profile(company)

    # 3. Get send data stats + build analysis context
    from datetime import datetime, timedelta, timezone
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    date_from = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    stats_text = ""
    sheet_name = _send_data_sheet_name(company)
    try:
        all_rows = sheets_writer.get_all_rows(sheet_name)
        if len(all_rows) >= 2:
            headers = all_rows[0]
            col_map = {h: i for i, h in enumerate(headers)}
            total = 0
            replied = 0
            for row in all_rows[1:]:
                row_date = row[col_map.get("日時", 0)][:10] if col_map.get("日時") is not None and len(row) > col_map["日時"] and row[col_map["日時"]] else ""
                if row_date >= date_from:
                    total += 1
                    if col_map.get("返信") is not None and len(row) > col_map["返信"] and row[col_map["返信"]] == "有":
                        replied += 1
            if total > 0:
                stats_text = f"直近30日: 送信{total}通, 返信{replied}件, 返信率{replied/total*100:.1f}%"
    except Exception:
        pass

    # 4. Build analysis data section
    analysis_section = ""
    if analysis_summary:
        analysis_section = f"""

---

## 分析データ

{analysis_summary}

上記のデータから読み取れる傾向を改善に活かしてください。
返信率が高いパターン・低いパターンがあれば、テンプレートのどの部分が影響しているかを考察し、改善案に反映してください。"""
    elif stats_text:
        analysis_section = f"""

---

## 送信実績

{stats_text}"""

    # 4b. Build diagnosis section (if diagnosis provided)
    diagnosis_section = ""
    if diagnosis and isinstance(diagnosis, dict):
        diag_parts = []
        diag_parts.append("\n\n---\n\n## 診断結果に基づく優先改善事項\n")
        diag_parts.append("以下はスカウト文診断システムが特定した問題点です。**これらを最優先で改善してください。**\n")

        # Gate scores
        gate_scores = diagnosis.get("gate_scores", {})
        c_gates = [k for k, v in gate_scores.items() if v == "C"]
        if c_gates:
            gate_names = {"gate1_open": "開封判断", "gate2_read": "読了判断", "gate3_reply": "返信判断"}
            diag_parts.append(f"\n**C判定のゲート:** {', '.join(gate_names.get(g, g) for g in c_gates)}\n")

        # Priority actions for template target
        template_actions = [pa for pa in diagnosis.get("priority_actions", [])
                          if pa.get("target") == "template"]
        if template_actions:
            diag_parts.append("\n**テンプレートの改善アクション:**\n")
            for pa in template_actions:
                diag_parts.append(f"- [{pa.get('impact', 'medium')}] {pa.get('action', '')}\n")

        # AI smell fixes
        ai_smells = diagnosis.get("ai_smell", [])
        if ai_smells:
            diag_parts.append("\n**AI臭の修正:**\n")
            for smell in ai_smells:
                diag_parts.append(f"- {smell.get('fingerprint', '')}: {smell.get('fix_hint', '')}\n")

        # Weak principles
        weak = diagnosis.get("weak_principles", [])
        high_weak = [w for w in weak if w.get("severity") == "high"]
        if high_weak:
            diag_parts.append("\n**弱い心理原則（severity: high）:**\n")
            for w in high_weak:
                diag_parts.append(f"- {w.get('principle', '')}: {w.get('issue', '')}\n")

        diagnosis_section = "".join(diag_parts)

    # 5. Build company profile section
    profile_section = ""
    display_name = COMPANY_DISPLAY_NAMES.get(company, company)
    if company_profile:
        profile_section = f"""

---

## 会社情報

{company_profile}

上記の会社情報を踏まえ、この会社が求職者に対して本当に訴求すべき強みは何かを判断してください。
全ての特徴を並べるのではなく、求職者が最も価値を感じるポイントに絞ってテンプレートに反映してください。"""
    else:
        profile_section = f"""

---

## 会社情報

会社名: {display_name}
（詳細な会社情報は取得できませんでした。テンプレートの文面から読み取れる情報をもとに改善してください。）"""

    # 6. Build system prompt
    system_prompt = f"""あなたは介護・医療系求人のスカウト文テンプレートを改善するエキスパートです。
目的はただ一つ: このテンプレートで送るスカウトの返信率を上げること。

表現の微調整ではなく、「求職者がこのスカウトを受け取ったとき、返信したくなるか？」という視点で改善してください。

---

## 求職者を知る

### 転職者の不安と動機

介護・医療職が転職を考えるとき、最も多い理由:
- **介護職**: 人間関係の問題が圧倒的に多い。次いで施設の理念・運営への不満、より良い条件の職場を求めて
- **看護師**: 上司との関係、長時間労働・残業の多さ、給与への不満、結婚・出産・育児などライフステージの変化

転職活動中の最大の不安は「転職先でも同じ問題が起きないか」。特に人間関係で辞めた人は、次の職場の雰囲気に最も敏感になる。

訪問看護特有の不安:
- 「一人で訪問することへの怖さ・プレッシャー」が最大の壁（過半数が感じる）
- オンコール対応の負担も大きな懸念材料
→ 訪問看護のテンプレートでは、この不安をどう解消するかが返信率に直結する

### 求職者が求人で見ているもの

優先順位（高い順）:
1. **給与・賞与・手当** — 最も多くの人が重視する。ただし具体的な数字がないと信用されない
2. **残業時間・勤務体制** — 「月平均○時間」の具体性が信頼につながる
3. **人間関係・職場の雰囲気** — 最も気にしているが、求人票だけでは分かりにくい。だからこそスカウト文で伝えられると強い
4. **勤務地・通勤時間** — 長く働けるかの判断材料
5. **教育体制・研修制度** — 特に未経験・ブランク層に響く
6. **休日数・有休取得率** — ワークライフバランスの指標

重要: 給与が地域相場より低い場合、給与を前面に出しても逆効果。その会社が本当に強いポイント（教育体制、雰囲気、柔軟な働き方等）で勝負すべき。

### 売り手市場という前提

介護関係職種の有効求人倍率は約4倍。求職者1人に対して約4件の求人がある。つまり求職者が選ぶ立場。条件に妥協する必要がなく、スカウトを受けても「もっと良い条件があるかも」と比較検討する余裕がある。

だからこそ、テンプレート一斉送信では埋もれる。「この会社は自分に合いそう」と思わせる具体性が必要。

---

## スカウトを読む人の心理

### 大量に届く中での判断

求職者は複数の事業所からスカウトを受け取る。特に関東圏では大量に届く。その中で:

1. **冒頭数十文字で開封するか決める** — ジョブメドレーの一覧画面では事業所名＋本文の冒頭部分がプレビュー表示される。ここで興味を引けなければ開かれない
2. **開封しても数秒で「読む価値があるか」を判断する** — 会社紹介から始まるスカウトは読み飛ばされる
3. **返信するかは「自分に合うか」で決める** — 待遇と「自分のスキルが活かせるか」で約7割の判断が決まる

### 好まれるスカウト

- **プロフィールを読んだと分かる**（最重要 — 約6割が重視）
- 特別感がある（テンプレ一斉送信ではないと感じる）
- なぜスカウトしたか理由が具体的
- **短くて簡潔**（約7割が好む）

### 嫌われるスカウト

- 希望に合わない求人のスカウト
- 明らかにテンプレートの一斉送信
- 会社の情報ばかりで自分への言及がない
- 断っても繰り返し送ってくる

### 潜在層と顕在層の違い

離職中の求職者は緊急度が高く、具体的な条件提示・早期入職可能性が響く。
就業中（情報収集中）の求職者は選別的で、「今の職場より良い点」を明確に示す必要がある。CTAも「まずは情報交換」程度のライトさが有効。

---

## 良いスカウトの原則

### 原則① 冒頭30文字が勝負

一覧画面のプレビューで見えるのは冒頭30〜50文字程度。全メールの半数以上がスマホで開封される。
最初の1文で「なぜあなたに送ったか」を伝える。

テンプレートには `{{personalized_text}}` が含まれるが、その前後の定型文がプレビューに出る可能性がある。
冒頭の定型文がテンプレ感を出していないか確認する。

### 原則② 「候補者の経験 × 会社の特色 = 接点」

パーソナライズの核心はこの掛け算。テンプレート内の `{{personalized_text}}` がこの役割を担う。
テンプレート側は、この接点が最大限活きる構成になっているべき。

テンプレートが会社情報の羅列になっていると、パーソナライズ文を入れても「会社紹介の中に1文だけ個別メッセージがある」状態になり、効果が薄れる。

### 原則③ 特徴ではなく「あなたにとっての利益」で語る

会社の特徴をそのまま書いても人は動かない。「それが相手にとって何を意味するか」まで踏み込む。
- ✕ 特徴そのまま:「電子カルテ導入済みです」
- ◎ 相手の利益:「残業が月平均5時間以内で、プライベートとの両立が可能です」

### 原則④ CTAは低いハードルで1つだけ

- 低（推奨）:「ご興味があればお気軽にご返信ください」「まずは見学だけでも歓迎です」
- 高（避ける）:「ぜひご応募ください」

CTAは1つだけ。複数並べると迷って行動しない。
{profile_section}
{analysis_section}
{diagnosis_section}

---

## NG表現・品質の最低ライン

以下は絶対に避けること:
- **年齢・世代への言及**（「20代」「若手」「ベテラン」）
- **会社名の誤り**
- **居住地の詳細すぎる言及**（「○○区にお住まい」→ 広域表現に）
- **憶測の記載**（「〜されたいのですね」→ 事実のみ）
- **過剰敬語**（「拝察いたします」「敬意を表します」）
- **送り手の感情が主語**（「ご一緒したい」→ 相手へのオファー主体で）
- **対象職種の資格への冗長な言及**（看護師求人で「看護師の資格をお持ちとのこと」→ 資格保有は前提なので不要）
- **上から目線**（「フォローします」「安心してください」→「チームでサポートし合う環境」）

---

## 出力ルール

1. **`{{personalized_text}}` を必ず含める**。位置は変えてよい
2. 改善したテンプレートの**全文**を出力する（部分ではなく全文）
3. 変更した箇所の直後に `<!-- 変更理由: 理由 -->` を入れる
4. 変更していない箇所は一字一句そのまま残す
5. テンプレート本文のみ出力。前置き・説明・コードフェンス不要
6. 各行の改行フォーマット（\\n）はそのまま維持する
7. 元テンプレートに存在しないプレースホルダー（{{お名前}}等）を追加しない

構成の変更、段落の順序入れ替え、大幅な書き換えは許可する。
返信率を上げるために必要であれば、遠慮なく変えてよい。
ただし変更理由を必ず明記すること。"""

    # ユーザーの改善指示があればプロンプトに追加
    directive_section = ""
    if directive:
        directive_section = f"\n\n## ディレクターからの改善指示（最優先）\n{directive}\n上記の指示を最優先で反映してください。"

    user_prompt = f"以下のテンプレートを改善してください。\n求職者の心理と会社の強みを踏まえ、返信率が上がる形に変えてください。{directive_section}\n\n{original_body}"

    # 7. Call Gemini
    try:
        from config import GEMINI_PRO_MODEL
        result = await generate_personalized_text(
            system_prompt,
            user_prompt,
            model_name=GEMINI_PRO_MODEL,
            max_output_tokens=8192,
            temperature=0.5,
        )
        raw_improved = result.text
    except Exception as e:
        raise HTTPException(500, f"AI生成エラー: {e}")

    # 5. Parse: extract change reasons, clean up
    # Strip markdown code fences if present
    raw_improved = re.sub(r'^```[^\n]*\n', '', raw_improved)
    raw_improved = re.sub(r'\n```$', '', raw_improved.rstrip())

    # Extract change reasons
    changes = []
    for m in re.finditer(r'<!-- 変更理由:\s*(.+?)\s*-->', raw_improved):
        reason = m.group(1)
        start = max(0, m.start() - 30)
        context = raw_improved[start:m.start()].strip()[-40:]
        changes.append({"reason": reason, "context": context})

    # Remove HTML comments to get clean version
    improved_clean = re.sub(r'\s*<!-- 変更理由:\s*.+?\s*-->', '', raw_improved).strip()

    # Validate placeholder
    if "{personalized_text}" not in improved_clean and "\\{personalized_text\\}" not in improved_clean:
        # Try to recover
        if "{personalized_text}" in original_body:
            return {
                "status": "error",
                "detail": "AIがプレースホルダー{personalized_text}を削除してしまいました。再度お試しください。",
            }

    # Generate improvement proposals from diagnosis (if applicable)
    proposals = []
    if diagnosis and isinstance(diagnosis, dict):
        import json as _json
        targets = diagnosis.get("improvement_targets", {})
        priority_actions = diagnosis.get("priority_actions", [])

        for target_key, sheet_target in [("prompt", "prompts"), ("recipes", "patterns")]:
            if not targets.get(target_key):
                continue
            target_actions = [pa for pa in priority_actions if pa.get("target") == target_key]
            if not target_actions:
                continue

            for pa in target_actions:
                proposal_id = f"fbprop_{uuid.uuid4().hex[:8]}"
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if sheet_target == "prompts":
                    payload = {
                        "section_type": "ai_guide",
                        "job_category": job_category or "",
                        "content": pa.get("action", ""),
                        "order": "8",
                    }
                else:  # patterns
                    payload = {
                        "action": pa.get("action", ""),
                    }

                proposal_row = [
                    proposal_id,
                    now_str,
                    "",  # source_fix_ids (none - from diagnosis)
                    sheet_target,
                    "append" if sheet_target == "prompts" else "update",
                    company,
                    _json.dumps(payload, ensure_ascii=False),
                    f"診断: {pa.get('action', '')}",
                    "pending",
                    "",  # actor
                    "",  # decided_at
                ]

                try:
                    sheets_writer.ensure_sheet_exists("改善提案", COLUMNS.get("improvement_proposals", [
                        "id", "created_at", "source_fix_ids", "target_sheet", "operation",
                        "scope_company", "payload_json", "rationale", "status", "actor", "decided_at",
                    ]))
                    sheets_writer.append_rows("改善提案", [proposal_row])
                except Exception:
                    pass

                proposals.append({
                    "id": proposal_id,
                    "target_sheet": sheet_target,
                    "operation": "append" if sheet_target == "prompts" else "update",
                    "scope_company": company,
                    "payload_json": _json.dumps(payload, ensure_ascii=False),
                    "rationale": f"診断: {pa.get('action', '')}",
                })

    result = {
        "status": "ok",
        "original": original_body,
        "improved": improved_clean,
        "changes": changes,
        "row_index": row_index,
    }
    if proposals:
        result["proposals"] = proposals
    return result


@router.post("/expand_template")
async def expand_template(
    data: dict,
    operator=Depends(verify_api_key),
):
    """ソーステンプレートを元に、複数ターゲットへ適応版を一括生成する。

    targets の各要素は { job_category, template_type, company? } を持つ。
    company を省略した場合は source と同じ会社として扱う。他会社の
    テンプレにも展開できるようにしており、その場合は target 会社の
    プロフィールが AI プロンプトに差し込まれる。
    """
    import re
    from pipeline.ai_generator import generate_personalized_text

    source_company = data.get("company", "")
    source_jc = data.get("source_job_category", "")
    source_type = data.get("source_template_type", "")
    targets = data.get("targets", [])
    directive = data.get("directive", "")

    if not source_company or not source_type or not targets:
        raise HTTPException(400, "company, source_template_type, targets are required")

    # 1. Get source template
    all_rows = sheets_writer.get_all_rows("テンプレート")
    if not all_rows:
        raise HTTPException(404, "テンプレートシートが空です")
    headers = [h.strip() for h in all_rows[0]]
    col_map = {h: i for i, h in enumerate(headers)}

    def _cell(row, col_name: str, default: str = "") -> str:
        idx = col_map.get(col_name)
        if idx is None:
            return default
        return row[idx].strip() if idx < len(row) else default

    source_body = ""
    for row in all_rows[1:]:
        if (
            _cell(row, "company") == source_company
            and _cell(row, "job_category") == source_jc
            and _cell(row, "type") == source_type
        ):
            raw = row[col_map.get("body", 3)] if col_map.get("body") is not None and len(row) > col_map["body"] else ""
            source_body = raw
            break

    if not source_body:
        raise HTTPException(404, f"ソーステンプレートが見つかりません: {source_jc}:{source_type}")

    source_body = source_body.replace("\\n", "\n")

    # 2. Profile cache: target company might differ from source. We load
    #    each distinct company profile lazily and reuse across targets.
    profile_cache: dict[str, str] = {}

    def _profile(company_id: str) -> str:
        if company_id not in profile_cache:
            try:
                profile_cache[company_id] = sheets_client.get_company_profile(company_id) or ""
            except Exception:
                profile_cache[company_id] = ""
        return profile_cache[company_id]

    # 3. Build target info + find existing templates
    target_rows = []
    for t in targets:
        t_company = (t.get("company") or source_company).strip()
        t_jc = t.get("job_category", "")
        t_type = t.get("template_type", "")
        existing_body = ""
        row_index = None
        for idx, row in enumerate(all_rows[1:], start=2):
            if (
                _cell(row, "company") == t_company
                and _cell(row, "job_category") == t_jc
                and _cell(row, "type") == t_type
            ):
                raw = row[col_map.get("body", 3)] if col_map.get("body") is not None and len(row) > col_map["body"] else ""
                existing_body = raw.replace("\\n", "\n")
                row_index = idx
                break
        target_rows.append({
            "company": t_company,
            "job_category": t_jc,
            "template_type": t_type,
            "existing_body": existing_body,
            "row_index": row_index,
        })

    # 4. Build adaptation prompt
    JOB_CATEGORY_NAMES = {
        "nurse": "看護師/准看護師",
        "rehab_pt": "理学療法士",
        "rehab_st": "言語聴覚士",
        "rehab_ot": "作業療法士",
        "medical_office": "医療事務",
    }

    TYPE_RULES = {
        "パート_初回": "パート・アルバイト向けの初回スカウト。柔軟な働き方を訴求。",
        "パート_再送": "パート向けの再送スカウト。前回の補足として短く、新たな魅力や変化を伝える。",
        "正社員_初回": "正社員/正職員向けの初回スカウト。キャリアや待遇面を訴求。",
        "正社員_再送": "正社員向けの再送スカウト。前回の補足として短く、新たな魅力や変化を伝える。",
    }

    def _build_system_prompt(target_company: str) -> str:
        profile = _profile(target_company)
        return (
            "あなたは介護・医療系のスカウト文テンプレートを、異なるテンプレート型・職種に適応させるエキスパートです。\n\n"
            "「お手本テンプレート」の構成・トーン・表現の質を維持しながら、ターゲットの型や職種に合わせて適応してください。\n\n"
            "## ルール\n"
            "- {personalized_text} プレースホルダーは必ず維持\n"
            "- お手本の構成（段落構成、CTA位置）を基本的に踏襲\n"
            "- 型の違い（初回↔再送、パート↔正社員）に応じてトーンと内容を調整\n"
            "- 職種の違いに応じて業務内容の表現を適切に変更\n"
            "- 再送テンプレートは初回より短く、「再度のご連絡」のトーンに\n"
            "- 正社員は待遇・キャリア面を強調、パートは柔軟性・働きやすさを強調\n"
            "- テンプレート本文のみ出力（説明不要）\n"
            + (f"\n## 会社情報（{target_company}）\n{profile[:2000]}\n" if profile else "")
        )

    # 5. Generate for each target (sequential to avoid rate limits)
    results = []
    for tr in target_rows:
        t_jc_name = JOB_CATEGORY_NAMES.get(tr["job_category"], tr["job_category"])
        t_type_rule = TYPE_RULES.get(tr["template_type"], "")
        source_jc_name = JOB_CATEGORY_NAMES.get(source_jc, source_jc)

        adaptation_notes = []
        if tr["company"] != source_company:
            adaptation_notes.append(f"会社変更: {source_company} → {tr['company']}")
        if tr["job_category"] != source_jc:
            adaptation_notes.append(f"職種変更: {source_jc_name} → {t_jc_name}")
        if tr["template_type"] != source_type:
            adaptation_notes.append(f"型変更: {source_type} → {tr['template_type']}")

        user_prompt = f"""以下のお手本テンプレートを適応してください。

## お手本（{source_company} / {source_jc_name} / {source_type}）
{source_body}

## 適応先
- 会社: {tr['company']}
- 職種: {t_jc_name}
- テンプレート型: {tr['template_type']}
- {t_type_rule}
{f'- 適応ポイント: {", ".join(adaptation_notes)}' if adaptation_notes else ''}
{f'{chr(10)}## ディレクターの指示{chr(10)}{directive}' if directive else ''}

テンプレート本文のみ出力してください。"""

        system_prompt = _build_system_prompt(tr["company"])

        try:
            from config import GEMINI_PRO_MODEL
            result = await generate_personalized_text(
                system_prompt,
                user_prompt,
                model_name=GEMINI_PRO_MODEL,
                max_output_tokens=8192,
                temperature=0.3,
            )
            proposed = result.text
            # Clean up
            proposed = re.sub(r'^```[^\n]*\n', '', proposed)
            proposed = re.sub(r'\n```$', '', proposed.rstrip())
            proposed = proposed.strip()

            results.append({
                "company": tr["company"],
                "job_category": tr["job_category"],
                "template_type": tr["template_type"],
                "original": tr["existing_body"],
                "proposed": proposed,
                "row_index": tr["row_index"],
            })
        except Exception as e:
            results.append({
                "company": tr["company"],
                "job_category": tr["job_category"],
                "template_type": tr["template_type"],
                "original": tr["existing_body"],
                "proposed": "",
                "row_index": tr["row_index"],
                "error": str(e),
            })

    return {"status": "ok", "results": results}


@router.post("/expand_template/to_prompt_proposals")
async def expand_template_to_prompt_proposals(
    data: dict,
    operator=Depends(verify_api_key),
):
    """Mode B: テンプレ展開で承認された差分を、プロンプトシート提案に変換する。

    `approved_diffs` は承認済みの target 差分リスト。各要素は
    { company, job_category, template_type, original, merged } を持つ。

    差分を fix_feedback 相当の pending 入力に詰め直したあと、既存の
    `_build_prompt_proposal_inputs` と同じフォーマットで Gemini に提案を
    書かせて、`改善提案` シートに status=pending で append する。

    実テンプレート更新は一切行わない。フォローアップとして管理画面の
    「修正フィードバック」タブから個別承認してもらう。
    """
    import json
    import re as _re
    from datetime import datetime as _dt
    from pipeline.ai_generator import generate_personalized_text
    from db.sheets_client import SHEET_IMPROVEMENT_PROPOSALS

    company = (data.get("company") or "").strip()
    source = data.get("source") or {}
    approved_diffs = data.get("approved_diffs") or []

    if not company or not approved_diffs:
        raise HTTPException(400, "company と approved_diffs は必須です")

    # 1. approved_diffs を pending fix_feedback 相当に変換
    pending_like: list[dict] = []
    for i, d in enumerate(approved_diffs):
        merged = (d.get("merged") or "").strip()
        original = (d.get("original") or "").strip()
        if not merged:
            continue
        pending_like.append({
            "id": f"expand_{i}",
            "company": (d.get("company") or company).strip(),
            "template_type": (d.get("template_type") or ""),
            "before": original[:1200],
            "after": merged[:1200],
            "reason": (
                f"テンプレ展開の差分 "
                f"(source={source.get('job_category','')}:{source.get('template_type','')} "
                f"→ target={d.get('job_category','')}:{d.get('template_type','')})"
            )[:300],
        })

    if not pending_like:
        return {"status": "ok", "appended": 0, "proposals": [], "warning": "空の差分"}

    # 2. 既存 helper で system/user prompt 組み立て
    system_prompt, user_prompt, dedup_keys = _build_prompt_proposal_inputs(pending_like)

    # 3. Gemini 呼び出し
    from config import GEMINI_PRO_MODEL
    try:
        result = await generate_personalized_text(
            system_prompt,
            user_prompt,
            model_name=GEMINI_PRO_MODEL,
            max_output_tokens=4096,
            temperature=0.3,
        )
        raw = result.text or ""
    except Exception as e:
        raise HTTPException(500, f"AI生成エラー: {e}")

    raw = _re.sub(r"^```[^\n]*\n", "", raw.strip())
    raw = _re.sub(r"\n```$", "", raw.strip())
    try:
        suggestions = json.loads(raw)
        if not isinstance(suggestions, list):
            raise ValueError("Gemini did not return a list")
    except Exception as e:
        raise HTTPException(500, f"Gemini出力のJSONパース失敗: {e} / raw={raw[:300]}")

    # 4. 既存 generate_improvement_proposals と同じ形式で proposal dict を作る
    proposals_out: list[dict] = []
    now_iso = _dt.utcnow().isoformat(timespec="seconds")
    for s in suggestions:
        scope_company = (s.get("scope_company") or company).strip()
        section_type = (s.get("section_type") or "").strip()
        job_category = (s.get("job_category") or "").strip()
        content = (s.get("content") or "").strip()
        if section_type not in PROMPT_COMPANY_SECTION_TYPES:
            continue
        if not job_category or not content:
            continue
        if (scope_company, section_type, job_category, content[:80]) in dedup_keys:
            continue
        order_default = "2" if section_type == "station_features" else ("3" if section_type == "education" else "8")
        payload = {
            "section_type": section_type,
            "job_category": job_category,
            "content": content,
            "order": order_default,
        }
        proposal = {
            "id": _gen_proposal_id(),
            "created_at": now_iso,
            "source_fix_ids": ",".join(s.get("source_fix_ids") or []),
            "target_sheet": "prompts",
            "operation": "append",
            "scope_company": scope_company,
            "payload_json": json.dumps(payload, ensure_ascii=False),
            "rationale": (s.get("rationale") or "").strip()[:300],
            "status": "pending",
            "actor": "",
            "decided_at": "",
        }
        proposals_out.append(proposal)

    if not proposals_out:
        return {"status": "ok", "appended": 0, "proposals": [], "warning": "AIから新規提案なし"}

    sheets_writer.ensure_sheet_exists(SHEET_IMPROVEMENT_PROPOSALS, IMPROVEMENT_PROPOSAL_COLUMNS)
    for p in proposals_out:
        sheets_writer.append_row(
            SHEET_IMPROVEMENT_PROPOSALS,
            [p[c] for c in IMPROVEMENT_PROPOSAL_COLUMNS],
        )

    return {
        "status": "ok",
        "appended": len(proposals_out),
        "proposals": proposals_out,
        "proposal_ids": [p["id"] for p in proposals_out],
    }


@router.post("/batch_update_templates")
async def batch_update_templates(
    data: dict,
    operator=Depends(verify_api_key),
):
    """複数テンプレートを一括更新（バージョニング+変更履歴付き）。

    Body comparison and version increment are delegated to
    `_bump_template_body`, which is shared with the single-row PUT path
    so the two cannot drift out of sync.
    """
    updates = data.get("updates", [])
    if not updates:
        raise HTTPException(400, "updates is required")

    # Touch the sheet once up front so we fail fast if it's empty.
    preflight = sheets_writer.get_all_rows("テンプレート")
    if not preflight:
        raise HTTPException(404, "テンプレートシートが空です")

    updated = 0
    noop = 0
    skipped: list[dict] = []
    errors: list[dict] = []

    for upd in updates:
        row_index = upd.get("row_index")
        new_body = upd.get("body", "")
        reason = upd.get("reason", "一括展開")
        upd_company = (upd.get("company") or "").strip() or None

        if not new_body:
            continue

        # row_indexがない場合は新規追加
        if not row_index:
            company_id = upd.get("company", "")
            job_cat = upd.get("job_category", "")
            ttype = upd.get("template_type", "")
            if company_id and ttype:
                sheets_writer.append_row("テンプレート", [
                    company_id, job_cat, ttype, _escape_body_for_sheets(new_body), "1",
                ])
                updated += 1
            continue

        try:
            result = _bump_template_body(
                row_index=int(row_index),
                new_body=new_body,
                reason=reason,
                actor="admin_ui:batch_update",
                expected_company=upd_company,
            )
        except ValueError as e:
            msg = str(e)
            # A missing required column is a configuration bug — surface
            # it as 500 so directors notice before more drift accrues.
            if "必須列がありません" in msg or "requires columns" in msg:
                raise HTTPException(500, f"テンプレートシートの列構成に問題があります: {msg}")
            errors.append({"row_index": row_index, "error": msg})
            continue

        if result["status"] == "updated":
            updated += 1
        elif result["status"] == "no-op":
            noop += 1
        elif result["status"] == "skipped":
            skipped.append(result)

    sheets_client.reload()
    return {
        "status": "ok",
        "updated": updated,
        "noop": noop,
        "skipped": skipped,
        "errors": errors,
    }


@router.post("/analyze_cycle")
async def analyze_cycle(
    data: dict,
    operator=Depends(verify_api_key),
):
    """送信データを多角的に分析し、改善仮説と改善案を自動生成する。"""
    from datetime import datetime, timedelta, timezone
    from pipeline.orchestrator import _send_data_sheet_name, COMPANY_DISPLAY_NAMES
    from pipeline.ai_generator import generate_personalized_text

    JST = timezone(timedelta(hours=9))
    company = data.get("company", "")
    is_cross_company = (company == "all")
    now = datetime.now(JST)
    date_from = data.get("date_from", (now - timedelta(days=30 if is_cross_company else 14)).strftime("%Y-%m-%d"))
    date_to = data.get("date_to", now.strftime("%Y-%m-%d"))

    # Collect rows from one or all company sheets
    headers = None
    col_map = {}
    filtered = []

    companies_to_scan = list(COMPANY_DISPLAY_NAMES.keys()) if is_cross_company else [company]

    for cid in companies_to_scan:
        sheet_name = _send_data_sheet_name(cid)
        try:
            all_rows = sheets_writer.get_all_rows(sheet_name)
        except Exception:
            continue
        if len(all_rows) < 2:
            continue

        if headers is None:
            headers = all_rows[0]
            col_map = {h: i for i, h in enumerate(headers)}

        display_name = COMPANY_DISPLAY_NAMES.get(cid, cid)
        for row in all_rows[1:]:
            row_date = row[col_map.get("日時", 0)][:10] if col_map.get("日時") is not None and len(row) > col_map["日時"] and row[col_map["日時"]] else ""
            if date_from <= row_date <= date_to:
                # For cross-company, tag each row with company name
                if is_cross_company:
                    row = list(row)
                    row.append(display_name)  # append company name as extra column
                filtered.append(row)

    if not filtered or headers is None:
        label = "全社" if is_cross_company else company
        return {"status": "error", "detail": f"{label} の {date_from}〜{date_to} にデータがありません"}

    # For cross-company, add virtual "会社" column
    if is_cross_company:
        company_col_idx = len(headers)  # appended at the end

    def _safe_get(row, col_name):
        if is_cross_company and col_name == "会社":
            return row[company_col_idx] if len(row) > company_col_idx else ""
        idx = col_map.get(col_name)
        if idx is None or idx >= len(row):
            return ""
        return row[idx]

    total = len(filtered)
    replied = sum(1 for r in filtered if _safe_get(r, "返信") == "有")
    reply_rate = replied / total if total > 0 else 0

    # Pattern display name mapping
    PATTERN_LABELS = {
        "A": "経験浅め・若手", "B1": "中堅・ブランクあり", "B2": "中堅・経験豊富",
        "C": "ベテラン", "D_就業中": "経験少なめ・就業中", "D_離職中": "経験少なめ・離職中",
        "E": "新人・未経験", "F_就業中": "高齢・就業中", "F_離職中": "高齢・離職中",
        "G": "情報不足（最小パターン）",
    }

    dimensions = ["テンプレート種別", "テンプレートVer", "生成パス", "パターン", "年齢層", "経験区分",
                   "希望雇用形態", "就業状況", "地域", "曜日", "時間帯"]
    if is_cross_company:
        dimensions = ["会社"] + dimensions
    cross_tabs = {}
    for dim in dimensions:
        buckets = {}
        for row in filtered:
            val = _safe_get(row, dim) or "(空)"
            # Map pattern codes to readable labels
            if dim == "パターン":
                if val == "(空)":
                    val = "AI生成（職歴・自己PRベース）"
                elif val in PATTERN_LABELS:
                    val = f"{val}（{PATTERN_LABELS[val]}）"
            if val not in buckets:
                buckets[val] = {"total": 0, "replied": 0}
            buckets[val]["total"] += 1
            if _safe_get(row, "返信") == "有":
                buckets[val]["replied"] += 1
        if len(buckets) > 1:
            cross_tabs[dim] = {
                k: {**v, "rate": f"{v['replied']/v['total']*100:.1f}%"}
                for k, v in sorted(buckets.items(), key=lambda x: -x[1]["total"])
            }

    # Get current template text for analysis context (full text)
    template_context = ""
    try:
        config = sheets_client.get_company_config(company)
        templates = config.get("templates", {})
        for tkey, tdata in templates.items():
            body = tdata.get("body", "").replace("\\n", "\n")
            template_context += f"\n### テンプレート: {tkey}\n{body}\n---\n"
    except Exception:
        pass

    summary_text = f"""## スカウト送信データ分析（{company}）
期間: {date_from} 〜 {date_to}
総送信数: {total}
返信数: {replied}
返信率: {reply_rate*100:.1f}%

### クロス集計
"""
    for dim, buckets in cross_tabs.items():
        summary_text += f"\n**{dim}別:**\n"
        for val, stats in buckets.items():
            summary_text += f"  {val}: {stats['total']}通 → 返信{stats['replied']}件 ({stats['rate']})\n"

    analysis_prompt = f"""あなたは介護・医療系求人のスカウト改善アナリストです。
以下のスカウト送信データと現在のテンプレートを分析し、具体的な改善提案を行ってください。
テンプレート内にメモやコメント（「※」「//」「【メモ】」等）があれば、それもディレクターの意図として読み取ってください。

{summary_text}

### 現在使用中のテンプレート（全文）
{template_context if template_context else "(テンプレート情報なし)"}

以下の形式で**必ず最後まで**回答してください:

## 発見したパターン
- 送信データから読み取れる傾向を3つまで箇条書き
- 数値の根拠を添える

## テンプレート改善案
各改善案について以下の3点をセットで提示:
1. **変更理由（仮説）**: なぜこの変更が必要か — データやテンプレートの文脈に基づく根拠
2. **現状の表現**: テンプレートから該当箇所を引用
3. **修正後の表現例**: 具体的な書き換え案

パーツ別（冒頭文 / 施設紹介 / 待遇 / 行動喚起CTA / その他）に分けて、優先度順に提案。

## 次サイクルの検証ポイント
- 改善実施後に見るべき指標を箇条書き"""

    from config import GEMINI_PRO_MODEL
    try:
        result = await generate_personalized_text(
            analysis_prompt,
            "上記のデータとテンプレートを分析してください。",
            model_name=GEMINI_PRO_MODEL,
            max_output_tokens=8192,
        )
        analysis_text = result.text
    except Exception as e:
        return {
            "status": "ok",
            "company": company,
            "period": f"{date_from}〜{date_to}",
            "summary": {"total": total, "replied": replied, "reply_rate": f"{reply_rate*100:.1f}%"},
            "cross_tabs": cross_tabs,
            "analysis": f"AI分析エラー: {e}",
        }

    return {
        "status": "ok",
        "company": company,
        "period": f"{date_from}〜{date_to}",
        "summary": {"total": total, "replied": replied, "reply_rate": f"{reply_rate*100:.1f}%"},
        "cross_tabs": cross_tabs,
        "analysis": analysis_text,
    }


# ---------------------------------------------------------------------------
# Customer-facing report export
# ---------------------------------------------------------------------------

# Dimensions kept in the customer-facing report. Internal bookkeeping
# columns (パターン / 生成パス / テンプレートVer / 曜日 / 時間帯) are
# deliberately excluded — clients don't need to see our machinery.
_CUSTOMER_REPORT_DIMENSIONS = [
    "地域",
    "年齢層",
    "経験区分",
    "希望雇用形態",
    "就業状況",
    "テンプレート種別",
]

_CUSTOMER_REPORT_TOP_N = 5  # cap each cross-tab at top 5 buckets by volume


def _collect_send_data_single(company: str, date_from: str, date_to: str):
    """Load and filter send data for a single company within a date range.

    Returns (headers, col_map, filtered_rows, kpi) where kpi is
    {total, replied, reply_rate_pct (float)} — or (None, {}, [], None) if
    the sheet is missing / empty / has no rows in range.
    """
    from pipeline.orchestrator import _send_data_sheet_name

    sheet_name = _send_data_sheet_name(company)
    try:
        all_rows = sheets_writer.get_all_rows(sheet_name)
    except Exception:
        return None, {}, [], None
    if len(all_rows) < 2:
        return None, {}, [], None

    headers = all_rows[0]
    col_map = {h: i for i, h in enumerate(headers)}
    date_col = col_map.get("日時")
    reply_col = col_map.get("返信")

    filtered = []
    for row in all_rows[1:]:
        row_date = ""
        if date_col is not None and len(row) > date_col and row[date_col]:
            row_date = row[date_col][:10]
        if date_from <= row_date <= date_to:
            filtered.append(row)

    if not filtered:
        return headers, col_map, [], None

    total = len(filtered)
    replied = 0
    if reply_col is not None:
        replied = sum(
            1
            for r in filtered
            if len(r) > reply_col and r[reply_col] == "有"
        )
    kpi = {
        "total": total,
        "replied": replied,
        "reply_rate_pct": (replied / total * 100) if total > 0 else 0.0,
    }
    return headers, col_map, filtered, kpi


def _build_customer_cross_tabs(
    filtered_rows: list,
    col_map: dict,
    dimensions: list = _CUSTOMER_REPORT_DIMENSIONS,
    top_n: int = _CUSTOMER_REPORT_TOP_N,
):
    """Compute cross-tabs for customer-facing dimensions only.

    Returns dict: {dim: {bucket_label: {total, replied, rate (str)}}}
    capped at top_n buckets per dimension (by volume).
    """
    reply_col = col_map.get("返信")
    result = {}
    for dim in dimensions:
        idx = col_map.get(dim)
        if idx is None:
            continue
        buckets = {}
        for row in filtered_rows:
            val = row[idx] if len(row) > idx and row[idx] else "(未設定)"
            if val not in buckets:
                buckets[val] = {"total": 0, "replied": 0}
            buckets[val]["total"] += 1
            if reply_col is not None and len(row) > reply_col and row[reply_col] == "有":
                buckets[val]["replied"] += 1
        if len(buckets) <= 1:
            continue
        ordered = sorted(buckets.items(), key=lambda kv: -kv[1]["total"])[:top_n]
        result[dim] = {
            k: {
                "total": v["total"],
                "replied": v["replied"],
                "rate": f"{(v['replied']/v['total']*100):.1f}%" if v["total"] > 0 else "0.0%",
            }
            for k, v in ordered
        }
    return result


_CUSTOMER_REPORT_PROMPT = """あなたは介護・医療系求人のスカウト運用をRPO（採用代行）として請け負っている担当者です。
以下のスカウト送信実績データをもとに、**クライアント（発注元の施設）に提出する報告所感**を作成してください。

## 禁止事項（必ず守る）
- 「と考えられます」「〜が示唆されます」「〜と推察されます」「AI分析」「興味深いことに」などAIっぽい婉曲表現は一切使わない
- 絵文字や装飾記号を入れない
- 箇条書きの多用を避け、段落で書く（数値は地の文に埋め込む）
- 施策の効果を断定せず、事実ベースで述べる

## トーン
- 「ございました」「しております」「いたしました」系の事務的な丁寧語
- 「◯通の送信のうち◯件の返信があり、返信率は◯%でした」のように数値を文章に織り込む
- 読み手は当該施設の採用担当者。運用の中身ではなく**結果と次の重点**に関心がある

## 出力形式（厳守）
JSON オブジェクトを **1 つだけ**出力してください。前後に解説文や ```json フェンスを含めないこと。

{
  "situation": "今期の送信状況を2〜4文（段落）で。数値は地の文に埋め込む。",
  "findings": "目立った傾向を2〜4文（段落）で。どのセグメントが反応良い/悪いかと、その数値根拠を明記する。",
  "next_actions": "次サイクルで取り組むべき観点を2〜3文（段落）で。具体的な施策名ではなく方向性として書く。"
}
"""


def _format_report_markdown(
    company_display: str,
    period: str,
    kpi: dict,
    cross_tabs: dict,
    narrative: dict,
) -> str:
    """Assemble the final customer-facing report as Markdown."""
    lines = []
    lines.append(f"# {company_display} スカウト送信レポート")
    lines.append("")
    lines.append(f"期間: {period}")
    lines.append("")
    lines.append("## サマリー")
    lines.append("")
    lines.append(f"- 送信数: {kpi['total']}通")
    lines.append(f"- 返信数: {kpi['replied']}件")
    lines.append(f"- 返信率: {kpi['reply_rate_pct']:.1f}%")
    lines.append("")

    if cross_tabs:
        lines.append("## 内訳")
        lines.append("")
        for dim, buckets in cross_tabs.items():
            lines.append(f"### {dim}別")
            lines.append("")
            lines.append("| 区分 | 送信 | 返信 | 返信率 |")
            lines.append("|---|---:|---:|---:|")
            for label, stats in buckets.items():
                lines.append(
                    f"| {label} | {stats['total']} | {stats['replied']} | {stats['rate']} |"
                )
            lines.append("")

    situation = (narrative or {}).get("situation", "").strip()
    findings = (narrative or {}).get("findings", "").strip()
    next_actions = (narrative or {}).get("next_actions", "").strip()

    if situation:
        lines.append("## 今期の状況")
        lines.append("")
        lines.append(situation)
        lines.append("")
    if findings:
        lines.append("## 見えてきた傾向")
        lines.append("")
        lines.append(findings)
        lines.append("")
    if next_actions:
        lines.append("## 次サイクルの重点")
        lines.append("")
        lines.append(next_actions)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _parse_narrative_json(raw_text: str) -> dict:
    """Extract the JSON object from a Gemini response.

    Tolerates wrapping ```json fences or a trailing period. Returns
    an empty dict if parsing fails so the caller can fall back to a
    KPI-only report.
    """
    import json
    import re

    if not raw_text:
        return {}
    text = raw_text.strip()
    # Strip ```json ... ``` fences if present.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # Find the first { ... last } span.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        obj = json.loads(text[start : end + 1])
    except Exception:
        return {}
    if not isinstance(obj, dict):
        return {}
    return {
        "situation": str(obj.get("situation", "")).strip(),
        "findings": str(obj.get("findings", "")).strip(),
        "next_actions": str(obj.get("next_actions", "")).strip(),
    }


@router.post("/export_report")
async def export_report(
    data: dict,
    operator=Depends(verify_api_key),
):
    """Generate a customer-facing Markdown report from send data analytics."""
    from datetime import datetime, timedelta, timezone
    from pipeline.orchestrator import COMPANY_DISPLAY_NAMES
    from pipeline.ai_generator import generate_personalized_text

    JST = timezone(timedelta(hours=9))
    company = (data.get("company") or "").strip()
    if not company or company == "all":
        raise HTTPException(400, "company is required (cross-company report is not supported)")

    now = datetime.now(JST)
    date_from = data.get("date_from") or (now - timedelta(days=30)).strftime("%Y-%m-%d")
    date_to = data.get("date_to") or now.strftime("%Y-%m-%d")
    directive = (data.get("directive") or "").strip()

    headers, col_map, filtered, kpi = _collect_send_data_single(company, date_from, date_to)
    if not filtered or kpi is None:
        return {
            "status": "error",
            "detail": f"{company} の {date_from}〜{date_to} に送信データがありません",
        }

    cross_tabs = _build_customer_cross_tabs(filtered, col_map)

    company_display = COMPANY_DISPLAY_NAMES.get(company, company)
    period = f"{date_from} 〜 {date_to}"

    # Build user prompt (data payload for Gemini).
    user_lines = [
        f"## 対象",
        f"- 施設: {company_display}",
        f"- 期間: {period}",
        "",
        f"## KPI",
        f"- 送信数: {kpi['total']}通",
        f"- 返信数: {kpi['replied']}件",
        f"- 返信率: {kpi['reply_rate_pct']:.1f}%",
        "",
    ]
    if cross_tabs:
        user_lines.append("## セグメント別の集計（顧客向けに絞り込み済）")
        for dim, buckets in cross_tabs.items():
            user_lines.append(f"\n### {dim}別")
            for label, stats in buckets.items():
                user_lines.append(
                    f"- {label}: 送信{stats['total']}通 / 返信{stats['replied']}件 ({stats['rate']})"
                )
        user_lines.append("")
    if directive:
        user_lines.append("## ディレクターからの補足")
        user_lines.append(directive)

    user_prompt = "\n".join(user_lines)

    narrative: dict = {}
    ai_error = None
    try:
        from config import GEMINI_PRO_MODEL
        result = await generate_personalized_text(
            _CUSTOMER_REPORT_PROMPT,
            user_prompt,
            model_name=GEMINI_PRO_MODEL,
            max_output_tokens=4096,
            temperature=0.5,
        )
        narrative = _parse_narrative_json(result.text)
    except Exception as e:
        ai_error = str(e)

    markdown_text = _format_report_markdown(
        company_display=company_display,
        period=period,
        kpi=kpi,
        cross_tabs=cross_tabs,
        narrative=narrative,
    )

    return {
        "status": "ok",
        "company": company,
        "company_display": company_display,
        "period": period,
        "date_from": date_from,
        "date_to": date_to,
        "kpi": {
            "total": kpi["total"],
            "replied": kpi["replied"],
            "reply_rate": f"{kpi['reply_rate_pct']:.1f}%",
        },
        "cross_tabs": cross_tabs,
        "narrative": narrative,
        "markdown": markdown_text,
        "ai_error": ai_error,
    }


@router.post("/export_report/google_docs")
async def export_report_google_docs(
    data: dict,
    operator=Depends(verify_api_key),
):
    """Create a Google Doc in the configured Drive folder from provided markdown."""
    import os
    from pipeline.orchestrator import COMPANY_DISPLAY_NAMES

    folder_id = os.environ.get("REPORTS_DRIVE_FOLDER_ID", "").strip()
    if not folder_id:
        raise HTTPException(
            500,
            "REPORTS_DRIVE_FOLDER_ID が設定されていません。Cloud Run の環境変数に出力先 Drive フォルダ ID を設定してください。",
        )

    company = (data.get("company") or "").strip()
    markdown_text = data.get("markdown") or ""
    date_from = (data.get("date_from") or "").strip()
    date_to = (data.get("date_to") or "").strip()
    if not company or not markdown_text:
        raise HTTPException(400, "company と markdown は必須です")

    company_display = COMPANY_DISPLAY_NAMES.get(company, company)
    title_parts = [f"{company_display}_スカウトレポート"]
    if date_from and date_to:
        title_parts.append(f"{date_from}_{date_to}")
    doc_title = "_".join(title_parts)

    try:
        from db.docs_exporter import docs_exporter
        result = docs_exporter.create_doc_from_markdown(
            title=doc_title,
            markdown_text=markdown_text,
            parent_folder_id=folder_id,
        )
    except Exception as e:
        raise HTTPException(500, f"Google Docs 作成に失敗しました: {e}")

    return {
        "status": "ok",
        "doc_id": result.get("id"),
        "web_view_link": result.get("webViewLink"),
        "title": doc_title,
    }


def _safe_reload() -> dict:
    """Reload sheets cache, but never let a reload failure turn a successful
    write into a 500. The row is already in Sheets — the client can re-fetch
    on next GET. Returns a small status dict for inclusion in the response.
    """
    try:
        sheets_client.reload()
        return {"cache_reloaded": True}
    except Exception as e:  # pragma: no cover - transient infra errors
        import logging
        logging.getLogger(__name__).warning(
            f"sheets_client.reload() failed after write (write still succeeded): {e}"
        )
        return {"cache_reloaded": False, "reload_error": str(e)[:200]}


# ---------------------------------------------------------------------------
# Competitor research: Gemini + Google Search grounding
# NOTE: Must be registered BEFORE the catch-all /{sheet_slug} route.
# ---------------------------------------------------------------------------

@router.post("/research_competitors")
async def research_competitors(
    data: dict,
    operator=Depends(verify_api_key),
):
    """Research competitors using Gemini + Google Search grounding.

    Returns competitive analysis with hidden strengths and scout hooks.
    Optionally saves extracted hooks to the knowledge pool.
    """
    from datetime import datetime, timedelta, timezone
    from pipeline.ai_generator import generate_personalized_text

    company = (data.get("company") or "").strip()
    if not company:
        return {"status": "error", "detail": "company が指定されていません"}

    job_category = data.get("job_category", "")
    save_to_knowledge = data.get("save_to_knowledge", False)

    # Load company context
    try:
        profile = sheets_client.get_company_profile(company) or ""
        display_name = sheets_client.get_company_display_name(company)
        config = sheets_client.get_company_config(company)
        categories = [c.get("display_name", c.get("id", "")) for c in config.get("job_categories", [])]
    except Exception:
        profile = ""
        display_name = company
        categories = []

    category_label = job_category or (categories[0] if categories else "看護師")

    # Extract area from profile
    area_hint = ""
    for keyword in ["所在地", "住所", "エリア", "拠点"]:
        for line in profile.split("\n"):
            if keyword in line:
                area_hint = line.strip()
                break
        if area_hint:
            break

    system_prompt = f"""あなたは介護・医療系の採用市場を分析する戦略コンサルタントです。
Google検索を活用して競合情報を調査し、対象会社が「まだ気づいていない自社の強み」を発見してください。

## あなたの役割
単なる情報比較ではなく、**対象会社にとっての「隠れた強み」や「差別化の種」を見つけ出す**こと。
プロフィールに書いてある強みを繰り返すのではなく、競合と比較して初めて見える優位性を提案する。

## 対象会社
- 会社名: {display_name}
- 職種: {category_label}
{f'- エリア: {area_hint}' if area_hint else ''}

## 会社プロフィール
{profile[:2000] if profile else '(未登録)'}

## 調査の観点

### 定量比較（同エリア・同業態・同職種）
- 給与水準（月給/時給）
- 勤務時間・シフト体制（夜勤、オンコール有無）
- 福利厚生・手当
- 施設の規模

### 定性比較
- 教育・研修体制
- 職場の雰囲気・文化（口コミ）
- キャリアパス
- 特色・専門領域
- 働き方の柔軟性

### 業界動向
- 当該エリアの求人市場状況
- 業界トレンド

## 出力形式

### 競合施設一覧
| 施設名 | 給与 | 勤務時間 | 福利厚生 | 規模 | 特色 |
|--------|------|----------|----------|------|------|

### 定性比較
教育体制・文化・キャリアパスの比較

### 🔍 隠れた強み・差別化の種（最重要）
対象会社が**まだ気づいていない可能性がある強み**を3-5個提案。

各提案:
1. **発見**: 何が強みか（1行）
2. **根拠**: なぜそう言えるか（競合との比較データ）
3. **活用案**: スカウト文でどう訴求するか（具体的な表現例）
4. **確認事項**: クライアントに裏取りすべきこと

profile.mdに書いてあることをそのまま繰り返すのはNG。

### 業界・エリア動向

### スカウト文への活用提案
- 推奨フック表現（5個）
- 避けるべき訴求

### 💡 ヒアリング提案
仮説検証型: 「〇〇という仮説がありますが実態は？」形式で。
"""

    user_prompt = f"「{display_name}」（{category_label}）の競合調査を実施してください。"

    from config import GEMINI_PRO_MODEL
    try:
        result = await generate_personalized_text(
            system_prompt,
            user_prompt,
            model_name=GEMINI_PRO_MODEL,
            max_output_tokens=8192,
            temperature=0.3,
        )
        analysis = result.text
    except Exception as e:
        return {"status": "error", "detail": f"AI調査エラー: {e}"}

    # Extract knowledge rules if requested
    knowledge_count = 0
    if save_to_knowledge:
        JST = timezone(timedelta(hours=9))
        now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
        rules = []
        next_id = int(datetime.now(JST).timestamp())

        # Extract lines from scout hook section and hidden strengths
        in_section = False
        for line in analysis.split("\n"):
            stripped = line.strip()
            if "スカウト文" in stripped or "フック" in stripped or "活用案" in stripped:
                in_section = True
                continue
            if in_section and stripped.startswith("- "):
                rule_text = stripped[2:].strip().strip("「」")
                if rule_text and len(rule_text) > 5:
                    rules.append([
                        str(next_id), company, "template_tip", rule_text,
                        f"競合調査 {now[:10]}", "pending", now,
                    ])
                    next_id += 1
            if in_section and stripped.startswith("###"):
                in_section = False

        if rules:
            sheets_writer.ensure_sheet_exists("ナレッジプール", [
                "id", "company", "category", "rule", "source", "status", "created_at",
            ])
            sheets_writer.append_rows("ナレッジプール", rules)
            knowledge_count = len(rules)

    return {
        "status": "ok",
        "company": display_name,
        "company_id": company,
        "job_category": category_label,
        "analysis": analysis,
        "knowledge_count": knowledge_count,
        "tokens": {
            "prompt": result.prompt_tokens,
            "output": result.output_tokens,
            "model": result.model_name,
        },
    }


# ---------------------------------------------------------------------------
# Knowledge pool: extract rules from analysis text
# NOTE: Must be registered BEFORE the catch-all /{sheet_slug} route.
# ---------------------------------------------------------------------------

KNOWLEDGE_POOL_SHEET = "ナレッジプール"
KNOWLEDGE_POOL_HEADERS = [
    "id", "company", "category", "rule", "source", "status", "created_at",
]


@router.post("/extract_knowledge")
async def extract_knowledge(
    data: dict,
    operator=Depends(verify_api_key),
):
    """Extract actionable rules from analysis text using AI.

    Writes extracted rules to the knowledge pool sheet with status=pending.
    """
    from datetime import datetime, timedelta, timezone
    from pipeline.ai_generator import generate_personalized_text
    from config import GEMINI_PRO_MODEL

    company = data.get("company", "")
    analysis_text = (data.get("analysis_text") or "").strip()
    source = data.get("source", "分析")

    if not analysis_text:
        return {"status": "error", "detail": "analysis_text が空です"}

    extraction_prompt = """あなたはスカウト文の品質改善アナリストです。
以下の分析テキストから、スカウト文生成AIに適用すべき具体的なルールを抽出してください。

## 出力形式
各ルールを1行ずつ、以下の形式で出力してください:
- [category] ルール本文

category は以下のいずれか:
- tone: トーン・文体に関するルール
- expression: NG表現・推奨表現
- profile_handling: 候補者タイプ別の対応方針
- template_tip: テンプレート・構成のコツ
- qualification: 資格・経験の言及ルール

## ルール
- 1ルール1行。具体的で短く。
- AIが「やる」「やらない」を即判断できる粒度で書く
- 曖昧な指針（「適切に対応する」等）は書かない
- 最大10ルールまで

## 分析テキスト
"""
    try:
        result = await generate_personalized_text(
            extraction_prompt,
            analysis_text[:8000],
            model_name=GEMINI_PRO_MODEL,
            max_output_tokens=2048,
        )
        raw_text = result.text
    except Exception as e:
        return {"status": "error", "detail": f"AI抽出エラー: {e}"}

    # Parse extracted rules
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    extracted_rules = []
    next_id = int(datetime.now(JST).timestamp())

    for line in raw_text.strip().split("\n"):
        line = line.strip()
        if not line or not line.startswith("- "):
            continue
        line = line[2:].strip()
        # Parse [category] rule_text
        category = "tone"
        rule_text = line
        if line.startswith("[") and "]" in line:
            bracket_end = line.index("]")
            category = line[1:bracket_end].strip()
            rule_text = line[bracket_end + 1:].strip()
        if not rule_text:
            continue
        extracted_rules.append({
            "id": str(next_id),
            "company": company if company != "all" else "",
            "category": category,
            "rule": rule_text,
            "source": source,
            "status": "pending",
        })
        next_id += 1

    # Write to knowledge pool sheet
    if extracted_rules:
        sheets_writer.ensure_sheet_exists(KNOWLEDGE_POOL_SHEET, KNOWLEDGE_POOL_HEADERS)
        rows = [
            [r["id"], r["company"], r["category"], r["rule"], r["source"], r["status"], now]
            for r in extracted_rules
        ]
        sheets_writer.append_rows(KNOWLEDGE_POOL_SHEET, rows)

    return {
        "status": "ok",
        "extracted_rules": extracted_rules,
        "count": len(extracted_rules),
    }


@router.post("/{sheet_slug}")
async def create_row(sheet_slug: str, data: dict, operator=Depends(verify_api_key)):
    sheet_name = SHEET_MAP.get(sheet_slug)
    if not sheet_name:
        raise HTTPException(404, f"Unknown sheet: {sheet_slug}")

    # For qualifiers, force pattern_type=QUAL
    if sheet_slug == "qualifiers":
        data["pattern_type"] = "QUAL"

    columns = COLUMNS.get(sheet_slug, [])
    values = [data.get(col, "") for col in columns]
    sheets_writer.ensure_sheet_exists(sheet_name, headers=columns)
    sheets_writer.append_row(sheet_name, values)
    reload_status = _safe_reload()
    return {"status": "created", **reload_status}


@router.put("/{sheet_slug}/{row_index}")
async def update_row(sheet_slug: str, row_index: int, data: dict, operator=Depends(verify_api_key)):
    sheet_name = SHEET_MAP.get(sheet_slug)
    if not sheet_name:
        raise HTTPException(404, f"Unknown sheet: {sheet_slug}")

    columns = COLUMNS.get(sheet_slug, [])

    # Read the actual sheet header so we can compare against the row being
    # updated and so the version-bump / history logic still has access to
    # the old values. We use update_cells_by_name to write — that method
    # internally re-reads the header and aligns by column name, so even if
    # COLUMNS in code drifts from the sheet, no data is scrambled.
    all_rows = sheets_writer.get_all_rows(sheet_name)
    if row_index < 2 or row_index > len(all_rows):
        raise HTTPException(404, f"Row {row_index} not found")

    header = [h.strip() for h in all_rows[0]]
    existing_row = all_rows[row_index - 1]
    existing_row += [""] * (len(header) - len(existing_row))
    existing = {header[i]: existing_row[i] for i in range(len(header))}

    # Build the cells to write: only fields present in `data` AND known
    # columns. Unknown keys are dropped to avoid creating phantom columns.
    valid_cols = set(columns) & set(header) if columns else set(header)
    cells: dict[str, str] = {}
    for key, value in data.items():
        if key.startswith("_"):
            continue  # private metadata like _change_reason
        if key in valid_cols:
            cells[key] = "" if value is None else str(value)

    # Template body update: delegate to the shared version-bump helper so
    # single-row PUT and batch_update_templates never drift apart.
    if sheet_slug == "templates" and "body" in cells:
        reason = data.get("_change_reason", "管理画面から更新")
        try:
            bump_result = _bump_template_body(
                row_index=row_index,
                new_body=cells["body"],
                reason=reason,
                actor="admin_ui",
            )
        except ValueError as e:
            raise HTTPException(500, f"テンプレート更新エラー: {e}")

        # Handle any non-body columns the same PUT also wants to touch
        # (e.g. job_category rename). body+version are owned by the helper.
        other_cells = {k: v for k, v in cells.items() if k not in ("body", "version")}
        if other_cells:
            other_result = sheets_writer.update_cells_by_name(
                sheet_name, row_index, other_cells, actor="admin_ui",
            )
            merged_fields = list(other_result["updated"]) + (
                ["body", "version"] if bump_result["status"] == "updated" else []
            )
            skipped_fields = other_result["skipped"]
        else:
            merged_fields = ["body", "version"] if bump_result["status"] == "updated" else []
            skipped_fields = []

        reload_status = _safe_reload()
        return {
            "status": bump_result["status"],
            "merged_fields": merged_fields,
            "skipped_fields": skipped_fields,
            "version": bump_result["new_version"],
            **reload_status,
        }

    if not cells:
        return {"status": "no-op", "merged_fields": [], "version": existing.get("version", "")}

    result = sheets_writer.update_cells_by_name(
        sheet_name, row_index, cells, actor="admin_ui",
    )
    reload_status = _safe_reload()
    return {
        "status": "updated",
        "merged_fields": result["updated"],
        "skipped_fields": result["skipped"],
        "version": cells.get("version", existing.get("version", "")),
        **reload_status,
    }


@router.delete("/{sheet_slug}/{row_index}")
async def delete_row(sheet_slug: str, row_index: int, operator=Depends(verify_api_key)):
    sheet_name = SHEET_MAP.get(sheet_slug)
    if not sheet_name:
        raise HTTPException(404, f"Unknown sheet: {sheet_slug}")

    sheets_writer.delete_row(sheet_name, row_index, actor="admin_ui")
    reload_status = _safe_reload()
    return {"status": "deleted", **reload_status}


# --- Cost monitoring endpoints ---

@router.get("/costs/today")
async def get_costs_today(operator=Depends(verify_api_key)):
    """Get today's cost summary."""
    from monitoring.cost_tracker import cost_tracker
    return cost_tracker.get_daily_summary()


@router.get("/costs/monthly")
async def get_costs_monthly(operator=Depends(verify_api_key)):
    """Get current month's cost summary."""
    from monitoring.cost_tracker import cost_tracker
    return cost_tracker.get_monthly_summary()


@router.post("/cron/prune-audit-log")
async def cron_prune_audit_log(
    days: int = 90,
    operator=Depends(verify_api_key),
):
    """Cloud Scheduler が定期的に叩くエンドポイント。
    操作履歴シートから `days` 日より古い行を削除する。

    Default retention: 90 days. Pass `?days=30` etc. to override.
    Set `days=0` to wipe everything older than today (use with care).
    """
    if days < 0:
        raise HTTPException(400, "days must be >= 0")
    result = sheets_writer.prune_audit_log(retention_days=days)
    return {"status": "ok", **result}


@router.post("/cron/daily-report")
async def cron_daily_report(operator=Depends(verify_api_key)):
    """Cloud Scheduler が毎朝叩くエンドポイント。日次レポート + アラート。"""
    from monitoring.cost_tracker import cost_tracker
    from monitoring.notifier import notify_google_chat
    from monitoring.scheduler import _format_cost_message, _check_alert
    from datetime import datetime, timedelta, timezone

    JST = timezone(timedelta(hours=9))
    yesterday = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")
    summary = cost_tracker.get_daily_summary(yesterday)
    monthly = cost_tracker.get_monthly_summary()

    if summary["requests"] > 0:
        message = _format_cost_message(summary, "日次コストレポート")
    else:
        message = (
            f"📊 *日次コストレポート*\n"
            f"期間: {yesterday}\n"
            f"総生成数: 0"
        )
    message += (
        f"\n\n📅 今月累計: ${monthly['estimated_cost_usd']:.4f} "
        f"(AI {monthly.get('ai_requests', 0):,} / "
        f"パターン {monthly.get('pattern_requests', 0):,})"
    )

    sent = await notify_google_chat(message)
    await _check_alert()

    return {"status": "ok", "sent": sent, "yesterday": yesterday}
