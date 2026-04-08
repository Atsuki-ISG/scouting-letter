from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from google.api_core import retry as api_retry

from config import GEMINI_MODEL, GEMINI_API_KEY, PROJECT_ID, LOCATION, MOCK_AI

logger = logging.getLogger(__name__)


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
    name = model_name or GEMINI_MODEL

    # Mock mode for local testing
    if MOCK_AI:
        await asyncio.sleep(0.1)  # simulate latency
        return GenerationResult(
            text=f"【モック生成】候補者の経歴を拝見し、当ステーションでのご活躍を期待しております。（system_prompt: {len(system_prompt)}文字, user_prompt: {len(user_prompt)}文字）",
            model_name=name,
        )

    _ensure_initialized()

    if _use_vertex:
        from vertexai.generative_models import GenerativeModel
        model = GenerativeModel(model_name=name, system_instruction=system_prompt)
        response = await model.generate_content_async(
            user_prompt,
            generation_config={"temperature": temperature, "max_output_tokens": max_output_tokens},
        )
    else:
        import google.generativeai as genai
        model = genai.GenerativeModel(model_name=name, system_instruction=system_prompt)
        # google-generativeai doesn't have async, run in thread
        # Explicitly disable retry to avoid burning free-tier quota
        response = await asyncio.to_thread(
            model.generate_content,
            user_prompt,
            generation_config={"temperature": temperature, "max_output_tokens": max_output_tokens},
            request_options={"retry": _NO_RETRY},
        )

    if not response.text:
        raise ValueError("AI生成で空の応答が返されました")

    text = _strip_markdown(response.text)

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

    name = model_name or GEMINI_MODEL

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
            model_name=name,
        )

    _ensure_initialized()

    generation_config = {
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
        "response_mime_type": "application/json",
        "response_schema": response_schema,
    }

    if _use_vertex:
        from vertexai.generative_models import GenerativeModel
        model = GenerativeModel(model_name=name, system_instruction=system_prompt)
        response = await model.generate_content_async(
            user_prompt,
            generation_config=generation_config,
        )
    else:
        import google.generativeai as genai
        model = genai.GenerativeModel(model_name=name, system_instruction=system_prompt)
        response = await asyncio.to_thread(
            model.generate_content,
            user_prompt,
            generation_config=generation_config,
            request_options={"retry": _NO_RETRY},
        )

    if not response.text:
        raise ValueError("AI構造化生成で空の応答が返されました")

    raw = response.text.strip()
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
