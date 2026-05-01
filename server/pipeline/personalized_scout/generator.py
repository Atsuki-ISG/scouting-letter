"""Thin wrapper around `generate_structured` that knows about the
personalized_scout block schema. Kept separate from `pipeline.py` so
tests can mock just the AI call without stubbing out the whole flow.
"""
from __future__ import annotations

import json as _json
from typing import Literal, Optional

from pipeline.ai_generator import generate_structured, GenerationResult
from models.profile import CandidateProfile

from .prompt import (
    build_system_prompt,
    build_user_prompt,
    response_schema,
)
from .text_builder import BLOCK_PLACEHOLDERS, L2_BLOCKS


async def generate_blocks(
    *,
    level: Literal["L2", "L3"],
    profile: CandidateProfile,
    job_category: str,
    company_profile: str,
    prompt_sections_text: str,
    template_body: str,
    knowledge_rules: Optional[list[str]] = None,
    tone_instruction: Optional[str] = None,
    max_output_tokens: int = 4096,
    temperature: float = 0.55,
) -> tuple[dict[str, str], GenerationResult]:
    """Call the model once and return the named blocks + token metadata.

    The returned dict is always guaranteed to have every block key
    for the requested level (missing/empty fields become ""), so
    downstream code doesn't need to defend against partial payloads.
    """
    schema = response_schema(level)
    system_prompt = build_system_prompt(
        level=level,
        company_profile=company_profile,
        prompt_sections_text=prompt_sections_text,
        template_body=template_body,
        knowledge_rules=knowledge_rules,
        tone_instruction=tone_instruction,
    )
    user_prompt = build_user_prompt(profile, job_category)

    parsed, meta = await generate_structured(
        system_prompt,
        user_prompt,
        schema,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
    )

    expected = L2_BLOCKS if level == "L2" else BLOCK_PLACEHOLDERS
    blocks: dict[str, str] = {}
    for name in expected:
        value = parsed.get(name, "")
        blocks[name] = (value or "").strip() if isinstance(value, str) else ""
    return blocks, meta


_REVISE_SYSTEM_PROMPT = """あなたはスカウト文の最終校正を担当するエキスパートです。
入力として渡される 5 ブロックのドラフトを点検し、以下の癖が含まれていれば
自然な表現に**書き換えて**ください。癖が含まれていないブロックはそのまま
返してください。

## 検出して直す癖（厳守）

### 1. 属性反射フレーズ（無意識に出る慰め文句）
属性を見て反射的に出る同情・慰め前置きは、**1 回でも検出したら削除**:
- 「〜には不安もあるかと思います」「〜の不安を抱え込まないよう」
- 「〜には◯◯と感じる方もいらっしゃいますが」
- 「未経験でも安心」「ブランクがあっても安心」（事実で置き換え可：例「同行訪問が約 1 ヶ月」）
- 「丁寧にサポートします」（具体行動に置き換え可：例「先輩の同行訪問」）
- 削除した分でブロックの字数下限を下回ってもよい。**不自然な肉付けはしない**

### 2. PR 薄補完テンプレ（候補者 PR に具体記述がない形容を削除）
- 「お一人おひとりに寄り添う姿勢」「些細な変化に気づく観察眼」
- 「初対面の方との信頼関係を築きながら情報を整理し」
- 「現場の最前線で支えてこられた」
- 「生活リズムを尊重する視点」「自己学習にも励む姿勢」
- 「丁寧に汲み取る対話力」
- これらは候補者 PR に具体記述がある場合のみ書ける。なければ削除

### 3. 「いただけます／いただける」の乱用
- 1 ブロックで 2 回以上、または全体で 3 回以上出ていれば置換
- 言い換え: 「〜できる環境です」「〜の場として活きます」「〜が深まります」

### 4. 「あなた」直接呼びかけ・断定
- 「あなたに〜」「〜のあなたに」 → 「ご自身の」「お持ちの方」「経験を重ねてこられた方」
- 「〜のはずです」「〜なるはずです」「〜大きな力になるはずです」「〜に違いない」「〜は必ず〜です」 → 「〜になるのではと思います」

### 5. NG 語（1 回でも禁止）
- 「局面」 → 「場面」
- 「還元」 → 「活かす」「役立てる」
- 「接続可能」「接続できます」 → 「つながります」「活きます」
- 「文脈」 → 「場面」「状況」
- 「志向」 → 「思い」「お考え」「気持ち」（日常会話で使わない硬い語）

### 5b. 同義語の重複（1 文または隣接 2 文で意味の近い語が重なっていれば書き換え）
- ✕「連携する**環境**で、専門性を磨いていただける**場**がある」 → ◎「連携する中で、専門性を磨いていただける**環境**です」
- ✕「ご経験で培われた**姿勢**が、現場で活きる**視点**になる」（姿勢/視点 が重複）
- ✕「**経験**を活かしながら、**実績**を積み重ねていく」（経験/実績 が近い）
- 具体的に避ける近接同義ペア: 環境⇔場、姿勢⇔視点、経験⇔実績、思い⇔気持ち、力⇔強み、現場⇔場面

### 6. 立地・地理への AI 側からの言及
- 「◯◯区を拠点に」「◯◯区を中心に」「ご希望のエリア」 → 削除
- 立地・所在地・通勤の話はテンプレート固定セクションに任せる

### 7. 心情汲み取り前置き
- 「〜ではないでしょうか」「〜タイミングではないでしょうか」 → 直接の事実提示に置換
- 「〜が気になるかもしれません」「気にされる方が多いです」 → 削除

## 修正方針

- ドラフトの**文体・トーンは尊重**する。過度に書き換えず、該当箇所だけ直す
- 削除した分で字数が短くなっても、無理な肉付けはしない
- 「不安」「両立」「サポート」等の語自体は OK。**属性反射的な慰め前置き構文**だけが対象
- 各ブロックの役割（opening/bridge/facility_intro/job_framing/closing_cta）は変えない
- 出力は入力と同じ JSON スキーマで、**全 5 ブロック**を含める（無修正でもブロックは省略しない）
"""


async def revise_blocks(
    *,
    level: Literal["L2", "L3"],
    draft_blocks: dict[str, str],
    max_output_tokens: int = 4096,
    temperature: float = 0.3,
) -> tuple[dict[str, str], GenerationResult]:
    """Run a self-critique/revision pass on a draft set of blocks.

    Catches reflex patterns (慰め前置き・PR 薄補完・乱用語句) that the
    first-pass prompt cannot fully suppress. Uses the same response
    schema so callers can swap in the revised dict transparently.

    Lower temperature than the draft pass — we want stable cleanup,
    not creative rewriting.
    """
    schema = response_schema(level)
    user_prompt = (
        "以下が初稿の 5 ブロックです。検出して直す癖が含まれていれば書き換えて、"
        "同じ JSON スキーマで返してください。\n\n"
        f"{_json.dumps(draft_blocks, ensure_ascii=False, indent=2)}"
    )
    parsed, meta = await generate_structured(
        _REVISE_SYSTEM_PROMPT,
        user_prompt,
        schema,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
    )
    expected = L2_BLOCKS if level == "L2" else BLOCK_PLACEHOLDERS
    blocks: dict[str, str] = {}
    for name in expected:
        value = parsed.get(name, "")
        revised = (value or "").strip() if isinstance(value, str) else ""
        # Defensive fallback: if the revise pass returned an empty
        # block where the draft had content, keep the draft. Better
        # to ship the draft than a broken empty block.
        if not revised and draft_blocks.get(name, "").strip():
            blocks[name] = draft_blocks[name].strip()
        else:
            blocks[name] = revised
    return blocks, meta
