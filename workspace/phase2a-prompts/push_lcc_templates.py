#!/usr/bin/env python3
"""Push LCC templates from local templates.md to Sheets (18 rows, excluding medical office)."""
import re
import sys
import os
import json
import requests

API_BASE = "https://scout-api-1080076995871.asia-northeast1.run.app/api/v1/admin"
API_KEY = "anycare"
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

TEMPLATES_MD = "/Users/aki/scouting-letter/companies/lcc-visiting-nurse/templates.md"

# Local section heading -> Sheets row_index mapping
# Sheets: LCC templates rows 37-57 (49, 50, 57 are medical office -> skip)
MAPPING = [
    # (local_section_heading, sheets_row_index)
    ("## 看護師正社員 初回テンプレート", 37),
    ("## 看護師正社員 再送テンプレート", 38),
    ("## 看護師パート 初回テンプレート", 39),
    ("## 看護師パート 再送テンプレート", 40),
    ("## リハビリ職（PT）正社員 初回テンプレート", 41),
    ("## リハビリ職（PT）正社員 再送テンプレート", 42),
    ("## リハビリ職（PT）パート 初回テンプレート", 43),
    ("## リハビリ職（PT）パート 再送テンプレート", 44),
    ("## リハビリ職（ST）正社員 初回テンプレート", 45),
    ("## リハビリ職（ST）正社員 再送テンプレート", 46),
    ("## リハビリ職（ST）パート 初回テンプレート", 47),
    ("## リハビリ職（ST）パート 再送テンプレート", 48),
    # medical office rows 49, 50 SKIP
    ("### 正社員_お気に入り (看護師) — row 34", 51),
    ("### パート_お気に入り (看護師) — row 35", 52),
    ("### 正社員_お気に入り (理学療法士(PT)) — row 36", 53),
    ("### パート_お気に入り (理学療法士(PT)) — row 37", 54),
    ("### 正社員_お気に入り (言語聴覚士(ST)) — row 38", 55),
    ("### パート_お気に入り (言語聴覚士(ST)) — row 39", 56),
    # medical office row 57 SKIP
]


def extract_body(content: str, heading: str) -> str:
    """Extract the body content inside ``` after the given heading."""
    # Find the heading
    idx = content.find(heading)
    if idx < 0:
        raise ValueError(f"Heading not found: {heading}")
    # After heading, find the first ``` block
    after = content[idx + len(heading):]
    # Find opening ```
    open_match = re.search(r"\n```\n", after)
    if not open_match:
        raise ValueError(f"No opening ``` after: {heading}")
    body_start = open_match.end()
    # Find closing ```
    close_idx = after.find("\n```", body_start)
    if close_idx < 0:
        raise ValueError(f"No closing ``` after: {heading}")
    return after[body_start:close_idx]


def main():
    dry_run = "--dry-run" in sys.argv

    with open(TEMPLATES_MD, encoding="utf-8") as f:
        content = f.read()

    updates = []
    for heading, row_index in MAPPING:
        try:
            body = extract_body(content, heading)
            updates.append({
                "heading": heading,
                "row_index": row_index,
                "body": body,
                "body_preview": body[:80].replace("\n", "\\n"),
                "body_len": len(body),
            })
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    # Preview
    print(f"=== {len(updates)} templates to update ===\n")
    for u in updates:
        print(f"row={u['row_index']:3} len={u['body_len']:4} | {u['heading'][:60]}")
        print(f"        preview: {u['body_preview']}\n")

    if dry_run:
        print("[DRY RUN] No changes made")
        return

    # Confirm
    print(f"\n--- Proceeding to update {len(updates)} rows in LCC templates ---\n")

    # Execute updates (use PUT — matches server_admin.py update command)
    results = []
    for u in updates:
        url = f"{API_BASE}/templates/{u['row_index']}"
        payload = {"body": u["body"]}
        try:
            resp = requests.put(url, json=payload, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            results.append((u['row_index'], "OK", resp.json() if resp.text else {}))
            print(f"  row={u['row_index']:3}: OK (body_len={u['body_len']})")
        except requests.RequestException as e:
            results.append((u['row_index'], f"ERROR: {e}", None))
            print(f"  row={u['row_index']:3}: ERROR: {e}")

    ok_count = sum(1 for _, s, _ in results if s.startswith("OK"))
    print(f"\n=== {ok_count}/{len(updates)} updates succeeded ===")
    if ok_count < len(updates):
        print("\nFailed rows:")
        for row, status, _ in results:
            if not status.startswith("OK"):
                print(f"  row={row}: {status}")


if __name__ == "__main__":
    main()
