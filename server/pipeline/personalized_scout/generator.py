"""Thin wrapper around `generate_structured` that knows about the
personalized_scout block schema. Kept separate from `pipeline.py` so
tests can mock just the AI call without stubbing out the whole flow.
"""
from __future__ import annotations

from typing import Literal

from pipeline.ai_generator import generate_structured, GenerationResult
from models.profile import CandidateProfile

from .prompt import (
    build_system_prompt,
    build_user_prompt,
    response_schema,
)
from .text_builder import BLOCK_PLACEHOLDERS, L2_BLOCKS


async def generate_blocks(
    *,
    level: Literal["L2", "L3"],
    profile: CandidateProfile,
    job_category: str,
    company_profile: str,
    prompt_sections_text: str,
    template_body: str,
    max_output_tokens: int = 4096,
    temperature: float = 0.7,
) -> tuple[dict[str, str], GenerationResult]:
    """Call the model once and return the named blocks + token metadata.

    The returned dict is always guaranteed to have every block key
    for the requested level (missing/empty fields become ""), so
    downstream code doesn't need to defend against partial payloads.
    """
    schema = response_schema(level)
    system_prompt = build_system_prompt(
        level=level,
        company_profile=company_profile,
        prompt_sections_text=prompt_sections_text,
        template_body=template_body,
    )
    user_prompt = build_user_prompt(profile, job_category)

    parsed, meta = await generate_structured(
        system_prompt,
        user_prompt,
        schema,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
    )

    expected = L2_BLOCKS if level == "L2" else BLOCK_PLACEHOLDERS
    blocks: dict[str, str] = {}
    for name in expected:
        value = parsed.get(name, "")
        blocks[name] = (value or "").strip() if isinstance(value, str) else ""
    return blocks, meta
