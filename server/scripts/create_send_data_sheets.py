"""Create per-company send data sheets in the API config spreadsheet.

Usage:
    python3 scripts/create_send_data_sheets.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import google.auth
from googleapiclient.discovery import build
from config import SPREADSHEET_ID

COMPANIES = [
    ("ark-visiting-nurse", "アーク訪看"),
    ("lcc-visiting-nurse", "LCC訪看"),
    ("ichigo-visiting-nurse", "いちご訪看"),
    ("an-visiting-nurse", "an訪看"),
    ("chigasaki-tokushukai", "茅ヶ崎徳洲会"),
]

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


def main():
    print(f"Spreadsheet: {SPREADSHEET_ID}")
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=credentials)

    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    existing = {s["properties"]["title"] for s in spreadsheet.get("sheets", [])}

    for company_id, display_name in COMPANIES:
        sheet_name = f"送信_{display_name}"
        if sheet_name in existing:
            print(f"  Skip: '{sheet_name}' already exists")
            continue

        color = COMPANY_COLORS.get(display_name, {"red": 0.5, "green": 0.5, "blue": 0.5})

        resp = service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{
                "addSheet": {
                    "properties": {
                        "title": sheet_name,
                        "tabColorStyle": {"rgbColor": color},
                        "gridProperties": {"frozenRowCount": 1},
                    }
                }
            }]}
        ).execute()
        sheet_id = resp["replies"][0]["addSheet"]["properties"]["sheetId"]

        # Write headers
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{sheet_name}'!A1",
            valueInputOption="RAW",
            body={"values": [HEADERS]},
        ).execute()

        # Format header row
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": color,
                            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }
            }]}
        ).execute()

        print(f"  Created: '{sheet_name}'")

    print("Done.")


if __name__ == "__main__":
    main()
