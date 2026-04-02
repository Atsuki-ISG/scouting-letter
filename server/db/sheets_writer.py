"""Google Sheets writer for admin operations."""
import logging
import google.auth
from googleapiclient.discovery import build
from config import SPREADSHEET_ID

logger = logging.getLogger(__name__)


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

    def ensure_sheet_exists(self, sheet_name: str, headers: list[str] | None = None) -> None:
        """Create a sheet if it doesn't exist. Update header row if columns are missing."""
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
        elif headers:
            # Check if existing header needs updating
            try:
                result = service.spreadsheets().values().get(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"'{sheet_name}'!1:1"
                ).execute()
                current = result.get("values", [[]])[0] if result.get("values") else []
                current_stripped = [h.strip() for h in current]
                if current_stripped != headers:
                    service.spreadsheets().values().update(
                        spreadsheetId=SPREADSHEET_ID,
                        range=f"'{sheet_name}'!A1",
                        valueInputOption="RAW",
                        body={"values": [headers]}
                    ).execute()
                    logger.info(f"Updated headers for '{sheet_name}': {current_stripped} -> {headers}")
            except Exception as e:
                logger.warning(f"Failed to check/update headers for '{sheet_name}': {e}")

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
        """Update a specific row (1-indexed, row 1 = header)."""
        service = self._get_service()
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{sheet_name}'!A{row_index}",
            valueInputOption="RAW",
            body={"values": [values]}
        ).execute()

    def delete_row(self, sheet_name: str, row_index: int) -> None:
        """Delete a specific row by sheet name and row index (1-indexed)."""
        service = self._get_service()
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

    def ensure_sheet_exists(self, sheet_name: str, headers: list[str]) -> None:
        """Create a sheet with headers if it doesn't exist yet."""
        service = self._get_service()
        spreadsheet = service.spreadsheets().get(
            spreadsheetId=SPREADSHEET_ID
        ).execute()
        existing = [s["properties"]["title"] for s in spreadsheet.get("sheets", [])]
        if sheet_name in existing:
            return
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]}
        ).execute()
        # Write header row
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{sheet_name}'!A1",
            valueInputOption="RAW",
            body={"values": [headers]}
        ).execute()
        logger.info(f"Created sheet '{sheet_name}' with {len(headers)} columns")


sheets_writer = SheetsWriter()
