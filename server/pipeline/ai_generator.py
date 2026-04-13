from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from google.api_core import exceptions as api_exceptions
from google.api_core import retry as api_retry

from config import (
    GEMINI_MODEL,
    GEMINI_FALLBACK_MODELS,
    GEMINI_API_KEY,
    GEMINI_THINKING_BUDGET,
    PROJECT_ID,
    LOCATION,
    MOCK_AI,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Safety settings: disable overly aggressive filters for legitimate
# recruitment content (medical/care job descriptions).
# ---------------------------------------------------------------------------
def _safety_settings_genai():
    """Return safety settings for google-generativeai SDK."""
    import google.generativeai as genai
    return {
        genai.types.HarmCategory.HARM_CATEGORY_HARASSMENT: genai.types.HarmBlockThreshold.BLOCK_NONE,
        genai.types.HarmCategory.HARM_CATEGORY_HATE_SPEECH: genai.types.HarmBlockThreshold.BLOCK_NONE,
        genai.types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: genai.types.HarmBlockThreshold.BLOCK_NONE,
        genai.types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: genai.types.HarmBlockThreshold.BLOCK_NONE,
    }


def _safety_settings_vertex():
    """Return safety settings for Vertex AI SDK."""
    from vertexai.generative_models import HarmCategory, HarmBlockThreshold
    return {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }


def _extract_text_safe(response) -> str:
    """Extract text from Gemini response, filtering out thinking parts."""
    try:
        # Vertex AI SDK returns thinking as separate parts with .thought=True
        # We must filter them out to avoid leaking reasoning into output
        try:
            parts = response.candidates[0].content.parts
            texts = []
            for part in parts:
                # Skip thinking parts (Vertex AI SDK marks them with .thought)
                if getattr(part, "thought", False):
                    continue
                if hasattr(part, "text") and part.text:
                    texts.append(part.text)
            if texts:
                return "\n".join(texts)
        except (AttributeError, IndexError):
            pass
        # Fallback: use response.text (genai SDK without thinking)
        return response.text or ""
    except (ValueError, AttributeError):
        # response.text throws when safety filters block the output
        block_reasons = []
        try:
            for candidate in response.candidates:
                if candidate.finish_reason and candidate.finish_reason.name != "STOP":
                    block_reasons.append(candidate.finish_reason.name)
                for rating in (candidate.safety_ratings or []):
                    if rating.blocked:
                        block_reasons.append(f"{rating.category.name}={rating.probability.name}")
        except Exception:
            pass
        detail = ", ".join(block_reasons) if block_reasons else "不明"
        raise ValueError(f"安全フィルタによりブロック ({detail})")


@dataclass
class GenerationResult:
    """AI generation result with token usage metadata."""
    text: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model_name: str = ""

# Disable all automatic retries to avoid burning API quota
_NO_RETRY = api_retry.Retry(initial=0, maximum=0, deadline=0)

_initialized = False
_use_vertex = False

# ---------------------------------------------------------------------------
# Circuit breaker: skip models that recently returned 429 so we don't waste
# seconds per candidate waiting for a guaranteed failure.
# ---------------------------------------------------------------------------
import time as _time

# model_name -> timestamp when 429 was first observed
_tripped_models: dict[str, float] = {}

# How long to keep a model tripped (seconds). RPD resets daily at midnight PT,
# but a 5-minute window is enough to avoid hammering within a single batch run.
_CIRCUIT_BREAKER_TTL = 300  # 5 minutes


def _trip_model(model: str) -> None:
    """Mark a model as quota-exhausted."""
    _tripped_models[model] = _time.time()
    logger.warning(f"Circuit breaker tripped for {model} (skip for {_CIRCUIT_BREAKER_TTL}s)")


def _is_tripped(model: str) -> bool:
    """Check if a model is currently tripped (should be skipped)."""
    ts = _tripped_models.get(model)
    if ts is None:
        return False
    if _time.time() - ts > _CIRCUIT_BREAKER_TTL:
        del _tripped_models[model]
        return False
    return True


def _model_chain(primary: str) -> list[str]:
    """Return [primary, ...fallbacks] de-duplicated, skipping tripped models.

    The primary model comes from GEMINI_MODEL (or a per-call override);
    on 429 / ResourceExhausted we walk through GEMINI_FALLBACK_MODELS in
    order. Models that recently hit 429 (circuit breaker) are moved to the
    end of the chain so they're only tried as a last resort.
    """
    raw_chain: list[str] = [primary]
    raw = (GEMINI_FALLBACK_MODELS or "").replace(",", "|")
    for m in raw.split("|"):
        m = m.strip()
        if m and m not in raw_chain:
            raw_chain.append(m)

    # Partition: healthy models first, tripped models last
    healthy = [m for m in raw_chain if not _is_tripped(m)]
    tripped = [m for m in raw_chain if _is_tripped(m)]
    chain = healthy + tripped

    if chain[0] != primary and not _is_tripped(primary):
        # Should not happen, but safety net
        chain = [primary] + [m for m in chain if m != primary]

    return chain


def _is_quota_error(exc: BaseException) -> bool:
    """True if the exception looks like a Gemini RPD/TPM/RPM 429."""
    if isinstance(exc, api_exceptions.ResourceExhausted):
        return True
    # google-generativeai sometimes wraps 429 inside RetryError or a
    # generic Exception whose message contains the status.
    msg = str(exc)
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower()


def _ensure_initialized() -> None:
    """Initialize the appropriate Gemini SDK."""
    global _initialized, _use_vertex
    if _initialized:
        return

    if GEMINI_API_KEY:
        # Use Gemini Developer API (free tier / API key auth)
        # transport="rest" avoids gRPC output truncation bug in deprecated SDK
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY, transport="rest")
        _use_vertex = False
    else:
        # Use Vertex AI (GCP service account auth)
        import vertexai
        vertexai.init(project=PROJECT_ID, location=LOCATION)
        _use_vertex = True

    _initialized = True


def _build_generation_config(
    temperature: float,
    max_output_tokens: int,
    model_name: str,
    *,
    for_vertex: bool = False,
    **extra,
) -> dict:
    """Build generation_config dict, adding thinking_config for supported models.

    google-generativeai SDK (<=0.8) does not recognize thinking_config
    in GenerationConfig and raises a validation error. Only Vertex AI SDK
    accepts it, so `for_vertex=True` must be set explicitly.
    """
    config: dict = {
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
        **extra,
    }
    # Add thinking only for Vertex AI path (genai SDK doesn't support it yet)
    if for_vertex and GEMINI_THINKING_BUDGET > 0 and ("gemini-3" in model_name or "gemini-2.5" in model_name):
        config["thinking_config"] = {"thinking_budget": GEMINI_THINKING_BUDGET}
    return config


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting artifacts from generated text."""
    text = re.sub(r"```[\s\S]*?```", lambda m: m.group(0).strip("`").strip(), text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    return text.strip()


async def generate_personalized_text(
    system_prompt: str,
    user_prompt: str,
    model_name: str | None = None,
    max_output_tokens: int = 2048,
    temperature: float = 0.7,
) -> GenerationResult:
    """Call Gemini to generate personalized scout text.

    Supports both:
    - Gemini Developer API (GEMINI_API_KEY set) — free tier, API key auth
    - Vertex AI (GEMINI_API_KEY not set) — GCP, service account auth
    """
    primary = model_name or GEMINI_MODEL

    # Mock mode for local testing
    if MOCK_AI:
        await asyncio.sleep(0.1)  # simulate latency
        return GenerationResult(
            text=f"【モック生成】候補者の経歴を拝見し、当ステーションでのご活躍を期待しております。（system_prompt: {len(system_prompt)}文字, user_prompt: {len(user_prompt)}文字）",
            model_name=primary,
        )

    _ensure_initialized()

    chain = _model_chain(primary)
    last_exc: BaseException | None = None
    response = None
    name = primary

    for idx, candidate in enumerate(chain):
        try:
            if _use_vertex:
                gen_config = _build_generation_config(temperature, max_output_tokens, candidate, for_vertex=True)
                from vertexai.generative_models import GenerativeModel
                model = GenerativeModel(model_name=candidate, system_instruction=system_prompt)
                response = await model.generate_content_async(
                    user_prompt,
                    generation_config=gen_config,
                    safety_settings=_safety_settings_vertex(),
                )
            else:
                gen_config = _build_generation_config(temperature, max_output_tokens, candidate, for_vertex=False)
                import google.generativeai as genai
                model = genai.GenerativeModel(model_name=candidate, system_instruction=system_prompt)
                # google-generativeai doesn't have async, run in thread
                # Explicitly disable retry to avoid burning quota
                response = await asyncio.to_thread(
                    model.generate_content,
                    user_prompt,
                    generation_config=gen_config,
                    safety_settings=_safety_settings_genai(),
                    request_options={"retry": _NO_RETRY},
                )
            name = candidate
            if idx > 0:
                logger.warning(
                    f"AI fallback used: {primary} -> {candidate} "
                    f"(primary exhausted, fallback step {idx})"
                )
            break
        except Exception as exc:
            if _is_quota_error(exc):
                _trip_model(candidate)
                if idx + 1 < len(chain):
                    logger.warning(
                        f"AI quota exhausted on {candidate}: {type(exc).__name__}; "
                        f"falling back to {chain[idx + 1]}"
                    )
                    last_exc = exc
                    continue
            raise

    if response is None:
        # Should be unreachable: either break sets response or we raised.
        raise last_exc or RuntimeError("AI生成: 応答が取得できませんでした")

    raw_text = _extract_text_safe(response)
    if not raw_text:
        raise ValueError("AI生成で空の応答が返されました")

    text = _strip_markdown(raw_text)

    if not text:
        raise ValueError("AI生成の結果が空です（マークダウン除去後）")

    # Extract token usage
    prompt_tokens = 0
    output_tokens = 0
    total_tokens = 0
    try:
        if response.usage_metadata:
            prompt_tokens = response.usage_metadata.prompt_token_count or 0
            output_tokens = response.usage_metadata.candidates_token_count or 0
            total_tokens = response.usage_metadata.total_token_count or 0
    except Exception as e:
        logger.warning(f"Failed to extract token usage: {e}")

    return GenerationResult(
        text=text,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        model_name=name,
    )


async def generate_structured(
    system_prompt: str,
    user_prompt: str,
    response_schema: dict,
    *,
    model_name: str | None = None,
    max_output_tokens: int = 4096,
    temperature: float = 0.7,
) -> tuple[dict, GenerationResult]:
    """Call Gemini with a JSON schema and parse the structured output.

    Used by the personalized_scout pipeline (L2/L3) where the model is
    asked to produce a dict of named blocks in a single call. Normal
    text generation should keep using `generate_personalized_text`.

    Returns (parsed_json_dict, generation_metadata). Raises ValueError
    if the response is empty or JSON parsing fails even after cleanup.
    """
    import json as _json

    primary = model_name or GEMINI_MODEL

    # Mock mode: return a deterministic stub matching the schema so
    # local tests and offline development both work without burning
    # quota. The mock fills every top-level string property with a
    # short placeholder and defaults nested/array shapes to empty.
    if MOCK_AI:
        await asyncio.sleep(0.1)
        mock_dict: dict = {}
        props = (response_schema or {}).get("properties", {})
        for key, spec in props.items():
            t = (spec or {}).get("type", "string")
            if t == "string":
                mock_dict[key] = f"【モック:{key}】候補者の経歴を踏まえた{key}の内容です。"
            elif t == "array":
                mock_dict[key] = []
            elif t == "object":
                mock_dict[key] = {}
            else:
                mock_dict[key] = ""
        return mock_dict, GenerationResult(
            text=_json.dumps(mock_dict, ensure_ascii=False),
            model_name=primary,
        )

    _ensure_initialized()

    chain = _model_chain(primary)
    last_exc: BaseException | None = None
    response = None
    name = primary

    for idx, candidate in enumerate(chain):
        try:
            if _use_vertex:
                gen_config = _build_generation_config(
                    temperature, max_output_tokens, candidate, for_vertex=True,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                )
                from vertexai.generative_models import GenerativeModel
                model = GenerativeModel(model_name=candidate, system_instruction=system_prompt)
                response = await model.generate_content_async(
                    user_prompt,
                    generation_config=gen_config,
                    safety_settings=_safety_settings_vertex(),
                )
            else:
                gen_config = _build_generation_config(
                    temperature, max_output_tokens, candidate, for_vertex=False,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                )
                import google.generativeai as genai
                model = genai.GenerativeModel(model_name=candidate, system_instruction=system_prompt)
                response = await asyncio.to_thread(
                    model.generate_content,
                    user_prompt,
                    generation_config=gen_config,
                    safety_settings=_safety_settings_genai(),
                    request_options={"retry": _NO_RETRY},
                )
            name = candidate
            if idx > 0:
                logger.warning(
                    f"AI fallback used (structured): {primary} -> {candidate} "
                    f"(primary exhausted, fallback step {idx})"
                )
            break
        except Exception as exc:
            if _is_quota_error(exc) and idx + 1 < len(chain):
                logger.warning(
                    f"AI quota exhausted on {candidate} (structured): "
                    f"{type(exc).__name__}; falling back to {chain[idx + 1]}"
                )
                last_exc = exc
                continue
            raise

    if response is None:
        raise last_exc or RuntimeError("AI構造化生成: 応答が取得できませんでした")

    raw_text = _extract_text_safe(response)
    if not raw_text:
        raise ValueError("AI構造化生成で空の応答が返されました")

    raw = raw_text.strip()
    # Some SDK versions wrap JSON in markdown fences even with
    # response_mime_type=application/json — strip defensively.
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        parsed = _json.loads(raw)
    except Exception as e:
        raise ValueError(f"AI構造化生成のJSONパースに失敗: {e} / raw={raw[:300]}")

    if not isinstance(parsed, dict):
        raise ValueError(f"AI構造化生成はJSONオブジェクトを期待: got {type(parsed).__name__}")

    # Token usage
    prompt_tokens = 0
    output_tokens = 0
    total_tokens = 0
    try:
        if response.usage_metadata:
            prompt_tokens = response.usage_metadata.prompt_token_count or 0
            output_tokens = response.usage_metadata.candidates_token_count or 0
            total_tokens = response.usage_metadata.total_token_count or 0
    except Exception as e:
        logger.warning(f"Failed to extract token usage: {e}")

    return parsed, GenerationResult(
        text=raw,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        model_name=name,
    )
