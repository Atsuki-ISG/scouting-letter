#!/usr/bin/env python3
"""Server admin: read/write Google Sheets via Cloud Run admin API.

Usage:
  server_admin.py show <company> [sheet]           # Show server data
  server_admin.py diff <company>                    # Diff local recipes.md vs server patterns
  server_admin.py sync <company> [--dry-run]        # Sync recipes.md patterns → server
  server_admin.py create-patterns <company> [jc]    # Create patterns from recipes.md (new company)
  server_admin.py init <company> [--dry-run]        # Init new company from local files via AI
  server_admin.py update <sheet> <row_index> <json> # Update a specific row
  server_admin.py add <sheet> <json>                # Add a row
  server_admin.py delete <sheet> <row_index>        # Delete a row
  server_admin.py companies                         # List all companies

Sheets: templates, patterns, qualifiers, prompts, validation, job_offers, logs

Options:
  --dry-run    Preview without writing

Environment:
  SCOUT_API_BASE  API base URL (default: Cloud Run production)
  SCOUT_API_KEY   API key (default: anycare)
"""
import json
import os
import re
import sys
import textwrap

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)

API_BASE = os.environ.get(
    "SCOUT_API_BASE",
    "https://scout-api-1080076995871.asia-northeast1.run.app/api/v1/admin",
)
API_KEY = os.environ.get("SCOUT_API_KEY", "anycare")
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

COMPANIES_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "companies")
)

DRY_RUN = "--dry-run" in sys.argv

VALID_SHEETS = ["templates", "patterns", "qualifiers", "prompts", "validation", "job_offers", "logs"]

# --- Match rules & metadata (shared across companies) ---
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

# LCC multi-category support
LCC_CATEGORY_MAP = {
    "看護師": "nurse",
    "リハビリ職（PT/ST）": "rehab",
    "医療事務": "medical_office",
}


# ============================================================
# API helpers
# ============================================================

def api_get(path, params=None):
    resp = requests.get(f"{API_BASE}/{path}", params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def api_post(path, data):
    if DRY_RUN:
        print(f"  [DRY RUN] POST {path}")
        return {"status": "dry_run"}
    resp = requests.post(f"{API_BASE}/{path}", json=data, headers=HEADERS, timeout=120)
    resp.raise_for_status()
    return resp.json()


def api_put(path, data):
    if DRY_RUN:
        print(f"  [DRY RUN] PUT {path}")
        return {"status": "dry_run"}
    resp = requests.put(f"{API_BASE}/{path}", json=data, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def api_delete(path):
    if DRY_RUN:
        print(f"  [DRY RUN] DELETE {path}")
        return {"status": "dry_run"}
    resp = requests.delete(f"{API_BASE}/{path}", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ============================================================
# recipes.md parser (from sync_patterns.py)
# ============================================================

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

    result = {}
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


def parse_qualifiers(filepath):
    """Parse qualification modifiers from recipes.md."""
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    qualifiers = []
    # Find "## 資格修飾" section
    match = re.search(r'## 資格修飾.*?\n(.*?)(?=\n## |\Z)', content, re.DOTALL)
    if not match:
        return qualifiers

    section = match.group(1)
    # Find each ### block
    blocks = re.split(r'\n### ', section)
    for block in blocks:
        if not block.strip():
            continue
        # Extract title for qualification_combo hint
        title = block.split('\n')[0].strip()
        # Extract code block
        code_match = re.search(r'```\n(.*?)\n```', block, re.DOTALL)
        if not code_match:
            continue
        text = code_match.group(1).strip()

        # Infer qualification_combo from title
        combo = []
        if '看護師' in title:
            combo.append('看護師')
        if '保健師' in title:
            combo.append('保健師')
        if 'ケアマネ' in title:
            combo.append('ケアマネジャー')
        if '認定看護師' in title or '専門資格' in title:
            # Skip template-style entries with {資格名}
            if '{' in text:
                continue

        if combo:
            qualifiers.append({
                "qualification_combo": ",".join(combo),
                "replacement_text": text,
            })

    return qualifiers


# ============================================================
# Local file helpers
# ============================================================

def get_local_path(company, filename):
    path = os.path.normpath(os.path.join(COMPANIES_DIR, company, filename))
    if not os.path.exists(path):
        return None
    return path


def read_local_file(company, filename):
    path = get_local_path(company, filename)
    if not path:
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def extract_first_template(templates_content):
    """Extract the first template code block from templates.md."""
    # Find first ``` block after "## テンプレート" or "本文:"
    blocks = re.findall(r'```\n(.*?)\n```', templates_content, re.DOTALL)
    # Skip the subject line block (short, contains 🍓 etc)
    for block in blocks:
        if len(block) > 100:  # Template body is long
            return block.strip()
    return blocks[0].strip() if blocks else None


# ============================================================
# Commands
# ============================================================

def cmd_companies():
    """List all companies on server."""
    # Get from templates sheet (most reliable)
    for sheet in ["templates", "patterns"]:
        try:
            data = api_get(sheet)
            companies = sorted(set(r.get("company", "") for r in data.get("rows", []) if r.get("company")))
            if companies:
                print("Companies on server:")
                for c in companies:
                    print(f"  - {c}")
                return
        except Exception:
            continue
    print("No companies found")


def cmd_show(company, sheet=None):
    """Show server data for a company."""
    sheets = [sheet] if sheet else ["templates", "patterns", "qualifiers", "prompts", "validation", "job_offers"]

    for s in sheets:
        if s not in VALID_SHEETS:
            print(f"Unknown sheet: {s}. Valid: {', '.join(VALID_SHEETS)}")
            return

        try:
            data = api_get(s, {"company": company})
        except requests.exceptions.HTTPError as e:
            print(f"\n=== {s} === ERROR: {e}")
            continue

        rows = data.get("rows", [])
        print(f"\n=== {s} ({len(rows)} rows) ===")

        if not rows:
            print("  (empty)")
            continue

        if s == "templates":
            for r in rows:
                body = r.get("body", "")
                print(f"\n  [{r.get('type', '')}] job_category={r.get('job_category', '')} (row {r.get('_row_index', '')})")
                print(f"    {body[:120]}{'...' if len(body) > 120 else ''}")

        elif s == "patterns":
            for r in sorted(rows, key=lambda x: x.get("pattern_type", "")):
                pt = r.get("pattern_type", "")
                emp = r.get("employment_variant", "")
                key = f"{pt}_{emp}" if emp else pt
                text = r.get("template_text", "")
                features = r.get("feature_variations", "")
                print(f"\n  [{key}] {r.get('display_name', '')} (row {r.get('_row_index', '')})")
                print(f"    text: {text[:100]}{'...' if len(text) > 100 else ''}")
                if features:
                    print(f"    features: {features}")

        elif s == "qualifiers":
            for r in rows:
                combo = r.get("qualification_combo", "")
                text = r.get("replacement_text", "")
                print(f"  [{combo}] (row {r.get('_row_index', '')})")
                print(f"    {text[:100]}{'...' if len(text) > 100 else ''}")

        elif s == "prompts":
            for r in sorted(rows, key=lambda x: x.get("order", 0)):
                st = r.get("section_type", "")
                content = r.get("content", "")
                print(f"\n  [{st}] order={r.get('order', '')} jc={r.get('job_category', '')} (row {r.get('_row_index', '')})")
                print(f"    {content[:120]}{'...' if len(content) > 120 else ''}")

        elif s == "validation":
            for r in rows:
                print(f"  age_min={r.get('age_min', '')} age_max={r.get('age_max', '')} (row {r.get('_row_index', '')})")
                print(f"  rules: {r.get('qualification_rules', '')}")

        elif s == "job_offers":
            for r in rows:
                active = r.get("active", "")
                print(f"  [{r.get('id', '')}] {r.get('name', '')} ({r.get('employment_type', '')}) active={active} (row {r.get('_row_index', '')})")


def cmd_diff(company):
    """Show diff between local recipes.md and server patterns."""
    recipes_path = get_local_path(company, "recipes.md")
    if not recipes_path:
        print(f"ERROR: companies/{company}/recipes.md not found")
        sys.exit(1)

    existing = api_get("patterns", {"company": company}).get("rows", [])

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
    diffs = 0
    server_keys = set()

    for row in rows:
        pt = row.get("pattern_type", "")
        variant = row.get("employment_variant", "")
        key = f"{pt}_{variant}" if variant else pt
        server_keys.add(key)

        if key not in recipes:
            continue

        new_text = recipes[key]["text"]
        old_text = row.get("template_text", "")

        new_features = recipes[key].get("features") or []
        old_features_raw = row.get("feature_variations", "")
        old_features = old_features_raw.split("|") if old_features_raw else []

        text_match = new_text == old_text
        features_match = new_features == old_features or not new_features

        if text_match and features_match:
            print(f"  OK   {key}")
        else:
            if not text_match:
                print(f"  DIFF {key} (text):")
                print(f"    server: {old_text[:80]}...")
                print(f"    local:  {new_text[:80]}...")
            if not features_match:
                print(f"  DIFF {key} (features):")
                print(f"    server: {old_features}")
                print(f"    local:  {new_features}")
            diffs += 1

    for key in recipes:
        if key not in server_keys:
            print(f"  NEW  {key}: in recipes.md but not on server")
            diffs += 1

    return diffs


def cmd_sync(company):
    """Sync local recipes.md patterns → server."""
    recipes_path = get_local_path(company, "recipes.md")
    if not recipes_path:
        print(f"ERROR: companies/{company}/recipes.md not found")
        sys.exit(1)

    existing = api_get("patterns", {"company": company}).get("rows", [])
    if not existing:
        print(f"No existing patterns for {company}. Use 'create-patterns' instead.")
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
    updated = 0
    for row in rows:
        pt = row.get("pattern_type", "")
        variant = row.get("employment_variant", "")
        key = f"{pt}_{variant}" if variant else pt

        if key not in recipes:
            continue

        new_text = recipes[key]["text"]
        old_text = row.get("template_text", "")
        new_features = recipes[key].get("features")

        needs_update = False
        if new_text != old_text:
            needs_update = True
        if new_features:
            old_features_raw = row.get("feature_variations", "")
            old_features = old_features_raw.split("|") if old_features_raw else []
            if new_features != old_features:
                needs_update = True

        if not needs_update:
            print(f"  OK   {key}")
            continue

        print(f"  UPD  {key}:")
        print(f"    OLD: {old_text[:80]}...")
        print(f"    NEW: {new_text[:80]}...")

        update_data = {k: v for k, v in row.items() if k != "_row_index"}
        update_data["template_text"] = new_text
        if new_features:
            update_data["feature_variations"] = "|".join(new_features)

        api_put(f"patterns/{row['_row_index']}", update_data)
        updated += 1

    return updated


def cmd_create_patterns(company, job_category="nurse"):
    """Create patterns from recipes.md for a new company."""
    recipes_path = get_local_path(company, "recipes.md")
    if not recipes_path:
        print(f"ERROR: companies/{company}/recipes.md not found")
        sys.exit(1)

    existing = api_get("patterns", {"company": company}).get("rows", [])
    if existing:
        print(f"WARNING: {company} already has {len(existing)} patterns. Use 'sync' to update.")
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
        api_post("patterns", row_data)
        created += 1

    print(f"\nCreated: {created} rows")


def cmd_init(company):
    """Initialize a new company on the server from local files.

    Reads profile.md for company_info, templates.md for template body,
    then calls generate_company API to create templates + AI-generate
    patterns, prompts, validation, and qualifiers.
    """
    # Check local files
    profile = read_local_file(company, "profile.md")
    if not profile:
        print(f"ERROR: companies/{company}/profile.md not found")
        sys.exit(1)

    templates_content = read_local_file(company, "templates.md")
    template_body = None
    if templates_content:
        template_body = extract_first_template(templates_content)
        if template_body:
            print(f"Template extracted ({len(template_body)} chars)")

    # Check if company already exists
    try:
        existing = api_get("templates", {"company": company}).get("rows", [])
        if existing:
            print(f"ERROR: {company} already exists on server ({len(existing)} template rows).")
            print("Use 'sync' to update patterns, or delete the company first.")
            sys.exit(1)
    except Exception:
        pass

    payload = {
        "company_id": company,
        "company_info": profile,
    }
    if template_body:
        payload["template_text"] = template_body

    print(f"Calling generate_company API for {company}...")
    if DRY_RUN:
        print("[DRY RUN] Would call POST /generate_company with:")
        print(f"  company_id: {company}")
        print(f"  company_info: {len(profile)} chars")
        print(f"  template_text: {len(template_body) if template_body else 0} chars")
        return

    # Use direct requests for this endpoint (longer timeout)
    resp = requests.post(
        f"{API_BASE}/generate_company",
        json=payload,
        headers=HEADERS,
        timeout=120,
    )
    resp.raise_for_status()
    result = resp.json()

    total = result.get("total_rows", 0)
    print(f"Created {total} rows on server.")

    generated = result.get("generated", {})
    patterns = generated.get("patterns", [])
    prompts = generated.get("prompts", [])
    qualifiers = generated.get("qualifiers", [])

    print(f"  Templates: 4 (same body for all types)")
    print(f"  Patterns: {len(patterns)}")
    print(f"  Prompts: {len(prompts)}")
    print(f"  Qualifiers: {len(qualifiers)}")
    print(f"  Validation: 1")

    # Check if recipes.md exists → suggest sync
    if get_local_path(company, "recipes.md"):
        print(f"\nrecipes.md found. Run 'sync {company}' to overwrite AI-generated patterns with local ones.")


def cmd_update(sheet, row_index, json_str):
    """Update a specific row."""
    if sheet not in VALID_SHEETS:
        print(f"Unknown sheet: {sheet}. Valid: {', '.join(VALID_SHEETS)}")
        sys.exit(1)

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        sys.exit(1)

    api_put(f"{sheet}/{row_index}", data)
    print(f"Updated row {row_index} in {sheet}")


def cmd_add(sheet, json_str):
    """Add a row to a sheet."""
    if sheet not in VALID_SHEETS:
        print(f"Unknown sheet: {sheet}. Valid: {', '.join(VALID_SHEETS)}")
        sys.exit(1)

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        sys.exit(1)

    api_post(sheet, data)
    print(f"Added row to {sheet}")


def cmd_delete(sheet, row_index):
    """Delete a row from a sheet."""
    if sheet not in VALID_SHEETS:
        print(f"Unknown sheet: {sheet}. Valid: {', '.join(VALID_SHEETS)}")
        sys.exit(1)

    api_delete(f"{sheet}/{row_index}")
    print(f"Deleted row {row_index} from {sheet}")


# ============================================================
# Main
# ============================================================

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if not args:
        print(__doc__)
        sys.exit(1)

    command = args[0]

    if command == "companies":
        cmd_companies()

    elif command == "show":
        if len(args) < 2:
            print("Usage: show <company> [sheet]")
            sys.exit(1)
        cmd_show(args[1], args[2] if len(args) > 2 else None)

    elif command == "diff":
        if len(args) < 2:
            print("Usage: diff <company>")
            sys.exit(1)
        cmd_diff(args[1])

    elif command == "sync":
        if len(args) < 2:
            print("Usage: sync <company> [--dry-run]")
            sys.exit(1)
        cmd_sync(args[1])

    elif command == "create-patterns":
        if len(args) < 2:
            print("Usage: create-patterns <company> [job_category]")
            sys.exit(1)
        jc = args[2] if len(args) > 2 else "nurse"
        cmd_create_patterns(args[1], jc)

    elif command == "init":
        if len(args) < 2:
            print("Usage: init <company> [--dry-run]")
            sys.exit(1)
        cmd_init(args[1])

    elif command == "update":
        if len(args) < 4:
            print("Usage: update <sheet> <row_index> '<json>'")
            sys.exit(1)
        cmd_update(args[1], int(args[2]), args[3])

    elif command == "add":
        if len(args) < 3:
            print("Usage: add <sheet> '<json>'")
            sys.exit(1)
        cmd_add(args[1], args[2])

    elif command == "delete":
        if len(args) < 3:
            print("Usage: delete <sheet> <row_index>")
            sys.exit(1)
        cmd_delete(args[1], int(args[2]))

    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
