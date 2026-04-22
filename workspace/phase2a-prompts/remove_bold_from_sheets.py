#!/usr/bin/env python3
"""Remove ** markdown bold from Sheets templates bodies.

JM スカウト本文では **太字** が literal `**xxx**` で表示されてしまうため、
テンプレ本文から `**` を削除する。
"""
import re
import sys
import time
import requests

API_BASE = "https://scout-api-1080076995871.asia-northeast1.run.app/api/v1/admin"
API_KEY = "anycare"
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}


def put_with_retry(url, payload):
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


def get_with_retry(url):
    last_err = None
    for attempt in range(4):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < 3:
                wait = 15 * (attempt + 1)
                print(f"  [GET retry {attempt+1}/3] {type(e).__name__} — wait {wait}s", flush=True)
                time.sleep(wait)
                continue
            raise
    raise last_err


def main():
    dry_run = "--dry-run" in sys.argv

    data = get_with_retry(f"{API_BASE}/templates")

    updates = []
    for r in data.get("rows", []):
        body = r.get("body", "")
        if "**" not in body:
            continue
        new_body = re.sub(r"\*\*(.+?)\*\*", r"\1", body, flags=re.DOTALL)
        cnt = (body.count("**") - new_body.count("**")) // 2
        updates.append({
            "row_index": r["_row_index"],
            "company": r.get("company", ""),
            "type": r.get("type", ""),
            "body": new_body,
            "count": cnt,
        })

    print(f"=== {len(updates)} templates to clean ===\n", flush=True)
    for u in updates:
        print(f"  row={u['row_index']:3}  {u['company']:25}  {u['type']:20}  removing {u['count']} ** pairs", flush=True)

    if dry_run:
        print("\n[DRY RUN] No changes", flush=True)
        return

    print(f"\n--- Cleaning {len(updates)} rows with 11s pacing ---\n", flush=True)
    ok = 0
    for i, u in enumerate(updates, 1):
        url = f"{API_BASE}/templates/{u['row_index']}"
        try:
            put_with_retry(url, {"body": u["body"], "_change_reason": "Remove ** markdown bold (JM不対応)"})
            ok += 1
            print(f"  [{i}/{len(updates)}] row={u['row_index']:3}: OK", flush=True)
        except Exception as e:
            print(f"  [{i}/{len(updates)}] row={u['row_index']:3}: ERROR: {e}", flush=True)
        if i < len(updates):
            time.sleep(11)

    print(f"\n=== {ok}/{len(updates)} cleaned ===", flush=True)


if __name__ == "__main__":
    main()
