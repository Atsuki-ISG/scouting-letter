from __future__ import annotations

from models.profile import CandidateProfile


def build_system_prompt(
    sections: list[dict],
    template_body: str,
    examples: list[dict] | None = None,
) -> str:
    """Assemble prompt sections into a system prompt string.

    Args:
        sections: Ordered list of dicts with 'section_type' and 'content'.
        template_body: The template that the personalized text will be inserted into.
        examples: Optional list of good example dicts with 'title' and 'text'.

    Returns:
        Complete system prompt string.
    """
    parts: list[str] = []

    # Add all sections
    for section in sections:
        content = section.get("content", "")
        if content and content.strip():
            parts.append(content.strip())

    # Add template context (full body for tone reference)
    template_section = (
        "## テンプレート\n\n"
        "以下のテンプレートの中にパーソナライズ文が挿入されます。"
        "テンプレート全体のトーンに合わせてください。\n\n"
        f"```\n{template_body}\n```"
    )
    parts.append(template_section)

    # Add examples if available
    if examples:
        example_lines = ["## 最近の良い例\n"]
        for ex in examples:
            title = ex.get("title", "")
            text = ex.get("text", "")
            if text:
                header = f"### {title}\n" if title else ""
                example_lines.append(f"{header}{text}")
        parts.append("\n\n".join(example_lines))

    # Add output instructions
    parts.append(
        "## 出力指示\n\n"
        "パーソナライズ文のみを出力してください。説明・前置き・補足は不要です。"
    )

    return "\n\n---\n\n".join(parts)


def build_user_prompt(profile: CandidateProfile, job_category: str) -> str:
    """Format candidate profile as user message for LLM.

    Args:
        profile: Candidate profile with all available fields.
        job_category: Resolved job category.

    Returns:
        Formatted profile string for the user message.
    """
    fields = [
        ("職種カテゴリ", job_category),
        ("保有資格", profile.qualifications),
        ("経験職種", profile.experience_type),
        ("経験年数", profile.experience_years),
        ("就業状況", profile.employment_status),
        ("年齢", profile.age),
        ("性別", profile.gender),
        ("居住地", profile.area),
        ("希望職種", profile.desired_job),
        ("希望勤務地", profile.desired_area),
        ("希望雇用形態", profile.desired_employment_type),
        ("希望入職時期", profile.desired_start),
        ("自己PR", profile.self_pr),
        ("職務経歴概要", profile.work_history_summary),
        ("特記事項", profile.special_conditions),
    ]

    lines: list[str] = []
    for label, value in fields:
        if value and value.strip() and value.strip() not in ("未入力", "なし", "-", "ー"):
            lines.append(f"{label}: {value.strip()}")

    return "\n".join(lines)
