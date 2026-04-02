"""Migrate existing 生成ログ rows into per-company 送信_* sheets.

Maps available columns; missing columns (年齢層, 経験区分 etc.) are left blank.

Usage:
    python3 scripts/migrate_logs_to_send_data.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import google.auth
from googleapiclient.discovery import build
from config import SPREADSHEET_ID

COMPANY_DISPLAY_NAMES = {
    "ark-visiting-nurse": "アーク訪看",
    "lcc-visiting-nurse": "LCC訪看",
    "ichigo-visiting-nurse": "いちご訪看",
    "an-visiting-nurse": "an訪看",
    "chigasaki-tokushukai": "茅ヶ崎徳洲会",
}

SEND_HEADERS = [
    "日時", "会員番号", "テンプレート種別", "生成パス", "パターン",
    "年齢層", "資格", "経験区分", "希望雇用形態", "就業状況",
    "曜日", "時間帯",
    "返信", "返信日", "返信カテゴリ",
]

# Mapping: 生成ログ column → 送信データ column
LOG_TO_SEND = {
    "timestamp": "日時",
    "member_id": "会員番号",
    "template_type": "テンプレート種別",
    "generation_path": "生成パス",
    "pattern_type": "パターン",
}

WEEKDAY_NAMES = ["月", "火", "水", "木", "金", "土", "日"]


def main():
    print(f"Spreadsheet: {SPREADSHEET_ID}")
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=credentials)

    # Read 生成ログ
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range="'生成ログ'!A:Z",
    ).execute()
    rows = result.get("values", [])
    if len(rows) < 2:
        print("No data in 生成ログ")
        return

    log_headers = rows[0]
    log_col = {h: i for i, h in enumerate(log_headers)}

    # Group by company, only successful generations
    company_rows = {}
    skipped = 0
    for row in rows[1:]:
        def get(col):
            idx = log_col.get(col)
            if idx is None or idx >= len(row):
                return ""
            return row[idx]

        status = get("status")
        if status != "成功":
            skipped += 1
            continue

        company = get("company")
        if not company:
            skipped += 1
            continue

        # Parse weekday/time from timestamp
        ts = get("timestamp")
        weekday = ""
        time_slot = ""
        if ts and len(ts) >= 10:
            try:
                from datetime import datetime
                dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
                weekday = WEEKDAY_NAMES[dt.weekday()]
                h = dt.hour
                if h < 9: time_slot = "早朝"
                elif h < 12: time_slot = "午前"
                elif h < 14: time_slot = "昼"
                elif h < 17: time_slot = "午後"
                else: time_slot = "夕方以降"
            except Exception:
                pass

        send_row = [
            get("timestamp"),       # 日時
            get("member_id"),       # 会員番号
            get("template_type"),   # テンプレート種別
            get("generation_path"), # 生成パス
            get("pattern_type"),    # パターン
            "",                     # 年齢層 (not in log)
            "",                     # 資格 (not in log)
            "",                     # 経験区分 (not in log)
            "",                     # 希望雇用形態 (not in log)
            "",                     # 就業状況 (not in log)
            weekday,                # 曜日 (computed)
            time_slot,              # 時間帯 (computed)
            "",                     # 返信
            "",                     # 返信日
            "",                     # 返信カテゴリ
        ]

        if company not in company_rows:
            company_rows[company] = []
        company_rows[company].append(send_row)

    print(f"Parsed {sum(len(v) for v in company_rows.values())} rows, skipped {skipped}")

    # Write to per-company sheets
    for company_id, rows in company_rows.items():
        display = COMPANY_DISPLAY_NAMES.get(company_id, company_id)
        sheet_name = f"送信_{display}"

        # Check if sheet exists, if not create with headers
        spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        existing = {s["properties"]["title"] for s in spreadsheet.get("sheets", [])}
        if sheet_name not in existing:
            print(f"  Skip: '{sheet_name}' does not exist (create it first)")
            continue

        # Check if already has data
        existing_data = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{sheet_name}'!A:A",
        ).execute()
        existing_rows = len(existing_data.get("values", []))
        if existing_rows > 1:
            print(f"  Skip: '{sheet_name}' already has {existing_rows - 1} data rows")
            continue

        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{sheet_name}'!A:O",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()
        print(f"  Wrote {len(rows)} rows to '{sheet_name}'")

    print("Done.")


if __name__ == "__main__":
    main()
