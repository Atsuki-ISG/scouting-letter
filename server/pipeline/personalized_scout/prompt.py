"""Prompts and JSON schemas for the personalized_scout pipeline (L2/L3).

Phase 2 本番チューニング済み。
- 静的ヘッド: JSON構造制御・ブロック別ライティングガイド・重複回避
- 品質ルール（NG表現・トーン等）: Sheetsプロンプトセクション + ナレッジプール
"""
from __future__ import annotations

from typing import Literal, Optional

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
        "opening": (
            "冒頭の接点予告。候補者経歴の具体的な1点と会社側の接続ポイントを示す。"
            "役割は『接点予告まで』に限定し、利益・意味・『活きる/力になる』系の"
            "表現は使わない（それは bridge/facility_intro に委ねる）。"
            "文末は『〜と重なります』『〜が目に留まりました』『〜が気になりました』等。"
            "『はじめまして』禁止、『拝見し』禁止（テンプレや他ブロックで既出）。"
            "求人職種と同一資格名への言及は不要。80〜150字"
        ),
        "bridge": (
            "opening で触れた接点を具体的な利益・意味に展開する。"
            "冒頭は『会社側の文脈』から入る（候補者経歴の事実反復で始めない）。"
            "例: ◎『当ステーションの○○では〜』『○○の現場では〜』"
            "✕『X年のご経験は〜』『○○のご実績は〜』（opening と重複）。"
            "opening と同じ動詞（重なる・目に留まる・気になる）を再使用しない。"
            "120〜200字"
        ),
        "facility_intro": (
            "会社・施設の紹介を候補者の背景と接続する形で。教育体制や特色は"
            "プロンプトセクション・会社情報に**明記されている内容のみ**使用"
            "（他社・他職種の制度、業界一般の制度名の創作は禁止）。"
            "経験豊富な候補者には専門性を活かせる環境として、情報が"
            "少ない候補者には成長環境として訴求。150〜250字"
        ),
        "job_framing": (
            "求人ポジションを候補者の状況に合わせてフレーミング。希望雇用形態・"
            "希望入職時期・希望勤務地があれば触れる。給与・住所・勤務時間は"
            "テンプレート固定セクションに任せ、ここでは書かない。100〜180字"
        ),
        "closing_cta": (
            "行動喚起。『まずはお話だけでも』のような軽い誘い。送り手の感情"
            "（『ご一緒したい』『想いを強く感じ』）ではなく候補者へのオファーを"
            "主語にする。プレッシャーを与えない。80〜120字"
        ),
    }.get(name, name)


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_STATIC_HEAD = """あなたは介護・医療系求人のスカウト文をブロック単位で全文個別化するエキスパートです。
候補者情報と会社情報を元に、指定されたブロックを JSON で書き分けてください。
生成したブロックはテンプレートの固定セクション（募集要項・会社概要等）に挿入されます。

## JSON 出力ルール (厳守)
- 出力は指定された JSON スキーマに厳密に従う
- 各ブロックは指定された文字数範囲を守る

## ブロック別ライティングガイド

### opening (冒頭接点予告 80〜150字)

候補者経歴の具体的な1点 × 会社側の接続ポイント を1段落で示す。
**役割は「接点予告まで」に限定**。利益・意味・「活きる/力になる/役割を担う」系の表現は使わない（それは bridge/facility_intro の役割）。

- 「はじめまして」から始めない
- 求人職種と同一の資格名への言及は不要（保有前提で送っている）
- 複数資格（例: 看護師+保健師）への言及はOK
- テンプレートに「拝見し」がある場合はブロック内で別表現を使う

**opening 文末パターン（利益表現は禁止）**:
- ◎「〜と重なります」「〜と重なる場面が多いと感じました」
- ◎「〜が目に留まりました」「〜が印象的でした」「〜が気になりました」
- ◎「〜が、当ステーションでも注目しているポイントでした」
- ✕「〜で活きます」「〜で大きな力になります」「〜の役割を担います」（bridge の役割）

### bridge (接点の展開 120〜200字)

opening で触れた接点を**具体的な利益・意味・役割**に展開する。

**冒頭は「会社側の文脈」から入る**（候補者経歴の事実反復で始めない）。opening と同じ構造で始めると、読み手は同じ話を2回読む印象を受ける。

- ✕「X年のご経験は〜」「○○のご実績は〜」（opening と冒頭構造が被る）
- ◎「当ステーションの○○では〜」「○○の現場では〜」（会社側の描写から入る）
- ◎「当ステーションは〜を大切にしており〜」（会社側の文脈から）

opening と同じ動詞（重なる・目に留まる・気になる）を再使用しない。
facility_intro と話題が重複しないよう注意。
経験豊富な候補者には「即戦力」として、経験浅い候補者には「基盤がある」として接続。

### facility_intro (施設紹介 150〜250字)

会社・施設の紹介を候補者の背景と接続する形で。

- 教育体制や特色はプロンプトセクション・会社情報に**明記されている内容のみ**使用する
- 他社・他職種の制度を混ぜない（必ず当該会社の情報のみ）
- 経験豊富な候補者 → 専門性を活かせる環境として訴求
- 情報が少ない候補者 → 成長環境として訴求（ただし就業中なら経験者前提で書く）

### job_framing (フレーミング 100〜180字)

求人ポジションを候補者の状況に合わせて切り出す。

- 希望雇用形態・希望入職時期・希望勤務地があれば触れる
- 給与・住所・勤務時間はテンプレート固定セクションに任せ、ここでは書かない

### closing_cta (行動喚起 80〜120字)

次のステップへの軽い誘い。

- 送り手の感情（「ご一緒したい」「想いを強く感じ」）ではなく、候補者へのオファーを主語にする
- プレッシャーを与えない

## 重複回避ルール

- **opening ↔ bridge**: 最重要。opening は「接点予告」、bridge は「意味・利益の展開」。bridge の冒頭は会社側の文脈から入ること
- ブロック間: 同じ話題・同じ表現を複数ブロックで繰り返さない
- ブロック↔テンプレート: テンプレート固定セクションに含まれる情報をブロックに書かない
- 矛盾を作らない（例: bridge で訪問経験を強みにしたなら facility_intro で「未経験でも安心」と書かない）

## 捏造防止（厳守）

以下は**絶対にやってはいけない**:

1. **会社情報・プロンプトセクション・求人情報に明記されていない制度名を作り出す**
   - 業界一般の制度名（事例検討会・1on1・メンター制度・プリセプター制度・ラダー研修・S-QUE 等）であっても、当社情報に記載がなければ書かない
2. **業界の標準制度を「当ステーションにある」と断定する**（推測で書かない）
3. **数値（手当額・月回数・研修期間・有給消化率等）を概算で丸める**（明記値を正確に使う）
4. **施設名・事業所名・担当者名の漢字表記を間違える**
5. **候補者経歴の数値改変**（経験年数・職歴期間を「約」「およそ」で丸めない）

### 情報がない場合の対処

会社情報に候補者経歴に関連する制度・仕組みの記載が**ない**場合:
- そのトピック自体を書かない（別の切り口に変える）
- 抽象語で誤魔化さない（「仕組みが整っています」「体制があります」で逃げない）
- 明記のある別の差別化要素（資格取得支援・有給消化率・新規オープン等）に誘導する

## 出力制約

- 候補者の氏名・名前は絶対に出力に含めない。職務経歴や自己PRに名前が含まれていても無視し、「〇〇様」等の呼びかけも書かない

## セクション優先ルール
以下のルールはデフォルト。会社固有のプロンプトセクションやナレッジに別の指示がある場合はそちらを優先する。
"""


def build_system_prompt(
    *,
    level: Literal["L2", "L3"],
    company_profile: str,
    prompt_sections_text: str,
    template_body: str,
    knowledge_rules: Optional[list[str]] = None,
    tone_instruction: Optional[str] = None,
) -> str:
    """Assemble the system prompt for structured generation.

    Fields that are empty are rendered as a placeholder string so
    the prompt stays readable in logs.

    tone_instruction: optional per-candidate tone directive injected
    after the static head. Used to switch between casual/compact/
    business/letter tones based on candidate attributes. If None,
    the default (casual) baked into the static head applies.
    """
    profile_txt = (company_profile or "(会社プロフィールなし)")[:4000]
    sections_txt = (prompt_sections_text or "(セクションなし)")[:4000]
    body_txt = (template_body or "(テンプレートなし)")[:2500]

    # Level-specific hint
    if level == "L2":
        level_hint = (
            "L2 モード: opening と closing_cta のみ出力してください。\n"
            "この2ブロックだけで「あなた宛に書いた」と感じさせること。\n"
            "opening は候補者固有の導入として最も重要なブロック。\n"
            "closing_cta は opening のトーンに合わせた自然な締めくくり。"
        )
    else:
        level_hint = (
            "L3 モード: 5 ブロック全てを出力してください。\n"
            "各ブロックは固有の役割を持ち、情報の重複を避ける。\n"
            "全体として一貫した流れ（導入→接続→紹介→フレーミング→行動喚起）を作ること。"
        )

    # Template dedup hints
    dedup_hints = ""
    if "拝見し" in body_txt:
        dedup_hints = (
            "\n\n## テンプレート重複注意\n"
            "テンプレートに「拝見し」が含まれています。"
            "opening で「拝見し」を使わないでください。"
            "代わりに「注目しました」「関心を持ち」等の別表現を使ってください。"
        )

    # Knowledge rules injection
    knowledge_section = ""
    if knowledge_rules:
        rules_text = "\n".join(f"- {r}" for r in knowledge_rules)
        knowledge_section = (
            "\n\n## ナレッジ（蓄積されたルール）\n"
            + rules_text
        )

    # Tone instruction injection (per-candidate tone override)
    tone_section = ""
    if tone_instruction and tone_instruction.strip():
        tone_section = (
            "\n\n## トーン指示（この候補者向けの文体）\n"
            + tone_instruction.strip()
            + "\n\n上記のトーンに合わせて全ブロックを統一した文体で生成してください。"
        )

    return (
        _SYSTEM_PROMPT_STATIC_HEAD
        + "\n## 会社情報\n"
        + profile_txt
        + "\n\n## プロンプトセクション (会社の特色・教育体制・接点ガイド)\n"
        + sections_txt
        + "\n\n## 参考: 使用するテンプレート (募集要項ブロックは固定で後から付く)\n"
        + body_txt
        + dedup_hints
        + knowledge_section
        + tone_section
        + f"\n\n## レベル指定\n{level_hint}\n"
    )


# ---------------------------------------------------------------------------
# Info richness classification
# ---------------------------------------------------------------------------

_PLACEHOLDER_VALUES = {"未入力", "なし", "-", "ー", ""}


def _classify_info_richness(profile: CandidateProfile) -> str:
    """Classify profile information richness as rich/moderate/sparse.

    - rich: Has self_pr or work_history_summary + experience details
    - moderate: Has experience_type + some other fields
    - sparse: Mainly basic info only
    """
    has_pr = bool(
        (profile.self_pr or "").strip()
        and profile.self_pr.strip() not in _PLACEHOLDER_VALUES
    )
    has_history = bool(
        (profile.work_history_summary or "").strip()
        and profile.work_history_summary.strip() not in _PLACEHOLDER_VALUES
    )
    has_experience = bool(
        (profile.experience_type or "").strip()
        and profile.experience_type.strip() not in _PLACEHOLDER_VALUES
    )

    detail_fields = [
        profile.experience_years,
        profile.desired_job,
        profile.desired_employment_type,
        profile.desired_area,
    ]
    detail_count = sum(
        1 for f in detail_fields
        if f and f.strip() and f.strip() not in _PLACEHOLDER_VALUES
    )

    if has_pr or has_history:
        return "rich"
    if has_experience and detail_count >= 1:
        return "moderate"
    return "sparse"


def build_user_prompt(profile: CandidateProfile, job_category: str) -> str:
    """Format the candidate profile for structured generation.

    Uses labeled text format (matching L1 style) instead of raw JSON.
    Skips empty and placeholder values to save tokens.
    Adds info richness signal for the model.
    """
    richness = _classify_info_richness(profile)

    fields = [
        ("職種カテゴリ", job_category),
        ("会員番号", profile.member_id),
        ("保有資格", profile.qualifications),
        ("経験職種", profile.experience_type),
        ("経験年数", profile.experience_years),
        ("就業状況", profile.employment_status),
        ("年齢", profile.age),
        ("性別", profile.gender),
        ("居住地", profile.area),
        ("希望職種", profile.desired_job),
        ("希望勤務地", profile.desired_area),
        ("希望雇用形態", profile.desired_employment_type),
        ("希望入職時期", profile.desired_start),
        ("自己PR", profile.self_pr),
        ("職務経歴概要", profile.work_history_summary),
        ("特記事項", profile.special_conditions),
    ]

    lines: list[str] = []
    lines.append(f"情報量: {richness}")

    if richness == "sparse":
        lines.append(
            "※ 情報が少ない候補者です。就業状況と希望条件を軸に、"
            "会社の強みを前面に出してください。"
        )

    lines.append("")

    for label, value in fields:
        if value and value.strip() and value.strip() not in _PLACEHOLDER_VALUES:
            lines.append(f"{label}: {value.strip()}")

    return "\n".join(lines)
