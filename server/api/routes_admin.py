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
    "qualifiers": "資格修飾",
    "prompts": "プロンプト",
    "job_offers": "求人",
    "validation": "バリデーション",
}

# Column order for each sheet (must match header row)
COLUMNS = {
    "templates": ["company", "job_category", "type", "body"],
    "patterns": ["company", "job_category", "pattern_type", "employment_variant", "template_text", "feature_variations", "display_name", "target_description", "match_rules"],
    "qualifiers": ["company", "qualification_combo", "replacement_text"],
    "prompts": ["company", "section_type", "job_category", "order", "content"],
    "job_offers": ["company", "job_category", "id", "name", "label", "employment_type", "active"],
    "validation": ["company", "age_min", "age_max", "qualification_rules"],
}


@router.get("/prompt_preview")
async def prompt_preview(company: str, operator=Depends(verify_api_key)):
    """Preview how the system prompt is assembled for a company."""
    from pipeline.prompt_builder import build_system_prompt, build_user_prompt
    from models.profile import CandidateProfile

    config = sheets_client.get_company_config(company)

    # Use a sample template (パート_初回)
    template_data = config["templates"].get("パート_初回") or {}
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
    data_rows = []
    for i, row in enumerate(rows[1:], start=2):  # row 2 = first data row in sheet
        item = {}
        for j, h in enumerate(headers):
            item[h.strip()] = row[j].strip() if j < len(row) else ""
        if company and item.get("company") != company:
            continue
        item["_row_index"] = i  # actual sheet row number
        data_rows.append(item)

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
