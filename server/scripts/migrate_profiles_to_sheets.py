"""Sync company profile.md files to the プロフィール sheet via Admin API.

Usage:
    python3 server/scripts/migrate_profiles_to_sheets.py [--dry-run] [--base-url URL]

Reads each company's profile.md and upserts to /api/v1/admin/profiles.
- Existing rows (matched by company) are updated via PUT.
- Missing rows are created via POST.
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
    "chigasaki-tokushukai",
    "nomura-hospital",
    "an-visiting-nurse",
    "daiwa-house-ls",
]

DEFAULT_BASE_URL = "https://scout-api-1080076995871.asia-northeast1.run.app"


def _request(url, api_key, data=None, method="GET"):
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        method=method,
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

    # Read local profiles
    profiles: list[tuple[str, str]] = []
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
        print(f"\n[DRY RUN] Would sync {len(profiles)} profiles to {args.base_url}")
        return

    # Fetch existing rows to find row_index for each company
    base = args.base_url.rstrip("/")
    existing = _request(f"{base}/api/v1/admin/profiles", api_key)
    row_map: dict[str, int] = {}
    for row in existing.get("rows", []):
        c = row.get("company", "")
        ri = row.get("_row_index") or row.get("row_index")
        if c and ri:
            row_map[c] = int(ri)

    success = 0
    for company, content in profiles:
        try:
            if company in row_map:
                # Update existing row
                ri = row_map[company]
                result = _request(
                    f"{base}/api/v1/admin/profiles/{ri}",
                    api_key,
                    {"content": content},
                    method="PUT",
                )
                print(f"  UPDATE {company} (row {ri}): {result.get('status', '?')}")
            else:
                # Create new row
                result = _request(
                    f"{base}/api/v1/admin/profiles",
                    api_key,
                    {"company": company, "content": content},
                    method="POST",
                )
                print(f"  CREATE {company}: {result.get('status', '?')}")
            success += 1
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"  FAIL {company}: {e.code} {body}")
        except Exception as e:
            print(f"  FAIL {company}: {e}")

    print(f"\n  {success}/{len(profiles)} profiles synced")


if __name__ == "__main__":
    main()
