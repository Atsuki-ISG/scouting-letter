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


def _build_search_tool_vertex():
    """Build the Google Search grounding tool for the Vertex AI SDK.

    Returns None if the SDK version doesn't support it, so callers can
    fall back silently instead of crashing.
    """
    try:
        from vertexai.generative_models import Tool, grounding
        return Tool.from_google_search_retrieval(grounding.GoogleSearchRetrieval())
    except Exception as e:
        logger.warning(f"Vertex GoogleSearchRetrieval unavailable: {e}")
        return None


def _build_search_tool_genai():
    """Build the Google Search grounding tool for the genai SDK.

    The google-generativeai SDK exposes GoogleSearchRetrieval via protos.
    Note: genai SDK's grounding support is less reliable than Vertex; when
    running via API key, grounding may silently no-op for some models.
    """
    try:
        from google.generativeai import protos
        return protos.Tool(google_search_retrieval=protos.GoogleSearchRetrieval())
    except Exception as e:
        logger.warning(f"genai GoogleSearchRetrieval unavailable: {e}")
        return None


def _extract_citations(response) -> list[dict]:
    """Pull citation URIs/titles out of Gemini grounding metadata.

    Works with both Vertex and genai SDK response shapes. Returns an empty
    list when no grounding metadata is present (e.g. tool wasn't enabled
    or the model chose not to ground its answer).
    """
    citations: list[dict] = []
    seen_uris: set[str] = set()
    try:
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            meta = getattr(candidate, "grounding_metadata", None)
            if meta is None:
                continue
            # Gemini 2.x+: grounding_chunks[].web.{uri, title}
            for chunk in getattr(meta, "grounding_chunks", None) or []:
                web = getattr(chunk, "web", None)
                if web is None:
                    continue
                uri = getattr(web, "uri", "") or ""
                title = getattr(web, "title", "") or ""
                if uri and uri not in seen_uris:
                    seen_uris.add(uri)
                    citations.append({"uri": uri, "title": title})
            # Gemini 1.5 fallback: grounding_attributions[].web.{uri, title}
            for attr in getattr(meta, "grounding_attributions", None) or []:
                web = getattr(attr, "web", None)
                if web is None:
                    continue
                uri = getattr(web, "uri", "") or ""
                title = getattr(web, "title", "") or ""
                if uri and uri not in seen_uris:
                    seen_uris.add(uri)
                    citations.append({"uri": uri, "title": title})
    except Exception as e:
        logger.warning(f"Failed to extract grounding citations: {e}")
    return citations


def _extract_text_safe(response) -> str:
    """Extract text from Gemini response, filtering out thinking parts."""
    try:
        # Vertex AI SDK returns thinking as separate parts.
        # The high-level Part wrapper doesn't expose .thought, but the
        # underlying proto (part._raw_part.thought) does since SDK >=1.85.
        try:
            parts = response.candidates[0].content.parts
            texts = []
            for part in parts:
                # Check proto-level thought flag
                raw = getattr(part, "_raw_part", None)
                if raw is not None and getattr(raw, "thought", False):
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
    # Google Search grounding output. Populated only when the caller passes
    # `use_google_search=True`. Each entry: {"uri": str, "title": str}.
    # Empty list means either the tool was off or Gemini returned no sources.
    citations: list[dict] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.citations is None:
            self.citations = []

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
    thinking_budget: int | None = None,
    **extra,
) -> dict:
    """Build generation_config dict, adding thinking_config for supported models.

    google-generativeai SDK (<=0.8) does not recognize thinking_config
    in GenerationConfig and raises a validation error. Only Vertex AI SDK
    accepts it, so `for_vertex=True` must be set explicitly.

    `thinking_budget` overrides the env-level `GEMINI_THINKING_BUDGET` for
    one call. Use 0 to disable thinking entirely, or a positive integer to
    cap reasoning tokens. If None, falls back to the env default.
    """
    config: dict = {
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
        **extra,
    }
    effective_budget = GEMINI_THINKING_BUDGET if thinking_budget is None else thinking_budget
    # Add thinking only for Vertex AI path (genai SDK doesn't support it yet)
    if for_vertex and effective_budget > 0 and ("gemini-3" in model_name or "gemini-2.5" in model_name):
        config["thinking_config"] = {"thinking_budget": effective_budget}
    return config


# Patterns used by _strip_thinking() to identify leaked reasoning paragraphs.
_THINKING_MARKER_RE = re.compile(
    r"^\s*("
    r"Draft(?:ing)?\s*\d*\s*[:：]?|"
    r"Characters?\s*(?:count|check)(?:\s+check)?\b|"  # Character count / Character check / Character count check
    r"Count\s*check\b|"
    r"Characters?\s*[:：]|"
    r"Total\s*[:：]|"
    r"Wait[,\s]|"
    r"One\s+more\s+check|"
    r"One\s+check|"
    r"Double\s+check|"
    r"Triple\s+check|"
    r"My\s+draft|"
    r"My\s+sentence|"
    r"Let\s+me|"
    r"Note\s*[:：]|"
    r"Refine\s*[:：]|"
    r"Polish\s*[:：]|"
    r"Check\s*[:：]|"
    r"Final\s+(version|text|output|answer|response)\s*[:：]?|"
    r"Thoughtful|"
    r"Actually[,\s]|"
    r"Hmm[,\s]|"
    r"Okay[,\s]|"
    r"書き出し\s*[:：]"
    r")",
    re.IGNORECASE,
)
# 「(119 characters)」「(39 chars)」または独立行の「-> 113 characters.」「113 chars.」等
_CHAR_COUNT_ANNOTATION_RE = re.compile(
    r"(?:\(\s*\d+\s*(?:char|character)s?\s*\)|(?:->|→|:)\s*\d+\s*(?:char|character)s?\b|^\s*\d+\s*(?:char|character)s?\.)",
    re.IGNORECASE,
)
_COUNTED_CHAR_RE = re.compile(r".\(\d+\)")

# 単一行レベルで「これはメタだけの行」と判定するためのパターン。
# `Drafting:` のように本文と同一段落内の先頭/末尾にだけ現れるメタを剥がすのに使う。
_META_LINE_PATTERNS = [
    re.compile(r"^\s*Drafting\s*[:：]?\s*$", re.IGNORECASE),
    re.compile(r"^\s*Draft\s*\d*\s*[:：]?\s*$", re.IGNORECASE),
    re.compile(r"^\s*It'?s\s+\d+\s+(?:char|character)s?\.?\s*$", re.IGNORECASE),
    re.compile(r"^\s*\d+\s+(?:char|character)s?\.?\s*$", re.IGNORECASE),
    # 「118文字。」「118文字。これが一番事実に基づいている。」など
    re.compile(r"^\s*\d+\s*文字[。.]?.*$"),
    # 「これが一番事実に基づいている」「これが最も自然」などの自己検証コメント
    re.compile(r"^\s*これが(?:一番|最も)?(?:事実|正しい|良い|自然|適切|シンプル)"),
    re.compile(r"^\s*(?:最終版|これが最終|これでOK|Final)"),
]


def _is_meta_line(line: str) -> bool:
    """その1行だけで『メタ出力』とみなせるかを判定。本文と同居している場合に前後から剥がす用。"""
    s = line.strip()
    if not s:
        return True
    # 短めの行かつ既知マーカーで始まる → メタ
    if len(s) < 80 and _THINKING_MARKER_RE.match(s):
        return True
    for pat in _META_LINE_PATTERNS:
        if pat.match(s):
            return True
    return False


def _trim_meta_lines(text: str) -> str:
    """段落内の先頭・末尾にある『メタだけの行』を剥がす。本文行が消えない限り繰り返す。"""
    lines = text.split("\n")
    # 先頭
    while len(lines) > 1 and _is_meta_line(lines[0]):
        lines.pop(0)
    # 末尾
    while len(lines) > 1 and _is_meta_line(lines[-1]):
        lines.pop()
    return "\n".join(lines).strip()


def _strip_thinking(text: str) -> str:
    """Remove leaked thinking/reasoning blocks from Gemini output.

    Gemini 3 / 2.5 models with thinking enabled sometimes leak their
    internal reasoning into the output. Observed patterns include:

    - English reasoning paragraphs (ASCII-heavy)
    - "Draft 1:", "Draft 2:" variants with Japanese that look real
    - "(119 characters)" length annotations
    - "Characters:" sections with X(N)X(N)... character counting
    - Meta markers: "Wait,", "One more check", "My draft", "Total:"

    The final output is often wrapped in quotes — they are stripped too.
    """
    paragraphs = re.split(r"\n\s*\n", text)
    kept: list[str] = []
    for para in paragraphs:
        # 段落の先頭/末尾に混じったメタ行（例: "Drafting:\n本文..." の "Drafting:"）を先に剥がす。
        # 本文と同一段落に同居しているケースはこれで救える。
        stripped = _trim_meta_lines(para.strip())
        if not stripped:
            continue

        total_chars = len(stripped.replace(" ", "").replace("\n", ""))
        if total_chars == 0:
            continue

        # Detect if this paragraph looks like leaked thinking
        ascii_alpha = sum(1 for c in stripped if c.isascii() and c.isalpha())
        first_line = stripped.split("\n", 1)[0].lstrip()
        is_thinking = (
            # 1. ASCII-heavy reasoning (>30% alpha mixed with some Japanese is still meta)
            (total_chars > 20 and ascii_alpha / total_chars > 0.3)
            # 2. Known thinking/draft/meta marker at start
            or bool(_THINKING_MARKER_RE.match(first_line))
            # 3. "(XXX characters)" length annotations anywhere
            or bool(_CHAR_COUNT_ANNOTATION_RE.search(stripped))
            # 4. Character-counting paragraphs: many X(N) patterns
            or len(_COUNTED_CHAR_RE.findall(stripped)) >= 10
        )

        # 本文が既に採用されている後に出てくる、鍵括弧で始まる未完文は代替ドラフトの断片。
        # 例: "本文。\n\n「訪問看護と病棟での経験は、当ステーションで活きる" ← 句点なしで切れている
        if kept and not is_thinking:
            opens_with_quote = stripped.startswith("「") or stripped.startswith("『")
            ends_complete = any(stripped.rstrip().endswith(e) for e in ["。", "！", "？", "」", "』", "."])
            if opens_with_quote and not ends_complete:
                is_thinking = True

        if is_thinking:
            # Once we have legit content and see thinking, stop — everything
            # after is self-revision noise (Gemini's "Final Text:" / "Actually,
            # let's refine:" pattern that re-emits duplicate drafts).
            if kept:
                break
            # No legit content yet — just skip this paragraph and keep looking
            continue

        kept.append(stripped)

    result = "\n\n".join(kept).strip()

    # Strip outer quotation marks around the final output
    pairs = [('"', '"'), ("“", "”"), ("「", "」"), ("『", "』")]
    for open_q, close_q in pairs:
        if result.startswith(open_q) and result.endswith(close_q) and len(result) >= 2:
            result = result[len(open_q):-len(close_q)].strip()
            break

    # 末尾に閉じ括弧だけ残っている（対応する開き括弧がない）ケースを剥がす。
    # 例: "本文。」" → "本文。"
    for close_q, open_q in [("」", "「"), ("』", "『"), ("\"", "\""), ("”", "“")]:
        if result.endswith(close_q) and result.count(close_q) > result.count(open_q):
            result = result[: -len(close_q)].rstrip()

    return result


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
    thinking_budget: int | None = None,
    use_google_search: bool = False,
) -> GenerationResult:
    """Call Gemini to generate personalized scout text.

    Supports both:
    - Gemini Developer API (GEMINI_API_KEY set) — free tier, API key auth
    - Vertex AI (GEMINI_API_KEY not set) — GCP, service account auth

    `thinking_budget` overrides the env default for one call (Vertex AI only;
    ignored by the genai SDK path). Pass 0 to disable thinking.

    `use_google_search=True` enables Google Search grounding. Citations are
    returned in `GenerationResult.citations`. If the underlying SDK/model
    doesn't support grounding, the call falls back silently to no-tool
    (citations will be empty) so the caller still gets a text response.
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
                gen_config = _build_generation_config(
                    temperature, max_output_tokens, candidate,
                    for_vertex=True, thinking_budget=thinking_budget,
                )
                from vertexai.generative_models import GenerativeModel
                model = GenerativeModel(model_name=candidate, system_instruction=system_prompt)
                vertex_tools = None
                if use_google_search:
                    tool = _build_search_tool_vertex()
                    if tool is not None:
                        vertex_tools = [tool]
                response = await model.generate_content_async(
                    user_prompt,
                    generation_config=gen_config,
                    safety_settings=_safety_settings_vertex(),
                    tools=vertex_tools,
                )
            else:
                gen_config = _build_generation_config(
                    temperature, max_output_tokens, candidate,
                    for_vertex=False, thinking_budget=thinking_budget,
                )
                import google.generativeai as genai
                model = genai.GenerativeModel(model_name=candidate, system_instruction=system_prompt)
                genai_tools = None
                if use_google_search:
                    tool = _build_search_tool_genai()
                    if tool is not None:
                        genai_tools = [tool]
                # google-generativeai doesn't have async, run in thread
                # Explicitly disable retry to avoid burning quota
                response = await asyncio.to_thread(
                    model.generate_content,
                    user_prompt,
                    generation_config=gen_config,
                    safety_settings=_safety_settings_genai(),
                    tools=genai_tools,
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

    text = _strip_thinking(raw_text)
    text = _strip_markdown(text)

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

    citations = _extract_citations(response) if use_google_search else []

    return GenerationResult(
        text=text,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        model_name=name,
        citations=citations,
    )


async def generate_structured(
    system_prompt: str,
    user_prompt: str,
    response_schema: dict,
    *,
    model_name: str | None = None,
    max_output_tokens: int = 4096,
    temperature: float = 0.7,
    thinking_budget: int | None = None,
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
                    thinking_budget=thinking_budget,
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
                    thinking_budget=thinking_budget,
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
