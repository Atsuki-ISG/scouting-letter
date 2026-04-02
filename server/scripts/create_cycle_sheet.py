"""Create サイクル管理 sheets for each company in the dashboard spreadsheet.

Usage:
    python scripts/create_cycle_sheet.py

Creates one "スカウト管理" sheet per company with PDCA columns
for the 2-week improvement cycle.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import google.auth
from googleapiclient.discovery import build

# Dashboard spreadsheet (separate from API config spreadsheet)
DASHBOARD_SPREADSHEET_ID = "1a3XE212nZgsQP-93phk22VlSSZ5aD1ig72M4A6p2awE"

COMPANIES = [
    ("ark-visiting-nurse", "アーク訪看"),
    ("lcc-visiting-nurse", "LCC訪看"),
    ("ichigo-visiting-nurse", "いちご訪看"),
    ("an-visiting-nurse", "an訪看"),
]

CYCLE_HEADERS = [
    "サイクル",        # C01, C02...
    "期間",            # 04/01-04/14
    "テンプレート種別", # パート_初回, 正社員_初回 etc.
    "送信数",
    "返信数",
    "返信率",          # =E/D (数式)
    "分析",            # データから読み取れるパターン・傾向
    "仮説",            # なぜその傾向が出ているか
    "改善案",          # 具体的な変更提案
    "実施内容",        # 実際に変更したこと
    "結果メモ",        # 次サイクルでの検証結果
]

# Column widths (pixels)
COLUMN_WIDTHS = {
    0: 80,   # サイクル
    1: 120,  # 期間
    2: 140,  # テンプレート種別
    3: 80,   # 送信数
    4: 80,   # 返信数
    5: 80,   # 返信率
    6: 300,  # 分析
    7: 300,  # 仮説
    8: 300,  # 改善案
    9: 300,  # 実施内容
    10: 300, # 結果メモ
}

# Color palette per company (matching existing dashboards)
COMPANY_COLORS = {
    "アーク訪看": {"red": 0.22, "green": 0.46, "blue": 0.72},   # Blue
    "LCC訪看": {"red": 0.85, "green": 0.55, "blue": 0.20},       # Orange
    "いちご訪看": {"red": 0.16, "green": 0.56, "blue": 0.55},     # Teal
    "an訪看": {"red": 0.53, "green": 0.33, "blue": 0.65},         # Purple
}


def create_cycle_sheets():
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=credentials)

    # Get existing sheets
    spreadsheet = service.spreadsheets().get(
        spreadsheetId=DASHBOARD_SPREADSHEET_ID
    ).execute()
    existing = {s["properties"]["title"] for s in spreadsheet.get("sheets", [])}

    for company_id, display_name in COMPANIES:
        sheet_name = f"{display_name}_スカウト管理"
        if sheet_name in existing:
            print(f"  Skip: '{sheet_name}' already exists")
            continue

        color = COMPANY_COLORS.get(display_name, {"r": 0.3, "g": 0.3, "b": 0.3})

        # Create sheet
        resp = service.spreadsheets().batchUpdate(
            spreadsheetId=DASHBOARD_SPREADSHEET_ID,
            body={"requests": [{
                "addSheet": {
                    "properties": {
                        "title": sheet_name,
                        "tabColorStyle": {"rgbColor": color},
                    }
                }
            }]}
        ).execute()
        sheet_id = resp["replies"][0]["addSheet"]["properties"]["sheetId"]

        # Write headers
        service.spreadsheets().values().update(
            spreadsheetId=DASHBOARD_SPREADSHEET_ID,
            range=f"'{sheet_name}'!A1",
            valueInputOption="RAW",
            body={"values": [CYCLE_HEADERS]}
        ).execute()

        # Format: header row styling + column widths + freeze row 1
        requests = []

        # Header background color
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0, "endRowIndex": 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": color,
                        "textFormat": {
                            "bold": True,
                            "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                        },
                        "horizontalAlignment": "CENTER",
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
            }
        })

        # Freeze header row
        requests.append({
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        })

        # Column widths
        for col_idx, width in COLUMN_WIDTHS.items():
            requests.append({
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": col_idx,
                        "endIndex": col_idx + 1,
                    },
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            })

        # Text wrap for analysis columns (F onwards)
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "startColumnIndex": 6,  # 分析 column onwards
                    "endColumnIndex": 11,
                },
                "cell": {
                    "userEnteredFormat": {
                        "wrapStrategy": "WRAP",
                    }
                },
                "fields": "userEnteredFormat.wrapStrategy",
            }
        })

        # 返信率 column: percentage format
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "startColumnIndex": 5,
                    "endColumnIndex": 6,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {
                            "type": "PERCENT",
                            "pattern": "0.0%",
                        }
                    }
                },
                "fields": "userEnteredFormat.numberFormat",
            }
        })

        # Data validation: 返信率 as formula placeholder
        # Add sample row with formula
        service.spreadsheets().values().update(
            spreadsheetId=DASHBOARD_SPREADSHEET_ID,
            range=f"'{sheet_name}'!A2",
            valueInputOption="USER_ENTERED",
            body={"values": [[
                "C01", "", "", "", "",
                '=IF(D2>0,E2/D2,"")',
                "", "", "", "", "",
            ]]}
        ).execute()

        service.spreadsheets().batchUpdate(
            spreadsheetId=DASHBOARD_SPREADSHEET_ID,
            body={"requests": requests}
        ).execute()

        print(f"  Created: '{sheet_name}'")

    print("Done.")


if __name__ == "__main__":
    create_cycle_sheets()
