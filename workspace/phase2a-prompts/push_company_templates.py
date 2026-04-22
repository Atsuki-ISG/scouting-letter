#!/usr/bin/env python3
"""Push improved templates from workspace/phase2a-prompts/template-improvements/<company>-templates.md
to Sheets via Cloud Run admin API.

Usage:
  push_company_templates.py <company> [--dry-run]

Companies:
  ark-visiting-nurse / chigasaki-tokushukai / an-visiting-nurse /
  ichigo-visiting-nurse / daiwa-house-ls / nomura-hospital
"""
import os
import re
import sys
import time
import requests

API_BASE = "https://scout-api-1080076995871.asia-northeast1.run.app/api/v1/admin"
API_KEY = "anycare"
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

TEMPLATES_DIR = "/Users/aki/scouting-letter/workspace/phase2a-prompts/template-improvements"

# (company) → {section_heading → row_index}
MAPPINGS = {
    "ark-visiting-nurse": {
        "## 看護師パート 初回テンプレート": 22,
        "## 看護師パート 再送テンプレート": 23,
        "## 看護師正社員 初回テンプレート": 24,
        "## 看護師正社員 再送テンプレート": 25,
        "## お気に入りテンプレート（パート）": 26,
        "## お気に入りテンプレート（正社員）": 27,
    },
    "chigasaki-tokushukai": {
        "## 看護師正職員 初回テンプレート": 28,
        "## 看護師正職員 再送テンプレート": 29,
        "## お気に入りテンプレート": 30,
    },
    "an-visiting-nurse": {
        "## 看護師パート 初回テンプレート": 2,
        "## 看護師パート 再送テンプレート": 3,
        "## 看護師正社員 初回テンプレート": 4,
        "## 看護師正社員 再送テンプレート": 5,
        "### 看護師パート お気に入り": 6,
        "### 看護師正社員 お気に入り": 7,
        "## 相談支援専門員パート 初回テンプレート": 8,
        "## 相談支援専門員パート 再送テンプレート": 9,
        "## 作業療法士正社員 初回テンプレート": 10,
        "## 作業療法士正社員 再送テンプレート": 11,
        "## 理学療法士正社員 初回テンプレート": 12,
        "## 理学療法士正社員 再送テンプレート": 13,
        "### 作業療法士正社員 お気に入り": 14,
        "### 理学療法士正社員 お気に入り": 15,
        "## 作業療法士パート 初回テンプレート": 16,
        "## 作業療法士パート 再送テンプレート": 17,
        # row 18 (rehab_ot パート_お気に入り): improved 未作成、既存 Sheets そのまま
        "## 理学療法士パート 初回テンプレート": 19,
        "## 理学療法士パート 再送テンプレート": 20,
        # row 21 (rehab_pt パート_お気に入り): improved 未作成、既存 Sheets そのまま
    },
    "ichigo-visiting-nurse": {
        # Sheets has 3 rows (34,35,36) - all nurse 正社員. 改善版 6本だが Sheets は正社員のみ
        "## 看護師正社員 初回テンプレート": 34,
        "## 看護師正社員 再送テンプレート": 35,
        "### 看護師正社員 お気に入り": 36,
    },
    "daiwa-house-ls": {
        "## 入居相談員 正職員 初回テンプレート": 31,
        "## 入居相談員 正職員 再送テンプレート": 32,
        "### 入居相談員 お気に入り": 33,
    },
    "nomura-hospital": {
        # 改善版は 正社員 のみ。パート (rows 58,59,62,64,65,66) は既存 Sheets そのまま。
        "## 病棟看護師 初回テンプレート": 60,           # 看護師 正社員_初回
        "## 病棟看護師 再送テンプレート": 61,           # 看護師 正社員_再送
        "## 病棟看護師 お気に入り": 63,                # 看護師 正社員_お気に入り
        "## 管理栄養士 初回テンプレート": 67,          # dietitian 正社員_初回
        "## 管理栄養士 再送テンプレート": 68,          # dietitian 正社員_再送
        "## 管理栄養士 お気に入り": 69,               # dietitian 正社員_お気に入り
    },
}


def extract_body(content: str, heading: str) -> str:
    """Extract body from the ``` block after heading.

    For お気に入り templates (件名＋本文 two blocks), scan to the "本文:" marker
    within the same section to get the body block (not subject).
    """
    idx = content.find(heading)
    if idx < 0:
        raise ValueError(f"Heading not found: {heading}")
    after = content[idx + len(heading):]

    # Restrict search to current section (stop at next heading)
    next_heading = re.search(r"\n##+ ", after)
    if next_heading:
        section = after[:next_heading.start()]
    else:
        section = after

    # For お気に入り: use "本文:" marker to skip over subject block
    if "お気に入り" in heading:
        honbun_idx = section.find("\n本文:\n")
        if honbun_idx >= 0:
            section = section[honbun_idx + len("\n本文:\n"):]

    open_match = re.search(r"```\n", section)
    if not open_match:
        raise ValueError(f"No opening ``` after: {heading}")
    body_start = open_match.end()
    close_idx = section.find("\n```", body_start)
    if close_idx < 0:
        raise ValueError(f"No closing ``` after: {heading}")
    return section[body_start:close_idx]


def put_with_retry(url: str, payload: dict) -> requests.Response:
    last_err = None
    for attempt in range(4):
        try:
            resp = requests.put(url, json=payload, headers=HEADERS, timeout=60)
            resp.raise_for_status()
            return resp
        except requests.exceptions.HTTPError as e:
            last_err = e
            status = getattr(e.response, "status_code", None)
            if status in (429, 500, 502, 503, 504) and attempt < 3:
                wait = 15 * (attempt + 1)
                print(f"    [retry {attempt+1}/3] HTTP {status} — wait {wait}s", flush=True)
                time.sleep(wait)
                continue
            raise
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < 3:
                wait = 15 * (attempt + 1)
                print(f"    [retry {attempt+1}/3] {type(e).__name__} — wait {wait}s", flush=True)
                time.sleep(wait)
                continue
            raise
    raise last_err


def main():
    if len(sys.argv) < 2:
        print("Usage: push_company_templates.py <company> [--dry-run]")
        sys.exit(1)

    company = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    if company not in MAPPINGS:
        print(f"ERROR: Unknown company: {company}")
        print(f"Available: {', '.join(MAPPINGS)}")
        sys.exit(1)

    mapping = MAPPINGS[company]
    templates_path = f"{TEMPLATES_DIR}/{company}-templates.md"

    if not os.path.isfile(templates_path):
        print(f"ERROR: Not found: {templates_path}")
        sys.exit(1)

    with open(templates_path, encoding="utf-8") as f:
        content = f.read()

    # Extract bodies
    updates = []
    for heading, row_index in mapping.items():
        try:
            body = extract_body(content, heading)
            updates.append({
                "heading": heading,
                "row_index": row_index,
                "body": body,
                "body_len": len(body),
                "preview": body[:60].replace("\n", "\\n"),
            })
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    print(f"=== {company}: {len(updates)} templates to update ===\n", flush=True)
    for u in updates:
        print(f"  row={u['row_index']:3}  len={u['body_len']:4}  {u['heading'][:50]}", flush=True)
        print(f"        preview: {u['preview']}", flush=True)
    print(flush=True)

    if dry_run:
        print("[DRY RUN] No changes made", flush=True)
        return

    print(f"--- Pushing {len(updates)} rows with 11s pacing ---\n", flush=True)

    results = []
    for i, u in enumerate(updates, 1):
        url = f"{API_BASE}/templates/{u['row_index']}"
        payload = {"body": u["body"], "_change_reason": "Phase 2-C-1 お手紙トーン＋LCC水準の構造再編"}
        try:
            resp = put_with_retry(url, payload)
            results.append((u['row_index'], "OK"))
            print(f"  [{i}/{len(updates)}] row={u['row_index']:3}: OK (len={u['body_len']})", flush=True)
        except requests.RequestException as e:
            results.append((u['row_index'], f"ERROR: {e}"))
            print(f"  [{i}/{len(updates)}] row={u['row_index']:3}: ERROR: {e}", flush=True)

        # pacing (skip after last)
        if i < len(updates):
            time.sleep(11)

    ok_count = sum(1 for _, s in results if s == "OK")
    print(f"\n=== {ok_count}/{len(updates)} pushed ===", flush=True)
    if ok_count < len(updates):
        print("\nFailed rows:", flush=True)
        for row, status in results:
            if status != "OK":
                print(f"  row={row}: {status}", flush=True)


if __name__ == "__main__":
    main()
