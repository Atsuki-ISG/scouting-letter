"""Google Sheets から `ichigo-care-home` 関連の行を一括削除するスクリプト。

Cloud Run 側の `POST /admin/purge_company` を叩いて削除する。サーバー側で
`delete_rows_bulk` を使って batchUpdate 1 回で削除するため高速。

使い方:
    # dry-run
    API_KEY=anycare python3 server/scripts/delete_ichigo_care_home.py

    # 実行
    API_KEY=anycare python3 server/scripts/delete_ichigo_care_home.py --execute
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

TARGET_COMPANY = "ichigo-care-home"
DEFAULT_API_BASE = "https://scout-api-1080076995871.asia-northeast1.run.app/api/v1/admin"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--api-base", default=os.environ.get("API_BASE", DEFAULT_API_BASE))
    parser.add_argument("--company", default=TARGET_COMPANY)
    args = parser.parse_args()

    api_key = os.environ.get("API_KEY", "").strip()
    if not api_key:
        print("ERROR: API_KEY 環境変数が必要", file=sys.stderr)
        return 1

    url = f"{args.api_base}/purge_company"
    body = {"company_id": args.company, "dry_run": not args.execute}
    req = urllib.request.Request(
        url,
        method="POST",
        headers={"X-API-Key": api_key, "Content-Type": "application/json"},
        data=json.dumps(body).encode(),
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()[:500]}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Request failed: {e}", file=sys.stderr)
        return 1

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"=== {mode} ===")
    print(f"対象会社: {data.get('company_id')}\n")
    total = 0
    for r in data.get("results", []):
        sheet = r.get("sheet")
        n = r.get("deleted", 0)
        extra = ""
        if r.get("error"):
            extra = f" ERROR: {r['error']}"
        elif r.get("skip"):
            extra = f" (skip: {r['skip']})"
        print(f"[{sheet}] {n} 行{extra}")
        total += n
    print(f"\n{'削除' if args.execute else 'dry-run 対象'}: 合計 {total} 行")
    if not args.execute:
        print("実行するには --execute を付けて再度実行してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
