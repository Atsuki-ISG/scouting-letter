#!/usr/bin/env python3
"""Push ARK templates from local templates.md to Sheets (6 rows)."""
import re
import sys
import time
import requests

API_BASE = "https://scout-api-1080076995871.asia-northeast1.run.app/api/v1/admin"
HEADERS = {"X-API-Key": "anycare", "Content-Type": "application/json"}

TEMPLATES_MD = "/Users/aki/scouting-letter/companies/ark-visiting-nurse/templates.md"

# (heading, row_index)
MAPPING = [
    ("## テンプレート", 22),                       # パート初回
    ("## 再送スカウト テンプレート", 23),           # パート再送
    ("## 正社員テンプレート", 24),                  # 正社員初回
    ("## 正社員 再送テンプレート", 25),             # 正社員再送
    ("## お気に入りテンプレート（パート）", 26),    # お気に入りパート
    ("## お気に入りテンプレート（正社員）", 27),    # お気に入り正社員
]


def extract_body(content, heading):
    idx = content.find(heading)
    if idx < 0:
        raise ValueError(f"Not found: {heading}")
    after = content[idx + len(heading):]
    open_m = re.search(r"\n```\n", after)
    body_start = open_m.end()
    close_idx = after.find("\n```", body_start)
    return after[body_start:close_idx]


def main():
    with open(TEMPLATES_MD, encoding="utf-8") as f:
        content = f.read()

    for heading, row in MAPPING:
        body = extract_body(content, heading)
        url = f"{API_BASE}/templates/{row}"
        try:
            r = requests.put(url, json={"body": body}, headers=HEADERS, timeout=30)
            r.raise_for_status()
            print(f"  row={row:3}: OK (len={len(body)})")
        except Exception as e:
            print(f"  row={row:3}: FAIL {e}")
            if hasattr(r, "text"):
                print(f"    {r.text[:200]}")
        time.sleep(10)  # Rate limit pacing


if __name__ == "__main__":
    main()
