"""Import reply data from conversations YAML into per-company send data sheets.

Usage:
    python3 scripts/import_replies_from_yaml.py /path/to/conversations.yml [--classify]

--classify: Use Gemini to auto-classify reply categories (requires GEMINI_API_KEY)

What it does:
1. Reads conversations YAML (multi-document)
2. For each conversation with a candidate reply:
   - Finds the matching row in 送信_[会社] sheet by member_id
   - Updates: 返信=有, 返信日, 返信カテゴリ
   - Fills missing candidate attributes (年齢層) if available
   - If no matching row found, appends a new row
3. Optionally classifies reply category with Gemini
"""
import sys
import os
import argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yaml
import google.auth
from googleapiclient.discovery import build
from config import SPREADSHEET_ID

COMPANY_DISPLAY_NAMES = {
    "ark-visiting-nurse": "アーク訪看",
    "lcc-visiting-nurse": "LCC訪看",
    "ichigo-visiting-nurse": "いちご訪看",
    "an-visiting-nurse": "an訪看",
    "chigasaki-tokushukai": "茅ヶ崎徳洲会",
    "nomura-hospital": "野村病院",
}

SEND_HEADERS = [
    "日時", "会員番号", "テンプレート種別", "生成パス", "パターン",
    "年齢層", "資格", "経験年数", "希望雇用形態", "就業状況",
    "曜日", "時間帯",
    "返信", "返信日", "返信カテゴリ",
]

WEEKDAY_NAMES = ["月", "火", "水", "木", "金", "土", "日"]

REPLY_CATEGORIES = {
    "興味あり": "面談・見学を希望、前向きな返信",
    "質問": "条件や詳細について質問",
    "辞退": "お断り、条件が合わない",
    "面談設定済": "面談の日程調整が完了",
    "保留": "検討中、すぐには決められない",
}


def age_bucket(age_str):
    if not age_str:
        return ""
    try:
        age = int("".join(c for c in age_str if c.isdigit()))
        if age < 25: return "〜24歳"
        elif age < 30: return "25-29歳"
        elif age < 35: return "30-34歳"
        elif age < 40: return "35-39歳"
        elif age < 45: return "40-44歳"
        elif age < 50: return "45-49歳"
        else: return "50歳〜"
    except (ValueError, TypeError):
        return ""


def classify_reply_simple(messages):
    """Simple rule-based classification from conversation flow."""
    candidate_msgs = [m for m in messages if m.get("role") == "candidate"]
    if not candidate_msgs:
        return ""

    all_text = " ".join(m.get("text", "") for m in candidate_msgs).lower()
    company_msgs = [m for m in messages if m.get("role") == "company"]

    # Check for meeting/interview scheduling
    has_schedule = any("日程" in m.get("text", "") or "meet.google" in m.get("text", "")
                       for m in company_msgs)
    candidate_confirmed = any("よろしくお願い" in m.get("text", "") for m in candidate_msgs[1:]) if len(candidate_msgs) > 1 else False

    if has_schedule and candidate_confirmed:
        return "面談設定済"

    first_reply = candidate_msgs[0].get("text", "")

    if any(w in first_reply for w in ["辞退", "遠慮", "他で", "難しい", "今回は"]):
        return "辞退"
    if any(w in first_reply for w in ["お話を伺い", "興味", "ぜひ", "お話しさせて"]):
        return "興味あり"
    if "?" in first_reply or "？" in first_reply or "でしょうか" in first_reply:
        return "質問"

    # Check later messages for decline
    if any("遠慮" in m.get("text", "") or "辞退" in m.get("text", "") for m in candidate_msgs):
        return "辞退"

    return "興味あり"  # default if they replied at all


def classify_reply_ai(messages, genai_model):
    """Use Gemini to classify the reply category."""
    candidate_msgs = [m for m in messages if m.get("role") == "candidate"]
    if not candidate_msgs:
        return ""

    # Build conversation summary (keep it short)
    conv_text = ""
    for m in messages[:8]:  # First 8 messages max
        role = "事業所" if m["role"] == "company" else "求職者"
        text = m.get("text", "")[:200]
        conv_text += f"[{role}] {text}\n"

    prompt = f"""以下のスカウトメッセージのやりとりから、求職者の返信カテゴリを1つ選んでください。

カテゴリ:
- 面談設定済: 面談の日程が確定した
- 興味あり: 前向きな返信、詳しく聞きたい
- 質問: 条件や詳細について質問している
- 辞退: お断り、条件が合わない
- 保留: 検討中

やりとり:
{conv_text}

カテゴリ名だけを回答してください（例: 面談設定済）"""

    try:
        response = genai_model.generate_content(prompt)
        cat = response.text.strip()
        # Validate against known categories
        for key in REPLY_CATEGORIES:
            if key in cat:
                return key
        return cat[:10]  # Fallback: first 10 chars
    except Exception as e:
        print(f"    AI classify error: {e}")
        return classify_reply_simple(messages)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("yaml_path", help="Path to conversations YAML file")
    parser.add_argument("--company", help="Override company ID (e.g. ark-visiting-nurse)")
    parser.add_argument("--classify", action="store_true", help="Use Gemini for reply classification")
    args = parser.parse_args()

    # Read YAML
    with open(args.yaml_path) as f:
        docs = list(yaml.safe_load_all(f))
    print(f"Loaded {len(docs)} conversations from {args.yaml_path}")

    # Setup Sheets API
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=credentials)

    # Setup Gemini if classifying
    genai_model = None
    if args.classify:
        from config import GEMINI_API_KEY, GEMINI_MODEL
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        genai_model = genai.GenerativeModel(model_name=GEMINI_MODEL)
        print(f"Using Gemini ({GEMINI_MODEL}) for classification")

    # Group conversations by company (with optional override)
    by_company = {}
    for doc in docs:
        company = args.company or doc.get("company", "")
        if company not in by_company:
            by_company[company] = []
        by_company[company].append(doc)

    total_updated = 0
    total_added = 0

    for company_id, convos in by_company.items():
        display = COMPANY_DISPLAY_NAMES.get(company_id, company_id)
        sheet_name = f"送信_{display}"

        # Read existing sheet
        try:
            result = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{sheet_name}'!A:O",
            ).execute()
            all_rows = result.get("values", [])
        except Exception as e:
            print(f"  {sheet_name}: sheet not found, skipping ({e})")
            continue

        if not all_rows:
            print(f"  {sheet_name}: empty sheet, skipping")
            continue

        headers = all_rows[0]
        col = {h: i for i, h in enumerate(headers)}

        # Build member_id → row_index map
        member_rows = {}
        for idx, row in enumerate(all_rows[1:], start=2):  # 1-indexed, skip header
            if len(row) > col.get("会員番号", 0):
                mid = row[col["会員番号"]]
                if mid:
                    member_rows[mid] = idx

        updates = []
        new_rows = []

        for doc in convos:
            member_id = doc.get("member_id", "")
            messages = doc.get("messages", [])
            candidate_msgs = [m for m in messages if m.get("role") == "candidate"]

            if not candidate_msgs:
                continue

            # First candidate reply date
            reply_date = candidate_msgs[0].get("date", "")

            # Classify
            if genai_model:
                category = classify_reply_ai(messages, genai_model)
            else:
                category = classify_reply_simple(messages)

            # Age bucket from YAML
            yaml_age = age_bucket(doc.get("candidate_age"))

            if member_id in member_rows:
                # Update existing row
                row_idx = member_rows[member_id]
                row = all_rows[row_idx - 1] if row_idx - 1 < len(all_rows) else []
                # Pad to full width
                while len(row) < len(headers):
                    row.append("")

                row[col["返信"]] = "有"
                row[col["返信日"]] = reply_date
                row[col["返信カテゴリ"]] = category

                # Fill missing age
                if col.get("年齢層") is not None and not row[col["年齢層"]] and yaml_age:
                    row[col["年齢層"]] = yaml_age

                updates.append((row_idx, row))
            else:
                # New row (sent via CSV or before API tracking)
                from datetime import datetime
                started = doc.get("started", "")
                weekday = ""
                time_slot = ""
                if started:
                    try:
                        dt = datetime.strptime(started, "%Y-%m-%d")
                        weekday = WEEKDAY_NAMES[dt.weekday()]
                    except Exception:
                        pass

                new_row = [
                    started,        # 日時 (use started date)
                    member_id,
                    "",             # テンプレート種別
                    "",             # 生成パス
                    "",             # パターン
                    yaml_age,       # 年齢層
                    "",             # 資格
                    "",             # 経験区分
                    "",             # 希望雇用形態
                    "",             # 就業状況
                    weekday,        # 曜日
                    time_slot,      # 時間帯
                    "有",           # 返信
                    reply_date,     # 返信日
                    category,       # 返信カテゴリ
                ]
                new_rows.append(new_row)

        # Write updates
        for row_idx, row in updates:
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{sheet_name}'!A{row_idx}",
                valueInputOption="RAW",
                body={"values": [row]},
            ).execute()

        # Append new rows
        if new_rows:
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{sheet_name}'!A:O",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": new_rows},
            ).execute()

        print(f"  {sheet_name}: updated {len(updates)}, added {len(new_rows)} (categories: {', '.join(set(category for _, _, category in [(0, 0, classify_reply_simple(d.get('messages', []))) for d in convos if any(m.get('role') == 'candidate' for m in d.get('messages', []))]))})")
        total_updated += len(updates)
        total_added += len(new_rows)

    print(f"\nDone. Updated: {total_updated}, Added: {total_added}")


if __name__ == "__main__":
    main()
