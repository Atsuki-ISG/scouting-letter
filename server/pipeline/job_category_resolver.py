"""Multi-stage job category resolver.

Goals:
- Self-driving: cover ambiguous cases via multiple stages instead of failing fast.
- Maintenance-free: keyword dictionary lives in Sheets, not in Python constants.
- Diagnosable: when resolution fails, return a structured failure with a
  human-readable message that tells the operator exactly what to fix.

Stages (in order):
  1. Explicit  - options.job_category_filter
  2. Qualification - match keywords against profile.qualifications
  3. Keyword       - match keywords against desired_job + experience + self_pr
  3.5 Batch        - (batch path only) lift unresolved candidates onto the
                     dominant category found in the same batch
  4. Company-single - if the company recruits only one category, use it
  5. Failed        - return ResolutionFailure with diagnostic info

The Stage 5 AI fallback is intentionally not implemented in this iteration.
We'll judge whether it's needed after observing the failure_* logs in production.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from db.sheets_client import label_for_categories, label_for_category
from models.profile import CandidateProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Static qualification map (kept in code because qualification names are stable)
# ---------------------------------------------------------------------------
# Used by `resolve_qualification_only` (backward compat for dashboard helpers)
# and as a baseline before the Sheets-driven keyword list is consulted.
_QUALIFICATION_MAP: list[tuple[str, str]] = [
    ("看護師", "nurse"),
    ("准看護師", "nurse"),
    ("理学療法士", "rehab_pt"),
    ("言語聴覚士", "rehab_st"),
    ("作業療法士", "rehab_ot"),
    ("管理栄養士", "dietitian"),
    ("栄養士", "dietitian"),
    ("主任相談支援専門員", "counselor"),
    ("相談支援従事者研修", "counselor"),
    ("相談支援専門員", "counselor"),
    ("医療事務", "medical_office"),
]


_LEGACY_DESIRED_FALLBACK: list[tuple[str, str]] = [
    ("相談支援専門員", "counselor"),
    ("医療事務", "medical_office"),
    ("受付", "medical_office"),
    ("理学療法士", "rehab_pt"),
    ("PT", "rehab_pt"),
    ("言語聴覚士", "rehab_st"),
    ("ST", "rehab_st"),
    ("作業療法士", "rehab_ot"),
    ("OT", "rehab_ot"),
    ("看護師", "nurse"),
    ("准看護師", "nurse"),
    ("管理栄養士", "dietitian"),
    ("栄養士", "dietitian"),
]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ResolutionFailure:
    """Structured reason for a failed resolution.

    All fields are populated even when not directly relevant, so downstream
    consumers (logs, admin UI, automated proposal workflows) can rely on a
    stable shape.
    """
    missing_fields: list[str]
    searched_text: str
    ambiguous_candidates: list[str]
    company_categories: list[str]
    stage_reached: str  # "explicit" | "qualification" | "keyword" | "company_single"
    human_message: str


@dataclass
class JobCategoryResolution:
    category: str | None
    method: str  # "explicit" | "qualification" | "keyword" | "batch_dominant" | "company_single" | "failed"
    warnings: list[str] = field(default_factory=list)
    debug: str = ""
    failure: ResolutionFailure | None = None


# Built-in fallback keyword set, used when the Sheets-driven dictionary is
# empty (e.g. before the migration script has been run, or during tests).
# Keep in sync with `_QUALIFICATION_MAP` and `_LEGACY_DESIRED_FALLBACK` above.
_BUILTIN_KEYWORDS: list[dict] = (
    [
        {
            "keyword": kw,
            "job_category": cat,
            "source_fields": ["qualification"],
            "weight": 1,
            "company": "",
        }
        for kw, cat in _QUALIFICATION_MAP
    ]
)


def _effective_keywords(keywords: list[dict] | None) -> list[dict]:
    """Return the keyword list to use, falling back to built-ins if empty.

    The fallback also adds the legacy desired-job keyword set so the
    multi-stage resolver behaves at least as well as the old resolver until
    the Sheets-driven dictionary is populated.
    """
    if keywords:
        return keywords
    return _BUILTIN_KEYWORDS + [
        {
            "keyword": kw,
            "job_category": cat,
            "source_fields": ["desired", "experience", "pr"],
            "weight": 1,
            "company": "",
        }
        for kw, cat in _LEGACY_DESIRED_FALLBACK
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_job_category(
    profile: CandidateProfile,
    company_categories: list[str],
    keywords: list[dict] | None = None,
    explicit: str | None = None,
) -> JobCategoryResolution:
    """Resolve a single candidate's job category through Stages 1-2-3-4.

    `keywords` is the merged list returned by SheetsClient._get_job_category_keywords.
    Each item has: keyword, job_category, source_fields (list[str]), weight, company.
    If `keywords` is empty/None, the built-in static dictionary is used as
    a non-breaking fallback.

    Stage 3.5 (batch dominant) is NOT applied here — that lives in
    `resolve_job_category_batch`. The single-candidate path goes straight from
    Stage 3 to Stage 4 to failure.
    """
    return _resolve(
        profile, company_categories, _effective_keywords(keywords), explicit,
        allow_stage_4=True,
    )


def resolve_job_category_batch(
    profiles: list[CandidateProfile],
    company_categories: list[str],
    keywords: list[dict] | None = None,
    explicit: str | None = None,
    dominance_threshold: float = 0.7,
) -> list[JobCategoryResolution]:
    """Resolve a batch of candidates with Stage 3.5 (batch dominant) applied.

    The batch path runs Stage 1-3 individually first, then looks at the
    distribution of decided categories. If one category dominates the batch
    (>= `dominance_threshold` of decided candidates), unresolved candidates
    are lifted onto that category with a warning. Anything still unresolved
    falls through to Stage 4 → failure.
    """
    keywords_eff = _effective_keywords(keywords)
    # Pass 1: individual Stage 1-3 (Stage 4 deferred until after batch lift)
    results = [
        _resolve(p, company_categories, keywords_eff, explicit, allow_stage_4=False)
        for p in profiles
    ]

    # Pass 2: aggregate distribution
    decided_categories = [r.category for r in results if r.category is not None]
    dominant: str | None = None
    dominant_count = 0
    if decided_categories:
        counter = Counter(decided_categories)
        top_category, top_count = counter.most_common(1)[0]
        if top_count / len(decided_categories) >= dominance_threshold:
            dominant = top_category
            dominant_count = top_count

    # Pass 3: lift unresolved using dominant, then Stage 4, then failure
    for i, (profile, r) in enumerate(zip(profiles, results)):
        if r.category is not None:
            continue
        if dominant and dominant in company_categories:
            results[i] = JobCategoryResolution(
                category=dominant,
                method="batch_dominant",
                warnings=[
                    f"[職種推定] バッチ全体の分布からカテゴリ {label_for_category(dominant)} に寄せました "
                    f"({dominant_count}/{len(decided_categories)})"
                ],
                debug=f"batch dominant: {dominant} ({dominant_count}/{len(decided_categories)})",
                failure=None,
            )
            continue
        # Retry Stage 4 + Stage 5 (failure) for this candidate now
        results[i] = _apply_stage_4_or_fail(
            profile, company_categories, keywords_eff, r
        )

    return results


def resolve_qualification_only(
    qualifications: str, desired_job: str = ""
) -> str | None:
    """Backward-compatible lightweight resolver used by dashboard helpers.

    Mirrors the legacy `resolve_job_category(qualifications, desired_job)` API.
    Does NOT consider company_categories or Sheets keywords. Only used for
    quick categorization of historical send data, where richer context isn't
    available.
    """
    if not qualifications:
        return _legacy_check_desired(desired_job)
    normalized = qualifications.replace("/", ",").replace("／", ",").replace("、", ",")
    quals = [q.strip() for q in normalized.split(",") if q.strip()]
    for qual_keyword, category in _QUALIFICATION_MAP:
        for q in quals:
            if qual_keyword in q:
                return category
    return _legacy_check_desired(desired_job)


def _legacy_check_desired(desired_job: str) -> str | None:
    if not desired_job:
        return None
    for keyword, category in _LEGACY_DESIRED_FALLBACK:
        if keyword in desired_job:
            return category
    return None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

# source_fields → which CandidateProfile attributes to read
_SOURCE_FIELD_ATTRS: dict[str, list[str]] = {
    "qualification": ["qualifications"],
    "desired": ["desired_job"],
    "experience": ["experience_type", "experience_years", "work_history_summary"],
    "pr": ["self_pr"],
}


def _gather_text(profile: CandidateProfile, source_field: str) -> str:
    parts: list[str] = []
    for attr in _SOURCE_FIELD_ATTRS.get(source_field, []):
        value = getattr(profile, attr, None)
        if value:
            parts.append(str(value))
    return " ".join(parts)


def _missing_fields(profile: CandidateProfile) -> list[str]:
    """Return the list of resolver-relevant fields that are empty on this profile."""
    missing = []
    for label, attr in [
        ("qualifications", "qualifications"),
        ("desired_job", "desired_job"),
        ("experience_type", "experience_type"),
        ("work_history_summary", "work_history_summary"),
        ("self_pr", "self_pr"),
    ]:
        value = getattr(profile, attr, None)
        if not value or not str(value).strip():
            missing.append(label)
    return missing


def _build_searched_text(profile: CandidateProfile, max_chars: int = 200) -> str:
    """Concatenate all free-text fields for diagnostic display."""
    parts = []
    for source in ("qualification", "desired", "experience", "pr"):
        text = _gather_text(profile, source)
        if text.strip():
            parts.append(f"[{source}] {text.strip()}")
    joined = " | ".join(parts)
    if len(joined) > max_chars:
        return joined[: max_chars - 1] + "…"
    return joined


def _match_keywords(
    profile: CandidateProfile,
    keywords: list[dict],
    company_categories: list[str],
    source_filter: set[str],
) -> set[str]:
    """Return the set of categories matched by keywords whose source_fields
    intersect `source_filter`.

    Only categories that the company actually recruits for are returned.
    """
    company_set = set(company_categories)
    matched: set[str] = set()
    # Cache field text per profile (cheap dict)
    text_cache: dict[str, str] = {}

    for kw in keywords:
        kw_sources = set(kw.get("source_fields", []))
        applicable_sources = kw_sources & source_filter
        if not applicable_sources:
            continue
        category = kw.get("job_category", "")
        if category not in company_set:
            continue
        keyword_text = (kw.get("keyword") or "").strip()
        if not keyword_text:
            continue
        # Search each applicable source field
        for src in applicable_sources:
            if src not in text_cache:
                text_cache[src] = _gather_text(profile, src)
            if keyword_text in text_cache[src]:
                matched.add(category)
                break

    return matched


def _resolve(
    profile: CandidateProfile,
    company_categories: list[str],
    keywords: list[dict],
    explicit: str | None,
    allow_stage_4: bool,
) -> JobCategoryResolution:
    company_set = set(company_categories)

    # ---------- Stage 1: Explicit ----------
    # 拡張から職種が明示指定された場合は無条件で採用する。
    # 会社の company_set に含まれなくても警告付きで通し、判定ロジックの
    # 穴で落ちる候補者を救済する（テンプレ未設定などの後段エラーは維持）。
    if explicit:
        if explicit in company_set:
            return JobCategoryResolution(
                category=explicit,
                method="explicit",
                debug=f"explicit: {explicit}",
            )
        return JobCategoryResolution(
            category=explicit,
            method="explicit",
            warnings=[
                f"[職種強制指定] '{label_for_category(explicit)}' は会社の求人カテゴリに含まれていません"
            ],
            debug=f"explicit (not in company_set): {explicit}",
        )

    # ---------- Stage 0 sanity: company has no recruiting categories ----------
    if not company_categories:
        return _fail(
            profile=profile,
            company_categories=company_categories,
            stage_reached="company_categories_empty",
            ambiguous=[],
        )

    # ---------- Stage 2: Qualification keywords ----------
    qual_matches = _match_keywords(
        profile, keywords, company_categories, source_filter={"qualification"}
    )
    if len(qual_matches) == 1:
        cat = next(iter(qual_matches))
        return JobCategoryResolution(
            category=cat,
            method="qualification",
            debug=f"qualification matched: {cat}",
        )

    # ---------- Stage 3: Free-text keywords ----------
    text_matches = _match_keywords(
        profile,
        keywords,
        company_categories,
        source_filter={"desired", "experience", "pr"},
    )
    # Combine qualification matches into the text search to give preference
    # to candidates that already had a Stage 2 hit
    combined = qual_matches | text_matches

    if len(combined) == 1:
        cat = next(iter(combined))
        method = "qualification" if cat in qual_matches and not text_matches else "keyword"
        return JobCategoryResolution(
            category=cat,
            method=method,
            debug=f"{method} matched: {cat}",
        )

    if len(combined) > 1:
        # Ambiguous — caller may try Stage 4 (single-company fallback) or fail
        if allow_stage_4 and len(company_categories) == 1:
            sole = company_categories[0]
            return JobCategoryResolution(
                category=sole,
                method="company_single",
                warnings=[
                    f"[職種推定] 候補が複数該当しましたが会社の募集カテゴリが {label_for_category(sole)} のみのため確定しました"
                ],
                debug=f"company_single (over ambiguous {sorted(combined)}): {sole}",
            )
        return _fail(
            profile=profile,
            company_categories=company_categories,
            stage_reached="keyword",
            ambiguous=sorted(combined),
        )

    # ---------- Stage 4: Company-single fallback ----------
    if allow_stage_4 and len(company_categories) == 1:
        sole = company_categories[0]
        return JobCategoryResolution(
            category=sole,
            method="company_single",
            warnings=[
                f"[職種推定] 会社の募集カテゴリが {label_for_category(sole)} のみのため自動確定しました"
            ],
            debug=f"company_single: {sole}",
        )

    # ---------- Stage 5: Failed ----------
    return _fail(
        profile=profile,
        company_categories=company_categories,
        stage_reached="keyword",
        ambiguous=[],
    )


def _apply_stage_4_or_fail(
    profile: CandidateProfile,
    company_categories: list[str],
    keywords: list[dict],
    previous: JobCategoryResolution,
) -> JobCategoryResolution:
    """Retry Stage 4 / final failure for a candidate that wasn't lifted by batch."""
    if len(company_categories) == 1:
        sole = company_categories[0]
        return JobCategoryResolution(
            category=sole,
            method="company_single",
            warnings=[
                f"[職種推定] 会社の募集カテゴリが {label_for_category(sole)} のみのため自動確定しました"
            ],
            debug=f"company_single (post-batch): {sole}",
        )
    # Failure: re-derive ambiguous list from the previous attempt's failure if any
    ambiguous: list[str] = []
    if previous.failure and previous.failure.ambiguous_candidates:
        ambiguous = previous.failure.ambiguous_candidates
    return _fail(
        profile=profile,
        company_categories=company_categories,
        stage_reached="keyword",
        ambiguous=ambiguous,
        post_batch=True,
    )


# ---------------------------------------------------------------------------
# Failure construction
# ---------------------------------------------------------------------------

def _fail(
    profile: CandidateProfile,
    company_categories: list[str],
    stage_reached: str,
    ambiguous: list[str],
    post_batch: bool = False,
) -> JobCategoryResolution:
    missing = _missing_fields(profile)
    searched = _build_searched_text(profile)
    failure = ResolutionFailure(
        missing_fields=missing,
        searched_text=searched,
        ambiguous_candidates=sorted(ambiguous),
        company_categories=list(company_categories),
        stage_reached=stage_reached,
        human_message="",  # filled in below
    )
    failure.human_message = _build_failure_message(failure, post_batch=post_batch)
    return JobCategoryResolution(
        category=None,
        method="failed",
        warnings=[],
        debug=f"failed at {stage_reached} (post_batch={post_batch}, ambiguous={ambiguous})",
        failure=failure,
    )


# Field labels used in human messages (Japanese)
_FIELD_LABELS_JA = {
    "qualifications": "資格",
    "desired_job": "希望職種",
    "experience_type": "経験種別",
    "work_history_summary": "職務経歴",
    "self_pr": "自己PR",
}


def _build_failure_message(failure: ResolutionFailure, post_batch: bool = False) -> str:
    """Map a structured failure to an operator-readable message.

    The 10 cases listed in the design plan are all covered. Any future
    branches must be added explicitly — the final fallback returns a
    "[未分類]" prefix so missing cases are surfaced loudly in tests/logs.
    """
    missing = failure.missing_fields
    company_cats = failure.company_categories
    ambiguous = failure.ambiguous_candidates
    stage = failure.stage_reached

    # ---- Case 7: company has no recruiting categories registered ----
    if stage == "company_categories_empty" or not company_cats:
        return (
            "会社の募集カテゴリ（テンプレート）が登録されていません。"
            "管理画面でテンプレートを追加してください"
        )

    # ---- Case 10: explicit category outside company list ----
    if stage == "explicit":
        return (
            f"明示指定されたカテゴリは会社の募集カテゴリ "
            f"[{', '.join(label_for_categories(company_cats))}] に含まれません。指定を見直してください"
        )

    # ---- Case 4 / 5: ambiguous matches across categories ----
    if ambiguous:
        if "qualification" in stage or any(
            "qualification" in (m or "") for m in [stage]
        ):
            # not actually used; ambiguous lives at "keyword" stage in our flow
            pass
        return (
            f"候補者から複数の職種カテゴリ [{', '.join(label_for_categories(ambiguous))}] が検出されました。"
            f"拡張の職種指定で明示してください "
            f"(会社募集: [{', '.join(label_for_categories(company_cats))}])"
        )

    # ---- Case 1: all relevant fields are empty ----
    all_resolver_fields = {
        "qualifications", "desired_job", "experience_type", "work_history_summary", "self_pr"
    }
    if all_resolver_fields.issubset(set(missing)):
        return (
            "候補者のプロフィール情報が不足しています（資格・希望職種・経歴・自己PRすべて空）。"
            "Chrome拡張で再抽出するか、対象から除外してください"
        )

    # ---- Case 2 / 3: text exists but no keyword hit ----
    if failure.searched_text:
        # Distinguish "qualification empty but free text exists" — likely
        # a dictionary gap rather than a profile gap
        free_text_present = any(
            label not in missing
            for label in ("desired_job", "experience_type", "work_history_summary", "self_pr")
        )
        if free_text_present:
            # Case 3 (dictionary gap suspected) vs Case 2 (truly no clue)
            # We can't perfectly distinguish without AI; we surface the
            # searched text and ask the operator to choose.
            base = (
                f"候補者の希望職種・経歴・自己PRから職種キーワードを検出できませんでした"
                f"（参照テキスト: \"{failure.searched_text}\"）。"
                f"辞書追加で救える可能性があります（管理画面の職種キーワードに登録）。"
                f"会社の募集カテゴリ: [{', '.join(label_for_categories(company_cats))}]"
            )
            if post_batch:
                base += "。バッチ全体でも分布が割れたため自動推定できませんでした"
            return base
        # No free text either, qualifications had something but it didn't match any keyword
        # → Case 6 (qualification outside company categories)
        if "qualifications" not in missing:
            return (
                f"候補者の資格は会社の募集カテゴリ [{', '.join(label_for_categories(company_cats))}] に該当しません。"
                f"この候補者は対象外の可能性が高いです"
            )

    # ---- Case 8: post-batch failure with multiple categories ----
    if post_batch and len(company_cats) > 1:
        return (
            f"バッチ全体でも職種分布が割れており、会社募集カテゴリ "
            f"[{', '.join(label_for_categories(company_cats))}] から絞り込めませんでした。"
            f"明示指定するかバッチを職種別に分けてください"
        )

    # ---- Case 9: text empty + multiple company categories ----
    if len(company_cats) > 1 and not failure.searched_text:
        return (
            f"候補者から職種を特定できる情報が得られず、会社の募集カテゴリも複数 "
            f"[{', '.join(label_for_categories(company_cats))}] あるため自動判定できません"
        )

    # ---- Final fallback: surface as "unclassified" so we notice ----
    return (
        f"[未分類] 職種判定に失敗しました "
        f"(stage={stage}, missing={missing}, ambiguous={ambiguous}, "
        f"company_categories={company_cats})"
    )
