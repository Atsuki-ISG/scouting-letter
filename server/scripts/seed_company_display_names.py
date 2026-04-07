"""One-shot: populate display_name column on the プロフィール sheet.

Run from server/ as:
  GOOGLE_APPLICATION_CREDENTIALS=sa-key.json \
  SPREADSHEET_ID=... \
  python3 scripts/seed_company_display_names.py
"""
from __future__ import annotations

import sys
from db.sheets_client import sheets_client, SHEET_PROFILES
from db.sheets_writer import sheets_writer

DISPLAY_NAMES: dict[str, str] = {
    "ark-visiting-nurse": "アーク訪問看護ステーション",
    "lcc-visiting-nurse": "LCC訪問看護ステーション",
    "ichigo-visiting-nurse": "いちご訪問看護グループ",
    "ichigo-care-home": "いちごの里",
    "chigasaki-tokushukai": "茅ヶ崎徳洲会病院",
    "an-visiting-nurse": "an訪問看護ステーション",
    "daiwa-house-ls": "ネオ・サミット湯河原",
    "nomura-hospital": "野村病院",
}


def main() -> int:
    # Ensure the column exists (non-destructive add)
    sheets_writer.ensure_sheet_exists(
        SHEET_PROFILES, ["company", "content", "detection_keywords", "display_name"]
    )

    # Read all rows to find each company's row index
    all_rows = sheets_writer.get_all_rows(SHEET_PROFILES)
    if not all_rows:
        print(f"ERROR: '{SHEET_PROFILES}' sheet is empty", file=sys.stderr)
        return 1
    headers = [h.strip() for h in all_rows[0]]
    if "company" not in headers:
        print(f"ERROR: 'company' column not found in headers: {headers}", file=sys.stderr)
        return 1
    company_col = headers.index("company")

    updated = 0
    missing: list[str] = []
    for company_id, display_name in DISPLAY_NAMES.items():
        row_index: int | None = None
        for i, row in enumerate(all_rows[1:], start=2):  # 1-based; data starts at 2
            if len(row) > company_col and row[company_col].strip() == company_id:
                row_index = i
                break
        if row_index is None:
            missing.append(company_id)
            continue
        result = sheets_writer.update_cells_by_name(
            SHEET_PROFILES,
            row_index,
            {"display_name": display_name},
            actor="seed_company_display_names",
        )
        print(f"  [{company_id}] row={row_index} -> {display_name} {result}")
        updated += 1

    print(f"\nUpdated {updated}/{len(DISPLAY_NAMES)} companies")
    if missing:
        print(f"Missing in sheet (no row found): {missing}")
    sheets_client.reload()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
