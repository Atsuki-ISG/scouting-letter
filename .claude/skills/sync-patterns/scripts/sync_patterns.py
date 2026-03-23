#!/usr/bin/env python3
"""Sync pattern texts between recipes.md and Google Sheets via admin API.

Usage:
  sync_patterns.py sync <company> [--dry-run]     # recipes.md → サーバ反映
  sync_patterns.py show <company>                  # サーバの現在値を表示
  sync_patterns.py diff <company>                  # recipes.md とサーバの差分表示
  sync_patterns.py create <company> [--dry-run]    # 新規会社のパターン一括作成

Options:
  --dry-run    変更せずプレビューのみ

Environment:
  SCOUT_API_BASE  API base URL (default: Cloud Run production)
  SCOUT_API_KEY   API key (default: anycare)
"""
import json
import os
import re
import sys

import requests

API_BASE = os.environ.get(
    "SCOUT_API_BASE",
    "https://scout-api-1080076995871.asia-northeast1.run.app/api/v1/admin",
)
API_KEY = os.environ.get("SCOUT_API_KEY", "anycare")
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

COMPANIES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "companies")

# LCC has multiple job categories in one recipes.md
LCC_CATEGORY_MAP = {
    "看護師": "nurse",
    "リハビリ職（PT/ST）": "rehab",
    "医療事務": "medical_office",
}

DRY_RUN = "--dry-run" in sys.argv

# Standard match rules shared across companies
STANDARD_MATCH_RULES = {
    "A": [{"exp_min": 10}, {"age_group": "40s+", "exp_min": 6}],
    "B1": [{"exp_min": 6, "exp_max": 9}],
    "B2": [{"exp_min": 3, "exp_max": 5}],
    "C": [{"age_group": "40s+", "exp_min": 1, "exp_max": 2}],
    "D_就業中": [{"age_group": "40s+", "employment": "就業中"}],
    "D_離職中": [{"age_group": "40s+", "employment": "離職中"}],
    "E": [{"age_group": "young", "exp_min": 1, "exp_max": 2}],
    "F_就業中": [{"age_group": "young", "employment": "就業中"}],
    "F_離職中": [{"age_group": "young", "employment": "離職中"}],
    "G": [{"employment": "在学中"}],
}

STANDARD_META = {
    "A": {"display_name": "豊富な経験への期待", "target_description": "経験10年+/40代〜×経験6年+"},
    "B1": {"display_name": "確かな経験×特色", "target_description": "経験6〜9年"},
    "B2": {"display_name": "経験×特色", "target_description": "経験3〜5年"},
    "C": {"display_name": "経験とのフィット", "target_description": "40代〜×経験1〜2年"},
    "D_就業中": {"display_name": "経験ある前提で評価", "target_description": "40代〜×経験未入力"},
    "D_離職中": {"display_name": "経験ある前提で評価", "target_description": "40代〜×経験未入力"},
    "E": {"display_name": "ポテンシャル+成長環境", "target_description": "20〜30代×経験1〜2年"},
    "F_就業中": {"display_name": "成長環境+チーム体制", "target_description": "20〜30代×経験未入力"},
    "F_離職中": {"display_name": "成長環境+チーム体制", "target_description": "20〜30代×経験未入力"},
    "G": {"display_name": "成長環境メイン", "target_description": "在学中"},
}


def parse_recipes(filepath):
    """Parse recipes.md and extract pattern texts and feature variations."""
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    patterns = {}
    sections = re.split(r'\n### ', content)

    for section in sections:
        type_match = re.match(r'型([A-G]\d?)', section)
        if not type_match:
            continue
        pattern_type = type_match.group(1)

        lines = section.split('\n')
        current_variant = ""
        in_code = False
        code_lines = []
        feature_lines = []
        in_features = False

        for line in lines:
            if line.strip() == '就業中:':
                current_variant = "就業中"
                in_features = False
            elif line.strip() == '離職中:':
                if code_lines:
                    key = f"{pattern_type}_{current_variant}" if current_variant else pattern_type
                    patterns[key] = {
                        "text": '\n'.join(code_lines).strip(),
                        "features": [l.strip('- ').strip() for l in feature_lines] if feature_lines else None,
                    }
                    code_lines = []
                    feature_lines = []
                current_variant = "離職中"
                in_features = False
            elif line.strip() == '```':
                if in_code:
                    key = f"{pattern_type}_{current_variant}" if current_variant else pattern_type
                    patterns[key] = {"text": '\n'.join(code_lines).strip(), "features": None}
                    code_lines = []
                    in_code = False
                else:
                    in_code = True
                    in_features = False
            elif in_code:
                code_lines.append(line)
            elif line.startswith('特色バリエーション:'):
                in_features = True
            elif in_features and line.startswith('- '):
                feature_lines.append(line)
            elif not line.startswith('- ') and line.strip() and in_features:
                in_features = False

        if code_lines:
            key = f"{pattern_type}_{current_variant}" if current_variant else pattern_type
            patterns[key] = {"text": '\n'.join(code_lines).strip(), "features": None}

        if feature_lines:
            features = [l.strip('- ').strip() for l in feature_lines]
            if pattern_type in patterns and patterns[pattern_type]["features"] is None:
                patterns[pattern_type]["features"] = features
            for v in ["就業中", "離職中"]:
                k = f"{pattern_type}_{v}"
                if k in patterns and patterns[k]["features"] is None:
                    patterns[k]["features"] = features

    return patterns


def parse_lcc_recipes(filepath):
    """Parse LCC recipes.md with multiple job category sections."""
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    result = {}  # {job_category: {pattern_key: {text, features}}}
    category_sections = re.split(r'\n## ', content)

    for section in category_sections:
        jc = None
        for name, code in LCC_CATEGORY_MAP.items():
            if section.startswith(name):
                jc = code
                break
        if not jc:
            continue

        recipes = {}
        subsections = re.split(r'\n####? ', section)

        for subsec in subsections:
            type_match = re.match(r'型([A-G]\d?)', subsec)
            if not type_match:
                continue
            pattern_type = type_match.group(1)

            lines = subsec.split('\n')
            current_variant = ""
            in_code = False
            code_lines = []
            feature_lines = []
            in_features = False

            for line in lines:
                if line.strip() == '就業中:':
                    current_variant = "就業中"
                    in_features = False
                elif line.strip() == '離職中:':
                    if code_lines:
                        key = f"{pattern_type}_{current_variant}" if current_variant else pattern_type
                        recipes[key] = {"text": '\n'.join(code_lines).strip(), "features": None}
                        code_lines = []
                        feature_lines = []
                    current_variant = "離職中"
                    in_features = False
                elif line.strip() == '```':
                    if in_code:
                        key = f"{pattern_type}_{current_variant}" if current_variant else pattern_type
                        recipes[key] = {"text": '\n'.join(code_lines).strip(), "features": None}
                        code_lines = []
                        in_code = False
                    else:
                        in_code = True
                        in_features = False
                elif in_code:
                    code_lines.append(line)
                elif line.startswith('特色バリエーション:'):
                    in_features = True
                elif in_features and line.startswith('- '):
                    feature_lines.append(line)
                elif not line.startswith('- ') and line.strip() and in_features:
                    in_features = False

            if code_lines:
                key = f"{pattern_type}_{current_variant}" if current_variant else pattern_type
                recipes[key] = {"text": '\n'.join(code_lines).strip(), "features": None}

            if feature_lines:
                features = [l.strip('- ').strip() for l in feature_lines]
                if pattern_type in recipes and recipes[pattern_type]["features"] is None:
                    recipes[pattern_type]["features"] = features
                for v in ["就業中", "離職中"]:
                    k = f"{pattern_type}_{v}"
                    if k in recipes and recipes[k]["features"] is None:
                        recipes[k]["features"] = features

        result[jc] = recipes

    return result


def get_existing_patterns(company):
    """Fetch existing patterns from API."""
    resp = requests.get(f"{API_BASE}/patterns", params={"company": company}, headers=HEADERS)
    resp.raise_for_status()
    return resp.json().get("rows", [])


def update_row(row_index, row_data):
    """Update a single row via API."""
    if DRY_RUN:
        print(f"  [DRY RUN] Would update row {row_index}")
        return
    resp = requests.put(f"{API_BASE}/patterns/{row_index}", json=row_data, headers=HEADERS)
    resp.raise_for_status()


def create_row(row_data):
    """Create a new row via API."""
    if DRY_RUN:
        print(f"  [DRY RUN] Would create: {row_data.get('pattern_type')} {row_data.get('employment_variant', '')}")
        return
    resp = requests.post(f"{API_BASE}/patterns", json=row_data, headers=HEADERS)
    resp.raise_for_status()


def get_recipes_path(company):
    """Resolve recipes.md path for a company."""
    path = os.path.normpath(os.path.join(COMPANIES_DIR, company, "recipes.md"))
    if not os.path.exists(path):
        print(f"ERROR: {path} not found")
        sys.exit(1)
    return path


def cmd_show(company):
    """Show current server patterns for a company."""
    rows = get_existing_patterns(company)
    if not rows:
        print(f"No patterns found for {company}")
        return

    # Group by job_category
    by_jc = {}
    for r in rows:
        jc = r.get("job_category", "")
        by_jc.setdefault(jc, []).append(r)

    for jc, jc_rows in sorted(by_jc.items()):
        print(f"\n=== {company} / {jc} ===")
        for r in sorted(jc_rows, key=lambda x: x.get("pattern_type", "")):
            pt = r["pattern_type"]
            variant = r.get("employment_variant", "")
            key = f"{pt}_{variant}" if variant else pt
            text = r.get("template_text", "")
            features = r.get("feature_variations", "")
            print(f"\n  [{key}] {r.get('display_name', '')}")
            print(f"    text: {text[:100]}{'...' if len(text) > 100 else ''}")
            if features:
                print(f"    features: {features}")


def cmd_diff(company):
    """Show diff between recipes.md and server."""
    recipes_path = get_recipes_path(company)
    existing = get_existing_patterns(company)

    if company == "lcc-visiting-nurse":
        all_recipes = parse_lcc_recipes(recipes_path)
        diffs = 0
        for jc, recipes in all_recipes.items():
            jc_rows = [r for r in existing if r.get("job_category", "") == jc]
            print(f"\n--- {jc} ---")
            diffs += _diff_patterns(recipes, jc_rows)
        print(f"\nTotal diffs: {diffs}")
    else:
        recipes = parse_recipes(recipes_path)
        diffs = _diff_patterns(recipes, existing)
        print(f"\nTotal diffs: {diffs}")


def _diff_patterns(recipes, rows):
    """Compare recipes dict with server rows. Returns diff count."""
    diffs = 0
    for row in rows:
        pt = row["pattern_type"]
        variant = row.get("employment_variant", "")
        key = f"{pt}_{variant}" if variant else pt

        if key not in recipes:
            print(f"  SKIP {key}: not in recipes")
            continue

        new_text = recipes[key]["text"]
        old_text = row.get("template_text", "")

        if new_text == old_text:
            print(f"  OK   {key}")
        else:
            print(f"  DIFF {key}:")
            print(f"    server: {old_text[:80]}...")
            print(f"    local:  {new_text[:80]}...")
            diffs += 1

    # Check for patterns in recipes but not on server
    server_keys = set()
    for row in rows:
        pt = row["pattern_type"]
        variant = row.get("employment_variant", "")
        server_keys.add(f"{pt}_{variant}" if variant else pt)

    for key in recipes:
        if key not in server_keys:
            print(f"  NEW  {key}: exists in recipes but not on server")
            diffs += 1

    return diffs


def cmd_sync(company):
    """Sync recipes.md → server for existing company."""
    recipes_path = get_recipes_path(company)
    existing = get_existing_patterns(company)

    if not existing:
        print(f"No existing patterns for {company}. Use 'create' command instead.")
        sys.exit(1)

    if company == "lcc-visiting-nurse":
        all_recipes = parse_lcc_recipes(recipes_path)
        total = 0
        for jc, recipes in all_recipes.items():
            jc_rows = [r for r in existing if r.get("job_category", "") == jc]
            print(f"\n--- {jc} ---")
            total += _sync_patterns(recipes, jc_rows)
        print(f"\nTotal updated: {total}")
    else:
        recipes = parse_recipes(recipes_path)
        updated = _sync_patterns(recipes, existing)
        print(f"\nUpdated: {updated}")


def _sync_patterns(recipes, rows):
    """Sync recipes to server rows. Returns update count."""
    updated = 0
    for row in rows:
        pt = row["pattern_type"]
        variant = row.get("employment_variant", "")
        key = f"{pt}_{variant}" if variant else pt

        if key not in recipes:
            print(f"  SKIP {key}: not in recipes")
            continue

        new_text = recipes[key]["text"]
        old_text = row.get("template_text", "")

        if new_text == old_text:
            print(f"  OK   {key}: up to date")
            continue

        print(f"  UPD  {key}:")
        print(f"    OLD: {old_text[:80]}...")
        print(f"    NEW: {new_text[:80]}...")

        update_data = dict(row)
        update_data["template_text"] = new_text

        features = recipes[key].get("features")
        if features:
            update_data["feature_variations"] = "|".join(features)

        del update_data["_row_index"]
        update_row(row["_row_index"], update_data)
        updated += 1

    return updated


def cmd_create(company, job_category="nurse"):
    """Create all patterns for a new company from recipes.md."""
    recipes_path = get_recipes_path(company)
    existing = get_existing_patterns(company)
    if existing:
        print(f"WARNING: {company} already has {len(existing)} patterns on server.")
        print("Use 'sync' to update existing patterns, or delete them first.")
        sys.exit(1)

    recipes = parse_recipes(recipes_path)

    created = 0
    for key in ["A", "B1", "B2", "C", "D_就業中", "D_離職中", "E", "F_就業中", "F_離職中", "G"]:
        if key not in recipes:
            print(f"  WARN: {key} not found in recipes!")
            continue

        pt = key.split("_")[0]
        variant = key.split("_")[1] if "_" in key else ""
        features = recipes[key].get("features") or []

        row_data = {
            "company": company,
            "job_category": job_category,
            "pattern_type": pt,
            "employment_variant": variant,
            "template_text": recipes[key]["text"],
            "feature_variations": "|".join(features) if features else "",
            "display_name": STANDARD_META.get(key, {}).get("display_name", ""),
            "target_description": STANDARD_META.get(key, {}).get("target_description", ""),
            "match_rules": json.dumps(STANDARD_MATCH_RULES.get(key, []), ensure_ascii=False),
            "qualification_combo": "",
            "replacement_text": "",
        }

        print(f"  CREATE {key}: {row_data['template_text'][:60]}...")
        create_row(row_data)
        created += 1

    print(f"\nCreated: {created} rows")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)

    command = args[0]
    company = args[1]

    if command == "show":
        cmd_show(company)
    elif command == "diff":
        cmd_diff(company)
    elif command == "sync":
        cmd_sync(company)
    elif command == "create":
        job_category = args[2] if len(args) > 2 else "nurse"
        cmd_create(company, job_category)
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
