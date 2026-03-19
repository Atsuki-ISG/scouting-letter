"""Admin CRUD routes for Google Sheets data management."""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

from db.sheets_writer import sheets_writer
from db.sheets_client import sheets_client
from auth.api_key import verify_api_key

router = APIRouter(prefix="/admin", tags=["admin"])

# Slug to Japanese sheet name mapping
SHEET_MAP = {
    "templates": "テンプレート",
    "patterns": "パターン",
    "qualifiers": "資格修飾",
    "prompts": "プロンプト",
    "job_offers": "求人",
    "validation": "バリデーション",
}

# Column order for each sheet (must match header row)
COLUMNS = {
    "templates": ["company", "job_category", "type", "body"],
    "patterns": ["company", "job_category", "pattern_type", "employment_variant", "template_text", "feature_variations"],
    "qualifiers": ["company", "qualification_combo", "replacement_text"],
    "prompts": ["company", "section_type", "job_category", "order", "content"],
    "job_offers": ["company", "job_category", "id", "name", "label", "employment_type", "active"],
    "validation": ["company", "age_min", "age_max", "qualification_rules"],
}


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
    data_rows = []
    for i, row in enumerate(rows[1:], start=2):  # row 2 = first data row in sheet
        item = {}
        for j, h in enumerate(headers):
            item[h.strip()] = row[j].strip() if j < len(row) else ""
        if company and item.get("company") != company:
            continue
        item["_row_index"] = i  # actual sheet row number
        data_rows.append(item)

    return {"headers": [h.strip() for h in headers], "rows": data_rows}


@router.post("/{sheet_slug}")
async def create_row(sheet_slug: str, data: dict, operator=Depends(verify_api_key)):
    sheet_name = SHEET_MAP.get(sheet_slug)
    if not sheet_name:
        raise HTTPException(404, f"Unknown sheet: {sheet_slug}")

    columns = COLUMNS.get(sheet_slug, [])
    values = [data.get(col, "") for col in columns]
    sheets_writer.append_row(sheet_name, values)
    sheets_client.reload()
    return {"status": "created"}


@router.put("/{sheet_slug}/{row_index}")
async def update_row(sheet_slug: str, row_index: int, data: dict, operator=Depends(verify_api_key)):
    sheet_name = SHEET_MAP.get(sheet_slug)
    if not sheet_name:
        raise HTTPException(404, f"Unknown sheet: {sheet_slug}")

    columns = COLUMNS.get(sheet_slug, [])
    values = [data.get(col, "") for col in columns]
    sheets_writer.update_row(sheet_name, row_index, values)
    sheets_client.reload()
    return {"status": "updated"}


@router.delete("/{sheet_slug}/{row_index}")
async def delete_row(sheet_slug: str, row_index: int, operator=Depends(verify_api_key)):
    sheet_name = SHEET_MAP.get(sheet_slug)
    if not sheet_name:
        raise HTTPException(404, f"Unknown sheet: {sheet_slug}")

    sheets_writer.delete_row(sheet_name, row_index)
    sheets_client.reload()
    return {"status": "deleted"}
