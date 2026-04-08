"""Block-based text builder and personalization measurement for
the personalized_scout pipeline.

A template body here uses named placeholders like `{opening}`,
`{bridge}`, `{facility_intro}`, `{job_framing}`, `{closing_cta}`.
Anything not in one of the known block names is treated as a fixed
section (e.g. `## 募集要項 ...`) and contributes to `fixed_chars`
in the measurement.
"""
from __future__ import annotations

import re
from typing import Literal

# Block names used by L2 and L3. The order matters: stats output
# preserves it, and the AI prompt references these names 1:1.
BLOCK_PLACEHOLDERS: tuple[str, ...] = (
    "opening",
    "bridge",
    "facility_intro",
    "job_framing",
    "closing_cta",
)

# L2 touches only these two blocks (bridge/facility_intro/job_framing
# stay as whatever is written in the template body).
L2_BLOCKS: tuple[str, ...] = ("opening", "closing_cta")

# Matches {opening}, {bridge}, etc. as literal substrings. We
# purposely don't use str.format because the template body often
# contains other unbalanced braces.
_BLOCK_PATTERN = re.compile(
    r"\{(" + "|".join(BLOCK_PLACEHOLDERS) + r")\}"
)


def list_placeholders(template_body: str) -> list[str]:
    """Return the block names that actually appear in the template body,
    in order of first appearance. Useful for:
      - deciding which blocks the AI should produce
      - refusing templates that don't have any of the new placeholders
    """
    seen: list[str] = []
    for m in _BLOCK_PATTERN.finditer(template_body or ""):
        name = m.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def build_scout_from_blocks(template_body: str, blocks: dict[str, str]) -> str:
    """Substitute each `{block_name}` placeholder with the matching
    value from `blocks`.

    - Placeholders not present in `blocks` are replaced with an empty
      string (e.g. L2 leaves bridge/facility_intro/job_framing blank).
    - Unknown keys in `blocks` are silently ignored — they cannot
      appear in the template body anyway.
    - The rest of the template body (募集要項 など) is left as-is.
    """
    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        return blocks.get(name, "") or ""

    return _BLOCK_PATTERN.sub(_sub, template_body or "")


def compute_personalization_stats(
    template_body: str,
    blocks: dict[str, str],
    *,
    level: Literal["L2", "L3"],
) -> dict:
    """Compute how much of the final scout text is personalized.

    Definitions used:
    - `personalized_chars` = sum of len() across all blocks that were
      actually substituted into the body (empty block → 0).
    - `fixed_chars` = length of the template body with ALL known
      block placeholders removed. This is the template "skeleton"
      that every candidate sees regardless of personalization.
    - `total_chars` = personalized + fixed (equals len(full_scout_text)
      up to any whitespace collapsing).
    - `ratio` = personalized / total, 0..1, or 0 if total is 0.
    - `per_block_chars` = per-block character counts, in the
      BLOCK_PLACEHOLDERS order, with missing blocks set to 0.
    """
    # Fixed scaffolding: remove placeholders entirely, then count.
    skeleton = _BLOCK_PATTERN.sub("", template_body or "")
    fixed_chars = len(skeleton)

    per_block: dict[str, int] = {}
    for name in BLOCK_PLACEHOLDERS:
        per_block[name] = len(blocks.get(name, "") or "")

    personalized_chars = sum(per_block.values())
    total_chars = personalized_chars + fixed_chars
    ratio = (personalized_chars / total_chars) if total_chars > 0 else 0.0

    return {
        "level": level,
        "total_chars": total_chars,
        "personalized_chars": personalized_chars,
        "fixed_chars": fixed_chars,
        "ratio": round(ratio, 4),
        "per_block_chars": per_block,
    }
