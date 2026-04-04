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
    "profiles": "プロフィール",
}

# Column order for each sheet (must match header row)
COLUMNS = {
    "templates": ["company", "job_category", "type", "body", "version"],
    "patterns": ["company", "job_category", "pattern_type", "employment_variant", "template_text", "feature_variations", "display_name", "target_description", "match_rules", "qualification_combo", "replacement_text"],
    "qualifiers": ["company", "job_category", "pattern_type", "employment_variant", "template_text", "feature_variations", "display_name", "target_description", "match_rules", "qualification_combo", "replacement_text"],
    "prompts": ["company", "section_type", "job_category", "order", "content"],
    "job_offers": ["company", "job_category", "id", "name", "label", "employment_type", "active"],
    "validation": ["company", "age_min", "age_max", "qualification_rules", "category_exclusions", "category_config"],
    "logs": ["timestamp", "company", "member_id", "job_category", "template_type", "generation_path", "pattern_type", "status", "detail", "personalized_text_preview"],
    "profiles": ["company", "content", "detection_keywords"],
}


DASHBOARD_SPREADSHEET_ID = "1a3XE212nZgsQP-93phk22VlSSZ5aD1ig72M4A6p2awE"


@router.get("/server_info")
async def server_info(operator=Depends(verify_api_key)):
    """Return server metadata for admin help page."""
    from config import SPREADSHEET_ID
    result = {}
    if SPREADSHEET_ID:
        result["spreadsheet_url"] = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"
    result["dashboard_url"] = f"https://docs.google.com/spreadsheets/d/{DASHBOARD_SPREADSHEET_ID}/edit"
    return result


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


@router.get("/validate")
async def validate_config(
    company: Optional[str] = None,
    operator=Depends(verify_api_key),
):
    """Validate company config for prompt contamination and missing sections."""
    from pipeline.prompt_validator import (
        validate_all_companies,
        validate_company_sections,
        validate_prompt_content,
    )

    if company:
        config = sheets_client.get_company_config(company)
        sections = config.get("prompt_sections", [])
        errors = validate_company_sections(company, sections)
        all_content = "\n".join(s.get("content", "") for s in sections)
        errors.extend(validate_prompt_content(company, all_content))
        return {"company": company, "errors": errors, "ok": len(errors) == 0}

    issues = validate_all_companies(sheets_client)
    companies = sheets_client.get_company_list()
    results = {}
    for c in companies:
        errors = issues.get(c, [])
        results[c] = {"errors": errors, "ok": len(errors) == 0}
    all_ok = all(r["ok"] for r in results.values())
    return {"results": results, "all_ok": all_ok}


# --- Send summary endpoint ---

@router.get("/send_summary")
async def send_summary(
    company: Optional[str] = None,
    operator: dict = Depends(verify_api_key),
):
    """今月の送信数サマリー（職種カテゴリ別）を返す。"""
    from datetime import datetime, timedelta, timezone
    from pipeline.orchestrator import _send_data_sheet_name, COMPANY_DISPLAY_NAMES
    from pipeline.job_category_resolver import resolve_job_category

    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    current_month = now.strftime("%Y-%m")

    # カテゴリ表示名
    CATEGORY_DISPLAY = {
        "nurse": "看護師",
        "rehab_pt": "PT",
        "rehab_st": "ST",
        "rehab_ot": "OT",
        "medical_office": "医療事務",
        "care": "介護",
        "counselor": "相談員",
    }

    companies_to_scan = [company] if company else list(COMPANY_DISPLAY_NAMES.keys())
    total = 0
    by_category: dict[str, int] = {}

    for cid in companies_to_scan:
        sheet_name = _send_data_sheet_name(cid)
        try:
            all_rows = sheets_writer.get_all_rows(sheet_name)
        except Exception:
            continue
        if len(all_rows) < 2:
            continue

        headers = all_rows[0]
        col_map = {h.strip(): i for i, h in enumerate(headers)}
        date_idx = col_map.get("日時", 0)
        cat_idx = col_map.get("職種カテゴリ")
        qual_idx = col_map.get("資格")

        for row in all_rows[1:]:
            if len(row) <= date_idx:
                continue
            row_date = row[date_idx][:7]  # YYYY-MM
            if row_date != current_month:
                continue
            total += 1

            # 職種カテゴリ取得（列があれば使う、なければ資格から推定）
            cat = ""
            if cat_idx is not None and cat_idx < len(row):
                cat = row[cat_idx].strip()
            if not cat and qual_idx is not None and qual_idx < len(row):
                cat = resolve_job_category(row[qual_idx]) or ""

            display = CATEGORY_DISPLAY.get(cat, cat) or "不明"
            by_category[display] = by_category.get(display, 0) + 1

    # 件数降順でソート
    by_category_sorted = dict(sorted(by_category.items(), key=lambda x: -x[1]))

    return {
        "month": current_month,
        "month_display": f"{now.month}月",
        "total": total,
        "by_category": by_category_sorted,
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

    # Profile: 1 empty row
    # columns: company, content
    sheets_writer.append_row("プロフィール", [company_id, ""])
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
    # Load ALL existing companies as reference examples
    import json as _json_ref
    ref_configs = {}
    try:
        all_companies = sheets_client.get_company_list()
        for cid in all_companies:
            if cid == company_id:
                continue  # Skip the company being created
            try:
                ref_configs[cid] = sheets_client.get_company_config(cid)
            except Exception:
                pass
    except Exception:
        pass

    # Build reference pattern examples from multiple companies
    ref_pattern_examples = ""
    target_types_per_company = {"A": "ベテラン向け", "E": "若手向け", "G": "在学中向け"}
    for cid, cfg in ref_configs.items():
        patterns = cfg.get("patterns", [])
        if not patterns:
            continue
        ref_pattern_examples += f"\n【{cid}】\n"
        for p in patterns:
            pt = p.get("pattern_type", "")
            if pt in target_types_per_company:
                emp = p.get("employment_variant", "")
                label = f"型{pt}" + (f"_{emp}" if emp else "")
                features = p.get("feature_variations", [])
                ref_pattern_examples += f"- {label}: template_text=\"{p.get('template_text','')}\", feature_variations={features}\n"
        if len(ref_configs) > 2:
            break  # Show max 2 companies to avoid prompt bloat

    # Build reference prompt sections from multiple companies (company-specific only)
    ref_prompt_example = ""
    company_specific_types = {"station_features", "education", "ai_guide"}
    for cid, cfg in ref_configs.items():
        prompts = cfg.get("prompt_sections", [])
        relevant = [s for s in prompts if s.get("content") and s.get("section_type") in company_specific_types]
        if not relevant:
            continue
        ref_prompt_example += f"\n【{cid}】\n"
        for sec in relevant:
            ref_prompt_example += f"- section_type: \"{sec.get('section_type','')}\", job_category: \"{sec.get('job_category','')}\", order: {sec.get('order','')}, content: \"{sec.get('content','')}\"\n"
        if len(ref_configs) > 2:
            break

    # Build reference validation example (pick first company that has it)
    ref_validation_example = ""
    for cid, cfg in ref_configs.items():
        val = cfg.get("validation_config", {})
        if val:
            age_range = val.get("age_range", {})
            qual_rules = val.get("qualification_rules", {})
            ref_validation_example = f"\n参考例（{cid}）:\n- age_min: {age_range.get('min','')}, age_max: {age_range.get('max','')}\n- qualification_rules: {_json_ref.dumps(qual_rules, ensure_ascii=False)}\n"
            break

    # Build reference qualifier examples from multiple companies
    ref_qualifier_example = ""
    for cid, cfg in ref_configs.items():
        qualifiers = cfg.get("qualification_modifiers", [])
        if not qualifiers:
            continue
        ref_qualifier_example += f"\n【{cid}】\n"
        for q in qualifiers[:3]:
            combo = q.get("qualification_combo", [])
            combo_str = ",".join(combo) if isinstance(combo, list) else combo
            ref_qualifier_example += f"- combo: \"{combo_str}\", text: \"{q.get('replacement_text','')}\"\n"
        if len(ref_configs) > 2:
            break

    # Build reference template examples if generating templates
    ref_template_section = ""
    template_output_schema = ""
    if generate_templates:
        # Show 初回 and 再送 from first company that has both
        for cid, cfg in ref_configs.items():
            templates = cfg.get("templates", {})
            found_initial = found_resend = ""
            for key, t in templates.items():
                ttype = t.get("type", "")
                body = t.get("body", "")
                if not body:
                    continue
                if "初回" in ttype and not found_initial:
                    found_initial = f"\n#### {ttype} の例（{cid}、冒頭300文字）:\n{body[:300]}...\n"
                elif "再送" in ttype and not found_resend:
                    found_resend = f"\n#### {ttype} の例（{cid}、冒頭300文字）:\n{body[:300]}...\n"
            if found_initial and found_resend:
                ref_template_section = found_initial + found_resend
                break

        template_instructions = f"""### 0. テンプレート（4種類）
スカウトメールの本文テンプレート。以下の4種を生成:
- パート_初回: パートタイム向け初回スカウト
- パート_再送: パートタイム向け再送スカウト（2回目以降）
- 正社員_初回: 正社員向け初回スカウト
- 正社員_再送: 正社員向け再送スカウト

各テンプレートのルール:
- **必ず `{{ここに生成した文章を挿入}}` プレースホルダーを1箇所含める**（AIが候補者ごとのパーソナライズ文を挿入する位置）
- プレースホルダーの前後に、会社の特色や共通メッセージを配置
- 末尾は応募を促す文言で締める
- ですます調、自然な日本語
- 正社員テンプレートは給与・待遇情報を含める
- 全体で300〜500文字程度

初回 vs 再送の違い:
- **初回**: 冒頭「はじめまして。突然のご連絡大変失礼いたします、[会社名]の[担当者名]と申します。」
- **再送**: 冒頭を「度々のご連絡大変申し訳ございません。諦めきれず、ご連絡させていただきます、[会社名]の[担当者名]と申します。」のように、再度連絡している旨に変える。「はじめまして」は使わない
- 本文の構成は同じでよいが、冒頭の挨拶文は必ず変えること
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
- 上から目線にならない（「フォローします」「安心してスタートいただけます」等は厳禁）
- feature_variations: 3つ、各バリエーションは会社の特色を短く表現（連体修飾形「〜する」「〜な」で終わる）
- 型E・F・G: **その会社固有の**教育体制を具体的に記載すること（他社の制度を混ぜない）

参考例（他社）:
{ref_pattern_examples}

### 2. プロンプトセクション（会社固有の3セクション）
AI生成時のシステムプロンプトの構成パーツ。section_type と content を設定。
トーン・共通ルール・NG表現は全社共通で登録済みのため、**会社固有の情報のみ**を生成する。
候補者の経歴が豊富な場合にAIが使う生成ガイドになるため、**具体的で実用的な内容**にすること。

必須セクション（section_type名を正確に使うこと）:
1. **station_features**（会社特色）order=2: AIが接点を見つけるための会社の強み・特色リスト。箇条書きで5〜8項目。各項目に（カッコ内で候補者のどんな経験が活きるか）を添える
2. **education**（教育体制）order=3: **その会社固有の**研修・サポート体制。他社の制度を混ぜないよう注意。制度がない場合は「現場のスタッフと協力しながら業務を覚えられる体制」等の事実のみ記載
3. **ai_guide**（AI生成ガイド）order=8: 以下の2つを含めること:
   a. 経歴別の接点対応表: 候補者の経験パターン → 会社の強み → 接点の表現方向。5〜8パターン
   b. NGパターン: やってはいけない接点の作り方（弱い接点、会社情報の羅列、地理的要素のみ等）

以下は全社共通で既に登録済み（生成不要）:
- role_definition（order=1）: パーソナライズ文の基本指示
- tone_and_manner（order=4）: トーン・マナールール
- common_rules（order=5）: 文字数・書き出し・経験年数記載等の共通ルール
- ng_expressions（order=9）: NG表現リスト

つまり、会社固有で生成するのは **station_features, education, ai_guide** の3セクションのみ。
各セクションは200〜800文字。job_category は会社情報から推測（看護系なら"nurse"等）。

参考例（他社）:
{ref_prompt_example}

### 3. バリデーション（1件）
スカウト対象のフィルタリング条件。JSON形式。
- age_min, age_max: 年齢範囲（空欄なら制限なし）
- qualification_rules: JSON。必須資格、除外条件等
{ref_validation_example}

### 4. 資格修飾（5〜10件）
複数資格保持者への修飾テキスト。型はめパターンの冒頭を差し替える文。
- qualification_combo: 資格の組み合わせ（カンマ区切り）
- replacement_text: その資格の組み合わせが**なぜこの会社で活きるのか**を具体的に書いた1〜2文
  - 悪い例: 「看護師・介護福祉士の両方の資格をお持ちとのこと、」（接点がない）
  - 良い例: 「看護師の資格に加え、ケアマネージャーの資格もお持ちとのこと、医療と介護の両面から患者様を支える視点は、地域に根差した精神科医療を提供する当院で大きな力になると考えております。」（資格×会社の特色の接点がある）
{ref_qualifier_example}

## 出力形式
以下のJSON1つで返してください。他のテキストは不要です。
```json
{{
{template_output_schema}  "patterns": [
    {{"pattern_type": "A", "employment_variant": "", "template_text": "...", "feature_variations": ["...", "...", "..."]}},
    ... (10件: A, B1, B2, C, D就業中, D離職中, E, F就業中, F離職中, G)
  ],
  "prompts": [
    {{"section_type": "station_features", "job_category": "nurse", "order": 2, "content": "- 特色1（どんな経験が活きるか）\\n- 特色2..."}},
    {{"section_type": "education", "job_category": "nurse", "order": 3, "content": "- 研修制度1\\n- 研修制度2..."}},
    {{"section_type": "ai_guide", "job_category": "nurse", "order": 8, "content": "経歴別の接点対応表:\\n- 〇〇経験 → 会社の強み → 接点表現\\n...\\n\\nNGパターン:\\n- ..."}}
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
        gen_result = await generate_personalized_text(
            system_prompt=system_prompt,
            user_prompt=f"以下の会社情報から、スカウト文生成の全設定を生成してください。\n\n{company_info}",
            model_name=None,
            max_output_tokens=8192,
            temperature=0.5,
        )
        result_text = gen_result.text

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
        cat_excl = validation.get("category_exclusions", "")
        if isinstance(cat_excl, dict):
            cat_excl = _json.dumps(cat_excl, ensure_ascii=False)
        sheets_writer.append_row("バリデーション", [
            company_id,
            str(validation.get("age_min", "")),
            str(validation.get("age_max", "")),
            qual_rules,
            cat_excl,
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
        gen_result = await generate_personalized_text(
            system_prompt=system_prompt,
            user_prompt=f"以下の会社情報をもとに、10パターンのスカウト文を生成してください。\n\n{company_info}",
            model_name=None,
        )
        result_text = gen_result.text

        # Extract JSON from response (may be wrapped in markdown code blocks)
        import re
        json_match = re.search(r'\[[\s\S]*\]', result_text)
        if not json_match:
            raise ValueError("AI応答からJSONを抽出できませんでした")

        patterns = _json.loads(json_match.group(0))
        return {"patterns": patterns}
    except Exception as e:
        raise HTTPException(500, f"AI生成エラー: {str(e)}")


@router.post("/sync_replies")
async def sync_replies(
    data: dict,
    operator=Depends(verify_api_key),
):
    """Chrome拡張から返信データを受け取り、送信データシートを更新する。"""
    company = data.get("company", "")
    replies = data.get("replies", [])
    if not replies:
        return {"status": "ok", "updated": 0}

    from pipeline.orchestrator import _send_data_sheet_name
    sheet_name = _send_data_sheet_name(company)

    try:
        all_rows = sheets_writer.get_all_rows(sheet_name)
    except Exception:
        return {"status": "error", "detail": f"送信データシート '{sheet_name}' が存在しません"}
    if len(all_rows) < 2:
        return {"status": "ok", "updated": 0}

    headers = all_rows[0]
    try:
        col_member = headers.index("会員番号")
        col_reply = headers.index("返信")
        col_reply_date = headers.index("返信日")
        col_reply_cat = headers.index("返信カテゴリ")
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"シートヘッダー不正: {e}")

    reply_map = {r["member_id"]: r for r in replies}

    updated = 0
    for row_idx, row in enumerate(all_rows[1:], start=2):
        if len(row) <= col_member:
            continue
        member_id = row[col_member]
        if member_id not in reply_map:
            continue

        reply = reply_map[member_id]
        while len(row) < len(headers):
            row.append("")
        row[col_reply] = "有"
        row[col_reply_date] = reply.get("replied_at", "")
        row[col_reply_cat] = reply.get("category", "")

        sheets_writer.update_row(sheet_name, row_idx, row)
        updated += 1

    return {"status": "ok", "updated": updated}


@router.post("/improve_template")
async def improve_template(
    data: dict,
    operator=Depends(verify_api_key),
):
    """AIがテンプレートを改善し、変更理由付きの改善版を返す。"""
    import re
    from pipeline.orchestrator import _send_data_sheet_name, COMPANY_DISPLAY_NAMES
    from pipeline.ai_generator import generate_personalized_text

    company = data.get("company", "")
    template_type = data.get("template_type", "")
    job_category = data.get("job_category", "")
    directive = data.get("directive", "")  # ユーザーの改善指示
    analysis_summary = data.get("analysis_summary", "")  # 分析タブからの連携データ
    requested_row_index = data.get("row_index")  # 管理画面から直接渡されるrow_index

    if not company or not template_type:
        raise HTTPException(400, "company and template_type are required")

    # 1. Get current template body
    all_template_rows = sheets_writer.get_all_rows("テンプレート")
    row_index = None
    original_body = ""

    if requested_row_index:
        # row_indexが直接指定されている場合はそれを使用（Sheet行番号: 1-based）
        row_index = int(requested_row_index)
        if row_index >= 2 and row_index <= len(all_template_rows):
            row = all_template_rows[row_index - 1]
            original_body = row[3].replace("\\n", "\n") if len(row) > 3 else ""
        else:
            raise HTTPException(404, f"Row {row_index} not found")
    else:
        # row_indexが指定されていない場合は検索
        for idx, row in enumerate(all_template_rows[1:], start=2):
            if len(row) >= 4 and row[0] == company and row[2] == template_type:
                if not job_category or row[1] == job_category:
                    row_index = idx
                    original_body = row[3].replace("\\n", "\n") if len(row) > 3 else ""
                    break

    if row_index is None or not original_body:
        raise HTTPException(404, "テンプレートの行が見つかりません")

    # 2. Load company profile from Sheets
    company_profile = sheets_client.get_company_profile(company)

    # 3. Get send data stats + build analysis context
    from datetime import datetime, timedelta, timezone
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    date_from = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    stats_text = ""
    sheet_name = _send_data_sheet_name(company)
    try:
        all_rows = sheets_writer.get_all_rows(sheet_name)
        if len(all_rows) >= 2:
            headers = all_rows[0]
            col_map = {h: i for i, h in enumerate(headers)}
            total = 0
            replied = 0
            for row in all_rows[1:]:
                row_date = row[col_map.get("日時", 0)][:10] if col_map.get("日時") is not None and len(row) > col_map["日時"] and row[col_map["日時"]] else ""
                if row_date >= date_from:
                    total += 1
                    if col_map.get("返信") is not None and len(row) > col_map["返信"] and row[col_map["返信"]] == "有":
                        replied += 1
            if total > 0:
                stats_text = f"直近30日: 送信{total}通, 返信{replied}件, 返信率{replied/total*100:.1f}%"
    except Exception:
        pass

    # 4. Build analysis data section
    analysis_section = ""
    if analysis_summary:
        analysis_section = f"""

---

## 分析データ

{analysis_summary}

上記のデータから読み取れる傾向を改善に活かしてください。
返信率が高いパターン・低いパターンがあれば、テンプレートのどの部分が影響しているかを考察し、改善案に反映してください。"""
    elif stats_text:
        analysis_section = f"""

---

## 送信実績

{stats_text}"""

    # 5. Build company profile section
    profile_section = ""
    display_name = COMPANY_DISPLAY_NAMES.get(company, company)
    if company_profile:
        profile_section = f"""

---

## 会社情報

{company_profile}

上記の会社情報を踏まえ、この会社が求職者に対して本当に訴求すべき強みは何かを判断してください。
全ての特徴を並べるのではなく、求職者が最も価値を感じるポイントに絞ってテンプレートに反映してください。"""
    else:
        profile_section = f"""

---

## 会社情報

会社名: {display_name}
（詳細な会社情報は取得できませんでした。テンプレートの文面から読み取れる情報をもとに改善してください。）"""

    # 6. Build system prompt
    system_prompt = f"""あなたは介護・医療系求人のスカウト文テンプレートを改善するエキスパートです。
目的はただ一つ: このテンプレートで送るスカウトの返信率を上げること。

表現の微調整ではなく、「求職者がこのスカウトを受け取ったとき、返信したくなるか？」という視点で改善してください。

---

## 求職者を知る

### 転職者の不安と動機

介護・医療職が転職を考えるとき、最も多い理由:
- **介護職**: 人間関係の問題が圧倒的に多い。次いで施設の理念・運営への不満、より良い条件の職場を求めて
- **看護師**: 上司との関係、長時間労働・残業の多さ、給与への不満、結婚・出産・育児などライフステージの変化

転職活動中の最大の不安は「転職先でも同じ問題が起きないか」。特に人間関係で辞めた人は、次の職場の雰囲気に最も敏感になる。

訪問看護特有の不安:
- 「一人で訪問することへの怖さ・プレッシャー」が最大の壁（過半数が感じる）
- オンコール対応の負担も大きな懸念材料
→ 訪問看護のテンプレートでは、この不安をどう解消するかが返信率に直結する

### 求職者が求人で見ているもの

優先順位（高い順）:
1. **給与・賞与・手当** — 最も多くの人が重視する。ただし具体的な数字がないと信用されない
2. **残業時間・勤務体制** — 「月平均○時間」の具体性が信頼につながる
3. **人間関係・職場の雰囲気** — 最も気にしているが、求人票だけでは分かりにくい。だからこそスカウト文で伝えられると強い
4. **勤務地・通勤時間** — 長く働けるかの判断材料
5. **教育体制・研修制度** — 特に未経験・ブランク層に響く
6. **休日数・有休取得率** — ワークライフバランスの指標

重要: 給与が地域相場より低い場合、給与を前面に出しても逆効果。その会社が本当に強いポイント（教育体制、雰囲気、柔軟な働き方等）で勝負すべき。

### 売り手市場という前提

介護関係職種の有効求人倍率は約4倍。求職者1人に対して約4件の求人がある。つまり求職者が選ぶ立場。条件に妥協する必要がなく、スカウトを受けても「もっと良い条件があるかも」と比較検討する余裕がある。

だからこそ、テンプレート一斉送信では埋もれる。「この会社は自分に合いそう」と思わせる具体性が必要。

---

## スカウトを読む人の心理

### 大量に届く中での判断

求職者は複数の事業所からスカウトを受け取る。特に関東圏では大量に届く。その中で:

1. **冒頭数十文字で開封するか決める** — ジョブメドレーの一覧画面では事業所名＋本文の冒頭部分がプレビュー表示される。ここで興味を引けなければ開かれない
2. **開封しても数秒で「読む価値があるか」を判断する** — 会社紹介から始まるスカウトは読み飛ばされる
3. **返信するかは「自分に合うか」で決める** — 待遇と「自分のスキルが活かせるか」で約7割の判断が決まる

### 好まれるスカウト

- **プロフィールを読んだと分かる**（最重要 — 約6割が重視）
- 特別感がある（テンプレ一斉送信ではないと感じる）
- なぜスカウトしたか理由が具体的
- **短くて簡潔**（約7割が好む）

### 嫌われるスカウト

- 希望に合わない求人のスカウト
- 明らかにテンプレートの一斉送信
- 会社の情報ばかりで自分への言及がない
- 断っても繰り返し送ってくる

### 潜在層と顕在層の違い

離職中の求職者は緊急度が高く、具体的な条件提示・早期入職可能性が響く。
就業中（情報収集中）の求職者は選別的で、「今の職場より良い点」を明確に示す必要がある。CTAも「まずは情報交換」程度のライトさが有効。

---

## 良いスカウトの原則

### 原則① 冒頭30文字が勝負

一覧画面のプレビューで見えるのは冒頭30〜50文字程度。全メールの半数以上がスマホで開封される。
最初の1文で「なぜあなたに送ったか」を伝える。

テンプレートには `{{personalized_text}}` が含まれるが、その前後の定型文がプレビューに出る可能性がある。
冒頭の定型文がテンプレ感を出していないか確認する。

### 原則② 「候補者の経験 × 会社の特色 = 接点」

パーソナライズの核心はこの掛け算。テンプレート内の `{{personalized_text}}` がこの役割を担う。
テンプレート側は、この接点が最大限活きる構成になっているべき。

テンプレートが会社情報の羅列になっていると、パーソナライズ文を入れても「会社紹介の中に1文だけ個別メッセージがある」状態になり、効果が薄れる。

### 原則③ 特徴ではなく「あなたにとっての利益」で語る

会社の特徴をそのまま書いても人は動かない。「それが相手にとって何を意味するか」まで踏み込む。
- ✕ 特徴そのまま:「電子カルテ導入済みです」
- ◎ 相手の利益:「残業が月平均5時間以内で、プライベートとの両立が可能です」

### 原則④ CTAは低いハードルで1つだけ

- 低（推奨）:「ご興味があればお気軽にご返信ください」「まずは見学だけでも歓迎です」
- 高（避ける）:「ぜひご応募ください」

CTAは1つだけ。複数並べると迷って行動しない。
{profile_section}
{analysis_section}

---

## NG表現・品質の最低ライン

以下は絶対に避けること:
- **年齢・世代への言及**（「20代」「若手」「ベテラン」）
- **会社名の誤り**
- **居住地の詳細すぎる言及**（「○○区にお住まい」→ 広域表現に）
- **憶測の記載**（「〜されたいのですね」→ 事実のみ）
- **過剰敬語**（「拝察いたします」「敬意を表します」）
- **送り手の感情が主語**（「ご一緒したい」→ 相手へのオファー主体で）
- **対象職種の資格への冗長な言及**（看護師求人で「看護師の資格をお持ちとのこと」→ 資格保有は前提なので不要）
- **上から目線**（「フォローします」「安心してください」→「チームでサポートし合う環境」）

---

## 出力ルール

1. **`{{personalized_text}}` を必ず含める**。位置は変えてよい
2. 改善したテンプレートの**全文**を出力する（部分ではなく全文）
3. 変更した箇所の直後に `<!-- 変更理由: 理由 -->` を入れる
4. 変更していない箇所は一字一句そのまま残す
5. テンプレート本文のみ出力。前置き・説明・コードフェンス不要
6. 各行の改行フォーマット（\\n）はそのまま維持する
7. 元テンプレートに存在しないプレースホルダー（{{お名前}}等）を追加しない

構成の変更、段落の順序入れ替え、大幅な書き換えは許可する。
返信率を上げるために必要であれば、遠慮なく変えてよい。
ただし変更理由を必ず明記すること。"""

    # ユーザーの改善指示があればプロンプトに追加
    directive_section = ""
    if directive:
        directive_section = f"\n\n## ディレクターからの改善指示（最優先）\n{directive}\n上記の指示を最優先で反映してください。"

    user_prompt = f"以下のテンプレートを改善してください。\n求職者の心理と会社の強みを踏まえ、返信率が上がる形に変えてください。{directive_section}\n\n{original_body}"

    # 7. Call Gemini
    try:
        result = await generate_personalized_text(
            system_prompt,
            user_prompt,
            max_output_tokens=8192,
            temperature=0.5,
        )
        raw_improved = result.text
    except Exception as e:
        raise HTTPException(500, f"AI生成エラー: {e}")

    # 5. Parse: extract change reasons, clean up
    # Strip markdown code fences if present
    raw_improved = re.sub(r'^```[^\n]*\n', '', raw_improved)
    raw_improved = re.sub(r'\n```$', '', raw_improved.rstrip())

    # Extract change reasons
    changes = []
    for m in re.finditer(r'<!-- 変更理由:\s*(.+?)\s*-->', raw_improved):
        reason = m.group(1)
        start = max(0, m.start() - 30)
        context = raw_improved[start:m.start()].strip()[-40:]
        changes.append({"reason": reason, "context": context})

    # Remove HTML comments to get clean version
    improved_clean = re.sub(r'\s*<!-- 変更理由:\s*.+?\s*-->', '', raw_improved).strip()

    # Validate placeholder
    if "{personalized_text}" not in improved_clean and "\\{personalized_text\\}" not in improved_clean:
        # Try to recover
        if "{personalized_text}" in original_body:
            return {
                "status": "error",
                "detail": "AIがプレースホルダー{personalized_text}を削除してしまいました。再度お試しください。",
            }

    return {
        "status": "ok",
        "original": original_body,
        "improved": improved_clean,
        "changes": changes,
        "row_index": row_index,
    }


@router.post("/expand_template")
async def expand_template(
    data: dict,
    operator=Depends(verify_api_key),
):
    """ソーステンプレートを元に、複数ターゲットへ適応版を一括生成する。"""
    import re
    from pipeline.ai_generator import generate_personalized_text

    company = data.get("company", "")
    source_jc = data.get("source_job_category", "")
    source_type = data.get("source_template_type", "")
    targets = data.get("targets", [])
    directive = data.get("directive", "")

    if not company or not source_type or not targets:
        raise HTTPException(400, "company, source_template_type, targets are required")

    # 1. Get source template
    all_rows = sheets_writer.get_all_rows("テンプレート")
    if not all_rows:
        raise HTTPException(404, "テンプレートシートが空です")
    headers = all_rows[0]
    col_map = {h.strip(): i for i, h in enumerate(headers)}

    source_body = ""
    for row in all_rows[1:]:
        c = row[col_map.get("company", 0)] if col_map.get("company") is not None and len(row) > col_map["company"] else ""
        jc = row[col_map.get("job_category", 1)] if col_map.get("job_category") is not None and len(row) > col_map["job_category"] else ""
        tt = row[col_map.get("type", 2)] if col_map.get("type") is not None and len(row) > col_map["type"] else ""
        if c.strip() == company and jc.strip() == source_jc and tt.strip() == source_type:
            source_body = row[col_map.get("body", 3)] if col_map.get("body") is not None and len(row) > col_map["body"] else ""
            break

    if not source_body:
        raise HTTPException(404, f"ソーステンプレートが見つかりません: {source_jc}:{source_type}")

    source_body = source_body.replace("\\n", "\n")

    # 2. Load company profile
    company_profile = sheets_client.get_company_profile(company)

    # 3. Build target info + find existing templates
    target_rows = []
    for t in targets:
        t_jc = t.get("job_category", "")
        t_type = t.get("template_type", "")
        existing_body = ""
        row_index = None
        for idx, row in enumerate(all_rows[1:], start=2):
            c = row[col_map.get("company", 0)] if col_map.get("company") is not None and len(row) > col_map["company"] else ""
            jc = row[col_map.get("job_category", 1)] if col_map.get("job_category") is not None and len(row) > col_map["job_category"] else ""
            tt = row[col_map.get("type", 2)] if col_map.get("type") is not None and len(row) > col_map["type"] else ""
            if c.strip() == company and jc.strip() == t_jc and tt.strip() == t_type:
                existing_body = row[col_map.get("body", 3)] if col_map.get("body") is not None and len(row) > col_map["body"] else ""
                existing_body = existing_body.replace("\\n", "\n")
                row_index = idx
                break
        target_rows.append({
            "job_category": t_jc,
            "template_type": t_type,
            "existing_body": existing_body,
            "row_index": row_index,
        })

    # 4. Build adaptation prompt
    JOB_CATEGORY_NAMES = {
        "nurse": "看護師/准看護師",
        "rehab_pt": "理学療法士",
        "rehab_st": "言語聴覚士",
        "rehab_ot": "作業療法士",
        "medical_office": "医療事務",
    }

    TYPE_RULES = {
        "パート_初回": "パート・アルバイト向けの初回スカウト。柔軟な働き方を訴求。",
        "パート_再送": "パート向けの再送スカウト。前回の補足として短く、新たな魅力や変化を伝える。",
        "正社員_初回": "正社員/正職員向けの初回スカウト。キャリアや待遇面を訴求。",
        "正社員_再送": "正社員向けの再送スカウト。前回の補足として短く、新たな魅力や変化を伝える。",
    }

    system_prompt = f"""あなたは介護・医療系のスカウト文テンプレートを、異なるテンプレート型・職種に適応させるエキスパートです。

「お手本テンプレート」の構成・トーン・表現の質を維持しながら、ターゲットの型や職種に合わせて適応してください。

## ルール
- {{personalized_text}} プレースホルダーは必ず維持
- お手本の構成（段落構成、CTA位置）を基本的に踏襲
- 型の違い（初回↔再送、パート↔正社員）に応じてトーンと内容を調整
- 職種の違いに応じて業務内容の表現を適切に変更
- 再送テンプレートは初回より短く、「再度のご連絡」のトーンに
- 正社員は待遇・キャリア面を強調、パートは柔軟性・働きやすさを強調
- テンプレート本文のみ出力（説明不要）

{f'## 会社情報{chr(10)}{company_profile[:2000]}' if company_profile else ''}
"""

    # 5. Generate for each target (sequential to avoid rate limits)
    results = []
    for tr in target_rows:
        t_jc_name = JOB_CATEGORY_NAMES.get(tr["job_category"], tr["job_category"])
        t_type_rule = TYPE_RULES.get(tr["template_type"], "")
        source_jc_name = JOB_CATEGORY_NAMES.get(source_jc, source_jc)

        adaptation_notes = []
        if tr["job_category"] != source_jc:
            adaptation_notes.append(f"職種変更: {source_jc_name} → {t_jc_name}")
        if tr["template_type"] != source_type:
            adaptation_notes.append(f"型変更: {source_type} → {tr['template_type']}")

        user_prompt = f"""以下のお手本テンプレートを適応してください。

## お手本（{source_jc_name} / {source_type}）
{source_body}

## 適応先
- 職種: {t_jc_name}
- テンプレート型: {tr['template_type']}
- {t_type_rule}
{f'- 適応ポイント: {", ".join(adaptation_notes)}' if adaptation_notes else ''}
{f'{chr(10)}## ディレクターの指示{chr(10)}{directive}' if directive else ''}

テンプレート本文のみ出力してください。"""

        try:
            result = await generate_personalized_text(
                system_prompt,
                user_prompt,
                max_output_tokens=8192,
                temperature=0.3,
            )
            proposed = result.text
            # Clean up
            proposed = re.sub(r'^```[^\n]*\n', '', proposed)
            proposed = re.sub(r'\n```$', '', proposed.rstrip())
            proposed = proposed.strip()

            results.append({
                "job_category": tr["job_category"],
                "template_type": tr["template_type"],
                "original": tr["existing_body"],
                "proposed": proposed,
                "row_index": tr["row_index"],
            })
        except Exception as e:
            results.append({
                "job_category": tr["job_category"],
                "template_type": tr["template_type"],
                "original": tr["existing_body"],
                "proposed": "",
                "row_index": tr["row_index"],
                "error": str(e),
            })

    return {"status": "ok", "results": results}


@router.post("/batch_update_templates")
async def batch_update_templates(
    data: dict,
    operator=Depends(verify_api_key),
):
    """複数テンプレートを一括更新（バージョニング+変更履歴付き）。"""
    from datetime import datetime, timedelta, timezone
    JST = timezone(timedelta(hours=9))

    updates = data.get("updates", [])
    if not updates:
        raise HTTPException(400, "updates is required")

    all_rows = sheets_writer.get_all_rows("テンプレート")
    if not all_rows:
        raise HTTPException(404, "テンプレートシートが空です")
    header = all_rows[0]
    columns = COLUMNS.get("templates", [])

    updated = 0
    for upd in updates:
        row_index = upd.get("row_index")
        new_body = upd.get("body", "")
        reason = upd.get("reason", "一括展開")

        if not new_body:
            continue

        # row_indexがない場合は新規追加
        if not row_index:
            company_id = upd.get("company", "")
            job_cat = upd.get("job_category", "")
            ttype = upd.get("template_type", "")
            if company_id and ttype:
                sheets_writer.append_row("テンプレート", [
                    company_id, job_cat, ttype, new_body, "1",
                ])
                updated += 1
            continue

        if row_index < 2 or row_index > len(all_rows):
            continue

        existing_row = all_rows[row_index - 1]
        existing_row += [""] * (len(header) - len(existing_row))
        existing = {header[i]: existing_row[i] for i in range(len(header))}

        if existing.get("body", "") == new_body:
            continue  # no change

        # Version increment
        old_version = existing.get("version", "1")
        try:
            new_version = str(int(old_version) + 1)
        except (ValueError, TypeError):
            new_version = "2"

        # Log history
        try:
            sheets_writer.ensure_sheet_exists("テンプレート変更履歴", [
                "timestamp", "company", "job_category", "type",
                "old_version", "new_version", "reason", "old_body",
            ])
            sheets_writer.append_row("テンプレート変更履歴", [
                datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
                existing.get("company", ""),
                existing.get("job_category", ""),
                existing.get("type", ""),
                old_version,
                new_version,
                reason,
                existing.get("body", ""),
            ])
        except Exception:
            pass

        # Update row
        merged = {col: existing.get(col, "") for col in columns}
        merged["body"] = new_body
        merged["version"] = new_version
        values = [merged[col] for col in columns]
        sheets_writer.update_row("テンプレート", row_index, values)
        updated += 1

    sheets_client.reload()
    return {"status": "ok", "updated": updated}


@router.post("/analyze_cycle")
async def analyze_cycle(
    data: dict,
    operator=Depends(verify_api_key),
):
    """送信データを多角的に分析し、改善仮説と改善案を自動生成する。"""
    from datetime import datetime, timedelta, timezone
    from pipeline.orchestrator import _send_data_sheet_name, COMPANY_DISPLAY_NAMES
    from pipeline.ai_generator import generate_personalized_text

    JST = timezone(timedelta(hours=9))
    company = data.get("company", "")
    is_cross_company = (company == "all")
    now = datetime.now(JST)
    date_from = data.get("date_from", (now - timedelta(days=30 if is_cross_company else 14)).strftime("%Y-%m-%d"))
    date_to = data.get("date_to", now.strftime("%Y-%m-%d"))

    # Collect rows from one or all company sheets
    headers = None
    col_map = {}
    filtered = []

    companies_to_scan = list(COMPANY_DISPLAY_NAMES.keys()) if is_cross_company else [company]

    for cid in companies_to_scan:
        sheet_name = _send_data_sheet_name(cid)
        try:
            all_rows = sheets_writer.get_all_rows(sheet_name)
        except Exception:
            continue
        if len(all_rows) < 2:
            continue

        if headers is None:
            headers = all_rows[0]
            col_map = {h: i for i, h in enumerate(headers)}

        display_name = COMPANY_DISPLAY_NAMES.get(cid, cid)
        for row in all_rows[1:]:
            row_date = row[col_map.get("日時", 0)][:10] if col_map.get("日時") is not None and len(row) > col_map["日時"] and row[col_map["日時"]] else ""
            if date_from <= row_date <= date_to:
                # For cross-company, tag each row with company name
                if is_cross_company:
                    row = list(row)
                    row.append(display_name)  # append company name as extra column
                filtered.append(row)

    if not filtered or headers is None:
        label = "全社" if is_cross_company else company
        return {"status": "error", "detail": f"{label} の {date_from}〜{date_to} にデータがありません"}

    # For cross-company, add virtual "会社" column
    if is_cross_company:
        company_col_idx = len(headers)  # appended at the end

    def _safe_get(row, col_name):
        if is_cross_company and col_name == "会社":
            return row[company_col_idx] if len(row) > company_col_idx else ""
        idx = col_map.get(col_name)
        if idx is None or idx >= len(row):
            return ""
        return row[idx]

    total = len(filtered)
    replied = sum(1 for r in filtered if _safe_get(r, "返信") == "有")
    reply_rate = replied / total if total > 0 else 0

    # Pattern display name mapping
    PATTERN_LABELS = {
        "A": "経験浅め・若手", "B1": "中堅・ブランクあり", "B2": "中堅・経験豊富",
        "C": "ベテラン", "D_就業中": "経験少なめ・就業中", "D_離職中": "経験少なめ・離職中",
        "E": "新人・未経験", "F_就業中": "高齢・就業中", "F_離職中": "高齢・離職中",
        "G": "情報不足（最小パターン）",
    }

    dimensions = ["テンプレート種別", "テンプレートVer", "生成パス", "パターン", "年齢層", "経験区分",
                   "希望雇用形態", "就業状況", "地域", "曜日", "時間帯"]
    if is_cross_company:
        dimensions = ["会社"] + dimensions
    cross_tabs = {}
    for dim in dimensions:
        buckets = {}
        for row in filtered:
            val = _safe_get(row, dim) or "(空)"
            # Map pattern codes to readable labels
            if dim == "パターン":
                if val == "(空)":
                    val = "AI生成（職歴・自己PRベース）"
                elif val in PATTERN_LABELS:
                    val = f"{val}（{PATTERN_LABELS[val]}）"
            if val not in buckets:
                buckets[val] = {"total": 0, "replied": 0}
            buckets[val]["total"] += 1
            if _safe_get(row, "返信") == "有":
                buckets[val]["replied"] += 1
        if len(buckets) > 1:
            cross_tabs[dim] = {
                k: {**v, "rate": f"{v['replied']/v['total']*100:.1f}%"}
                for k, v in sorted(buckets.items(), key=lambda x: -x[1]["total"])
            }

    # Get current template text for analysis context (full text)
    template_context = ""
    try:
        config = sheets_client.get_company_config(company)
        templates = config.get("templates", {})
        for tkey, tdata in templates.items():
            body = tdata.get("body", "").replace("\\n", "\n")
            template_context += f"\n### テンプレート: {tkey}\n{body}\n---\n"
    except Exception:
        pass

    summary_text = f"""## スカウト送信データ分析（{company}）
期間: {date_from} 〜 {date_to}
総送信数: {total}
返信数: {replied}
返信率: {reply_rate*100:.1f}%

### クロス集計
"""
    for dim, buckets in cross_tabs.items():
        summary_text += f"\n**{dim}別:**\n"
        for val, stats in buckets.items():
            summary_text += f"  {val}: {stats['total']}通 → 返信{stats['replied']}件 ({stats['rate']})\n"

    analysis_prompt = f"""あなたは介護・医療系求人のスカウト改善アナリストです。
以下のスカウト送信データと現在のテンプレートを分析し、具体的な改善提案を行ってください。
テンプレート内にメモやコメント（「※」「//」「【メモ】」等）があれば、それもディレクターの意図として読み取ってください。

{summary_text}

### 現在使用中のテンプレート（全文）
{template_context if template_context else "(テンプレート情報なし)"}

以下の形式で**必ず最後まで**回答してください:

## 発見したパターン
- 送信データから読み取れる傾向を3つまで箇条書き
- 数値の根拠を添える

## テンプレート改善案
各改善案について以下の3点をセットで提示:
1. **変更理由（仮説）**: なぜこの変更が必要か — データやテンプレートの文脈に基づく根拠
2. **現状の表現**: テンプレートから該当箇所を引用
3. **修正後の表現例**: 具体的な書き換え案

パーツ別（冒頭文 / 施設紹介 / 待遇 / 行動喚起CTA / その他）に分けて、優先度順に提案。

## 次サイクルの検証ポイント
- 改善実施後に見るべき指標を箇条書き"""

    try:
        result = await generate_personalized_text(
            analysis_prompt,
            "上記のデータとテンプレートを分析してください。",
            max_output_tokens=8192,
        )
        analysis_text = result.text
    except Exception as e:
        return {
            "status": "ok",
            "company": company,
            "period": f"{date_from}〜{date_to}",
            "summary": {"total": total, "replied": replied, "reply_rate": f"{reply_rate*100:.1f}%"},
            "cross_tabs": cross_tabs,
            "analysis": f"AI分析エラー: {e}",
        }

    return {
        "status": "ok",
        "company": company,
        "period": f"{date_from}〜{date_to}",
        "summary": {"total": total, "replied": replied, "reply_rate": f"{reply_rate*100:.1f}%"},
        "cross_tabs": cross_tabs,
        "analysis": analysis_text,
    }


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
    sheets_writer.ensure_sheet_exists(sheet_name, headers=columns)
    sheets_writer.append_row(sheet_name, values)
    sheets_client.reload()
    return {"status": "created"}


@router.put("/{sheet_slug}/{row_index}")
async def update_row(sheet_slug: str, row_index: int, data: dict, operator=Depends(verify_api_key)):
    sheet_name = SHEET_MAP.get(sheet_slug)
    if not sheet_name:
        raise HTTPException(404, f"Unknown sheet: {sheet_slug}")

    columns = COLUMNS.get(sheet_slug, [])

    # Partial update: read existing row and merge with incoming data
    all_rows = sheets_writer.get_all_rows(sheet_name)
    if row_index < 2 or row_index > len(all_rows):
        raise HTTPException(404, f"Row {row_index} not found")

    header = all_rows[0]
    existing_row = all_rows[row_index - 1]
    # Pad existing row to match header length
    existing_row += [""] * (len(header) - len(existing_row))
    existing = {header[i]: existing_row[i] for i in range(len(header))}

    # Merge: only overwrite fields present in incoming data
    merged = {col: data[col] if col in data else existing.get(col, "") for col in columns}

    # Template versioning: auto-increment version + log history on body change
    if sheet_slug == "templates" and "body" in data and data["body"] != existing.get("body", ""):
        from datetime import datetime, timedelta, timezone
        JST = timezone(timedelta(hours=9))

        old_version = existing.get("version", "1")
        try:
            new_version = str(int(old_version) + 1)
        except (ValueError, TypeError):
            new_version = "2"
        merged["version"] = new_version

        # Log old version to history sheet
        try:
            sheets_writer.ensure_sheet_exists("テンプレート変更履歴", [
                "timestamp", "company", "job_category", "type",
                "old_version", "new_version", "reason", "old_body",
            ])
            reason = data.get("_change_reason", "管理画面から更新")
            sheets_writer.append_row("テンプレート変更履歴", [
                datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
                existing.get("company", ""),
                existing.get("job_category", ""),
                existing.get("type", ""),
                old_version,
                new_version,
                reason,
                existing.get("body", ""),
            ])
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to log template history: {e}")

    values = [merged[col] for col in columns]

    sheets_writer.update_row(sheet_name, row_index, values)
    sheets_client.reload()
    return {"status": "updated", "merged_fields": list(data.keys()), "version": merged.get("version", "")}


@router.delete("/{sheet_slug}/{row_index}")
async def delete_row(sheet_slug: str, row_index: int, operator=Depends(verify_api_key)):
    sheet_name = SHEET_MAP.get(sheet_slug)
    if not sheet_name:
        raise HTTPException(404, f"Unknown sheet: {sheet_slug}")

    sheets_writer.delete_row(sheet_name, row_index)
    sheets_client.reload()
    return {"status": "deleted"}


# --- Cost monitoring endpoints ---

@router.get("/costs/today")
async def get_costs_today(operator=Depends(verify_api_key)):
    """Get today's cost summary."""
    from monitoring.cost_tracker import cost_tracker
    return cost_tracker.get_daily_summary()


@router.get("/costs/monthly")
async def get_costs_monthly(operator=Depends(verify_api_key)):
    """Get current month's cost summary."""
    from monitoring.cost_tracker import cost_tracker
    return cost_tracker.get_monthly_summary()


@router.post("/cron/daily-report")
async def cron_daily_report(operator=Depends(verify_api_key)):
    """Cloud Scheduler が毎朝叩くエンドポイント。日次レポート + アラート。"""
    from monitoring.cost_tracker import cost_tracker
    from monitoring.notifier import notify_google_chat
    from monitoring.scheduler import _format_cost_message, _check_alert
    from datetime import datetime, timedelta, timezone

    JST = timezone(timedelta(hours=9))
    yesterday = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")
    summary = cost_tracker.get_daily_summary(yesterday)
    monthly = cost_tracker.get_monthly_summary()

    if summary["requests"] > 0:
        message = _format_cost_message(summary, "日次コストレポート")
        message += f"\n\n📅 今月累計: ${monthly['estimated_cost_usd']:.4f}"
    else:
        message = (
            f"📊 *日次コストレポート*\n"
            f"期間: {yesterday}\n"
            f"リクエスト数: 0\n"
            f"\n📅 今月累計: ${monthly['estimated_cost_usd']:.4f}"
        )

    sent = await notify_google_chat(message)
    await _check_alert()

    return {"status": "ok", "sent": sent, "yesterday": yesterday}
