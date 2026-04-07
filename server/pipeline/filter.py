from __future__ import annotations

import re
from datetime import datetime, timedelta

from db.sheets_client import label_for_category
from models.profile import CandidateProfile


# Qualifications required for each job category
_REQUIRED_QUALIFICATIONS: dict[str, list[str]] = {
    "nurse": ["看護師", "准看護師"],
    "rehab_pt": ["理学療法士"],
    "rehab_st": ["言語聴覚士"],
    "rehab_ot": ["作業療法士"],
    "dietitian": ["管理栄養士"],
    # counselor: resolved via desired_job, no specific qualification required
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


def _parse_experience_years(exp_str: str | None) -> int | None:
    """Parse experience years from string like '10年以上' → 10."""
    if not exp_str or exp_str.strip() in ("", "未入力", "なし"):
        return None
    match = re.search(r"(\d+)", exp_str)
    if not match:
        return None
    years = int(match.group(1))
    if "未満" in exp_str and years <= 1:
        return 0
    return years


_DATE_PATTERNS = [
    r"\d{4}/\d{1,2}/\d{1,2}",   # 2026/3/1 or 2026/03/01
    r"\d{4}-\d{1,2}-\d{1,2}",   # 2026-03-01
    r"\d{4}年\d{1,2}月\d{1,2}日",  # 2026年3月1日
]
_DATE_RE = re.compile("|".join(_DATE_PATTERNS))

_DATE_FORMATS = ["%Y/%m/%d", "%Y-%m-%d", "%Y年%m月%d日"]

# 相対時間パターン: "1時間前", "3日前", "30分前" など
_RELATIVE_RE = re.compile(r"(\d+)\s*(分|時間|日|週間|ヶ月|ヵ月|か月)\s*前")

_RELATIVE_UNITS: dict[str, str] = {
    "分": "minutes",
    "時間": "hours",
    "日": "days",
    "週間": "weeks",
    "ヶ月": "months",
    "ヵ月": "months",
    "か月": "months",
}


def _parse_scout_dates(scout_sent_date: str) -> list[datetime]:
    """Parse comma/newline-separated scout dates into a sorted list (oldest first).

    Supports absolute dates (2026/03/01, 2026-03-01, 2026年3月1日)
    and relative times (1時間前, 3日前, 30分前).
    """
    if not scout_sent_date or not scout_sent_date.strip():
        return []
    now = datetime.now()
    dates: list[datetime] = []

    # Parse absolute dates
    for m in _DATE_RE.findall(scout_sent_date):
        for fmt in _DATE_FORMATS:
            try:
                dates.append(datetime.strptime(m, fmt))
                break
            except ValueError:
                continue

    # Parse relative times
    for m in _RELATIVE_RE.finditer(scout_sent_date):
        num = int(m.group(1))
        unit_ja = m.group(2)
        unit = _RELATIVE_UNITS.get(unit_ja)
        if unit == "months":
            dates.append(now - timedelta(days=num * 30))
        elif unit == "weeks":
            dates.append(now - timedelta(weeks=num))
        elif unit:
            dates.append(now - timedelta(**{unit: num}))

    dates.sort()
    return dates


def _get_builtin_settings(validation_config: dict) -> dict:
    """Extract builtin on/off settings from qualification_rules.

    Supports both old format (list of rules) and new format (dict with builtin key).
    Old format = all builtin checks enabled (backward compatible).
    """
    defaults = {
        "require_qualification": True,
        "reject_non_clinical": True,
        "reject_already_scouted": True,
        "max_scout_count": 2,
        "resend_interval_days": 7,
    }
    qual_rules = validation_config.get("qualification_rules")
    if isinstance(qual_rules, dict) and "builtin" in qual_rules:
        merged = {**defaults, **qual_rules.get("builtin", {})}
        return merged
    # Old format or missing: all enabled with defaults
    return defaults


def _get_qualification_rules(validation_config: dict) -> list:
    """Extract per-job qualification rules from validation config."""
    qual_rules = validation_config.get("qualification_rules")
    if isinstance(qual_rules, dict):
        return qual_rules.get("qualification_rules", [])
    if isinstance(qual_rules, list):
        return qual_rules
    return []


def _get_custom_rules(validation_config: dict) -> list:
    """Extract custom rules from validation config."""
    qual_rules = validation_config.get("qualification_rules")
    if isinstance(qual_rules, dict):
        return qual_rules.get("custom_rules", [])
    return []


async def filter_candidate(
    profile: CandidateProfile,
    company_id: str,
    job_category: str,
    validation_config: dict,
) -> tuple[str | None, list[str]]:
    """Filter a candidate based on company validation rules.

    Returns:
        (hard_block_reason, soft_warnings)
        - hard_block_reason: 生成を中止する必要がある理由 (None なら通過)
        - soft_warnings: 生成は行うが UI に警告として出すべき理由のリスト

    方針: 「基本全て生成して警告で示す」
    - 送信済み (スカウト履歴あり) のみハードブロック (送信予算の浪費を防ぐ)
    - 資格不一致 / 非臨床経験 / 年齢制限 / AI判定NG はソフト (警告で生成は続行)
    """
    builtin = _get_builtin_settings(validation_config)
    warnings: list[str] = []

    # --- Soft check 1: 資格一致 ---
    if builtin.get("require_qualification", True):
        if not _has_qualifying_qualification(profile.qualifications or "", job_category):
            quals = profile.qualifications or "(資格なし)"
            warnings.append(
                f"[資格不一致] {label_for_category(job_category)}に必要な資格がありません (候補者の資格: {quals})"
            )

    # --- Soft check 2: 非臨床経験のみ (nurse のみ対象) ---
    if builtin.get("reject_non_clinical", True) and job_category == "nurse":
        if _is_non_clinical_only(profile.experience_type or "", profile.employment_status or ""):
            warnings.append(
                f"[非臨床経験] 臨床看護経験が見当たりません (経験: {profile.experience_type or '未入力'})"
            )

    # --- HARD block: 送信済み (送信予算を浪費しないため) ---
    if builtin.get("reject_already_scouted", True):
        scout_dates = _parse_scout_dates(profile.scout_sent_date or "")
        if scout_dates:
            max_count = builtin.get("max_scout_count", 2)
            interval_days = builtin.get("resend_interval_days", 7)
            if len(scout_dates) >= max_count:
                return (
                    f"[送信済み] スカウト{len(scout_dates)}回送信済 (上限{max_count}回): {profile.scout_sent_date}",
                    warnings,
                )
            latest = scout_dates[-1]
            days_since = (datetime.now() - latest).days
            if days_since < interval_days:
                return (
                    f"[送信済み] {days_since}日前に送信済 (再送間隔{interval_days}日未満): {profile.scout_sent_date}",
                    warnings,
                )

    # --- Soft check 3: 年齢制限 ---
    age_range = validation_config.get("age_range", {})
    min_age = age_range.get("min") if age_range else validation_config.get("min_age")
    max_age = age_range.get("max") if age_range else validation_config.get("max_age")
    if min_age is not None or max_age is not None:
        age = _parse_age(profile.age)
        if age is not None:
            if min_age is not None and age < min_age:
                warnings.append(f"[年齢制限] {age}歳 (下限: {min_age}歳)")
            elif max_age is not None and age > max_age:
                warnings.append(f"[年齢制限] {age}歳 (上限: {max_age}歳)")

    # --- Soft check 4: AI判定 ---
    ai_conditions = _get_ai_conditions(validation_config)
    if ai_conditions:
        reason = await _check_ai_conditions(ai_conditions, profile)
        if reason:
            warnings.append(f"[AI判定] {reason}")

    return None, warnings


def _get_ai_conditions(validation_config: dict) -> list[str]:
    """Extract AI condition strings from validation config."""
    qual_rules = validation_config.get("qualification_rules")
    if isinstance(qual_rules, dict):
        return qual_rules.get("ai_conditions", [])
    return []


async def _check_ai_conditions(conditions: list[str], profile: CandidateProfile) -> str | None:
    """Use AI to check if candidate violates any conditions."""
    from pipeline.ai_generator import generate_personalized_text

    conditions_text = "\n".join(f"- {c}" for c in conditions)

    # Build a compact profile summary for AI
    fields = []
    for key in ["qualifications", "experience_type", "experience_years", "employment_status", "age", "self_pr", "work_history_summary"]:
        val = getattr(profile, key, None)
        if val and str(val).strip() not in ("", "未入力", "なし"):
            fields.append(f"{key}: {val}")
    profile_text = "\n".join(fields) if fields else "情報なし"

    system = f"""あなたはスカウト対象の候補者をフィルタリングする判定者です。
以下のNG条件に該当する候補者は除外してください。

NG条件:
{conditions_text}

判定ルール:
- 候補者のプロフィール情報を見て、いずれかのNG条件に該当するか判定する
- 該当する場合: "NG: [該当する条件の要約]" と回答
- 該当しない場合: "OK" とだけ回答
- 情報が不足していて判定できない場合は "OK" とする（疑わしきは通す）
- 回答は1行のみ。説明不要"""

    try:
        result = await generate_personalized_text(
            system_prompt=system,
            user_prompt=profile_text,
            model_name=None,
        )
        result = result.strip()
        if result.startswith("NG"):
            return f"AI判定: {result[3:].strip()}" if len(result) > 3 else "AI判定: NG条件に該当"
    except Exception:
        # AI failure = don't filter (fail open)
        pass

    return None
