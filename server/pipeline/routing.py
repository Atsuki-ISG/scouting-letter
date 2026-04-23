"""Routing engine: decides (skeleton, tone, attribute) for a candidate
based on rules loaded from Sheets. Called by the pipeline before
generation to select the right template and tone_instruction.

Rules are defined in the `振り分けルール` sheet with a simple Python-like
DSL for the `condition` column. Supported syntax:

    Comparison: ==, !=, >=, <=, >, <
    Logical:    AND, OR (case-insensitive), also "and"/"or"
    Negation:   NOT, "not"
    Membership: "高収入" in special_conditions
                age_group in ("20s-early", "30s-early")
    Literals:   true, false, null, integers, strings (double-quoted)

Context variables available (built by build_context from the profile):

    nursing_years: int | None       — 訪問看護経験年数（推定）
    total_years:   int | None       — 看護師/PT/OT/ST等としての総経験年数
    has_pr:        bool             — 自己PRあり
    blank_years:   int              — 直近ブランク推定年数（0=ブランクなし）
    age_group:     str | None       — "20s-early"〜"40s+"
    employment_status: str          — "就業中" / "離職中" 等（raw text）
    special_conditions: list[str]   — こだわり条件（分解済み）
    management_keywords: bool       — 主任・師長・管理者 等のキーワード有無
    big_corp_keywords: bool         — 大手病院キーワード有無
"""
from __future__ import annotations

import ast
import logging
import operator
import re
from typing import Any, Optional, TypedDict

from db.sheets_client import sheets_client
from models.profile import CandidateProfile

logger = logging.getLogger(__name__)


class RoutingResult(TypedDict):
    skeleton: str
    tone: str
    attribute: str
    matched_rule: str


DEFAULT_ROUTING: RoutingResult = {
    "skeleton": "alpha",
    "tone": "casual",
    "attribute": "general",
    "matched_rule": "default_fallback",
}


# ---------------------------------------------------------------------------
# Context extraction — profile → flat dict for DSL evaluation
# ---------------------------------------------------------------------------

_PLACEHOLDER_VALUES = {"未入力", "なし", "-", "ー", ""}

_AGE_GROUP_THRESHOLDS = (
    ("20s-early", 20, 25),
    ("20s-late", 25, 30),
    ("30s-early", 30, 35),
    ("30s-late", 35, 40),
    ("40s+", 40, 200),
)

_MANAGEMENT_KEYWORDS = ("主任", "師長", "管理者", "所長", "リーダー", "マネージャー", "係長")
_BIG_CORP_KEYWORDS = (
    "虎の門", "聖路加", "慈恵", "順天堂", "東京医科", "日本医大",
    "日本赤十字", "東大", "慶應", "北里", "東京女子医",
)
_VISITING_NURSE_PATTERNS = ("訪問看護", "訪看", "訪問リハ")

_CONDITION_ALIASES = {
    # Map common こだわり条件 phrases → canonical tokens
    "高収入": "高収入",
    "年収アップ": "高収入",
    "高年収": "高収入",
    "ブランク": "ブランク可",
    "ブランク可": "ブランク可",
    "未経験": "未経験可",
    "未経験可": "未経験可",
    "教育": "教育体制",
    "教育体制": "教育体制",
    "研修": "教育体制",
    "残業なし": "残業少",
    "残業少": "残業少",
    "残業少なめ": "残業少",
    "定時": "残業少",
    "土日休": "土日休み",
    "土日休み": "土日休み",
    "産休": "産休育休",
    "育休": "産休育休",
    "託児": "託児所",
    "時短": "時短",
    "時短勤務": "時短",
    "資格取得": "資格取得支援",
    "資格取得支援": "資格取得支援",
    "スキルアップ": "資格取得支援",
    "車通勤": "車通勤可",
    "駅近": "駅近",
}


def _parse_int_years(text: str | None) -> int | None:
    """Extract the first integer from a free-text years string.

    Examples:
        "8年"     → 8
        "3年2ヶ月" → 3
        "1年未満" → 0
        None       → None
    """
    if not text or text.strip() in _PLACEHOLDER_VALUES:
        return None
    s = text.strip()
    if "未満" in s:
        return 0
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None


def _age_group_from_age(age_str: str | None) -> str | None:
    if not age_str or age_str.strip() in _PLACEHOLDER_VALUES:
        return None
    m = re.search(r"\d+", age_str)
    if not m:
        return None
    age = int(m.group())
    for label, lo, hi in _AGE_GROUP_THRESHOLDS:
        if lo <= age < hi:
            return label
    return None


def _is_visiting_nurse_experience(experience_type: str) -> bool:
    return any(p in experience_type for p in _VISITING_NURSE_PATTERNS)


def _estimate_nursing_years(
    experience_type: str, work_history: str, total_years: int | None
) -> int | None:
    """Estimate 訪問看護 experience years.

    Semantics:
    - None: 経歴情報ゼロ（experience_type・work_history・total_years 全て不明）
    - 0:    他職種経験はあるが訪問看護経験なし
    - N:    訪問看護 N 年

    Heuristic: if experience_type or work_history mentions 訪問看護, try
    to parse a specific year count; fall back to total_years. If neither
    mentions 訪問看護, return 0 when any other experience signal exists,
    None when no signal at all.
    """
    combined = f"{experience_type} {work_history}".strip()
    if not combined and total_years is None:
        return None  # no experience info at all
    if not _is_visiting_nurse_experience(combined):
        # Has some experience but not visiting nurse, OR has total_years but
        # experience_type is a different job type.
        return 0 if (combined or total_years is not None) else None
    m = re.search(r"訪問看護[^\d]{0,10}(\d+)\s*年", combined)
    if m:
        return int(m.group(1))
    return total_years


def _estimate_blank_years(work_history: str) -> int:
    """Very rough blank-years estimate from work history text.

    Looks for patterns like "2024年〜現在" or "2022年退職" near the end.
    Returns 0 if no blank is detected. Intentionally conservative —
    false positives here force unnecessary letter-tone routing.

    For the initial release this is a minimal stub; the rule
    `blank_years >= 1` is tuned to only fire when explicit cues
    are present in work_history_summary.
    """
    if not work_history:
        return 0
    # Look for explicit "ブランク" keyword
    m = re.search(r"ブランク[^\d]{0,5}(\d+)\s*年", work_history)
    if m:
        return int(m.group(1))
    if "ブランク" in work_history:
        return 1  # unknown length, but cue present
    return 0


def _parse_special_conditions(text: str | None) -> list[str]:
    """Parse the こだわり条件 field into canonical tokens.

    The field in profile extraction is free text separated by commas,
    spaces or newlines. We normalize via _CONDITION_ALIASES so DSL
    rules like `"高収入" in special_conditions` work robustly.
    """
    if not text or text.strip() in _PLACEHOLDER_VALUES:
        return []
    raw_tokens = re.split(r"[、,，\s\n]+", text.strip())
    result: list[str] = []
    for token in raw_tokens:
        tok = token.strip()
        if not tok:
            continue
        canonical = _CONDITION_ALIASES.get(tok)
        if canonical and canonical not in result:
            result.append(canonical)
        # also keep the raw token so exact-phrase matches still work
        if tok not in result:
            result.append(tok)
    return result


def build_context(profile: CandidateProfile) -> dict[str, Any]:
    """Extract routing DSL variables from a candidate profile."""
    total_years = _parse_int_years(profile.experience_years)
    experience_type = (profile.experience_type or "").strip()
    work_history = (profile.work_history_summary or "").strip()
    nursing_years = _estimate_nursing_years(experience_type, work_history, total_years)

    self_pr = (profile.self_pr or "").strip()
    has_pr = bool(self_pr and self_pr not in _PLACEHOLDER_VALUES)

    history_blob = f"{experience_type} {work_history} {self_pr}"
    management_keywords = any(kw in history_blob for kw in _MANAGEMENT_KEYWORDS)
    big_corp_keywords = any(kw in history_blob for kw in _BIG_CORP_KEYWORDS)

    return {
        "nursing_years": nursing_years,
        "total_years": total_years,
        "has_pr": has_pr,
        "blank_years": _estimate_blank_years(work_history),
        "age_group": _age_group_from_age(profile.age),
        "employment_status": (profile.employment_status or "").strip(),
        "special_conditions": _parse_special_conditions(profile.special_conditions),
        "management_keywords": management_keywords,
        "big_corp_keywords": big_corp_keywords,
    }


# ---------------------------------------------------------------------------
# DSL evaluator — safe AST-based expression evaluation
# ---------------------------------------------------------------------------

_COMPARISON_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b if b is not None else False,
    ast.NotIn: lambda a, b: a not in b if b is not None else True,
}


def _preprocess_condition(cond: str) -> str:
    """Convert Sheets DSL syntax to Python-parseable syntax.

    - AND/OR → and/or (case-insensitive on word boundaries)
    - NOT    → not
    - true/false/null → True/False/None (only as standalone tokens)
    """
    # Word-boundary replacements to avoid clobbering identifiers like
    # `management_keywords` (which contains no problematic substrings
    # but we keep the boundaries strict anyway).
    cond = re.sub(r"\b(AND|and)\b", "and", cond)
    cond = re.sub(r"\b(OR|or)\b", "or", cond)
    cond = re.sub(r"\b(NOT|not)\b", "not", cond)
    cond = re.sub(r"\btrue\b", "True", cond)
    cond = re.sub(r"\bfalse\b", "False", cond)
    cond = re.sub(r"\bnull\b", "None", cond)
    return cond


def _safe_eval(node: ast.AST, context: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body, context)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return context.get(node.id)
    if isinstance(node, ast.Tuple):
        return tuple(_safe_eval(e, context) for e in node.elts)
    if isinstance(node, ast.List):
        return [_safe_eval(e, context) for e in node.elts]
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return not _safe_eval(node.operand, context)
        if isinstance(node.op, ast.USub):
            return -_safe_eval(node.operand, context)
        raise ValueError(f"Unsupported unary op: {type(node.op).__name__}")
    if isinstance(node, ast.BoolOp):
        values = [_safe_eval(v, context) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise ValueError(f"Unsupported bool op: {type(node.op).__name__}")
    if isinstance(node, ast.Compare):
        left = _safe_eval(node.left, context)
        for op, comparator in zip(node.ops, node.comparators):
            right = _safe_eval(comparator, context)
            op_fn = _COMPARISON_OPS.get(type(op))
            if op_fn is None:
                raise ValueError(f"Unsupported comparison: {type(op).__name__}")
            # None-aware comparison: if either side is None for numeric ops,
            # the result is False (match nothing). This matches the intuitive
            # semantics of rules like `nursing_years >= 3` when the field is
            # unknown — the rule should NOT match, not raise.
            if type(op) in (ast.Lt, ast.LtE, ast.Gt, ast.GtE) and (
                left is None or right is None
            ):
                return False
            if type(op) in (ast.Eq, ast.NotEq):
                result = op_fn(left, right)
            else:
                try:
                    result = op_fn(left, right)
                except TypeError:
                    return False
            if not result:
                return False
            left = right
        return True
    raise ValueError(f"Unsupported AST node: {type(node).__name__}")


def evaluate_condition(cond: str, context: dict[str, Any]) -> bool:
    """Evaluate a routing rule condition string against the context.

    Returns False on any parse or evaluation error (never raises).
    """
    if not cond or not cond.strip():
        return False
    processed = _preprocess_condition(cond)
    try:
        tree = ast.parse(processed, mode="eval")
    except SyntaxError as e:
        logger.warning(f"Routing condition syntax error: {cond!r} → {e}")
        return False
    try:
        return bool(_safe_eval(tree, context))
    except Exception as e:
        logger.warning(f"Routing condition eval error: {cond!r} → {e}")
        return False


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def route(profile: CandidateProfile) -> RoutingResult:
    """Evaluate routing rules for a candidate and return the first match.

    If no rules are configured, or no rule matches, returns the default
    (alpha, casual, general).
    """
    try:
        rules = sheets_client.get_routing_rules()
    except Exception as e:
        logger.warning(f"Failed to load routing rules: {e}")
        return {**DEFAULT_ROUTING}

    if not rules:
        return {**DEFAULT_ROUTING}

    context = build_context(profile)
    for rule in rules:
        cond = rule.get("condition", "")
        if not cond:
            continue
        if evaluate_condition(cond, context):
            return {
                "skeleton": rule.get("skeleton") or "alpha",
                "tone": rule.get("tone") or "casual",
                "attribute": rule.get("attribute") or "general",
                "matched_rule": rule.get("name") or f"priority={rule.get('priority')}",
            }
    return {**DEFAULT_ROUTING}


def resolve_tone_instruction(tone_id: Optional[str]) -> Optional[str]:
    """Look up the tone_instruction text from Sheets for a given tone_id."""
    if not tone_id:
        return None
    try:
        return sheets_client.get_tone_instruction(tone_id)
    except Exception as e:
        logger.warning(f"Failed to load tone_instruction for {tone_id!r}: {e}")
        return None
