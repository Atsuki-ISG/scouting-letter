"""Migrate company profile.md files to the プロフィール sheet via Admin API.

Usage:
    python3 server/scripts/migrate_profiles_to_sheets.py [--dry-run] [--base-url URL]

Reads each company's profile.md and POSTs to /api/v1/admin/profiles.
Requires API_KEY env var (same as ADMIN_PASSWORD on Cloud Run).
"""
import sys
import os
import argparse
import json
import urllib.request
import urllib.error

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

COMPANIES = [
    "ark-visiting-nurse",
    "lcc-visiting-nurse",
    "ichigo-visiting-nurse",
    "ichigo-care-home",
    "chigasaki-tokushukai",
    "nomura-hospital",
    "an-visiting-nurse",
]

DEFAULT_BASE_URL = "https://scout-api-1080076995871.asia-northeast1.run.app"


def post_profile(base_url: str, api_key: str, company: str, content: str) -> dict:
    url = f"{base_url}/api/v1/admin/profiles"
    data = json.dumps({"company": company, "content": content}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL", DEFAULT_BASE_URL))
    args = parser.parse_args()

    api_key = os.environ.get("API_KEY", "")
    if not api_key and not args.dry_run:
        print("ERROR: Set API_KEY env var")
        sys.exit(1)

    profiles = []
    for company in COMPANIES:
        path = os.path.join(REPO_ROOT, "companies", company, "profile.md")
        if not os.path.exists(path):
            print(f"  SKIP {company}: profile.md not found")
            continue
        with open(path, encoding="utf-8") as f:
            content = f.read().strip()
        profiles.append((company, content))
        print(f"  READ {company}: {len(content)} chars")

    if args.dry_run:
        print(f"\n[DRY RUN] Would POST {len(profiles)} profiles to {args.base_url}")
        return

    success = 0
    for company, content in profiles:
        try:
            result = post_profile(args.base_url, api_key, company, content)
            print(f"  OK {company}: row {result.get('row_index', '?')}")
            success += 1
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"  FAIL {company}: {e.code} {body}")
        except Exception as e:
            print(f"  FAIL {company}: {e}")

    print(f"\n  {success}/{len(profiles)} profiles migrated")


if __name__ == "__main__":
    main()
