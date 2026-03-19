from __future__ import annotations

import re

from models.profile import CandidateProfile


# Qualifications required for each job category
_REQUIRED_QUALIFICATIONS: dict[str, list[str]] = {
    "nurse": ["看護師", "准看護師"],
    "pt": ["理学療法士"],
    "st": ["言語聴覚士"],
    "ot": ["作業療法士"],
    # medical_office: no additional qualification check needed
}

# Non-clinical roles that don't count as nursing experience
_NON_CLINICAL_ROLES = [
    "保健師",
    "事務",
    "医療事務",
    "生活支援員",
    "相談員",
    "ケースワーカー",
    "介護支援専門員",
    "支援相談員",
    "管理栄養士",
    "栄養士",
    "調理",
    "受付",
    "クラーク",
    "教員",
    "教諭",
    "保育士",
    "児童指導員",
]

_NON_CLINICAL_PATTERN = re.compile("|".join(re.escape(r) for r in _NON_CLINICAL_ROLES))

# Clinical nursing keywords that override non-clinical exclusion
_CLINICAL_KEYWORDS = [
    "病棟",
    "外来",
    "訪問看護",
    "オペ室",
    "手術室",
    "ICU",
    "救急",
    "クリニック",
    "診療所",
    "透析",
    "内視鏡",
    "病院",
    "施設看護",
    "看護師",
    "老健",
    "特養",
    "有料老人ホーム",
    "デイサービス",
    "ホームヘルパー",
]

_CLINICAL_PATTERN = re.compile("|".join(re.escape(k) for k in _CLINICAL_KEYWORDS))


def _has_qualifying_qualification(qualifications: str, job_category: str) -> bool:
    """Check if qualifications string contains at least one valid qualification for the category."""
    required = _REQUIRED_QUALIFICATIONS.get(job_category)
    if required is None:
        # medical_office etc. - always passes
        return True
    if not qualifications:
        return False
    return any(req in qualifications for req in required)


def _is_non_clinical_only(experience_type: str, employment_status: str) -> bool:
    """Check if experience is exclusively non-clinical.

    Returns True (should exclude) if experience contains ONLY non-clinical roles
    and no clinical nursing experience.
    """
    if not experience_type or experience_type.strip() in ("", "未入力"):
        # No experience listed - if currently working, assume clinical
        if employment_status and "就業中" in employment_status:
            return False
        # Not working and no experience - don't exclude on this check alone
        return False

    # Check if there's any clinical experience
    if _CLINICAL_PATTERN.search(experience_type):
        return False

    # Check if all listed roles are non-clinical
    if _NON_CLINICAL_PATTERN.search(experience_type):
        return True

    # Experience listed but doesn't match non-clinical patterns - assume clinical
    return False


def _parse_age(age_str: str | None) -> int | None:
    """Parse age from string like '44歳' → 44."""
    if not age_str:
        return None
    match = re.search(r"(\d+)", age_str)
    return int(match.group(1)) if match else None


def filter_candidate(
    profile: CandidateProfile,
    company_id: str,
    job_category: str,
    validation_config: dict,
) -> str | None:
    """Filter a candidate based on company validation rules.

    Args:
        profile: Candidate profile.
        company_id: Company identifier.
        job_category: Resolved job category.
        validation_config: Company-specific validation settings.

    Returns:
        None if candidate passes, or a filter_reason string if excluded.
    """
    # Check 1: Qualification match
    if not _has_qualifying_qualification(profile.qualifications or "", job_category):
        return f"資格不一致: {job_category}に必要な資格がありません"

    # Check 2: Non-clinical only exclusion
    if _is_non_clinical_only(profile.experience_type or "", profile.employment_status or ""):
        return "非臨床経験のみ: 臨床看護経験がありません"

    # Check 3: Already scouted
    if profile.scout_sent_date and profile.scout_sent_date.strip():
        return f"スカウト送信済み: {profile.scout_sent_date}"

    # Check 4: Age range
    min_age = validation_config.get("min_age")
    max_age = validation_config.get("max_age")
    if min_age is not None or max_age is not None:
        age = _parse_age(profile.age)
        if age is not None:
            if min_age is not None and age < min_age:
                return f"年齢下限: {age}歳 (下限: {min_age}歳)"
            if max_age is not None and age > max_age:
                return f"年齢上限: {age}歳 (上限: {max_age}歳)"

    return None
