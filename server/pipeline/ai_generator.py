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
