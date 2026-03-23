import re

# All known placeholder variants for personalized text insertion
_PLACEHOLDERS = [
    "{personalized_text}",
    "{ここにパーソナライズ文を挿入}",
    "{ここに生成した文章を挿入}",
    "{パーソナライズされた文章}",
]

_PLACEHOLDER_PATTERN = re.compile(
    "|".join(re.escape(p) for p in _PLACEHOLDERS)
)


def build_full_scout_text(template_body: str, personalized_text: str) -> str:
    """Replace personalized text placeholder in template body.

    Args:
        template_body: Template text containing a placeholder.
        personalized_text: Generated or pattern-matched personalized text.

    Returns:
        Complete scout text with personalized text inserted.
    """
    result = _PLACEHOLDER_PATTERN.sub(personalized_text, template_body)
    return result
