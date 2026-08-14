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
