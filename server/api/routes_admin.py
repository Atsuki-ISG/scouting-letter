"""Admin CRUD routes for Google Sheets data management."""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

from db.sheets_writer import sheets_writer
from db.sheets_client import sheets_client
from auth.api_key import verify_api_key

router = APIRouter(prefix="/admin", tags=["admin"])

# Slug to Japanese sheet name mapping
SHEET_MAP = {
    "templates": "テンプレート",
    "patterns": "パターン",
    "qualifiers": "パターン",  # QUAL rows in patterns sheet
    "prompts": "プロンプト",
    "job_offers": "求人",
    "validation": "バリデーション",
    "logs": "生成ログ",
}

# Column order for each sheet (must match header row)
COLUMNS = {
    "templates": ["company", "job_category", "type", "body"],
    "patterns": ["company", "job_category", "pattern_type", "employment_variant", "template_text", "feature_variations", "display_name", "target_description", "match_rules", "qualification_combo", "replacement_text"],
    "qualifiers": ["company", "job_category", "pattern_type", "employment_variant", "template_text", "feature_variations", "display_name", "target_description", "match_rules", "qualification_combo", "replacement_text"],
    "prompts": ["company", "section_type", "job_category", "order", "content"],
    "job_offers": ["company", "job_category", "id", "name", "label", "employment_type", "active"],
    "validation": ["company", "age_min", "age_max", "qualification_rules"],
    "logs": ["timestamp", "company", "member_id", "job_category", "template_type", "generation_path", "pattern_type", "status", "detail", "personalized_text_preview"],
}


@router.get("/prompt_preview")
async def prompt_preview(company: str, operator=Depends(verify_api_key)):
    """Preview how the system prompt is assembled for a company."""
    from pipeline.prompt_builder import build_system_prompt, build_user_prompt
    from models.profile import CandidateProfile

    config = sheets_client.get_company_config(company)

    # Use a sample template (パート_初回) - try first available
    template_data = None
    for key in config["templates"]:
        if key.endswith("パート_初回") or key == "パート_初回":
            template_data = config["templates"][key]
            break
    template_data = template_data or {}
    template_body = template_data.get("body", "(テンプレート未設定)")

    system_prompt = build_system_prompt(
        config["prompt_sections"],
        template_body,
        config.get("examples"),
    )

    # Build a dummy user prompt to show format
    dummy = CandidateProfile(
        member_id="SAMPLE",
        qualifications="看護師",
        experience_type="病棟看護",
        experience_years="5年",
        employment_status="就業中",
        age="35歳",
        self_pr="患者様一人ひとりに寄り添った看護を心がけてきました。",
        work_history_summary="急性期病棟3年、回復期病棟2年",
    )
    user_prompt = build_user_prompt(dummy, "nurse")

    # Build section breakdown
    sections = []
    for sec in config.get("prompt_sections", []):
        content = sec.get("content", "")
        if content and content.strip():
            sections.append({
                "section_type": sec.get("section_type", ""),
                "content": content.strip()[:200],
            })

    return {
        "system_prompt": system_prompt,
        "user_prompt_example": user_prompt,
        "sections": sections,
        "template_used": "パート_初回",
        "flow": [
            "1. プロフィール受信",
            "2. 職種カテゴリ判定（資格から自動）",
            "3. テンプレート種別判定（パート/正社員 × 初回/再送）",
            "4. バリデーション（年齢・資格・AI条件）",
            "5a. 経歴あり → AI生成（system prompt + user prompt）",
            "5b. 経歴なし → 型はめ（パターンマッチング）",
            "6. テンプレートにパーソナライズ文を挿入",
            "7. 求人ID解決 → 完成",
        ],
    }


@router.get("/{sheet_slug}")
async def list_rows(sheet_slug: str, company: Optional[str] = None, operator=Depends(verify_api_key)):
    sheet_name = SHEET_MAP.get(sheet_slug)
    if not sheet_name:
        raise HTTPException(404, f"Unknown sheet: {sheet_slug}")

    try:
        rows = sheets_writer.get_all_rows(sheet_name)
    except Exception:
        rows = []
    if not rows:
        return {"headers": COLUMNS.get(sheet_slug, []), "rows": []}

    headers = rows[0]
    # Determine pattern_type column index for QUAL filtering
    pt_col_idx = None
    for j, h in enumerate(headers):
        if h.strip() == "pattern_type":
            pt_col_idx = j
            break

    data_rows = []
    for i, row in enumerate(rows[1:], start=2):  # row 2 = first data row in sheet
        item = {}
        for j, h in enumerate(headers):
            item[h.strip()] = row[j].strip() if j < len(row) else ""
        item_company = item.get("company", "")
        if company and item_company and item_company != company:
            continue
        # Filter by pattern_type for qualifiers vs patterns
        pt_value = item.get("pattern_type", "")
        if sheet_slug == "qualifiers" and pt_value != "QUAL":
            continue
        if sheet_slug == "patterns" and pt_value == "QUAL":
            continue
        item["_row_index"] = i  # actual sheet row number
        data_rows.append(item)

    # Logs: newest first, limit to 200 rows
    if sheet_slug == "logs":
        data_rows = list(reversed(data_rows))[:200]

    return {"headers": [h.strip() for h in headers], "rows": data_rows}


@router.post("/init_company")
async def init_company(data: dict, operator=Depends(verify_api_key)):
    """Create empty scaffold rows for a new company."""
    company_id = data.get("company_id", "").strip()
    if not company_id:
        raise HTTPException(400, "company_id is required")

    # Check if company already exists
    existing = sheets_client.get_company_list()
    if company_id in existing:
        raise HTTPException(409, f"Company '{company_id}' already exists")

    total = 0

    # Templates: 4 empty rows (パート初回/再送, 正社員初回/再送)
    template_types = ["パート_初回", "パート_再送", "正社員_初回", "正社員_再送"]
    for tt in template_types:
        # columns: company, job_category, type, body
        sheets_writer.append_row("テンプレート", [company_id, "nurse", tt, ""])
        total += 1

    # Patterns: 型A〜G with default matching rules
    import json
    default_patterns = [
        ("A", "", "豊富な経験への期待", "経験10年+ / 40代〜×経験6年+",
         json.dumps([{"exp_min":10,"age_group":"40s+"},{"exp_min":6,"age_group":"late_30s"}])),
        ("B1", "", "確かな経験×特色", "経験6〜9年",
         json.dumps([{"exp_min":10,"age_group":"young"},{"exp_min":6,"exp_max":9}])),
        ("B2", "", "経験×特色", "経験3〜5年",
         json.dumps([{"exp_min":3,"exp_max":5}])),
        ("C", "", "経験とのフィット", "40代〜 × 経験1〜2年",
         json.dumps([{"exp_min":1,"exp_max":2,"age_group":"40s+"},{"exp_min":1,"exp_max":2,"age_group":"late_30s"}])),
        ("D", "就業中", "経験ある前提で評価", "40代〜 × 経験未入力",
         json.dumps([{"exp_max":0,"age_group":"40s+"},{"exp_max":0,"age_group":"late_30s"},{"exp_min":None,"age_group":"40s+"},{"exp_min":None,"age_group":"late_30s"}])),
        ("D", "離職中", "経験ある前提で評価", "40代〜 × 経験未入力",
         json.dumps([{"exp_max":0,"age_group":"40s+"},{"exp_max":0,"age_group":"late_30s"},{"exp_min":None,"age_group":"40s+"},{"exp_min":None,"age_group":"late_30s"}])),
        ("E", "", "ポテンシャル+教育体制", "20〜30代 × 経験1〜2年",
         json.dumps([{"exp_min":1,"exp_max":2,"age_group":"young"}])),
        ("F", "就業中", "教育体制+成長環境", "20〜30代 × 経験未入力",
         json.dumps([{"exp_max":0,"age_group":"young"},{"exp_min":None,"age_group":"young"}])),
        ("F", "離職中", "教育体制+成長環境", "20〜30代 × 経験未入力",
         json.dumps([{"exp_max":0,"age_group":"young"},{"exp_min":None,"age_group":"young"}])),
        ("G", "", "教育体制メイン", "在学中",
         json.dumps([{"employment":"在学中"}])),
    ]
    for pt, emp_var, disp_name, target_desc, rules in default_patterns:
        # columns: company, job_category, pattern_type, employment_variant, template_text, feature_variations, display_name, target_description, match_rules
        sheets_writer.append_row("パターン", [company_id, "nurse", pt, emp_var, "", "", disp_name, target_desc, rules])
        total += 1

    # Validation: 1 empty row
    # columns: company, age_min, age_max, qualification_rules
    sheets_writer.append_row("バリデーション", [company_id, "", "", ""])
    total += 1

    sheets_client.reload()
    return {"status": "created", "company_id": company_id, "total_rows": total}


@router.post("/generate_company")
async def generate_company(data: dict, operator=Depends(verify_api_key)):
    """Generate company config from free-text company info using AI.

    Creates empty template scaffolds, then AI-generates patterns, prompts,
    validation, and qualification modifiers, writing them to Google Sheets.
    """
    import json as _json
    from pipeline.ai_generator import generate_personalized_text

    company_id = data.get("company_id", "").strip()
    company_info = data.get("company_info", "").strip()
    template_text = data.get("template_text", "").strip()
    generate_templates = data.get("generate_templates", not template_text)
    if not company_id:
        raise HTTPException(400, "company_id is required")
    if not company_info:
        raise HTTPException(400, "company_info is required")

    # Check if company already exists
    existing = sheets_client.get_company_list()
    if company_id in existing:
        raise HTTPException(409, f"Company '{company_id}' already exists")

    # --- Build the mega-prompt ---
    # Load ARK as reference example
    ref_config = {}
    try:
        ref_config = sheets_client.get_company_config("ark-visiting-nurse")
    except Exception:
        pass  # OK if reference company doesn't exist

    # Build reference pattern example
    ref_pattern_examples = ""
    ref_patterns = ref_config.get("patterns", [])
    if ref_patterns:
        for p in ref_patterns[:2]:  # Show 2 examples
            ref_pattern_examples += f"- 型{p.get('pattern_type','')}: {p.get('template_text','')[:100]}... 特色: {', '.join(p.get('feature_variations',[])[:2])}\n"

    # Build reference prompt sections example
    ref_prompt_example = ""
    ref_prompts = ref_config.get("prompt_sections", [])
    for sec in ref_prompts[:2]:
        content = sec.get("content", "")
        if content and sec.get("section_type") != "pattern_generation":
            ref_prompt_example += f"- section_type: {sec.get('section_type','')}, content冒頭: {content[:150]}...\n"

    # Build reference template example if generating templates
    ref_template_section = ""
    template_output_schema = ""
    if generate_templates:
        ref_templates = ref_config.get("templates", {})
        for key, t in ref_templates.items():
            ttype = t.get("type", "")
            if ttype in ("パート_初回", "正社員_初回"):
                body = t.get("body", "")
                if body:
                    ref_template_section += f"\n### {ttype} の例（冒頭500文字）:\n{body[:500]}...\n"
                    break

        template_instructions = f"""### 0. テンプレート（4種類）
スカウトメールの本文テンプレート。以下の4種を生成:
- パート_初回: パートタイム向け初回スカウト
- パート_再送: パートタイム向け再送スカウト（2回目以降）
- 正社員_初回: 正社員向け初回スカウト
- 正社員_再送: 正社員向け再送スカウト

各テンプレートのルール:
- 冒頭: 「はじめまして。突然のご連絡大変失礼いたします、[会社名]の[担当者名]と申します。」
- 2段落目: 「この度は、ご経歴を拝見し、[会社名]の『[求人名]』のキャリアをご検討いただきたく、ご連絡いたしました。」
- **必ず `{{ここに生成した文章を挿入}}` プレースホルダーを1箇所含める**（AIが候補者ごとのパーソナライズ文を挿入する位置）
- プレースホルダーの前後に、会社の特色や共通メッセージを配置
- 末尾は応募を促す文言で締める
- ですます調、自然な日本語
- 再送テンプレートは「以前ご連絡させていただきました」等の表現を含め、少し表現を変える
- 正社員テンプレートは給与・待遇情報を含める
- 全体で300〜500文字程度
{ref_template_section}

"""
        template_output_schema = """  "templates": [
    {{"type": "パート_初回", "job_category": "nurse", "body": "テンプレート本文..."}},
    {{"type": "パート_再送", "job_category": "nurse", "body": "テンプレート本文..."}},
    {{"type": "正社員_初回", "job_category": "nurse", "body": "テンプレート本文..."}},
    {{"type": "正社員_再送", "job_category": "nurse", "body": "テンプレート本文..."}}
  ],
"""
    else:
        template_instructions = ""
        template_output_schema = ""

    system_prompt = f"""あなたは訪問看護・介護系のスカウト文生成システムの設定エキスパートです。
会社情報のフリーテキストから、スカウト文生成に必要な設定を一括生成してください。

## 生成する設定
{template_instructions}
### 1. パターン（10種類）
経歴が少ない候補者に使う型はめパターン。候補者の経験年数・年齢帯に応じて使い分ける。

| 型 | 対象 | 特徴 |
|----|------|------|
| A | 経験10年+のベテラン | 豊富な経験への期待・敬意を表現 |
| B1 | 経験6〜9年の中堅 | 確かな経験×会社の特色 |
| B2 | 経験3〜5年 | 経験×会社の特色 |
| C | 40代〜×経験1〜2年 | 経験とのフィット |
| D | 40代〜×経験未入力（就業中/離職中の2バリエーション） | 経験ある前提で評価 |
| E | 20〜30代×経験1〜2年 | ポテンシャル+教育体制 |
| F | 20〜30代×経験未入力（就業中/離職中の2バリエーション） | 教育体制+成長環境 |
| G | 在学中 | 教育体制メイン |

パターンのルール:
- template_text: 2〜3文、句点で終わる。ですます調
- `{{特色}}` プレースホルダーを1箇所含める（特色バリエーションが挿入される）
- 型A・B1・B2: `{{N}}` プレースホルダー可（経験年数が入る）
- 上から目線にならない
- feature_variations: 3つ、各バリエーションは会社の特色を短く表現（連体修飾形「〜する」「〜な」で終わる）
{ref_pattern_examples}

### 2. プロンプト（3〜5セクション）
AI生成時のシステムプロンプトの構成パーツ。section_type と content を設定。
- section_type例: "instruction"（生成指示）, "company_info"（会社特色）, "tone"（トーン指示）
- 各セクションは200〜500文字程度
- orderで表示順を制御（1, 2, 3...）
- job_category は空欄（全職種共通）
{ref_prompt_example}

### 3. バリデーション（1件）
スカウト対象のフィルタリング条件。JSON形式。
- age_min, age_max: 年齢範囲（空欄なら制限なし）
- qualification_rules: JSON。必須資格、除外条件等

### 4. 資格修飾（5〜10件）
複数資格保持者への修飾テキスト。
- qualification_combo: 資格の組み合わせ（カンマ区切り）
- replacement_text: 「看護師・介護福祉士の両方の資格をお持ちとのこと、」のような修飾文

## 出力形式
以下のJSON1つで返してください。他のテキストは不要です。
```json
{{
{template_output_schema}  "patterns": [
    {{"pattern_type": "A", "employment_variant": "", "template_text": "...", "feature_variations": ["...", "...", "..."]}},
    ... (10件: A, B1, B2, C, D就業中, D離職中, E, F就業中, F離職中, G)
  ],
  "prompts": [
    {{"section_type": "instruction", "job_category": "", "order": 1, "content": "..."}},
    {{"section_type": "company_info", "job_category": "", "order": 2, "content": "..."}},
    ...
  ],
  "validation": {{
    "age_min": "",
    "age_max": "",
    "qualification_rules": "{{...JSON文字列...}}"
  }},
  "qualifiers": [
    {{"qualification_combo": "看護師,介護福祉士", "replacement_text": "..."}},
    ...
  ]
}}
```"""

    try:
        result_text = await generate_personalized_text(
            system_prompt=system_prompt,
            user_prompt=f"以下の会社情報から、スカウト文生成の全設定を生成してください。\n\n{company_info}",
            model_name=None,
            max_output_tokens=8192,
            temperature=0.5,
        )

        # Extract JSON from response
        import re
        json_match = re.search(r'\{[\s\S]*\}', result_text)
        if not json_match:
            raise ValueError("AI応答からJSONを抽出できませんでした")

        generated = _json.loads(json_match.group(0))

        # --- Write to Sheets ---
        total = 0

        # 1. Templates
        template_types = ["パート_初回", "パート_再送", "正社員_初回", "正社員_再送"]
        if template_text:
            # User provided a template base — use it for all 4 types
            body_escaped = template_text.replace("\n", "\\n")
            for tt in template_types:
                sheets_writer.append_row("テンプレート", [company_id, "nurse", tt, body_escaped])
                total += 1
            generated["templates"] = [{"type": tt, "body": template_text} for tt in template_types]
        elif generate_templates and generated.get("templates"):
            # AI-generated templates
            for t in generated["templates"]:
                body = t.get("body", "").replace("\n", "\\n")
                sheets_writer.append_row("テンプレート", [
                    company_id,
                    t.get("job_category", "nurse"),
                    t.get("type", ""),
                    body,
                ])
                total += 1
        else:
            # Empty scaffolds (user fills in manually)
            for tt in template_types:
                sheets_writer.append_row("テンプレート", [company_id, "nurse", tt, ""])
                total += 1

        # 2. Patterns (with default match_rules)
        default_match_rules = {
            "A": _json.dumps([{"exp_min":10,"age_group":"40s+"},{"exp_min":6,"age_group":"late_30s"}]),
            "B1": _json.dumps([{"exp_min":10,"age_group":"young"},{"exp_min":6,"exp_max":9}]),
            "B2": _json.dumps([{"exp_min":3,"exp_max":5}]),
            "C": _json.dumps([{"exp_min":1,"exp_max":2,"age_group":"40s+"},{"exp_min":1,"exp_max":2,"age_group":"late_30s"}]),
            "D_就業中": _json.dumps([{"exp_max":0,"age_group":"40s+"},{"exp_max":0,"age_group":"late_30s"},{"exp_min":None,"age_group":"40s+"},{"exp_min":None,"age_group":"late_30s"}]),
            "D_離職中": _json.dumps([{"exp_max":0,"age_group":"40s+"},{"exp_max":0,"age_group":"late_30s"},{"exp_min":None,"age_group":"40s+"},{"exp_min":None,"age_group":"late_30s"}]),
            "E": _json.dumps([{"exp_min":1,"exp_max":2,"age_group":"young"}]),
            "F_就業中": _json.dumps([{"exp_max":0,"age_group":"young"},{"exp_min":None,"age_group":"young"}]),
            "F_離職中": _json.dumps([{"exp_max":0,"age_group":"young"},{"exp_min":None,"age_group":"young"}]),
            "G": _json.dumps([{"employment":"在学中"}]),
        }
        display_names = {
            "A": "豊富な経験への期待", "B1": "確かな経験×特色", "B2": "経験×特色",
            "C": "経験とのフィット", "D": "経験ある前提で評価", "E": "ポテンシャル+教育体制",
            "F": "教育体制+成長環境", "G": "教育体制メイン",
        }
        target_descs = {
            "A": "経験10年+ / 40代〜×経験6年+", "B1": "経験6〜9年", "B2": "経験3〜5年",
            "C": "40代〜 × 経験1〜2年", "D": "40代〜 × 経験未入力",
            "E": "20〜30代 × 経験1〜2年", "F": "20〜30代 × 経験未入力", "G": "在学中",
        }

        patterns = generated.get("patterns", [])
        for p in patterns:
            pt = p.get("pattern_type", "")
            emp_var = p.get("employment_variant", "")
            features = "|".join(p.get("feature_variations", []))
            rules_key = f"{pt}_{emp_var}" if emp_var else pt
            rules = default_match_rules.get(rules_key, "[]")
            sheets_writer.append_row("パターン", [
                company_id,
                "nurse",
                pt,
                emp_var,
                p.get("template_text", ""),
                features,
                display_names.get(pt, ""),
                target_descs.get(pt, ""),
                rules,
            ])
            total += 1

        # 3. Prompts
        prompts = generated.get("prompts", [])
        for sec in prompts:
            content = sec.get("content", "").replace("\n", "\\n")
            sheets_writer.append_row("プロンプト", [
                company_id,
                sec.get("section_type", ""),
                sec.get("job_category", ""),
                str(sec.get("order", 1)),
                content,
            ])
            total += 1

        # 4. Validation
        validation = generated.get("validation", {})
        qual_rules = validation.get("qualification_rules", "")
        if isinstance(qual_rules, dict):
            qual_rules = _json.dumps(qual_rules, ensure_ascii=False)
        sheets_writer.append_row("バリデーション", [
            company_id,
            str(validation.get("age_min", "")),
            str(validation.get("age_max", "")),
            qual_rules,
        ])
        total += 1

        # 5. Qualification modifiers (as QUAL rows in patterns sheet)
        qualifiers = generated.get("qualifiers", [])
        for q in qualifiers:
            # columns: company, job_category, pattern_type, employment_variant, template_text,
            #          feature_variations, display_name, target_description, match_rules,
            #          qualification_combo, replacement_text
            sheets_writer.append_row("パターン", [
                company_id, "nurse", "QUAL", "", "", "", "", "", "",
                q.get("qualification_combo", ""),
                q.get("replacement_text", ""),
            ])
            total += 1

        sheets_client.reload()

        # Add template info to response for UI preview
        if not generated.get("templates"):
            generated["templates"] = [{"type": tt, "body": "（手動入力）"} for tt in template_types]

        return {
            "status": "created",
            "company_id": company_id,
            "generated": generated,
            "total_rows": total,
        }

    except _json.JSONDecodeError as e:
        raise HTTPException(500, f"AI応答のJSON解析エラー: {str(e)}")
    except Exception as e:
        raise HTTPException(500, f"会社設定生成エラー: {str(e)}")


@router.post("/generate_patterns")
async def generate_patterns(data: dict, operator=Depends(verify_api_key)):
    """Generate pattern texts for all types using AI based on company info."""
    import json as _json
    from pipeline.ai_generator import generate_personalized_text

    company_id = data.get("company_id", "").strip()
    company_info = data.get("company_info", "").strip()
    if not company_info:
        raise HTTPException(400, "company_info is required")

    # Load company-specific prompt sections for pattern generation
    prompt_sections = sheets_client.get_company_config(company_id).get("prompt_sections", []) if company_id else []
    custom_prompt = ""
    for sec in prompt_sections:
        if sec.get("section_type") == "pattern_generation":
            custom_prompt += sec.get("content", "") + "\n"

    # Build system prompt
    system_prompt = custom_prompt if custom_prompt.strip() else """あなたは訪問看護・介護系のスカウト文ライターです。
以下の会社情報をもとに、8つのパターン型のスカウト文（template_text）と特色バリエーション（feature_variations）を生成してください。

## 型の構造
各型は「経歴が少ない候補者」に使う型はめパターンです。候補者の経験年数・年齢帯に応じて使い分けます。

| 型 | 対象 | 特徴 |
|----|------|------|
| A | 経験10年+のベテラン | 豊富な経験への期待・敬意を表現 |
| B1 | 経験6〜9年の中堅 | 確かな経験×会社の特色 |
| B2 | 経験3〜5年 | 経験×会社の特色 |
| C | 40代〜×経験1〜2年 | 経験とのフィット |
| D | 40代〜×経験未入力 | 経験ある前提で評価（就業中/離職中の2バリエーション） |
| E | 20〜30代×経験1〜2年 | ポテンシャル+教育体制 |
| F | 20〜30代×経験未入力 | 教育体制+成長環境（就業中/離職中の2バリエーション） |
| G | 在学中 | 教育体制メイン |

## ルール
- template_text: 2〜3文、句点で終わる。ですます調
- {特色} プレースホルダーを1箇所含める（特色バリエーションが挿入される位置）
- 型A・B1・B2: {N} プレースホルダー可（経験年数が入る）
- 型D・F: 就業中/離職中の2バリエーションを生成
- 型E・F・G: 教育体制を具体的に記載（会社情報から取得）
- 上から目線にならない（「フォローします」「安心してください」等は不可）
- feature_variations: 3つ、各バリエーションは会社の特色を短く表現（「〜する」「〜な」で終わる連体修飾形）

## 出力形式
以下のJSON配列で返してください。他のテキストは不要です。
```json
[
  {"pattern_type": "A", "employment_variant": "", "template_text": "...", "feature_variations": ["...", "...", "..."]},
  {"pattern_type": "B1", "employment_variant": "", "template_text": "...", "feature_variations": ["...", "...", "..."]},
  {"pattern_type": "B2", "employment_variant": "", "template_text": "...", "feature_variations": ["...", "...", "..."]},
  {"pattern_type": "C", "employment_variant": "", "template_text": "...", "feature_variations": ["...", "...", "..."]},
  {"pattern_type": "D", "employment_variant": "就業中", "template_text": "...", "feature_variations": ["...", "...", "..."]},
  {"pattern_type": "D", "employment_variant": "離職中", "template_text": "...", "feature_variations": ["...", "...", "..."]},
  {"pattern_type": "E", "employment_variant": "", "template_text": "...", "feature_variations": ["...", "...", "..."]},
  {"pattern_type": "F", "employment_variant": "就業中", "template_text": "...", "feature_variations": ["...", "...", "..."]},
  {"pattern_type": "F", "employment_variant": "離職中", "template_text": "...", "feature_variations": ["...", "...", "..."]},
  {"pattern_type": "G", "employment_variant": "", "template_text": "...", "feature_variations": ["...", "...", "..."]}
]
```"""

    try:
        result_text = await generate_personalized_text(
            system_prompt=system_prompt,
            user_prompt=f"以下の会社情報をもとに、10パターンのスカウト文を生成してください。\n\n{company_info}",
            model_name=None,
        )

        # Extract JSON from response (may be wrapped in markdown code blocks)
        import re
        json_match = re.search(r'\[[\s\S]*\]', result_text)
        if not json_match:
            raise ValueError("AI応答からJSONを抽出できませんでした")

        patterns = _json.loads(json_match.group(0))
        return {"patterns": patterns}
    except Exception as e:
        raise HTTPException(500, f"AI生成エラー: {str(e)}")


@router.post("/{sheet_slug}")
async def create_row(sheet_slug: str, data: dict, operator=Depends(verify_api_key)):
    sheet_name = SHEET_MAP.get(sheet_slug)
    if not sheet_name:
        raise HTTPException(404, f"Unknown sheet: {sheet_slug}")

    # For qualifiers, force pattern_type=QUAL
    if sheet_slug == "qualifiers":
        data["pattern_type"] = "QUAL"

    columns = COLUMNS.get(sheet_slug, [])
    values = [data.get(col, "") for col in columns]
    sheets_writer.append_row(sheet_name, values)
    sheets_client.reload()
    return {"status": "created"}


@router.put("/{sheet_slug}/{row_index}")
async def update_row(sheet_slug: str, row_index: int, data: dict, operator=Depends(verify_api_key)):
    sheet_name = SHEET_MAP.get(sheet_slug)
    if not sheet_name:
        raise HTTPException(404, f"Unknown sheet: {sheet_slug}")

    columns = COLUMNS.get(sheet_slug, [])
    values = [data.get(col, "") for col in columns]
    sheets_writer.update_row(sheet_name, row_index, values)
    sheets_client.reload()
    return {"status": "updated"}


@router.delete("/{sheet_slug}/{row_index}")
async def delete_row(sheet_slug: str, row_index: int, operator=Depends(verify_api_key)):
    sheet_name = SHEET_MAP.get(sheet_slug)
    if not sheet_name:
        raise HTTPException(404, f"Unknown sheet: {sheet_slug}")

    sheets_writer.delete_row(sheet_name, row_index)
    sheets_client.reload()
    return {"status": "deleted"}
