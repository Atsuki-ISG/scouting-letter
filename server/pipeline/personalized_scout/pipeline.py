"""End-to-end L2/L3 scout generation.

Parallel to `pipeline.orchestrator._process_candidate`. Shares the
expensive common pieces (job_category resolution, validation) by
importing existing functions — nothing is copy-pasted.
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from db.sheets_client import sheets_client, label_for_category
from models.profile import CandidateProfile
from pipeline.job_category_resolver import resolve_job_category
from pipeline.filter import filter_candidate
from pipeline.template_resolver import resolve_template_type
from pipeline.prompt_validator import validate_output_text
from pipeline.routing import route as route_candidate, resolve_tone_instruction

from .generator import generate_blocks
from .text_builder import (
    BLOCK_PLACEHOLDERS,
    L2_BLOCKS,
    build_scout_from_blocks,
    compute_personalization_stats,
    list_placeholders,
)

logger = logging.getLogger(__name__)


class PersonalizedScoutError(Exception):
    """Raised for user-visible failures during L2/L3 generation.

    The API endpoint catches this and turns it into a structured
    failure response so the extension UI can show the error on the
    specific candidate card.
    """

    def __init__(self, reason: str, *, stage: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.stage = stage


async def generate_personalized_scout(
    *,
    company_id: str,
    profile: CandidateProfile,
    level: Literal["L2", "L3"],
    template_row_index: Optional[int] = None,
    force_employment: Optional[str] = None,
    job_category_filter: Optional[str] = None,
    is_resend: bool = False,
    tone_instruction: Optional[str] = None,
) -> dict:
    """Run the L2/L3 pipeline for a single candidate.

    Returns a dict matching the `PersonalizedGenerateResponse` pydantic
    model — the endpoint just wraps it.
    """
    config = sheets_client.get_company_config(company_id)

    # 1. Resolve job category (reuse existing multi-stage resolver)
    company_categories = _company_categories_from_config(config)
    keywords = config.get("job_category_keywords", [])
    resolution = resolve_job_category(
        profile,
        company_categories,
        keywords,
        explicit=job_category_filter,
    )
    if resolution.category is None:
        fr = resolution.failure
        return _failure_response(
            profile,
            template_type="",
            job_category=None,
            filter_reason=(
                f"[職種判定不能] {fr.human_message if fr else '職種判定に失敗しました'}"
            ),
            level=level,
        )
    job_category = resolution.category

    # Build an options shim for resolve_template_type (it expects
    # the old GenerateOptions object — we fake the fields it reads).
    class _OptShim:
        pass

    opts = _OptShim()
    opts.is_resend = is_resend
    opts.force_seishain = False
    opts.force_employment = force_employment

    template_type = resolve_template_type(profile, opts, job_category)

    # 2. Soft/hard filter (reuses existing filter_candidate)
    hard_block_reason, soft_warnings = await filter_candidate(
        profile, company_id, job_category, config["validation_config"]
    )
    if hard_block_reason:
        return _failure_response(
            profile,
            template_type=template_type,
            job_category=job_category,
            filter_reason=hard_block_reason,
            validation_warnings=soft_warnings,
            level=level,
        )

    # 3. Resolve template body.
    template_body = _load_template_body(
        config, job_category, template_type, template_row_index
    )
    if template_body is None:
        return _failure_response(
            profile,
            template_type=template_type,
            job_category=job_category,
            filter_reason=(
                f"[テンプレート未設定] {label_for_category(job_category)}/{template_type}"
                f"用のテンプレートが登録されていません"
            ),
            validation_warnings=soft_warnings,
            level=level,
        )

    # L2/L3 requires the template to declare block placeholders.
    # If the template body only has {personalized_text} (the L1
    # placeholder) we refuse early with a clear message — this is
    # what tells the director "go add the new placeholders first".
    placeholders = list_placeholders(template_body)
    if not placeholders:
        return _failure_response(
            profile,
            template_type=template_type,
            job_category=job_category,
            filter_reason=(
                "[L2/L3 テンプレ未対応] このテンプレートには {opening} などの "
                "ブロックプレースホルダーが含まれていません。L1 用テンプレート "
                "は新パーソナライズ生成に使えません。"
            ),
            validation_warnings=soft_warnings,
            level=level,
        )

    # 4. Load company profile + company-specific prompt sections.
    company_profile = sheets_client.get_company_profile(company_id) or ""
    prompt_sections_text = _flatten_prompt_sections(
        config.get("prompt_sections", []), job_category
    )

    # 4.5. Load approved knowledge rules for prompt injection.
    # Only load categories that produce permanent, per-candidate guidance.
    # Hook expressions / template-level ideas live outside the pool now.
    PERSONALIZATION_CATEGORIES = ["tone", "expression", "profile_handling", "qualification"]
    knowledge_rules: list[str] = []
    try:
        pool = sheets_client.get_knowledge_pool(
            company_id, categories=PERSONALIZATION_CATEGORIES,
        )
        knowledge_rules = [item["rule"] for item in pool if item.get("rule")]
    except Exception as e:
        logger.warning(f"[{profile.member_id}] knowledge pool load failed: {e}")

    # 4.6. Auto-resolve tone_instruction via routing rules when not
    # provided explicitly by the caller. This lets the extension call
    # /generate without knowing about tones — the Sheets-managed rules
    # decide the tone from candidate attributes.
    routing_meta: Optional[dict] = None
    if tone_instruction is None:
        routing_meta = route_candidate(profile)
        resolved = resolve_tone_instruction(routing_meta.get("tone"))
        if resolved:
            tone_instruction = resolved
            logger.info(
                f"[{profile.member_id}] routed to "
                f"skeleton={routing_meta.get('skeleton')} tone={routing_meta.get('tone')} "
                f"attribute={routing_meta.get('attribute')} "
                f"rule={routing_meta.get('matched_rule')}"
            )

    # 5. Call structured generation.
    try:
        blocks, meta = await generate_blocks(
            level=level,
            profile=profile,
            job_category=job_category,
            company_profile=company_profile,
            prompt_sections_text=prompt_sections_text,
            template_body=template_body,
            knowledge_rules=knowledge_rules or None,
            tone_instruction=tone_instruction,
        )
    except Exception as e:
        logger.exception(f"[{profile.member_id}] structured generation failed")
        return _failure_response(
            profile,
            template_type=template_type,
            job_category=job_category,
            filter_reason=f"[AI生成エラー] {e}",
            validation_warnings=soft_warnings,
            level=level,
        )

    # For L3, the template body should have all 5 placeholders. For
    # L2 only opening/closing_cta are generated — the other blocks
    # in the body are left empty. Callers are expected to author L2
    # templates that don't have the other placeholders (or to accept
    # the gaps).
    full_scout_text = build_scout_from_blocks(template_body, blocks)

    # 6. Output validation (reuse existing foreign-company check).
    output_errors = validate_output_text(company_id, full_scout_text)
    if output_errors:
        return _failure_response(
            profile,
            template_type=template_type,
            job_category=job_category,
            filter_reason=f"[出力検証] {'; '.join(output_errors)}",
            validation_warnings=soft_warnings,
            level=level,
        )

    # 7. Measure.
    stats = compute_personalization_stats(template_body, blocks, level=level)

    return {
        "member_id": profile.member_id,
        "template_type": template_type,
        "generation_path": "ai_structured",
        "personalized_text": "\n\n".join(
            blocks.get(k, "") for k in BLOCK_PLACEHOLDERS if blocks.get(k)
        ),
        "full_scout_text": full_scout_text,
        "block_contents": blocks,
        "personalization_stats": stats,
        "job_category": job_category,
        "is_favorite": bool(getattr(profile, "is_favorite", False)),
        "validation_warnings": soft_warnings,
        "routing": routing_meta,
        "token_usage": {
            "prompt_tokens": meta.prompt_tokens,
            "output_tokens": meta.output_tokens,
            "total_tokens": meta.total_tokens,
            "model_name": meta.model_name,
        },
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _failure_response(
    profile: CandidateProfile,
    *,
    template_type: str,
    job_category: Optional[str],
    filter_reason: str,
    validation_warnings: Optional[list[str]] = None,
    level: str = "",
) -> dict:
    return {
        "member_id": profile.member_id,
        "template_type": template_type or "",
        "generation_path": "filtered_out",
        "personalized_text": "",
        "full_scout_text": "",
        "block_contents": {},
        "personalization_stats": {
            "level": level,
            "total_chars": 0,
            "personalized_chars": 0,
            "fixed_chars": 0,
            "ratio": 0.0,
            "per_block_chars": {name: 0 for name in BLOCK_PLACEHOLDERS},
        },
        "job_category": job_category,
        "is_favorite": bool(getattr(profile, "is_favorite", False)),
        "validation_warnings": validation_warnings or [],
        "filter_reason": filter_reason,
    }


def _company_categories_from_config(config: dict) -> list[str]:
    """Return the list of job categories this company has templates for.

    Mirrors the logic in orchestrator._company_categories_from_config
    without importing it (that is a module-private helper).
    """
    categories: set[str] = set()
    for key in (config.get("templates") or {}).keys():
        if ":" in key:
            jc = key.split(":", 1)[0]
            if jc:
                categories.add(jc)
    return sorted(categories)


def _load_template_body(
    config: dict,
    job_category: str,
    template_type: str,
    template_row_index: Optional[int],
) -> Optional[str]:
    """Find the template body matching (job_category, template_type)
    in the company config. If `template_row_index` is given we try
    the exact row first and fall back to the normal lookup — this
    lets the UI force a specific template.
    """
    templates = config.get("templates") or {}

    if template_row_index is not None:
        for tkey, tdata in templates.items():
            if tdata.get("_row_index") == template_row_index:
                return (tdata.get("body") or "").replace("\\n", "\n")

    for key in (
        f"{job_category}:{template_type}",
        template_type,
        f"{job_category}:{template_type.split('_')[0]}_初回",
        f"{template_type.split('_')[0]}_初回",
    ):
        tdata = templates.get(key)
        if tdata and tdata.get("body"):
            return (tdata["body"] or "").replace("\\n", "\n")

    return None


def _flatten_prompt_sections(sections: list[dict], job_category: str) -> str:
    """Collapse the relevant prompt sections into one text blob for
    the L2/L3 system prompt. Uses the same job_category-parent
    matching rule as the L1 orchestrator.
    """
    jc_parent = job_category.rsplit("_", 1)[0] if "_" in job_category else None
    jc_match = {job_category, jc_parent} if jc_parent else {job_category}

    lines: list[str] = []
    for s in sections or []:
        sec_jc = s.get("job_category") or ""
        if sec_jc and sec_jc not in jc_match:
            continue
        content = (s.get("content") or "").strip()
        if not content:
            continue
        label = s.get("section_type") or ""
        lines.append(f"### {label}\n{content}" if label else content)
    return "\n\n".join(lines)
