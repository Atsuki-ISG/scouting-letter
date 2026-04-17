"""Multi-pass competitor research pipeline.

Replaces the single-shot `research_competitors` endpoint with a staged
pipeline that actually uses Google Search grounding (the old code claimed
to but never passed the grounding tool).

Pipeline (5 passes):
  Pass 1  — list up competitors in the same area (grounded, Flash).
  Pass 2A — per-competitor求人条件 (grounded, Flash × N parallel).
  Pass 2B — per-competitor評判・研修・特色 (grounded, Flash × N parallel).
  Pass 3  — synthesis: conditions_table + culture_narrative + hidden_strengths
            (Pro + high thinking, no grounding — the only "smart" pass).
  Pass 4  — hook extraction from hidden_strengths (Flash, no thinking).

Output dict matches COMPETITOR_RESEARCH_HEADERS so the result can be
upserted to the Sheets `競合調査` sheet directly.

Design notes:
  - Pass 2 limits competitor count to MAX_COMPETITORS (default 6). Pass 1
    sometimes returns 10-15, but 3 queries × 15 = 45 grounded calls is too
    wasteful for a quarterly workflow. Prefer depth over breadth.
  - Pass 3 deliberately omits grounding — the synthesis model should work
    off the already-grounded Pass 2 findings rather than second-guessing
    them with more web searches.
  - All Gemini calls go through `generate_personalized_text` / `generate_structured`,
    so MOCK_AI=true Just Works for local testing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

from config import GEMINI_MODEL, GEMINI_PRO_MODEL
from pipeline.ai_generator import (
    generate_personalized_text,
    generate_structured,
    GenerationResult,
)
from pipeline.competitor_queries import queries_for

logger = logging.getLogger(__name__)

MAX_COMPETITORS = 6
PASS2_CONCURRENCY = 4  # asyncio semaphore for grounded per-competitor calls


@dataclass
class Competitor:
    name: str
    url: str = ""
    notes: str = ""


@dataclass
class CompetitorFindings:
    competitor: Competitor
    conditions_text: str = ""
    culture_text: str = ""
    citations: list[dict] = field(default_factory=list)


@dataclass
class ResearchResult:
    """Shape of the final pipeline output. Matches the 競合調査 sheet schema."""
    conditions_table: str = ""
    culture_narrative: str = ""
    hidden_strengths: str = ""
    hooks: str = ""
    sources: list[dict] = field(default_factory=list)
    competitors_list: list[dict] = field(default_factory=list)
    model_used: str = ""

    def to_sheet_dict(self) -> dict[str, str]:
        """Serialize for upsert_competitor_research (list columns → JSON)."""
        return {
            "conditions_table": self.conditions_table,
            "culture_narrative": self.culture_narrative,
            "hidden_strengths": self.hidden_strengths,
            "hooks": self.hooks,
            "sources": json.dumps(self.sources, ensure_ascii=False),
            "competitors_list": json.dumps(self.competitors_list, ensure_ascii=False),
            "model_used": self.model_used,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AREA_KEYWORDS = ("所在地", "住所", "エリア", "拠点")


def _extract_area_from_profile(profile: str) -> str:
    """Pull a geographic area hint out of a profile.md block.

    Strategy: find the first line mentioning 所在地/住所/エリア/拠点 and
    return the portion after the colon. Returns empty string if no hint
    — callers should fall back to the company's display name + "周辺".
    """
    if not profile:
        return ""
    for line in profile.splitlines():
        stripped = line.strip().lstrip("-*#").strip()
        for kw in _AREA_KEYWORDS:
            if kw in stripped:
                # Strip "所在地:" or "**所在地**:" prefix, keep the value.
                after = re.split(r"[：:]", stripped, maxsplit=1)
                if len(after) == 2 and after[1].strip():
                    return after[1].strip()
                return stripped
    return ""


def _merge_citations(groups: list[list[dict]]) -> list[dict]:
    """Flatten multiple citation lists, deduplicating on uri."""
    seen: set[str] = set()
    merged: list[dict] = []
    for group in groups:
        for c in group or []:
            uri = (c.get("uri") or "").strip()
            if not uri or uri in seen:
                continue
            seen.add(uri)
            merged.append({"uri": uri, "title": (c.get("title") or "").strip()})
    return merged


# ---------------------------------------------------------------------------
# Pass 1: competitor listup
# ---------------------------------------------------------------------------

_COMPETITOR_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "competitors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "url": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["name"],
            },
        },
    },
    "required": ["competitors"],
}


async def pass1_list_competitors(
    *,
    target_company_display: str,
    area: str,
    category_label: str,
    query_template: str,
) -> tuple[list[Competitor], list[dict], GenerationResult]:
    """Search Google + parse into a structured competitor list.

    Returns (competitors, citations, generation_metadata).
    """
    search_query = query_template.format(area=area) if area else target_company_display

    # Step 1: grounded search with Flash + no thinking. The output is
    # free-form text listing facilities with context.
    grounded_prompt = (
        f"「{target_company_display}」（{category_label}）の競合施設を、同エリアで"
        f"同じ候補者層を取り合う施設を中心に、最大10件、施設名・公式サイトURL・"
        f"特色を短く挙げてください。検索クエリ: {search_query}"
    )
    grounded = await generate_personalized_text(
        system_prompt=(
            "あなたは介護・医療系の採用市場を調査するアナリストです。"
            "Google検索で実在する施設を調べ、推測ではなく検索結果に基づいて回答してください。"
        ),
        user_prompt=grounded_prompt,
        model_name=GEMINI_MODEL,
        temperature=0.2,
        max_output_tokens=2048,
        thinking_budget=0,
        use_google_search=True,
    )

    # Step 2: structure the free-form text into JSON. No grounding needed,
    # no thinking — just parse. If this fails we fall back to empty list
    # rather than crashing the whole pipeline.
    structure_prompt = (
        "次のテキストから施設を抽出してJSONにしてください。"
        "求人サイト（マイナビ、ジョブメドレー、カイゴDB、協会リスト等）は除外し、"
        "実在の訪問看護ステーション・病院・施設のみを抽出してください。\n\n"
        f"テキスト:\n{grounded.text}"
    )
    try:
        parsed, _ = await generate_structured(
            system_prompt="入力テキストから施設名を抽出する正確なパーサーです。",
            user_prompt=structure_prompt,
            response_schema=_COMPETITOR_LIST_SCHEMA,
            model_name=GEMINI_MODEL,
            temperature=0.0,
            max_output_tokens=2048,
            thinking_budget=0,
        )
        items = parsed.get("competitors", []) or []
    except Exception as e:
        logger.warning(f"Pass 1 structuring failed, using empty list: {e}")
        items = []

    competitors: list[Competitor] = []
    seen_names: set[str] = set()
    for item in items:
        name = (item.get("name") or "").strip()
        # Skip obvious non-competitors and self.
        if not name or name in seen_names:
            continue
        if name == target_company_display:
            continue
        if any(bad in name for bad in ("求人サイト", "転職", "マイナビ", "ジョブメドレー")):
            continue
        seen_names.add(name)
        competitors.append(Competitor(
            name=name,
            url=(item.get("url") or "").strip(),
            notes=(item.get("notes") or "").strip(),
        ))
        if len(competitors) >= MAX_COMPETITORS:
            break

    return competitors, grounded.citations, grounded


# ---------------------------------------------------------------------------
# Pass 2: per-competitor deep dive (conditions + culture) in parallel
# ---------------------------------------------------------------------------

async def pass2_research_competitor(
    competitor: Competitor,
    *,
    conditions_query: str,
    reputation_query: str,
    training_query: str,
    sem: asyncio.Semaphore,
) -> CompetitorFindings:
    """Run 2A (conditions) + 2B (reputation + training) for one competitor."""
    # Even with Flash, N×3 parallel calls can hit quota. Throttle globally.
    async def _one(query: str, system: str) -> GenerationResult:
        async with sem:
            return await generate_personalized_text(
                system_prompt=system,
                user_prompt=query,
                model_name=GEMINI_MODEL,
                temperature=0.2,
                max_output_tokens=2048,
                thinking_budget=1024,
                use_google_search=True,
            )

    system_conditions = (
        "介護・医療業界の求人条件を調査するアナリストです。"
        "Google検索で公式採用ページ・ジョブメドレー・マイナビ看護師などを参照し、"
        "給与・手当・シフト等の数値は必ず出典のある情報のみ使用してください。"
    )
    system_reputation = (
        "介護・医療業界の職場評判を調査するアナリストです。"
        "OpenWork・転職会議・エン・Indeed等の口コミを参照し、"
        "ポジティブ／ネガティブ／退職理由／雰囲気を整理してください。"
    )
    system_training = (
        "介護・医療業界の研修・教育体制を調査するアナリストです。"
        "公式サイトを優先して、新人研修・継続教育・プリセプター制度・特色を整理してください。"
    )

    conditions_task = _one(
        f"「{competitor.name}」の求人条件を調べてください。"
        f"検索クエリ: {conditions_query.format(competitor=competitor.name)}\n"
        "以下の項目を箇条書きで記述してください（不明項目は「不明」と明記）:\n"
        "- 給与（月給・年収・基本給）\n"
        "- オンコール手当 / 夜勤手当\n"
        "- シフト・勤務時間\n"
        "- 各種手当・福利厚生\n"
        "- 年間休日\n"
        "- 施設規模（人員・利用者数）",
        system_conditions,
    )
    reputation_task = _one(
        f"「{competitor.name}」の評判・口コミを調べてください。"
        f"検索クエリ: {reputation_query.format(competitor=competitor.name)}\n"
        "以下の項目を箇条書きで記述してください（該当なしなら「不明」）:\n"
        "- ポジティブ評価（上位3つ）\n"
        "- ネガティブ評価（上位3つ）\n"
        "- 退職理由として挙がるもの\n"
        "- 職場の雰囲気・文化",
        system_reputation,
    )
    training_task = _one(
        f"「{competitor.name}」の研修・教育体制・特色を調べてください。"
        f"検索クエリ: {training_query.format(competitor=competitor.name)}\n"
        "以下の項目を箇条書きで記述してください（該当なしなら「不明」）:\n"
        "- 新人研修（期間・内容）\n"
        "- 継続教育（E-ラーニング・勉強会・外部研修補助）\n"
        "- プリセプター / 同行訪問制度\n"
        "- キャリアパス・専門領域\n"
        "- その他の特色・差別化ポイント",
        system_training,
    )

    conditions, reputation, training = await asyncio.gather(
        conditions_task, reputation_task, training_task,
        return_exceptions=True,
    )

    def _text_or_empty(result) -> tuple[str, list[dict]]:
        if isinstance(result, Exception):
            logger.warning(f"Pass 2 sub-call failed for {competitor.name}: {result}")
            return "（取得失敗）", []
        return result.text, result.citations

    cond_text, cond_cites = _text_or_empty(conditions)
    rep_text, rep_cites = _text_or_empty(reputation)
    train_text, train_cites = _text_or_empty(training)

    return CompetitorFindings(
        competitor=competitor,
        conditions_text=cond_text,
        culture_text=f"### 評判・雰囲気\n{rep_text}\n\n### 研修・特色\n{train_text}",
        citations=_merge_citations([cond_cites, rep_cites, train_cites]),
    )


# ---------------------------------------------------------------------------
# Pass 3: synthesis (conditions table + culture narrative + hidden strengths)
# ---------------------------------------------------------------------------

_SYNTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "conditions_table": {"type": "string"},
        "culture_narrative": {"type": "string"},
        "hidden_strengths": {"type": "string"},
    },
    "required": ["conditions_table", "culture_narrative", "hidden_strengths"],
}


async def pass3_synthesize(
    *,
    target_company_display: str,
    category_label: str,
    profile: str,
    findings: list[CompetitorFindings],
) -> tuple[dict[str, str], GenerationResult]:
    """Combine target profile + competitor findings into the final 3 artifacts.

    Runs on Pro + high thinking, NO grounding — this is the synthesis /
    reasoning pass, not a data-collection pass.
    """
    # Build the "competitors data" block that gets injected into the prompt.
    sections: list[str] = []
    for i, f in enumerate(findings, start=1):
        sections.append(
            f"## 競合{i}: {f.competitor.name}\n"
            f"URL: {f.competitor.url or '不明'}\n\n"
            f"### 求人条件\n{f.conditions_text}\n\n"
            f"### 文化・評判・研修\n{f.culture_text}"
        )
    competitors_block = "\n\n---\n\n".join(sections) if sections else "（競合データなし）"

    system_prompt = (
        "あなたは介護・医療業界の採用戦略コンサルタントです。"
        "対象会社のプロフィールと、Google検索で収集した競合データをもとに、"
        "求人条件の比較表・文化面の比較・隠れた強みの3点を作成します。\n\n"
        "## 出力の原則\n"
        "1. conditions_table は Markdown 表で、列は 施設名 / 給与 / オンコール / "
        "休日 / 特色 とする。数字が不明なら「不明」と書く。捏造しない。\n"
        "2. culture_narrative は各競合の雰囲気・評判・研修を 2-3 段落でまとめる。\n"
        "3. hidden_strengths は対象会社が**まだ気づいていない可能性がある強み**を"
        "3-5個、各100字程度で提案する。profile.md に書いてあることをそのまま"
        "繰り返すのは禁止。競合との比較で初めて浮かび上がる優位性を書くこと。\n"
        "4. 各 hidden_strength には『発見 / 根拠 / 活用案』の3要素を必ず含める。"
    )

    user_prompt = (
        f"# 対象会社\n{target_company_display}（{category_label}）\n\n"
        f"# 対象会社プロフィール\n{profile[:3000] if profile else '(未登録)'}\n\n"
        f"# 競合データ（Google検索で収集済み）\n\n{competitors_block}"
    )

    parsed, meta = await generate_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_schema=_SYNTHESIS_SCHEMA,
        model_name=GEMINI_PRO_MODEL,
        temperature=0.3,
        max_output_tokens=8192,
        thinking_budget=8192,
    )
    return parsed, meta


# ---------------------------------------------------------------------------
# Pass 4: hook extraction
# ---------------------------------------------------------------------------

async def pass4_extract_hooks(hidden_strengths: str) -> str:
    """Turn the hidden-strengths narrative into short scout-ready hooks."""
    if not hidden_strengths.strip():
        return ""

    result = await generate_personalized_text(
        system_prompt=(
            "あなたはスカウト文のコピーライターです。"
            "入力された『隠れた強み』から、スカウト文の冒頭フックに使える短い表現を抽出します。"
        ),
        user_prompt=(
            "以下の『隠れた強み』から、スカウト文で使えるフック表現を箇条書きで抽出してください。\n"
            "ルール:\n"
            "- 1行1フック、全体で5〜10行\n"
            "- 各行は30〜60字程度\n"
            "- 番号・記号・太字などの装飾は付けない（先頭は `- ` のみ）\n"
            "- 「〜とのこと」「〜と存じます」など回りくどい敬語は禁止\n"
            "- 具体的な数字・固有名詞（東京都指定 / 大手グループ等）があれば残す\n\n"
            f"# 隠れた強み\n{hidden_strengths}"
        ),
        model_name=GEMINI_MODEL,
        temperature=0.4,
        max_output_tokens=1024,
        thinking_budget=0,
    )
    return result.text.strip()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run_research(
    *,
    company_id: str,
    target_company_display: str,
    category_label: str,
    profile: str,
    job_category: str = "",
) -> ResearchResult:
    """Full multi-pass research. Returns a ResearchResult ready for Sheets upsert.

    The caller is responsible for calling `sheets_writer.upsert_competitor_research`
    with the returned `ResearchResult.to_sheet_dict()`. This function itself
    is pure: no Sheets I/O, no Sheets side effects.
    """
    queries = queries_for(company_id)
    area = _extract_area_from_profile(profile) or target_company_display

    logger.info(
        f"[competitor_research] start company={company_id} category={job_category} area={area!r}"
    )

    # Pass 1 — listup
    competitors, listup_cites, listup_meta = await pass1_list_competitors(
        target_company_display=target_company_display,
        area=area,
        category_label=category_label,
        query_template=queries.listup,
    )
    logger.info(f"[competitor_research] pass1: {len(competitors)} competitors")

    # Pass 2 — per-competitor deep dives
    sem = asyncio.Semaphore(PASS2_CONCURRENCY)
    findings: list[CompetitorFindings] = []
    if competitors:
        tasks = [
            pass2_research_competitor(
                c,
                conditions_query=queries.conditions,
                reputation_query=queries.reputation,
                training_query=queries.training_culture,
                sem=sem,
            )
            for c in competitors
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for c, r in zip(competitors, results):
            if isinstance(r, Exception):
                logger.warning(f"[competitor_research] pass2 failed for {c.name}: {r}")
                findings.append(CompetitorFindings(competitor=c, conditions_text="（取得失敗）", culture_text="（取得失敗）"))
            else:
                findings.append(r)
    logger.info(f"[competitor_research] pass2: {len(findings)} findings gathered")

    # Pass 3 — synthesis
    synth, synth_meta = await pass3_synthesize(
        target_company_display=target_company_display,
        category_label=category_label,
        profile=profile,
        findings=findings,
    )
    logger.info(
        f"[competitor_research] pass3 done: "
        f"conditions_len={len(synth.get('conditions_table', ''))} "
        f"culture_len={len(synth.get('culture_narrative', ''))} "
        f"strengths_len={len(synth.get('hidden_strengths', ''))}"
    )

    # Pass 4 — hook extraction
    hooks = await pass4_extract_hooks(synth.get("hidden_strengths", ""))

    all_cites = _merge_citations([listup_cites] + [f.citations for f in findings])

    return ResearchResult(
        conditions_table=synth.get("conditions_table", ""),
        culture_narrative=synth.get("culture_narrative", ""),
        hidden_strengths=synth.get("hidden_strengths", ""),
        hooks=hooks,
        sources=all_cites,
        competitors_list=[
            {"name": c.competitor.name, "url": c.competitor.url, "notes": c.competitor.notes}
            for c in findings
        ],
        model_used=f"pass1-2:{GEMINI_MODEL} / pass3:{GEMINI_PRO_MODEL}",
    )
