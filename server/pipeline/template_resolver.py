from __future__ import annotations

import re

from models.profile import CandidateProfile
from models.generation import GenerateOptions

# ジョブメドレーのカード上で「スカウト送信日」が未送信を意味する表記。
# 抽出はラベル直後のテキストを拾うため、日付以外が入るケースを空扱いにする。
_EMPTY_SENT_DATE_VALUES = {"", "-", "－", "ー", "—", "なし", "未送信"}


def _resolve_is_resend(profile: CandidateProfile, options: GenerateOptions) -> bool:
    """初回/再送の判定。

    send_type="auto" は候補者ごとにスカウト送信日の有無で判定するため、
    初回と再送が混ざったリストでもそれぞれ正しいテンプレートになる。
    send_type 未指定（旧クライアント）は従来どおり is_resend フラグに従う。
    """
    send_type = getattr(options, "send_type", None)
    if send_type == "resend":
        return True
    if send_type == "initial":
        return False
    if send_type == "auto":
        sent = (profile.scout_sent_date or "").strip()
        return sent not in _EMPTY_SENT_DATE_VALUES
    return options.is_resend


def resolve_template_type(
    profile: CandidateProfile,
    options: GenerateOptions,
    job_category: str,
) -> str:
    """Determine template type based on options, profile, and job category.

    Args:
        profile: Candidate profile.
        options: Generation options (force_seishain, is_resend, send_type).
        job_category: Resolved job category.

    Returns:
        Template type string like "パート_初回", "正社員_再送", etc.
    """
    # Categories with only part-time templates
    part_only_categories = {"counselor"}

    # Determine employment type
    if job_category in part_only_categories:
        employment = "パート"
    elif options.force_employment:
        employment = options.force_employment
    elif options.force_seishain:
        employment = "正社員"
    else:
        desired = profile.desired_employment_type or ""
        if "正職員" in desired or "正社員" in desired:
            employment = "正社員"
        elif "契約" in desired:
            employment = "契約"
        else:
            employment = "パート"

    # Determine send type
    if profile.is_favorite and job_category not in part_only_categories:
        send_type = "お気に入り"
    elif _resolve_is_resend(profile, options):
        send_type = "再送"
    else:
        send_type = "初回"

    return f"{employment}_{send_type}"


# 年代別テンプレート: 種別名の末尾に年齢帯を付けた行（例: 「正社員_初回_〜39歳」
# 「正社員_初回_40歳〜」「正社員_初回_25-29歳」）を置くと、その年齢の候補者には
# 帯つきの行が優先される。該当する帯が無い・年齢不明のときは従来の種別にそのまま
# フォールバックするので、帯つき行が無い会社の挙動は変わらない。
_AGE_BAND_RE = re.compile(r"^(?:(\d+)歳?)?[〜~\-－](?:(\d+)歳?)?$")


def parse_age_band(band: str) -> tuple[int | None, int | None] | None:
    """「〜39歳」→(None, 39)、「40歳〜」→(40, None)、「25-29歳」→(25, 29)。

    上限・下限は両端を含む。年齢帯として読めなければ None。
    """
    m = _AGE_BAND_RE.match(band.strip())
    if not m:
        return None
    lo, hi = m.group(1), m.group(2)
    if lo is None and hi is None:
        return None
    return (int(lo) if lo else None, int(hi) if hi else None)


def _parse_age(age_str: str | None) -> int | None:
    if not age_str:
        return None
    m = re.search(r"(\d+)", age_str)
    return int(m.group(1)) if m else None


def find_age_variant(
    templates: dict[str, dict],
    job_category: str,
    template_type: str,
    age_str: str | None,
) -> dict | None:
    """template_type に年齢帯を付けた行のうち、候補者の年齢を含むものを返す。

    職種指定のある行を職種なしの汎用行より優先する。年齢不明・該当帯なしは None。
    """
    age = _parse_age(age_str)
    if age is None:
        return None
    prefix = f"{template_type}_"
    candidates: list[tuple[int, dict]] = []
    for tpl in templates.values():
        ttype = tpl.get("type", "")
        if not ttype.startswith(prefix):
            continue
        tjc = tpl.get("job_category", "")
        if tjc and tjc != job_category:
            continue
        band = parse_age_band(ttype[len(prefix):])
        if band is None:
            continue
        lo, hi = band
        if lo is not None and age < lo:
            continue
        if hi is not None and age > hi:
            continue
        candidates.append((0 if tjc == job_category else 1, tpl))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]
