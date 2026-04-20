"""Seed the プロンプト sheet with baseline rule sections (global).

Adds 3 new section_types (behavior_guidelines / ng_patterns / writing_style)
as global (company="") entries, based on rules that appear consistently
across all companies' recipes.md. Company-specific tweaks are expected to
land later via the fix_feedback → improvement proposals loop.

Idempotent: fetches existing prompt rows first and skips any
(company, section_type, job_category, content_first_80_chars) tuple that
already exists. Safe to re-run.

Usage:
    API_KEY=xxx python3 server/scripts/seed_rule_sections.py [--dry-run] [--base-url URL]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

DEFAULT_BASE_URL = "https://scout-api-1080076995871.asia-northeast1.run.app"
JST = timezone(timedelta(hours=9))


def _request(base_url: str, api_key: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        text = resp.read().decode("utf-8")
        return json.loads(text) if text else {}


BASELINE_RULES: list[dict] = [
    # ----- behavior_guidelines -----
    {
        "section_type": "behavior_guidelines",
        "order": "4",
        "content": (
            "- 丁寧で誠実なトーン。堅くなりすぎない自然な敬語を使う\n"
            "- 対等でポジティブな評価。経験豊富な方には専門性に注目、経験が浅い方にはポテンシャルや強みに焦点を当てる\n"
            "- 候補者の事実（保有資格・経験年数）にフォーカスし、憶測や状況説明は書かない\n"
            "- 相手へのオファー主体で書く。送り手の感情（「ご一緒したい」「想いを強く感じ」等）は前に出さない\n"
            "- こだわり条件は参考程度。資格・経験で接点が作れるなら言及不要"
        ),
    },
    # ----- ng_patterns -----
    {
        "section_type": "ng_patterns",
        "order": "5",
        "content": (
            "- 年齢・世代への言及禁止（「〇代」「若手」「ベテラン」「シニア」等は使わない）\n"
            "- 上から目線になる表現を避ける（「安心してください」「フォローします」「基礎を固めてこられた」等は不可）\n"
            "- 憶測で書かない（「〜されたいのですね」「長く続けているはず」等）\n"
            "- 不要な前置きを書かない（「現在離職中とのこと」「新たな環境でとお考えの〜」等）\n"
            "- 居住地に言及する場合は広域表現に留める（「〇〇区」→「横浜市内」「神奈川県内」）\n"
            "- 堅苦しい敬語禁止（「拝察いたします」「敬意を表します」「お持ちとのこと」等）\n"
            "- 候補者の氏名・名前は絶対に含めない。「〇〇様」等の呼びかけも不要\n"
            "- 「感銘を受ける」は経験そのものに使用しない。代替: 「魅力を感じました」「注目しました」"
        ),
    },
    # ----- writing_style -----
    {
        "section_type": "writing_style",
        "order": "6",
        "content": (
            "- ですます調で統一する\n"
            "- 句点で終わる完成した2〜3文で書く。体言止めや「〜とのこと、」で文を切らない\n"
            "- 文字数: 初回は約100文字、再送は120〜150文字を目安に\n"
            "- 経験年数の記載ルール:\n"
            "  - 1〜2年: 書かない（伝えるとマイナス印象）\n"
            "  - 3年: 30代前半以下なら書く、30代後半以上なら書かない\n"
            "  - 4年以上: 書く\n"
            "- テンプレート冒頭に「ご経歴を拝見し」がある場合、パーソナライズ文の書き出しは「拝見し」以外で始める\n"
            "- 地理情報（勤務地・訪問範囲）はテンプレート本文に記載されるため、パーソナライズ文では言及しない"
        ),
    },
]


def fetch_existing(base_url: str, api_key: str) -> set[tuple[str, str, str, str]]:
    """Return set of existing (company, section_type, job_category, content_prefix)."""
    try:
        result = _request(base_url, api_key, "GET", "/api/v1/admin/prompts")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return set()
        raise
    keys: set[tuple[str, str, str, str]] = set()
    for row in result.get("rows", []):
        keys.add((
            (row.get("company") or "").strip(),
            (row.get("section_type") or "").strip(),
            (row.get("job_category") or "").strip(),
            (row.get("content") or "").strip()[:80],
        ))
    return keys


def post_prompt(base_url: str, api_key: str, payload: dict) -> dict:
    return _request(base_url, api_key, "POST", "/api/v1/admin/prompts", body=payload)


def build_payloads() -> list[dict]:
    payloads: list[dict] = []
    for rule in BASELINE_RULES:
        payloads.append({
            "company": "",          # global baseline
            "section_type": rule["section_type"],
            "job_category": "",     # rule-system sections are job-category-agnostic
            "order": rule["order"],
            "content": rule["content"],
        })
    return payloads


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("BASE_URL", DEFAULT_BASE_URL),
    )
    args = parser.parse_args()

    api_key = os.environ.get("API_KEY", "")
    if not api_key and not args.dry_run:
        print("ERROR: Set API_KEY env var", file=sys.stderr)
        sys.exit(1)

    payloads = build_payloads()
    print(f"Built {len(payloads)} baseline rule payloads")

    existing: set[tuple[str, str, str, str]] = set()
    if api_key:
        try:
            existing = fetch_existing(args.base_url, api_key)
            print(f"Found {len(existing)} existing prompt rows on {args.base_url}")
        except Exception as e:
            print(f"  (could not fetch existing rows: {e})")

    new_payloads = [
        p for p in payloads
        if (p["company"], p["section_type"], p["job_category"], p["content"][:80]) not in existing
    ]
    print(f"Would POST {len(new_payloads)} new rows (skipping {len(payloads) - len(new_payloads)} duplicates)")

    if args.dry_run:
        for p in new_payloads:
            print(f"  [DRY] {p['section_type']} (order={p['order']}) {p['content'][:60]}...")
        return

    if not new_payloads:
        print("Nothing to do. Exiting.")
        return

    for p in new_payloads:
        try:
            post_prompt(args.base_url, api_key, p)
            print(f"  ✓ added {p['section_type']}")
        except Exception as e:
            print(f"  ✗ FAILED {p['section_type']}: {e}", file=sys.stderr)

    print("Done.")


if __name__ == "__main__":
    main()
