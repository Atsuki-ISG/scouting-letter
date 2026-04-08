"""Google Sheets writer for admin operations.

Design notes — written after a data-loss incident:

- `update_row(row_index, values: list)` is the legacy API. It writes values
  starting at column A in *positional* order, so callers must pass values in
  the exact same order as the sheet's actual header row. If the order
  diverges (e.g. someone reordered columns in the spreadsheet), data gets
  scrambled silently. Prefer `update_cells_by_name` instead.

- `update_cells_by_name(row_index, cells: dict)` is the safe API. It reads
  the current sheet header, maps each cell name to its actual column letter,
  and only writes the specified cells. Cells whose column names don't exist
  in the sheet are silently skipped. Cells not in the dict are left
  untouched.

- `ensure_sheet_exists` only ADDS missing columns to the header row; it
  never reorders or removes existing columns, even if the caller's `headers`
  argument is shorter. This prevents accidental column destruction when the
  spreadsheet has been edited manually.

- `delete_row` and `update_cells_by_name` both snapshot the previous row to
  the `操作履歴` audit sheet, so an accidental destructive operation can be
  recovered manually from the spreadsheet UI.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

import google.auth
from googleapiclient.discovery import build

from config import SPREADSHEET_ID

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

AUDIT_SHEET = "操作履歴"
AUDIT_HEADERS = [
    "timestamp", "operation", "sheet", "row_index",
    "snapshot_json", "changed_fields_json", "actor",
]


def _column_letter(index: int) -> str:
    """Convert a 0-based column index to its A1-style letter (0→A, 25→Z, 26→AA)."""
    if index < 0:
        raise ValueError(f"Negative column index: {index}")
    letters = ""
    n = index
    while True:
        letters = chr(ord("A") + (n % 26)) + letters
        n = n // 26 - 1
        if n < 0:
            break
    return letters


class SheetsWriter:
    def __init__(self):
        self._service = None

    def _get_service(self):
        if self._service is None:
            credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/spreadsheets"]
            )
            self._service = build("sheets", "v4", credentials=credentials)
        return self._service

    def get_all_rows(self, sheet_name: str) -> list[list[str]]:
        """Get all rows including header from a sheet."""
        service = self._get_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{sheet_name}'!A:Z"
        ).execute()
        return result.get("values", [])

    def get_headers(self, sheet_name: str) -> list[str]:
        """Read just the header row of a sheet (returns trimmed strings)."""
        service = self._get_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{sheet_name}'!1:1",
        ).execute()
        rows = result.get("values", [])
        if not rows:
            return []
        return [h.strip() for h in rows[0]]

    def ensure_sheet_exists(self, sheet_name: str, headers: list[str] | None = None) -> None:
        """Create a sheet if it doesn't exist. ADD any missing columns to the
        header row, but never reorder or remove existing columns.

        Safety guarantees:
        - If the sheet doesn't exist, it's created with `headers` exactly.
        - If the sheet exists with no header row, `headers` is written as-is.
        - If the sheet exists with a header row that already contains all of
          `headers`, nothing is changed.
        - If `headers` contains columns the sheet is missing, those new
          columns are APPENDED to the right of the existing header row.
        - Existing columns are NEVER renamed, reordered, or removed.
        """
        service = self._get_service()
        meta = service.spreadsheets().get(
            spreadsheetId=SPREADSHEET_ID, fields="sheets.properties.title"
        ).execute()
        existing = {s["properties"]["title"] for s in meta.get("sheets", [])}

        if sheet_name not in existing:
            service.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]}
            ).execute()
            logger.info(f"Created sheet '{sheet_name}'")
            if headers:
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"'{sheet_name}'!A1",
                    valueInputOption="RAW",
                    body={"values": [headers]}
                ).execute()
            return

        if not headers:
            return

        # Sheet exists. Read current header and only ADD missing columns.
        try:
            current = self.get_headers(sheet_name)
        except Exception as e:
            logger.warning(f"Failed to read headers for '{sheet_name}': {e}")
            return

        if not current:
            # Empty sheet — write headers as-is
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{sheet_name}'!A1",
                valueInputOption="RAW",
                body={"values": [headers]}
            ).execute()
            logger.info(f"Initialized empty header for '{sheet_name}'")
            return

        # Find columns in `headers` that aren't already in the sheet.
        missing = [h for h in headers if h not in current]
        if not missing:
            return  # nothing to do, sheet already has everything

        # Append missing columns to the right of the existing header.
        new_header = current + missing
        start_letter = _column_letter(len(current))
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{sheet_name}'!{start_letter}1",
            valueInputOption="RAW",
            body={"values": [missing]},
        ).execute()
        logger.info(
            f"Extended '{sheet_name}' header with {len(missing)} new columns: "
            f"{missing}. Existing columns {current} preserved."
        )

    def append_row(self, sheet_name: str, values: list[str]) -> None:
        """Append a row to a sheet."""
        service = self._get_service()
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{sheet_name}'!A:Z",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [values]}
        ).execute()

    def update_row(self, sheet_name: str, row_index: int, values: list[str]) -> None:
        """Update a row by writing `values` from column A in positional order.

        DEPRECATED: this is unsafe if the caller's column order diverges from
        the sheet's actual header order. Prefer `update_cells_by_name`. The
        method is kept for backward compatibility with callers that build
        rows in the same order as the sheet (e.g. dashboard QUOTA writer).
        """
        service = self._get_service()
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{sheet_name}'!A{row_index}",
            valueInputOption="RAW",
            body={"values": [values]}
        ).execute()

    def update_cells_by_name(
        self,
        sheet_name: str,
        row_index: int,
        cells: dict[str, str],
        *,
        actor: str = "",
        strict_columns: list[str] | None = None,
    ) -> dict:
        """Safely update specific cells in a row by column name.

        Reads the current sheet header to map each name in `cells` to its
        actual column letter, then writes only those cells via batchUpdate.
        Cells in `cells` whose names aren't in the sheet header are silently
        skipped (logged as a warning). Cells not in `cells` are left
        untouched.

        If `strict_columns` is given, any name in that list that isn't in
        the sheet header causes a ValueError to be raised BEFORE any write
        happens. Use this when the caller depends on certain columns
        existing (e.g. `version` for the template versioning flow) — silent
        skipping of those would corrupt downstream bookkeeping.

        Snapshots the previous row contents to the audit sheet before
        writing, so the operation is recoverable if something goes wrong.

        Returns:
            {"updated": [...changed col names], "skipped": [...unknown col names]}
        """
        service = self._get_service()
        all_rows = self.get_all_rows(sheet_name)
        if not all_rows:
            raise ValueError(f"Sheet '{sheet_name}' is empty (no header row)")
        if row_index < 2 or row_index > len(all_rows):
            raise ValueError(
                f"Row {row_index} not found in '{sheet_name}' "
                f"(valid range: 2..{len(all_rows)})"
            )

        headers = [h.strip() for h in all_rows[0]]

        # Strict column check: refuse to write if any required column is
        # missing from the sheet header. Do this BEFORE the audit snapshot
        # so nothing lands on disk.
        if strict_columns:
            missing = [c for c in strict_columns if c not in headers]
            if missing:
                raise ValueError(
                    f"update_cells_by_name on '{sheet_name}' requires columns "
                    f"{missing} but sheet header is {headers}"
                )

        previous_row = all_rows[row_index - 1]
        previous_row += [""] * (len(headers) - len(previous_row))
        previous_dict = {headers[i]: previous_row[i] for i in range(len(headers))}

        # Snapshot to audit log BEFORE writing
        changed = {k: v for k, v in cells.items() if k in headers and previous_dict.get(k, "") != v}
        if changed:
            self._append_audit(
                operation="update",
                sheet=sheet_name,
                row_index=row_index,
                snapshot=previous_dict,
                changed=changed,
                actor=actor,
            )

        updated_names: list[str] = []
        skipped_names: list[str] = []
        data: list[dict] = []
        for col_name, new_value in cells.items():
            if col_name not in headers:
                skipped_names.append(col_name)
                continue
            col_idx = headers.index(col_name)
            letter = _column_letter(col_idx)
            data.append({
                "range": f"'{sheet_name}'!{letter}{row_index}",
                "values": [[new_value]],
            })
            updated_names.append(col_name)

        if skipped_names:
            logger.warning(
                f"update_cells_by_name skipped unknown columns in '{sheet_name}': "
                f"{skipped_names} (sheet headers: {headers})"
            )

        if data:
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={
                    "valueInputOption": "RAW",
                    "data": data,
                },
            ).execute()

        return {"updated": updated_names, "skipped": skipped_names}

    def delete_row(self, sheet_name: str, row_index: int, *, actor: str = "") -> None:
        """Delete a specific row by sheet name and row index (1-indexed).

        Snapshots the row contents to the audit log first, so deletes are
        recoverable from the operation history sheet.
        """
        service = self._get_service()

        # Snapshot before delete
        try:
            all_rows = self.get_all_rows(sheet_name)
            if 2 <= row_index <= len(all_rows):
                headers = [h.strip() for h in all_rows[0]]
                row = all_rows[row_index - 1]
                row += [""] * (len(headers) - len(row))
                snapshot = {headers[i]: row[i] for i in range(len(headers))}
                self._append_audit(
                    operation="delete",
                    sheet=sheet_name,
                    row_index=row_index,
                    snapshot=snapshot,
                    changed={},
                    actor=actor,
                )
        except Exception as e:
            logger.warning(
                f"Failed to snapshot row {row_index} of '{sheet_name}' before delete: {e}"
            )

        # First get the sheet ID
        spreadsheet = service.spreadsheets().get(
            spreadsheetId=SPREADSHEET_ID
        ).execute()
        sheet_id = None
        for sheet in spreadsheet.get("sheets", []):
            if sheet["properties"]["title"] == sheet_name:
                sheet_id = sheet["properties"]["sheetId"]
                break
        if sheet_id is None:
            raise ValueError(f"Sheet '{sheet_name}' not found")

        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={
                "requests": [{
                    "deleteDimension": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "startIndex": row_index - 1,  # 0-indexed
                            "endIndex": row_index
                        }
                    }
                }]
            }
        ).execute()

    def delete_rows_bulk(
        self, sheet_name: str, row_indices: list[int], *, audit: bool = True, actor: str = ""
    ) -> int:
        """Delete multiple rows in a single batchUpdate.

        Row indices are 1-based and refer to the sheet's pre-deletion state.
        Internally sorted descending so deleting one row never invalidates
        the indices of the remaining ones.

        Args:
            sheet_name: target sheet
            row_indices: 1-based row numbers to delete (header row 1 is rejected)
            audit: when True (default), snapshot each deleted row to the audit
                log first. Set to False for self-pruning the audit log to
                avoid recursion / unbounded growth.
            actor: free-form string written into the audit log

        Returns:
            number of rows actually deleted
        """
        if not row_indices:
            return 0
        # Reject header row
        unique_sorted = sorted({i for i in row_indices if i >= 2}, reverse=True)
        if not unique_sorted:
            return 0

        service = self._get_service()

        # Snapshot each row before delete (best-effort, skipped for audit prune)
        if audit:
            try:
                all_rows = self.get_all_rows(sheet_name)
                if all_rows:
                    headers = [h.strip() for h in all_rows[0]]
                    for ri in unique_sorted:
                        if 2 <= ri <= len(all_rows):
                            row = all_rows[ri - 1]
                            row += [""] * (len(headers) - len(row))
                            snapshot = {headers[i]: row[i] for i in range(len(headers))}
                            self._append_audit(
                                operation="delete",
                                sheet=sheet_name,
                                row_index=ri,
                                snapshot=snapshot,
                                changed={},
                                actor=actor,
                            )
            except Exception as e:
                logger.warning(
                    f"Failed to snapshot rows of '{sheet_name}' before bulk delete: {e}"
                )

        # Resolve sheet ID
        spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        sheet_id = None
        for s in spreadsheet.get("sheets", []):
            if s["properties"]["title"] == sheet_name:
                sheet_id = s["properties"]["sheetId"]
                break
        if sheet_id is None:
            raise ValueError(f"Sheet '{sheet_name}' not found")

        requests = [
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": ri - 1,
                        "endIndex": ri,
                    }
                }
            }
            for ri in unique_sorted
        ]
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": requests},
        ).execute()
        return len(unique_sorted)

    def prune_audit_log(self, retention_days: int = 90) -> dict:
        """Delete 操作履歴 rows older than `retention_days` days.

        Used by the /admin/cron/prune-audit-log scheduled endpoint to keep
        the audit sheet from growing unbounded. Does NOT snapshot the
        deleted rows (would cause recursion / defeat the purpose).

        Returns: {"checked": N, "deleted": M, "cutoff": "YYYY-MM-DD HH:MM:SS"}
        """
        cutoff = datetime.now(JST) - timedelta(days=retention_days)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

        try:
            rows = self.get_all_rows(AUDIT_SHEET)
        except Exception as e:
            logger.warning(f"prune_audit_log: cannot read {AUDIT_SHEET}: {e}")
            return {"checked": 0, "deleted": 0, "cutoff": cutoff_str}

        if not rows or len(rows) < 2:
            return {"checked": 0, "deleted": 0, "cutoff": cutoff_str}

        headers = [h.strip() for h in rows[0]]
        try:
            ts_idx = headers.index("timestamp")
        except ValueError:
            logger.warning(f"prune_audit_log: '{AUDIT_SHEET}' has no timestamp column")
            return {"checked": len(rows) - 1, "deleted": 0, "cutoff": cutoff_str}

        to_delete: list[int] = []
        for i, row in enumerate(rows[1:], start=2):
            if len(row) <= ts_idx:
                continue
            ts_str = (row[ts_idx] or "").strip()
            if not ts_str:
                continue
            # Try parsing both naive (legacy) and JST-suffixed timestamps
            parsed = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S+09:00"):
                try:
                    parsed = datetime.strptime(ts_str, fmt)
                    break
                except ValueError:
                    continue
            if parsed is None:
                continue
            # Treat parsed timestamps as JST (audit log writes JST)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=JST)
            if parsed < cutoff:
                to_delete.append(i)

        if to_delete:
            self.delete_rows_bulk(AUDIT_SHEET, to_delete, audit=False, actor="cron:prune")
            logger.info(
                f"prune_audit_log: deleted {len(to_delete)} rows older than {cutoff_str}"
            )

        return {
            "checked": len(rows) - 1,
            "deleted": len(to_delete),
            "cutoff": cutoff_str,
        }

    def append_rows(self, sheet_name: str, rows: list[list[str]]) -> None:
        """Append multiple rows to a sheet in a single API call."""
        if not rows:
            return
        service = self._get_service()
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{sheet_name}'!A:Z",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows}
        ).execute()

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def _append_audit(
        self,
        *,
        operation: str,
        sheet: str,
        row_index: int,
        snapshot: dict,
        changed: dict,
        actor: str,
    ) -> None:
        """Append an entry to the 操作履歴 audit sheet (best-effort)."""
        try:
            import json
            self.ensure_sheet_exists(AUDIT_SHEET, AUDIT_HEADERS)
            now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
            self.append_row(AUDIT_SHEET, [
                now,
                operation,
                sheet,
                str(row_index),
                json.dumps(snapshot, ensure_ascii=False),
                json.dumps(changed, ensure_ascii=False),
                actor or "",
            ])
        except Exception as e:
            # Audit logging must never block the actual operation
            logger.warning(f"Failed to write audit log: {e}")


sheets_writer = SheetsWriter()
