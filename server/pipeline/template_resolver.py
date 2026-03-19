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
    # Determine employment type
    if options.force_seishain:
        employment = "正社員"
    else:
        desired = profile.desired_employment_type or ""
        if "正職員" in desired or "正社員" in desired:
            employment = "正社員"
        else:
            employment = "パート"

    # Determine send type
    send_type = "再送" if options.is_resend else "初回"

    return f"{employment}_{send_type}"
