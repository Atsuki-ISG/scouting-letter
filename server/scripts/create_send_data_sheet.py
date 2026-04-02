"""Create a dedicated spreadsheet for send data, with per-company sheets.

Usage:
    python3 scripts/create_send_data_sheet.py

Creates a new spreadsheet and prints the ID. Set SEND_DATA_SPREADSHEET_ID env var to this.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import google.auth
from googleapiclient.discovery import build

COMPANIES = [
    ("ark-visiting-nurse", "アーク訪看"),
    ("lcc-visiting-nurse", "LCC訪看"),
    ("ichigo-visiting-nurse", "いちご訪看"),
    ("an-visiting-nurse", "an訪看"),
    ("chigasaki-tokushukai", "茅ヶ崎徳洲会"),
]

# Headers per company sheet (会社列は不要 — シート自体が会社)
HEADERS = [
    "日時", "会員番号", "テンプレート種別", "生成パス", "パターン",
    "年齢層", "資格", "経験区分", "希望雇用形態", "就業状況",
    "曜日", "時間帯",
    "返信", "返信日", "返信カテゴリ",
]

COMPANY_COLORS = {
    "アーク訪看": {"red": 0.22, "green": 0.46, "blue": 0.72},
    "LCC訪看": {"red": 0.85, "green": 0.55, "blue": 0.20},
    "いちご訪看": {"red": 0.16, "green": 0.56, "blue": 0.55},
    "an訪看": {"red": 0.53, "green": 0.33, "blue": 0.65},
    "茅ヶ崎徳洲会": {"red": 0.42, "green": 0.42, "blue": 0.42},
}

SERVICE_ACCOUNT = "scout-api@scout-generation-490709.iam.gserviceaccount.com"


def main():
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"]
    )
    sheets = build("sheets", "v4", credentials=credentials)
    drive = build("drive", "v3", credentials=credentials)

    # Create spreadsheet with company sheets
    sheet_props = []
    for i, (company_id, display_name) in enumerate(COMPANIES):
        color = COMPANY_COLORS.get(display_name, {"red": 0.5, "green": 0.5, "blue": 0.5})
        sheet_props.append({
            "properties": {
                "title": display_name,
                "index": i,
                "tabColorStyle": {"rgbColor": color},
                "gridProperties": {"frozenRowCount": 1},
            }
        })

    resp = sheets.spreadsheets().create(body={
        "properties": {"title": "スカウト送信データ"},
        "sheets": sheet_props,
    }).execute()

    spreadsheet_id = resp["spreadsheetId"]
    print(f"Created spreadsheet: {spreadsheet_id}")
    print(f"URL: https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit")

    # Write headers to each sheet
    data = []
    for _, display_name in COMPANIES:
        data.append({
            "range": f"'{display_name}'!A1",
            "values": [HEADERS],
        })

    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()

    # Format headers (bold, background)
    requests = []
    for sheet in resp["sheets"]:
        sid = sheet["properties"]["sheetId"]
        display_name = sheet["properties"]["title"]
        color = COMPANY_COLORS.get(display_name, {"red": 0.5, "green": 0.5, "blue": 0.5})

        requests.append({
            "repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": color,
                        "textFormat": {
                            "bold": True,
                            "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                        },
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        })

        # Column widths
        col_widths = [140, 100, 120, 80, 80, 80, 120, 80, 100, 80, 50, 60, 50, 90, 100]
        for ci, w in enumerate(col_widths):
            requests.append({
                "updateDimensionProperties": {
                    "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": ci, "endIndex": ci + 1},
                    "properties": {"pixelSize": w},
                    "fields": "pixelSize",
                }
            })

    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()

    # Share with user (owner's Google account)
    # The service account owns it, share with the main account
    try:
        drive.permissions().create(
            fileId=spreadsheet_id,
            body={
                "type": "user",
                "role": "writer",
                "emailAddress": "atsuki.maemitsumori@any.care",
            },
            sendNotificationEmail=False,
        ).execute()
        print("Shared with atsuki.maemitsumori@any.care")
    except Exception as e:
        print(f"Share warning: {e}")

    # Delete default Sheet1 if it exists
    for sheet in resp["sheets"]:
        if sheet["properties"]["title"] == "Sheet1":
            try:
                sheets.spreadsheets().batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={"requests": [{"deleteSheet": {"sheetId": sheet["properties"]["sheetId"]}}]},
                ).execute()
            except Exception:
                pass

    print(f"\nSet this env var:")
    print(f"  SEND_DATA_SPREADSHEET_ID={spreadsheet_id}")


if __name__ == "__main__":
    main()
