from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta

from models.generation import (
    GenerateRequest,
    GenerateResponse,
    GenerateOptions,
    BatchGenerateRequest,
    BatchGenerateResponse,
)
from pipeline.job_category_resolver import resolve_job_category
from pipeline.filter import filter_candidate
from pipeline.template_resolver import resolve_template_type
from pipeline.pattern_matcher import should_use_pattern, match_pattern
from pipeline.prompt_builder import build_system_prompt, build_user_prompt
from pipeline.ai_generator import generate_personalized_text, GenerationResult
from pipeline.prompt_validator import validate_prompt_content
from pipeline.text_builder import build_full_scout_text
from config import get_model_pricing, GEMINI_MODEL

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

LOG_SHEET = "生成ログ"
LOG_HEADERS = [
    "timestamp", "company", "member_id", "job_category",
    "template_type", "generation_path", "pattern_type",
    "status", "detail", "personalized_text_preview",
    "prompt_tokens", "output_tokens", "estimated_cost",
]


def _write_generation_logs(
    company_id: str,
    results: list[GenerateResponse],
    token_usage: dict[str, dict],
) -> None:
    """Write generation results to the log sheet (fire-and-forget).

    token_usage: {member_id: {"prompt_tokens": int, "output_tokens": int, "estimated_cost": float}}
    """
    try:
        from db.sheets_writer import sheets_writer
        sheets_writer.ensure_sheet_exists(LOG_SHEET, LOG_HEADERS)

        now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
        rows = []
        for r in results:
            is_error = r.generation_path == "filtered_out" and (
                r.filter_reason or ""
            ).startswith("生成エラー")
            status = "エラー" if is_error else (
                "除外" if r.generation_path == "filtered_out" else "成功"
            )
            detail = r.filter_reason or ""
            preview = (r.personalized_text or "")[:200]
            usage = token_usage.get(r.member_id, {})
            rows.append([
                now,
                company_id,
                r.member_id,
                r.job_category or "",
                r.template_type or "",
                r.generation_path or "",
                r.pattern_type or "",
                status,
                detail,
                preview,
                usage.get("prompt_tokens", ""),
                usage.get("output_tokens", ""),
                f"{usage['estimated_cost']:.6f}" if usage.get("estimated_cost") else "",
            ])
        sheets_writer.append_rows(LOG_SHEET, rows)
        logger.info(f"Wrote {len(rows)} log entries to '{LOG_SHEET}'")
    except Exception as e:
        logger.warning(f"Failed to write generation logs: {e}")


def _resolve_job_offer_id(
    job_offers,
    job_category: str,
    template_type: str,
) -> str | None:
    """Resolve job offer ID from job offers list and template type."""
    if not job_offers:
        return None

    # job_offers is a list of dicts from sheets
    if isinstance(job_offers, list):
        is_seishain = "正社員" in template_type
        for offer in job_offers:
            if offer.get("job_category") != job_category:
                continue
            emp = offer.get("employment_type", "")
            if is_seishain and "正" in emp:
                return offer.get("id")
            if not is_seishain and "パート" in emp:
                return offer.get("id")
        # Fallback: first offer matching job_category
        for offer in job_offers:
            if offer.get("job_category") == job_category:
                return offer.get("id")
        return None

    # Legacy dict format
    if isinstance(job_offers, dict):
        category_offers = job_offers.get(job_category)
        if category_offers is None:
            return None
        if isinstance(category_offers, str):
            return category_offers
        if isinstance(category_offers, dict):
            offer_id = category_offers.get(template_type)
            if offer_id:
                return offer_id
            employment = template_type.split("_")[0]
            return category_offers.get(employment)

    return None


async def _process_candidate(
    profile,
    company_id: str,
    options: GenerateOptions,
    config: dict,
) -> tuple[GenerateResponse, dict]:
    """Process a single candidate with pre-fetched company config.

    Returns (response, token_usage) where token_usage has prompt_tokens, output_tokens, estimated_cost.
    """
    # 1. Resolve job category
    job_category = resolve_job_category(
        profile.qualifications or "",
        profile.desired_job or "",
    )

    _empty_usage = {}

    if job_category is None:
        return GenerateResponse(
            member_id=profile.member_id,
            template_type="",
            generation_path="filtered_out",
            personalized_text="",
            full_scout_text="",
            filter_reason="職種カテゴリを特定できません",
        ), _empty_usage

    # 1.5. Filter by job_category if specified
    if options.job_category_filter and job_category != options.job_category_filter:
        return GenerateResponse(
            member_id=profile.member_id,
            template_type="",
            generation_path="filtered_out",
            personalized_text="",
            full_scout_text="",
            job_category=job_category,
            filter_reason=f"職種フィルタ: {job_category} ≠ {options.job_category_filter}",
        ), _empty_usage

    # 2. Resolve template type
    template_type = resolve_template_type(profile, options, job_category)

    # 3. Filter candidate
    filter_reason = await filter_candidate(
        profile, company_id, job_category, config["validation_config"]
    )
    if filter_reason:
        return GenerateResponse(
            member_id=profile.member_id,
            template_type=template_type,
            generation_path="filtered_out",
            personalized_text="",
            full_scout_text="",
            job_category=job_category,
            filter_reason=filter_reason,
        ), _empty_usage

    # 4. Get template body (prefer job_category-specific, fallback to generic)
    template_data = config["templates"].get(f"{job_category}:{template_type}")
    if template_data is None:
        template_data = config["templates"].get(template_type)
    if template_data is None:
        base = template_type.split("_")[0] + "_初回"
        template_data = config["templates"].get(f"{job_category}:{base}")
        if template_data is None:
            template_data = config["templates"].get(base)
    if template_data is None:
        raise ValueError(f"テンプレート '{template_type}' が見つかりません")

    template_body = template_data.get("body", "")

    # 5. Generate personalized text
    # Filter patterns and prompt_sections by job_category
    jc_patterns = [
        p for p in config["patterns"]
        if not p.get("job_category") or p["job_category"] == job_category
    ]
    jc_prompt_sections = [
        s for s in config["prompt_sections"]
        if not s.get("job_category") or s["job_category"] == job_category
    ]

    # Check if patterns have actual content (template_text filled in)
    has_patterns = any(
        p.get("template_text", "").strip() for p in jc_patterns
    )
    use_pattern = should_use_pattern(profile) and has_patterns

    token_usage = {}

    if use_pattern:
        try:
            pattern_type, personalized_text, debug_info = match_pattern(
                profile,
                jc_patterns,
                config["qualification_modifiers"],
                feature_rotation_index=hash(profile.member_id) % 100,
            )
            generation_path = "pattern"
            logger.info(f"[{profile.member_id}] pattern: {debug_info}")
        except ValueError:
            # Pattern not found → fall through to AI
            use_pattern = False

    if not use_pattern:
        if options and options.mock_ai:
            # Mock mode: skip AI call, return placeholder text
            personalized_text = "【テストモード】AI生成をスキップしました。実際の運用ではここにGeminiが生成したパーソナライズ文が入ります。"
            pattern_type = None
            generation_path = "ai"
            logger.info(f"[{profile.member_id}] ai: MOCK mode")
        else:
            system_prompt = build_system_prompt(
                jc_prompt_sections,
                template_body,
                config["examples"],
            )

            # Validate: block generation if foreign facility terms detected
            contamination = validate_prompt_content(request.company_id, system_prompt)
            if contamination:
                logger.error(f"[{profile.member_id}] prompt contamination blocked: {contamination}")
                return GenerateResponse(
                    member_id=profile.member_id,
                    template_type=template_type,
                    generation_path="filtered_out",
                    personalized_text="",
                    full_scout_text="",
                    job_offer_id="",
                    job_category=job_category,
                    filter_reason=f"プロンプト設定エラー: {'; '.join(contamination)}",
                ), {}

            user_prompt = build_user_prompt(profile, job_category)
            gen_result = await generate_personalized_text(system_prompt, user_prompt)
            personalized_text = gen_result.text
            pattern_type = None
            generation_path = "ai"
            logger.info(f"[{profile.member_id}] ai: {len(personalized_text)} chars, tokens: {gen_result.total_tokens}")

            # Calculate cost
            pricing = get_model_pricing(gen_result.model_name)
            estimated_cost = (
                gen_result.prompt_tokens * pricing["input"]
                + gen_result.output_tokens * pricing["output"]
            ) / 1_000_000
            token_usage = {
                "prompt_tokens": gen_result.prompt_tokens,
                "output_tokens": gen_result.output_tokens,
                "estimated_cost": estimated_cost,
            }

    # 6. Build full scout text
    full_scout_text = build_full_scout_text(template_body, personalized_text)

    # 7. Resolve job offer
    job_offer_id = _resolve_job_offer_id(
        config["job_offers"], job_category, template_type
    )

    return GenerateResponse(
        member_id=profile.member_id,
        template_type=template_type,
        generation_path=generation_path,
        pattern_type=pattern_type,
        personalized_text=personalized_text,
        full_scout_text=full_scout_text,
        job_offer_id=job_offer_id,
        job_category=job_category,
    ), token_usage


async def generate_single(
    request: GenerateRequest,
    data_client,
) -> GenerateResponse:
    """Process a single candidate through the full generation pipeline."""
    config = data_client.get_company_config(request.company_id)
    response, token_usage = await _process_candidate(
        request.profile,
        request.company_id,
        request.options or GenerateOptions(),
        config,
    )

    # Record cost
    if token_usage:
        try:
            from monitoring.cost_tracker import cost_tracker
            cost_tracker.record(
                token_usage["prompt_tokens"],
                token_usage["output_tokens"],
                GEMINI_MODEL,
            )
        except Exception as e:
            logger.warning(f"Failed to record cost: {e}")

    # Write log
    await asyncio.get_event_loop().run_in_executor(
        None,
        _write_generation_logs,
        request.company_id,
        [response],
        {response.member_id: token_usage} if token_usage else {},
    )

    return response


async def generate_batch(
    request: BatchGenerateRequest,
    data_client,
) -> BatchGenerateResponse:
    """Process multiple candidates with concurrency control.

    Company config is fetched once and shared across all candidates.
    """
    from config import MAX_BATCH_CONCURRENCY

    concurrency = min(request.concurrency, MAX_BATCH_CONCURRENCY)
    semaphore = asyncio.Semaphore(concurrency)
    options = request.options or GenerateOptions()

    # Fetch config once for the entire batch
    config = data_client.get_company_config(request.company_id)

    all_token_usage: dict[str, dict] = {}

    async def process_one(profile):
        async with semaphore:
            try:
                response, token_usage = await _process_candidate(
                    profile, request.company_id, options, config,
                )
                if token_usage:
                    all_token_usage[profile.member_id] = token_usage
                return response
            except Exception as e:
                logger.error(f"[{profile.member_id}] 生成エラー: {e}")
                return GenerateResponse(
                    member_id=profile.member_id,
                    template_type="",
                    generation_path="filtered_out",
                    personalized_text="",
                    full_scout_text="",
                    filter_reason=f"生成エラー: {str(e)}",
                    validation_warnings=[str(e)],
                )

    tasks = [process_one(profile) for profile in request.profiles]
    results = await asyncio.gather(*tasks)

    # Record costs
    if all_token_usage:
        try:
            from monitoring.cost_tracker import cost_tracker
            for usage in all_token_usage.values():
                cost_tracker.record(
                    usage["prompt_tokens"],
                    usage["output_tokens"],
                    GEMINI_MODEL,
                )
        except Exception as e:
            logger.warning(f"Failed to record costs: {e}")

    summary = {
        "total": len(results),
        "ai_generated": sum(1 for r in results if r.generation_path == "ai"),
        "pattern_matched": sum(1 for r in results if r.generation_path == "pattern"),
        "filtered_out": sum(1 for r in results if r.generation_path == "filtered_out"),
    }

    # Write generation logs to Sheets (must await before response on Cloud Run)
    await asyncio.get_event_loop().run_in_executor(
        None,
        _write_generation_logs,
        request.company_id,
        list(results),
        all_token_usage,
    )

    return BatchGenerateResponse(results=list(results), summary=summary)
