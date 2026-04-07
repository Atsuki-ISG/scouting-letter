"""Force-update the header row of every 送信_* sheet to the current SEND_DATA_HEADERS schema.

Background: a duplicate `ensure_sheet_exists` method in db/sheets_writer.py used to
silently skip header updates on existing sheets. As a result, some 送信_* sheets
retained their legacy 15-column header while newer rows were appended with 18
columns, causing column drift in the dashboard.

This script walks every configured company, reads the existing header row of its
送信_<display> sheet, and if it differs from SEND_DATA_HEADERS, overwrites it.
Data rows are NOT touched.

Usage:
    cd server && python3 scripts/fix_send_data_headers.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.sheets_writer import sheets_writer
from pipeline.orchestrator import COMPANY_DISPLAY_NAMES, SEND_DATA_HEADERS, _send_data_sheet_name


def main() -> None:
    print(f"Target schema ({len(SEND_DATA_HEADERS)} cols): {SEND_DATA_HEADERS}")
    print("-" * 60)
    for company_id in COMPANY_DISPLAY_NAMES.keys():
        sheet_name = _send_data_sheet_name(company_id)
        try:
            rows = sheets_writer.get_all_rows(sheet_name)
        except Exception as e:
            print(f"[skip] {sheet_name}: read failed ({e})")
            continue
        if not rows:
            print(f"[skip] {sheet_name}: does not exist yet")
            continue
        current = [h.strip() for h in rows[0]]
        if current == SEND_DATA_HEADERS:
            print(f"[ok]   {sheet_name}: already up to date")
            continue
        print(f"[fix]  {sheet_name}:")
        print(f"       before ({len(current)}): {current}")
        print(f"       after  ({len(SEND_DATA_HEADERS)}): {SEND_DATA_HEADERS}")
        # Call ensure_sheet_exists which now always updates headers
        sheets_writer.ensure_sheet_exists(sheet_name, SEND_DATA_HEADERS)
        print(f"       -> updated")
    print("-" * 60)
    print("Done. Note: pre-existing data rows keep their original column positions.")
    print("The dashboard read path uses a schema-drift fallback to tolerate both.")


if __name__ == "__main__":
    main()
