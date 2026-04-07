"""Seed the 職種キーワード sheet with the legacy static dictionary.

Reads the static `_QUALIFICATION_MAP` and `_LEGACY_DESIRED_FALLBACK` from
`pipeline.job_category_resolver` and POSTs each entry to the
`/api/v1/admin/job_category_keywords` admin endpoint.

Idempotent: fetches existing rows first and skips any
(company, job_category, keyword, source_fields) tuple that already exists.
Safe to re-run.

Usage:
    python3 server/scripts/migrate_keywords_to_sheets.py [--dry-run] [--base-url URL]

Requires API_KEY env var.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

# Make the server package importable when run from the repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.job_category_resolver import (  # noqa: E402
    _QUALIFICATION_MAP,
    _LEGACY_DESIRED_FALLBACK,
)

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
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8")
        return json.loads(text) if text else {}


def fetch_existing(base_url: str, api_key: str) -> set[tuple[str, str, str, str]]:
    """Return the set of existing (company, job_category, keyword, source_fields)
    tuples already in the sheet. Used to skip duplicates on re-run.

    Returns an empty set if the sheet doesn't exist yet (first run).
    """
    try:
        result = _request(base_url, api_key, "GET", "/api/v1/admin/job_category_keywords")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return set()
        raise
    keys: set[tuple[str, str, str, str]] = set()
    for row in result.get("rows", []):
        keys.add((
            (row.get("company") or "").strip(),
            (row.get("job_category") or "").strip(),
            (row.get("keyword") or "").strip(),
            (row.get("source_fields") or "").strip(),
        ))
    return keys


def post_keyword(base_url: str, api_key: str, payload: dict) -> dict:
    return _request(
        base_url, api_key, "POST", "/api/v1/admin/job_category_keywords", body=payload
    )


def build_payloads() -> list[dict]:
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    payloads: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    # Qualification keywords
    for keyword, category in _QUALIFICATION_MAP:
        key = ("", category, keyword)
        if key in seen:
            continue
        seen.add(key)
        payloads.append({
            "company": "",  # global
            "job_category": category,
            "keyword": keyword,
            "source_fields": "qualification",
            "weight": "1",
            "enabled": "TRUE",
            "added_at": now,
            "added_by": "migration",
            "note": "Migrated from _QUALIFICATION_MAP",
        })

    # Free-text keywords (desired_job + experience + self_pr)
    for keyword, category in _LEGACY_DESIRED_FALLBACK:
        key = ("", category, keyword)
        if key in seen:
            continue
        seen.add(key)
        payloads.append({
            "company": "",
            "job_category": category,
            "keyword": keyword,
            "source_fields": "desired,experience,pr",
            "weight": "1",
            "enabled": "TRUE",
            "added_at": now,
            "added_by": "migration",
            "note": "Migrated from _LEGACY_DESIRED_FALLBACK",
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
    print(f"Built {len(payloads)} candidate rows from static dictionary")

    if args.dry_run:
        # Try to fetch existing rows for the dry-run preview, but tolerate
        # missing API key / unreachable server.
        existing: set[tuple[str, str, str, str]] = set()
        if api_key:
            try:
                existing = fetch_existing(args.base_url, api_key)
                print(f"Found {len(existing)} existing rows on {args.base_url}")
            except Exception as e:
                print(f"  (could not fetch existing rows: {e})")
        new_payloads = [
            p for p in payloads
            if (p["company"], p["job_category"], p["keyword"], p["source_fields"]) not in existing
        ]
        print(f"Would POST {len(new_payloads)} new rows (skipped {len(payloads) - len(new_payloads)} duplicates)")
        for p in new_payloads[:5]:
            print(f"  + {p['job_category']}/{p['keyword']} ({p['source_fields']})")
        if len(new_payloads) > 5:
            print(f"  ... and {len(new_payloads) - 5} more")
        return

    existing = fetch_existing(args.base_url, api_key)
    print(f"Found {len(existing)} existing rows; will skip duplicates")

    new_payloads = [
        p for p in payloads
        if (p["company"], p["job_category"], p["keyword"], p["source_fields"]) not in existing
    ]
    skipped = len(payloads) - len(new_payloads)
    print(f"Posting {len(new_payloads)} new rows (skipped {skipped} duplicates)")

    success = 0
    for p in new_payloads:
        try:
            post_keyword(args.base_url, api_key, p)
            success += 1
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(
                f"  FAIL {p['job_category']}/{p['keyword']}: {e.code} {body}",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"  FAIL {p['job_category']}/{p['keyword']}: {e}", file=sys.stderr)

    print(f"\n  {success}/{len(new_payloads)} new keywords inserted, {skipped} duplicates skipped")


if __name__ == "__main__":
    main()
