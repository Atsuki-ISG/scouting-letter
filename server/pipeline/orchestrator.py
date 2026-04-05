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
from pipeline.prompt_validator import validate_prompt_content, validate_output_text
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

SEND_DATA_HEADERS = [
    # 自動（生成時に書き込み）— 会社列不要（シート自体が会社）
    "日時", "会員番号", "職種カテゴリ", "テンプレート種別", "テンプレートVer", "生成パス", "パターン",
    "年齢層", "資格", "経験区分", "希望雇用形態", "就業状況", "地域",
    "曜日", "時間帯",
    # 自動（返信同期で書き込み）
    "返信", "返信日", "返信カテゴリ",
]

COMPANY_DISPLAY_NAMES = {
    "ark-visiting-nurse": "アーク訪看",
    "lcc-visiting-nurse": "LCC訪看",
    "ichigo-visiting-nurse": "いちご訪看",
    "an-visiting-nurse": "an訪看",
    "chigasaki-tokushukai": "茅ヶ崎徳洲会",
    "nomura-hospital": "野村病院",
}


def _send_data_sheet_name(company_id: str) -> str:
    """Get the per-company send data sheet name."""
    display = COMPANY_DISPLAY_NAMES.get(company_id, company_id)
    return f"送信_{display}"


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


def _age_bucket(age_str: str | None) -> str:
    """Convert age string like '25歳' to bucket like '20代'."""
    if not age_str:
        return ""
    try:
        age = int("".join(c for c in age_str if c.isdigit()))
        if age < 25:
            return "〜24歳"
        elif age < 30:
            return "25-29歳"
        elif age < 35:
            return "30-34歳"
        elif age < 40:
            return "35-39歳"
        elif age < 45:
            return "40-44歳"
        elif age < 50:
            return "45-49歳"
        else:
            return "50歳〜"
    except (ValueError, TypeError):
        return ""


def _experience_bucket(exp_str: str | None) -> str:
    """Convert experience string to bucket."""
    if not exp_str:
        return "不明"
    try:
        years = int("".join(c for c in exp_str if c.isdigit()))
        if years == 0:
            return "未経験"
        elif years <= 3:
            return "1-3年"
        elif years <= 5:
            return "4-5年"
        elif years <= 10:
            return "6-10年"
        else:
            return "11年以上"
    except (ValueError, TypeError):
        return "不明"


def _time_slot(hour: int) -> str:
    """Categorize hour into time slot."""
    if hour < 9:
        return "早朝"
    elif hour < 12:
        return "午前"
    elif hour < 14:
        return "昼"
    elif hour < 17:
        return "午後"
    else:
        return "夕方以降"


WEEKDAY_NAMES = ["月", "火", "水", "木", "金", "土", "日"]


def _write_send_data(
    company_id: str,
    profiles: list,
    results: list[GenerateResponse],
    config: dict | None = None,
) -> None:
    """Write generation results to the per-company send data sheet.

    Only writes successful generations (excludes filtered-out candidates).
    """
    try:
        from db.sheets_writer import sheets_writer
        sheet_name = _send_data_sheet_name(company_id)
        sheets_writer.ensure_sheet_exists(sheet_name, SEND_DATA_HEADERS)

        now = datetime.now(JST)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        weekday = WEEKDAY_NAMES[now.weekday()]
        time_slot = _time_slot(now.hour)

        # Build template version lookup from config
        template_versions = {}
        if config and "templates" in config:
            for tkey, tdata in config["templates"].items():
                template_versions[tkey] = tdata.get("version", "1")

        profile_map = {p.member_id: p for p in profiles}

        rows = []
        for r in results:
            if r.generation_path == "filtered_out":
                continue
            p = profile_map.get(r.member_id)
            # Resolve template version
            tver = ""
            if r.template_type and r.job_category:
                tver = template_versions.get(f"{r.job_category}:{r.template_type}", "")
            if not tver and r.template_type:
                tver = template_versions.get(r.template_type, "")
            rows.append([
                now_str,
                r.member_id,
                r.job_category or "",
                r.template_type or "",
                tver,  # テンプレートVer
                r.generation_path or "",
                r.pattern_type or "",
                _age_bucket(p.age if p else None),
                p.qualifications or "" if p else "",
                _experience_bucket(p.experience_years if p else None),
                p.desired_employment_type or "" if p else "",
                p.employment_status or "" if p else "",
                p.area or p.desired_area or "" if p else "",  # 地域
                weekday,
                time_slot,
                "",  # 返信
                "",  # 返信日
                "",  # 返信カテゴリ
            ])
        if rows:
            sheets_writer.append_rows(sheet_name, rows)
            logger.info(f"Wrote {len(rows)} rows to '{sheet_name}'")
    except Exception as e:
        logger.warning(f"Failed to write send data: {e}")


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
        is_keiyaku = "契約" in template_type
        is_seishain = "正社員" in template_type
        for offer in job_offers:
            if offer.get("job_category") != job_category:
                continue
            emp = offer.get("employment_type", "")
            if is_keiyaku and "契約" in emp:
                return offer.get("id")
            if is_seishain and "正" in emp:
                return offer.get("id")
            if not is_seishain and not is_keiyaku and "パート" in emp:
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
    _empty_usage = {}

    # 1. Resolve job category
    if options.job_category_filter:
        # User explicitly selected a category — use it directly
        job_category = options.job_category_filter
    else:
        job_category = resolve_job_category(
            profile.qualifications or "",
            profile.desired_job or "",
        )

    if job_category is None:
        return GenerateResponse(
            member_id=profile.member_id,
            template_type="",
            generation_path="filtered_out",
            personalized_text="",
            full_scout_text="",
            filter_reason="職種カテゴリを特定できません",
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
    employment_mismatch_warning = ""
    original_template_type = template_type
    template_data = config["templates"].get(f"{job_category}:{template_type}")
    if template_data is None:
        template_data = config["templates"].get(template_type)
    if template_data is None:
        base = template_type.split("_")[0] + "_初回"
        template_data = config["templates"].get(f"{job_category}:{base}")
        if template_data is None:
            template_data = config["templates"].get(base)
    # Employment type fallback: if no matching template, try any template
    # for the same job_category and send_type (e.g. 正社員_初回 not found → 契約_初回)
    if template_data is None:
        send_type = template_type.split("_", 1)[1] if "_" in template_type else "初回"
        for key, tpl in config["templates"].items():
            if tpl.get("job_category") == job_category and tpl["type"].endswith(f"_{send_type}"):
                template_data = tpl
                original_employment = template_type.split("_")[0]
                actual_employment = tpl["type"].split("_")[0]
                template_type = tpl["type"]
                desired = profile.desired_employment_type or "未入力"
                employment_mismatch_warning = (
                    f"希望雇用形態「{desired}」≠ 求人の雇用形態「{actual_employment}」"
                )
                logger.info(
                    f"[{profile.member_id}] employment fallback: "
                    f"'{original_template_type}' → '{tpl['type']}' (desired={desired})"
                )
                break
    if template_data is None:
        raise ValueError(f"テンプレート '{template_type}' が見つかりません")

    template_body = template_data.get("body", "")

    # 5. Generate personalized text
    # Filter patterns and prompt_sections by job_category
    # rehab_pt/rehab_st also match parent category "rehab"
    jc_parent = job_category.rsplit("_", 1)[0] if "_" in job_category else None
    jc_match = {job_category, jc_parent} if jc_parent else {job_category}
    jc_patterns = [
        p for p in config["patterns"]
        if not p.get("job_category") or p["job_category"] in jc_match
    ]
    jc_prompt_sections = [
        s for s in config["prompt_sections"]
        if not s.get("job_category") or s["job_category"] in jc_match
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
            contamination = validate_prompt_content(company_id, system_prompt)
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

    # 7. Validate output: company name check
    output_errors = validate_output_text(company_id, full_scout_text)
    if output_errors:
        logger.error(f"[{profile.member_id}] output validation failed: {output_errors}")
        return GenerateResponse(
            member_id=profile.member_id,
            template_type=template_type,
            generation_path="filtered_out",
            personalized_text="",
            full_scout_text="",
            job_offer_id="",
            job_category=job_category,
            filter_reason=f"出力検証エラー: {'; '.join(output_errors)}",
        ), {}

    # 8. Resolve job offer
    job_offer_id = _resolve_job_offer_id(
        config["job_offers"], job_category, template_type
    )

    warnings = []
    if employment_mismatch_warning:
        warnings.append(employment_mismatch_warning)

    return GenerateResponse(
        member_id=profile.member_id,
        template_type=template_type,
        generation_path=generation_path,
        pattern_type=pattern_type,
        personalized_text=personalized_text,
        full_scout_text=full_scout_text,
        job_offer_id=job_offer_id,
        job_category=job_category,
        is_favorite=profile.is_favorite,
        validation_warnings=warnings,
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

    # Write logs
    loop = asyncio.get_event_loop()
    await asyncio.gather(
        loop.run_in_executor(
            None,
            _write_generation_logs,
            request.company_id,
            [response],
            {response.member_id: token_usage} if token_usage else {},
        ),
        loop.run_in_executor(
            None,
            _write_send_data,
            request.company_id,
            [request.profile],
            [response],
            config,
        ),
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

    # Write logs to Sheets (must await before response on Cloud Run)
    loop = asyncio.get_event_loop()
    await asyncio.gather(
        loop.run_in_executor(
            None,
            _write_generation_logs,
            request.company_id,
            list(results),
            all_token_usage,
        ),
        loop.run_in_executor(
            None,
            _write_send_data,
            request.company_id,
            list(request.profiles),
            list(results),
            config,
        ),
    )

    return BatchGenerateResponse(results=list(results), summary=summary)
