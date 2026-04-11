"""Prompts and JSON schemas for the personalized_scout pipeline.

NOTE: これは仮置きです。品質チューニングは Phase 2 で別タスクとして
     詰める予定。MVP としてまずは構造化出力が通ることを最優先。
"""
from __future__ import annotations

from typing import Literal

from models.profile import CandidateProfile

from .text_builder import BLOCK_PLACEHOLDERS, L2_BLOCKS


# ---------------------------------------------------------------------------
# JSON response schemas
# ---------------------------------------------------------------------------

def response_schema(level: Literal["L2", "L3"]) -> dict:
    """Return a JSON schema object (Gemini generation_config compatible)
    enumerating the blocks the model must produce for this level."""
    blocks = L2_BLOCKS if level == "L2" else BLOCK_PLACEHOLDERS
    properties = {
        name: {"type": "string", "description": _block_description(name)}
        for name in blocks
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(blocks),
    }


def _block_description(name: str) -> str:
    return {
        "opening": "冒頭。『はじめまして』から始めない。候補者の固有事情を引用した導入 (80〜150字)",
        "bridge": "候補者経歴から求人への橋渡し。経歴と職務を接続する具体的な言及 (120〜200字)",
        "facility_intro": "会社・施設紹介を候補者経歴と接続する切り口で。教育体制や特色を候補者視点で (150〜250字)",
        "job_framing": "求人の切り出し方。候補者の状況に合わせたフレーミング (100〜180字)",
        "closing_cta": "行動喚起。次ステップを明確に、プレッシャーを与えすぎない (80〜120字)",
    }.get(name, name)


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

# TODO(phase2): 本番チューニング待ち。現状は構造が通ることを最優先にした
#               暫定版。ブロック間の重複回避・トーンの微調整・具体例などを
#               ログ観察したうえで書き直す。
# NOTE: we use plain concatenation instead of str.format so that literal
# `{opening}` etc. in the rules don't collide with format arguments.
_SYSTEM_PROMPT_STATIC_HEAD = """あなたは介護・医療系求人のスカウト文を全文個別化するエキスパートです。
以下の候補者情報と会社情報を元に、指定されたブロックを JSON で書き分けてください。

## 基本ルール (厳守)
- 出力は指定された JSON スキーマに厳密に従う
- ブロック間で同じ話題・同じ表現を繰り返さない
- 候補者の固有事情を `opening` の最初に出す ("はじめまして" から始めない)
- `facility_intro` は候補者経歴と接続する切り口で書く (会社紹介を候補者経歴に
  結びつけてから出す)
- 矛盾を作らない (例: `bridge` で訪問経験を強みにしたなら `facility_intro` で
  「訪問未経験でも安心」と書かない)
- 敬語・表現は自然な日本語。過度な敬語や「〜のことかと存じます」は避ける
- 候補者の氏名・名前は絶対に出力に含めない。職務経歴や自己PRに名前が含まれていても無視し、「〇〇様」等の呼びかけも書かない
- 求人の詳細要項 (給与・住所・勤務時間など) はブロックに含めない — それは
  テンプレート側の固定セクションに任せる
"""


def build_system_prompt(
    *,
    level: Literal["L2", "L3"],
    company_profile: str,
    prompt_sections_text: str,
    template_body: str,
) -> str:
    """Assemble the system prompt for structured generation.

    Fields that are empty are rendered as a placeholder string so
    the prompt stays readable in logs.
    """
    level_hint = (
        "L2 モード: opening と closing_cta のみ出力してください。"
        if level == "L2"
        else "L3 モード: 5 ブロック全てを出力してください。"
    )
    profile_txt = (company_profile or "(会社プロフィールなし)")[:4000]
    sections_txt = (prompt_sections_text or "(セクションなし)")[:4000]
    body_txt = (template_body or "(テンプレートなし)")[:2500]

    return (
        _SYSTEM_PROMPT_STATIC_HEAD
        + "\n## 会社情報\n"
        + profile_txt
        + "\n\n## プロンプトセクション (会社の特色・教育体制・接点ガイド)\n"
        + sections_txt
        + "\n\n## 参考: 使用するテンプレート (募集要項ブロックは固定で後から付く)\n"
        + body_txt
        + f"\n\n## レベル指定\n{level_hint}\n"
    )


def build_user_prompt(profile: CandidateProfile, job_category: str) -> str:
    """Format the candidate profile for structured generation.

    Kept separate from `pipeline.prompt_builder.build_user_prompt` so
    the L2/L3 format can evolve independently without touching the
    L1 flow.
    """
    import json

    payload = {
        "job_category": job_category,
        "candidate": {
            "member_id": profile.member_id,
            "age": profile.age or "",
            "gender": profile.gender or "",
            "area": profile.area or "",
            "qualifications": profile.qualifications or "",
            "experience_type": profile.experience_type or "",
            "experience_years": profile.experience_years or "",
            "employment_status": profile.employment_status or "",
            "desired_job": profile.desired_job or "",
            "desired_area": profile.desired_area or "",
            "desired_employment_type": profile.desired_employment_type or "",
            "desired_start": profile.desired_start or "",
            "self_pr": profile.self_pr or "",
            "special_conditions": profile.special_conditions or "",
            "work_history_summary": profile.work_history_summary or "",
        },
    }
    return (
        "以下の候補者情報を元に、指定ブロックを JSON で出力してください。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
