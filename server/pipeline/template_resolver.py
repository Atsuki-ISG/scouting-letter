from models.profile import CandidateProfile
from models.generation import GenerateOptions


def resolve_template_type(
    profile: CandidateProfile,
    options: GenerateOptions,
    job_category: str,
) -> str:
    """Determine template type based on options, profile, and job category.

    Args:
        profile: Candidate profile.
        options: Generation options (force_seishain, is_resend).
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
    elif options.is_resend:
        send_type = "再送"
    else:
        send_type = "初回"

    return f"{employment}_{send_type}"
