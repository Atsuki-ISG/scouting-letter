#!/usr/bin/env python3
"""Seed the ナレッジプール sheet with initial rules from learnings.md.

Usage:
    cd server
    python scripts/seed_knowledge_pool.py

Requires SPREADSHEET_ID env var and GCP credentials.
Rules are inserted with status=approved (already validated knowledge).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")

SHEET_NAME = "ナレッジプール"
HEADERS = ["id", "company", "category", "rule", "source", "status", "created_at"]

# --- Initial knowledge rules extracted from learnings.md ---

RULES = [
    # expression: NG表現
    {
        "category": "expression",
        "rule": "「感銘を受ける」は経験への使用禁止。代替: 「心強く拝見しました」「注目しました」",
        "source": "learnings.md 2026-02-10",
    },
    {
        "category": "expression",
        "rule": "「お持ちとのこと」はAI臭い敬語。使わない",
        "source": "learnings.md 表現ルール",
    },
    {
        "category": "expression",
        "rule": "「〜のことかと存じます」は過度な敬語。使わない",
        "source": "learnings.md 表現ルール",
    },
    {
        "category": "expression",
        "rule": "送り手の感情を主語にした表現（「ご一緒したい」「想いを強く感じ」）は不自然。候補者へのオファーを主語にする",
        "source": "learnings.md 2026-02-10",
    },

    # qualification: 資格言及ルール
    {
        "category": "qualification",
        "rule": "求人職種と同一の資格（看護師求人で「看護師の資格をお持ち」等）への言及は不要。保有前提で送っている",
        "source": "learnings.md 2026-03-25",
    },
    {
        "category": "qualification",
        "rule": "複数資格（看護師+保健師等）への言及はOK。追加資格は差別化ポイント",
        "source": "learnings.md 2026-03-25",
    },
    {
        "category": "qualification",
        "rule": "経験年数の言及: 1-2年は書かない。3年は30代前半以下のみ。4年以上は書く。年数を書かない場合は研修制度の充実に焦点",
        "source": "learnings.md 2026-02-13",
    },

    # profile_handling: 候補者タイプ別対応
    {
        "category": "profile_handling",
        "rule": "情報が少ない≠経験が浅い。就業中なら経験者前提で書く。年齢からキャリアを推測し、教育体制訴求は上から目線になる場合がある",
        "source": "learnings.md 2026-03-06",
    },
    {
        "category": "profile_handling",
        "rule": "教育体制・研修制度の訴求は、経験が浅くブランクがある候補者にのみ使う。経験者には専門性への期待や即戦力としての評価をストレートに伝える",
        "source": "learnings.md 2026-03-06",
    },
    {
        "category": "profile_handling",
        "rule": "強力なキャリア（10年以上等）がある場合は、地理的接点より専門的接点を優先。期待値をストレートに伝える",
        "source": "learnings.md 2026-02-10",
    },
    {
        "category": "profile_handling",
        "rule": "こだわり条件（ターミナルケア希望等）は参考程度。資格・経験で十分な接点があればこだわり条件への言及は不要",
        "source": "learnings.md 2026-02-13",
    },

    # template_tip: テンプレート・構成のコツ
    {
        "category": "template_tip",
        "rule": "パーソナライズ文に勤務地・訪問範囲の情報を入れない。地理情報はテンプレート固定セクションに記載済み",
        "source": "learnings.md 2026-02-13",
    },
    {
        "category": "template_tip",
        "rule": "テンプレートに「拝見し」がある場合、パーソナライズ文で「拝見し」を使わない。「注目しました」「関心を持ち」等の別表現を使う",
        "source": "learnings.md 2026-03-06",
    },
    {
        "category": "template_tip",
        "rule": "教育制度への言及は当該会社・当該職種のテンプレートに記載された内容のみ使用。他社・他職種の制度を混ぜない",
        "source": "learnings.md 2026-03-06",
    },

    # tone: トーン
    {
        "category": "tone",
        "rule": "敬語の重ね使いを避ける。自然な日本語で書く",
        "source": "learnings.md 表現ルール",
    },
    {
        "category": "tone",
        "rule": "地理的要素のみに頼らず、会社の強み（教育体制、成長環境）を前面に出す",
        "source": "learnings.md 2026-02-10",
    },
]


def main():
    from db.sheets_writer import sheets_writer

    sheets_writer.ensure_sheet_exists(SHEET_NAME, HEADERS)

    rows = []
    base_id = int(datetime.now(JST).timestamp())
    for i, rule in enumerate(RULES):
        rows.append([
            str(base_id + i),           # id
            "",                          # company (empty = global)
            rule["category"],            # category
            rule["rule"],                # rule
            rule["source"],              # source
            "approved",                  # status (already validated)
            NOW,                         # created_at
        ])

    sheets_writer.append_rows(SHEET_NAME, rows)
    print(f"✓ {len(rows)}件のナレッジルールを「{SHEET_NAME}」シートに投入しました")


if __name__ == "__main__":
    main()
