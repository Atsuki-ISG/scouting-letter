from __future__ import annotations

import re

from models.profile import CandidateProfile


def _parse_age(age_str: str | None) -> int | None:
    """Parse age from string like '44歳' → 44."""
    if not age_str:
        return None
    match = re.search(r"(\d+)", age_str)
    return int(match.group(1)) if match else None


def _parse_experience_years(exp_str: str | None) -> int | None:
    """Parse experience years from string.

    '10年以上' → 10, '3年' → 3, '6〜9年' → 6, '1年未満' → 0, empty → None
    """
    if not exp_str or exp_str.strip() in ("", "未入力", "なし"):
        return None
    # Match first number in the string
    match = re.search(r"(\d+)", exp_str)
    if not match:
        return None
    years = int(match.group(1))
    # "1年未満" → treat as 0
    if "未満" in exp_str and years <= 1:
        return 0
    return years


def _determine_employment_state(profile: CandidateProfile) -> str:
    """Determine employment state: 就業中, 離職中, or 在学中."""
    status = profile.employment_status or ""
    if "在学中" in status:
        return "在学中"
    if "就業中" in status:
        return "就業中"
    return "離職中"


def _determine_age_bracket(age: int | None) -> str:
    """Determine age bracket for pattern matrix.

    Returns: '40s+', 'late_30s', 'young', or 'student' (handled separately).
    """
    if age is None:
        # Default to young if unknown
        return "young"
    if age >= 40:
        return "40s+"
    if age >= 35:
        return "late_30s"
    return "young"


def _select_pattern_type(
    age_bracket: str,
    experience_years: int | None,
    employment_state: str,
) -> str:
    """Select pattern type from the age x experience matrix."""
    if employment_state == "在学中":
        return "G"

    has_exp = experience_years is not None and experience_years > 0

    if has_exp:
        if experience_years >= 10:
            if age_bracket in ("40s+", "late_30s"):
                return "A"
            else:
                return "B1"
        elif experience_years >= 6:
            return "B1"
        elif experience_years >= 3:
            return "B2"
        elif experience_years >= 1:
            if age_bracket in ("40s+", "late_30s"):
                return "C"
            else:
                return "E"
        else:
            # experience_years == 0 (未満)
            if employment_state == "就業中":
                return "F_就業中" if age_bracket == "young" else "D_就業中"
            else:
                return "F_離職中" if age_bracket == "young" else "D_離職中"
    else:
        # No experience data
        if age_bracket in ("40s+", "late_30s"):
            if employment_state == "就業中":
                return "D_就業中"
            else:
                return "D_離職中"
        else:
            if employment_state == "就業中":
                return "F_就業中"
            else:
                return "F_離職中"


def should_use_pattern(profile: CandidateProfile) -> bool:
    """Returns True if candidate should use pattern matching (no substantial work history/self_pr).

    Pattern matching is used when the candidate has no meaningful work history
    or self-PR to personalize from.
    """
    has_work_history = bool(
        profile.work_history_summary
        and profile.work_history_summary.strip()
        and profile.work_history_summary.strip() not in ("未入力", "なし", "-", "ー")
    )
    has_self_pr = bool(
        profile.self_pr
        and profile.self_pr.strip()
        and profile.self_pr.strip() not in ("未入力", "なし", "-", "ー")
    )

    return not has_work_history and not has_self_pr


def _find_pattern(
    pattern_type: str,
    patterns: list[dict],
    employment_state: str,
) -> dict | None:
    """Find the best matching pattern from the patterns list.

    Patterns may have employment_variant to distinguish 就業中/離職中 variants.
    """
    # First try exact match including employment variant suffix
    for p in patterns:
        if p["pattern_type"] == pattern_type:
            variant = p.get("employment_variant")
            if variant is None:
                return p
            if variant == employment_state:
                return p

    # Try base pattern type (strip employment suffix)
    base_type = pattern_type.split("_")[0]
    for p in patterns:
        if p["pattern_type"] == base_type:
            variant = p.get("employment_variant")
            if variant is None:
                return p
            if variant == employment_state:
                return p

    # Fallback: any pattern with matching base
    for p in patterns:
        if p["pattern_type"].startswith(base_type):
            return p

    return None


def _apply_qualification_modifier(
    text: str,
    qualifications: str,
    qualification_modifiers: list[dict],
) -> str:
    """Apply qualification-based text modifier if applicable.

    qualification_modifiers items have:
        qualification_combo: list of qualification keywords that must ALL be present
        replacement_text: text to replace a placeholder or append
    """
    if not qualification_modifiers or not qualifications:
        return text

    for modifier in qualification_modifiers:
        combo = modifier.get("qualification_combo", [])
        if all(q in qualifications for q in combo):
            replacement = modifier.get("replacement_text", "")
            if replacement:
                # Replace {資格修飾} placeholder if present, otherwise prepend
                if "{資格修飾}" in text:
                    text = text.replace("{資格修飾}", replacement)
                else:
                    text = replacement + text
            break

    # Clean up unused placeholder
    text = text.replace("{資格修飾}", "")
    return text


def match_pattern(
    profile: CandidateProfile,
    patterns: list[dict],
    qualification_modifiers: list[dict],
    feature_rotation_index: int = 0,
) -> tuple[str, str, str]:
    """Match a candidate to a pattern and generate personalized text.

    Args:
        profile: Candidate profile.
        patterns: List of pattern definitions with pattern_type, template_text,
            feature_variations, and optional employment_variant.
        qualification_modifiers: List of qualification-based text modifiers.
        feature_rotation_index: Index for rotating through feature variations.

    Returns:
        Tuple of (pattern_type, personalized_text, debug_info).

    Raises:
        ValueError: If no matching pattern is found.
    """
    age = _parse_age(profile.age)
    experience_years = _parse_experience_years(profile.experience_years)
    employment_state = _determine_employment_state(profile)
    age_bracket = _determine_age_bracket(age)

    pattern_type = _select_pattern_type(age_bracket, experience_years, employment_state)

    debug_parts = [
        f"age={age}({age_bracket})",
        f"exp={experience_years}",
        f"status={employment_state}",
        f"pattern={pattern_type}",
    ]

    pattern = _find_pattern(pattern_type, patterns, employment_state)
    if pattern is None:
        raise ValueError(
            f"パターン '{pattern_type}' が見つかりません "
            f"(age={age}, exp={experience_years}, status={employment_state})"
        )

    template_text = pattern["template_text"]

    # Select feature variation by rotation
    feature_variations = pattern.get("feature_variations", [])
    if feature_variations:
        idx = feature_rotation_index % len(feature_variations)
        feature = feature_variations[idx]
        debug_parts.append(f"feature_idx={idx}/{len(feature_variations)}")
    else:
        feature = ""

    # Replace placeholders
    personalized = template_text.replace("{特色}", feature)

    # Replace {N} with experience years if available
    if experience_years is not None and experience_years > 0:
        personalized = personalized.replace("{N}", str(experience_years))
    else:
        personalized = personalized.replace("{N}", "")

    # Replace {職種名} with qualification-derived job name
    job_name = _resolve_job_name(profile.qualifications or "")
    personalized = personalized.replace("{職種名}", job_name)

    # Apply qualification modifiers
    personalized = _apply_qualification_modifier(
        personalized,
        profile.qualifications or "",
        qualification_modifiers,
    )

    debug_info = ", ".join(debug_parts)
    return pattern_type, personalized.strip(), debug_info


def _resolve_job_name(qualifications: str) -> str:
    """Resolve primary job name from qualifications string."""
    if "看護師" in qualifications:
        return "看護師"
    if "理学療法士" in qualifications:
        return "理学療法士"
    if "言語聴覚士" in qualifications:
        return "言語聴覚士"
    if "作業療法士" in qualifications:
        return "作業療法士"
    if "医療事務" in qualifications:
        return "医療事務"
    return ""
