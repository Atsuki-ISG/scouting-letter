# -*- coding: utf-8 -*-
"""Restore ark-visiting-nurse templates to original state."""
import json
import urllib.request

BASE = "https://scout-api-1080076995871.asia-northeast1.run.app"
KEY = "anycare"


def api(method, path, body=None):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=data,
        headers={"X-API-Key": KEY, "Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


# 1. Find and delete existing ark rows
print("Deleting existing ark rows...")
r = api("GET", "/api/v1/admin/templates?company=ark-visiting-nurse")
rows_to_delete = sorted([row["_row_index"] for row in r["rows"]], reverse=True)
for row_idx in rows_to_delete:
    try:
        api("DELETE", f"/api/v1/admin/templates/{row_idx}")
        print(f"  Deleted row {row_idx}")
    except Exception as e:
        print(f"  Failed row {row_idx}: {e}")

# 2. Read template bodies from templates.md
import os
tmpl_path = os.path.join(os.path.dirname(__file__), "..", "..", "companies", "ark-visiting-nurse", "templates.md")
with open(tmpl_path, encoding="utf-8") as f:
    content = f.read()

# Extract code blocks
import re
blocks = re.findall(r'```\n(.*?)```', content, re.DOTALL)
print(f"\nFound {len(blocks)} template blocks in templates.md")

# Map blocks to template types
# Block order: パート_初回, パート_再送, 正社員_初回, 正社員_再送
type_names = ["パート_初回", "パート_再送", "正社員_初回", "正社員_再送"]

for i, (ttype, block) in enumerate(zip(type_names, blocks)):
    body = block.strip()
    # Replace placeholder
    body = body.replace("{ここに生成した文章を挿入}", "{personalized_text}")
    # Convert to \\n for Sheets storage
    stored = body.replace("\n", "\\n")

    try:
        r = api("POST", "/api/v1/admin/templates", {
            "company": "ark-visiting-nurse",
            "job_category": "nurse",
            "type": ttype,
            "body": stored,
            "version": "1",
        })
        print(f"  Created {ttype}: {r}")
    except Exception as e:
        print(f"  Failed {ttype}: {e}")

# 3. Verify
print("\nVerifying...")
r = api("GET", "/api/v1/admin/templates?company=ark-visiting-nurse")
for row in r["rows"]:
    body_preview = row["body"][:60].replace("\\n", " ")
    print(f"  row {row['_row_index']}: {row['type']} v{row.get('version','?')} | {body_preview}...")
