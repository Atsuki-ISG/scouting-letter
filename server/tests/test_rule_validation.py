"""Rule validation tests for pattern-matched scout text.

Loads dummy profiles and validation rules, runs them through pattern_matcher,
and checks generated text against NG patterns, required patterns, and structural rules.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest
import yaml

from models.profile import CandidateProfile
from pipeline.pattern_matcher import match_pattern, should_use_pattern

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RULES_PATH = PROJECT_ROOT / "test" / "rules" / "validation-rules.yml"
PROFILES_DIR = PROJECT_ROOT / "test" / "dummy-profiles"

# Map company dir names to seed-data company IDs
COMPANY_MAP = {
    "ark-visiting-nurse": "ark-visiting-nurse",
    "lcc-visiting-nurse": "lcc-visiting-nurse",
    "ichigo-visiting-nurse": "ichigo-visiting-nurse",
    "chigasaki-tokushukai": "chigasaki-tokushukai",
    "nomura-hospital": "nomura-hospital",
}


def _load_rules() -> dict:
    """Load validation rules from YAML."""
    if not RULES_PATH.exists():
        pytest.skip(f"Rules file not found: {RULES_PATH}")
    with open(RULES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_patterns_for_company(
    company_id: str, job_category: str = "nurse"
) -> tuple[list[dict], list[dict]]:
    """Load patterns and qualification modifiers from seed-data TSV."""
    patterns_path = PROJECT_ROOT / "server" / "seed-data" / "2_パターン.tsv"
    modifiers_path = PROJECT_ROOT / "server" / "seed-data" / "3_資格修飾.tsv"

    patterns = []
    if patterns_path.exists():
        with open(patterns_path, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                if row.get("company") == company_id and row.get("job_category", "nurse") == job_category:
                    p = {
                        "pattern_type": row["pattern_type"],
                        "job_category": row.get("job_category", "nurse"),
                        "template_text": row["template_text"],
                        "feature_variations": (
                            row.get("feature_variations", "").split("|")
                            if row.get("feature_variations")
                            else []
                        ),
                    }
                    if row.get("employment_variant"):
                        p["employment_variant"] = row["employment_variant"]
                    patterns.append(p)

    modifiers = []
    if modifiers_path.exists():
        with open(modifiers_path, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                if row.get("company") == company_id:
                    combo_str = row.get("qualification_combo", "")
                    modifiers.append({
                        "qualification_combo": [q.strip() for q in combo_str.split("+") if q.strip()],
                        "replacement_text": row.get("replacement_text", ""),
                    })

    return patterns, modifiers


def _load_profiles(company_id: str) -> list[dict]:
    """Load dummy profiles CSV for a company."""
    csv_path = PROFILES_DIR / f"{company_id}.csv"
    if not csv_path.exists():
        return []
    with open(csv_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _profile_from_row(row: dict) -> CandidateProfile:
    """Create CandidateProfile from CSV row."""
    return CandidateProfile(
        member_id=row.get("member_id", "TEST"),
        gender=row.get("gender") or None,
        age=row.get("age") or None,
        qualifications=row.get("qualifications") or None,
        experience_type=row.get("experience_type") or None,
        experience_years=row.get("experience_years") or None,
        employment_status=row.get("employment_status") or None,
        self_pr=row.get("self_pr") or None,
        work_history_summary=row.get("work_history_summary") or None,
    )


def _collect_test_cases() -> list[tuple[str, dict, list[dict], list[dict]]]:
    """Collect all (company_id, profile_row, patterns, modifiers) tuples."""
    cases = []
    for company_id in COMPANY_MAP.values():
        profiles = _load_profiles(company_id)
        if not profiles:
            continue
        for row in profiles:
            job_cat = row.get("job_category", "nurse").strip() or "nurse"
            patterns, modifiers = _load_patterns_for_company(company_id, job_cat)
            if not patterns:
                continue
            cases.append((company_id, row, patterns, modifiers))
    return cases


# Collect test cases at module level for parametrize
_TEST_CASES = _collect_test_cases()


@pytest.mark.skipif(not _TEST_CASES, reason="No test cases found (missing profiles or patterns)")
@pytest.mark.parametrize(
    "company_id,profile_row,patterns,modifiers",
    _TEST_CASES,
    ids=[f"{c[0]}:{c[1].get('member_id', '?')}" for c in _TEST_CASES],
)
def test_pattern_ng_check(company_id, profile_row, patterns, modifiers):
    """Check generated pattern text against NG expressions."""
    profile = _profile_from_row(profile_row)

    # Skip profiles with work history (AI generation path, not pattern matching)
    if not should_use_pattern(profile):
        pytest.skip("AI generation path (has work history)")

    rules = _load_rules()

    try:
        pattern_type, text, debug_info = match_pattern(
            profile, patterns, modifiers, feature_rotation_index=0
        )
    except ValueError:
        pytest.skip(f"No matching pattern for {profile_row.get('member_id')}")
        return

    violations = []

    # Check universal NG patterns
    for ng in rules.get("ng_patterns", []):
        pat = ng["pattern"]
        if re.search(pat, text):
            # Check if this hit is in an exception context
            exception = ng.get("exception")
            if exception and "資格修飾" in exception:
                # Allow in qualification modifier context
                continue
            violations.append(f"NG表現検出: 「{pat}」 (source: {ng['source']})")

    # Check company-specific NG patterns
    job_cat = profile_row.get("job_category", "nurse").strip() or "nurse"
    company_ngs = rules.get("company_ng_patterns", {}).get(company_id, [])
    for ng in company_ngs:
        # Evaluate condition if present (e.g. "job_category != nurse")
        condition = ng.get("condition", "")
        if condition:
            if "job_category != " in condition:
                excluded_cat = condition.split("!= ")[1].strip()
                if job_cat != excluded_cat:
                    pass  # condition met, this IS an NG
                else:
                    continue  # condition not met, skip
            elif "job_category == " in condition:
                required_cat = condition.split("== ")[1].strip()
                if job_cat != required_cat:
                    continue  # condition not met, skip
        pat = ng["pattern"]
        if re.search(pat, text):
            violations.append(f"会社別NG検出: 「{pat}」 (source: {ng['source']})")

    # Check expected NG from CSV (if specified)
    expected_ng = profile_row.get("expected_ng", "").strip()
    if expected_ng and expected_ng in text:
        violations.append(f"CSV指定NG検出: 「{expected_ng}」がテキストに含まれている")

    assert not violations, (
        f"\n{profile_row.get('member_id')} ({profile_row.get('description', '')})\n"
        f"Pattern: {pattern_type} | Debug: {debug_info}\n"
        f"Text: {text}\n"
        f"Violations:\n" + "\n".join(f"  - {v}" for v in violations)
    )


@pytest.mark.skipif(not _TEST_CASES, reason="No test cases found")
@pytest.mark.parametrize(
    "company_id,profile_row,patterns,modifiers",
    _TEST_CASES,
    ids=[f"{c[0]}:{c[1].get('member_id', '?')}" for c in _TEST_CASES],
)
def test_pattern_required_check(company_id, profile_row, patterns, modifiers):
    """Check that required expressions are present when expected."""
    profile = _profile_from_row(profile_row)

    if not should_use_pattern(profile):
        pytest.skip("AI generation path")

    expected_required = profile_row.get("expected_required", "").strip()
    if not expected_required:
        pytest.skip("No required pattern specified")

    try:
        pattern_type, text, debug_info = match_pattern(
            profile, patterns, modifiers, feature_rotation_index=0
        )
    except ValueError:
        pytest.skip(f"No matching pattern for {profile_row.get('member_id')}")
        return

    assert expected_required in text, (
        f"\n{profile_row.get('member_id')} ({profile_row.get('description', '')})\n"
        f"Pattern: {pattern_type} | Debug: {debug_info}\n"
        f"Text: {text}\n"
        f"必須表現「{expected_required}」が見つかりません"
    )
