#!/usr/bin/env python3
"""野村病院 医療事務（パート）をサーバ（Google Sheets）に登録する。

2026-10 クライアント支給文の取り込み分。ローカルの companies/nomura-hospital/ の
templates.md / recipes.md を読み、以下をサーバに追加する（冪等: 既存行があればスキップ）。

  1. テンプレート: medical_office の パート_初回 / パート_再送 / パート_お気に入り（3行）
  2. パターン:     medical_office の 型A〜G（10行。server_admin.py create-patterns 相当）
  3. プロンプト:   medical_office の station_features / education / ai_guide（3行）
  4. 職種キーワード: nomura-hospital 固有の「医療事務」「受付」→ medical_office（3行）
  5. 求人:         2行（2026-10-07 あっきーさん共有の求人URLから）
                   - 医療事務/受付（パート・バイト）求人ID 285319  https://job-medley.com/mc/285319/
                   - 薬剤師（パート・バイト）求人ID 1729377  https://job-medley.com/apo/1729377/
                     薬剤師のテンプレ・パターン・プロンプトは 2026-09 に登録済み。求人だけ未登録だった

Usage (リポジトリルートで実行):
  python3 workspace/nomura-medical-office/push_server.py --dry-run
  python3 workspace/nomura-medical-office/push_server.py

Environment: SCOUT_API_BASE / SCOUT_API_KEY（server_admin.py と同じ）
"""
import importlib.util
import os
import re
import sys
import time

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
SA_PATH = os.path.join(ROOT, ".claude", "skills", "server-admin", "scripts", "server_admin.py")
COMPANY = "nomura-hospital"
JC = "medical_office"
COMPANY_DIR = os.path.join(ROOT, "companies", COMPANY)

spec = importlib.util.spec_from_file_location("server_admin", SA_PATH)
sa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sa)

# POST 1回ごとにサーバが全シートを読み直す（_safe_reload）ため、連続で書くと
# Sheets API の回数制限に当たり 500 になる（2026-10-07 パターン6件目で発生）。
# 書き込みの間隔を空け、5xx は待ってから再試行する。
POST_INTERVAL_SEC = 4
RETRY_WAITS_SEC = (20, 40, 60)


def post(path, data):
    for wait in RETRY_WAITS_SEC + (None,):
        try:
            sa.api_post(path, data)
            break
        except sa.requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if wait is None or status < 500:
                raise
            print(f"  RETRY {path}: HTTP {status}, {wait}秒待って再試行")
            time.sleep(wait)
    if not sa.DRY_RUN:
        time.sleep(POST_INTERVAL_SEC)

TEMPLATE_HEADINGS = {
    "パート_初回": "## 医療事務 パート 初回テンプレート",
    "パート_再送": "## 医療事務 パート 再送テンプレート",
    "パート_お気に入り": "## 医療事務 パート お気に入り",
}

PROMPT_SECTIONS = {
    "station_features": (2, "### 当院の特色（医療事務向け）"),
    "ai_guide": (8, "#### 経歴別の接点対応表"),  # 医療事務セクション内の表
}

EDUCATION_CONTENT = (
    "- 未経験可・無資格可・ブランク可・年齢不問。「精神科の医療事務は初めて」という方も歓迎\n"
    "- 歓迎要件は医療機関での受付経験（求人票）、入院レセプト・病院での勤務経験（支給文）\n"
    "- 応募要件はパソコン入力（Excel・Word）\n"
    "- ※研修制度・教育体制の記載なし。「寮完備」「引越し手当」「退職金」は医療事務の求人票にない。使わないこと\n"
    "- ※「1日4〜8時間」は求人票と食い違う（支給文にあった表記）。パーソナライズ文で書かないこと\n"
    "- 社会保険完備は正（テンプレ本文に記載済み。パーソナライズ文の接点にはしない）"
)

JOB_OFFERS = [
    {
        "company": COMPANY,
        "job_category": JC,
        "id": "285319",
        "name": "山口県 医療法人天秋会 野村病院 医療事務/受付 パート・バイト",
        "label": "医療事務 パート",
        "employment_type": "パート",
        "active": "TRUE",
    },
    {
        "company": COMPANY,
        "job_category": "pharmacist",
        "id": "1729377",
        "name": "山口県 医療法人天秋会 野村病院 精神科病院の薬剤師 薬剤師 パート・バイト",
        "label": "薬剤師 パート",
        "employment_type": "パート",
        "active": "TRUE",
    },
]

KEYWORDS = [
    {"keyword": "医療事務", "source_fields": "qualification"},
    {"keyword": "医療事務", "source_fields": "desired"},
    {"keyword": "受付", "source_fields": "desired"},
]


def read(name):
    with open(os.path.join(COMPANY_DIR, name), encoding="utf-8") as f:
        return f.read()


def code_block_after(text, heading):
    """heading 直後の最初の ``` ブロック本文を返す。"""
    idx = text.index(heading)
    m = re.search(r"```\n(.*?)\n```", text[idx:], re.S)
    if not m:
        raise SystemExit(f"code block not found after: {heading}")
    return m.group(1).strip()


def section_text(text, heading, stop_pattern=r"\n#{2,4} "):
    """heading から次の見出しまでの本文（見出し行を除く）。"""
    idx = text.index(heading) + len(heading)
    rest = text[idx:]
    m = re.search(stop_pattern, rest)
    body = rest[: m.start()] if m else rest
    return body.strip().rstrip("-").strip()  # 末尾の区切り線 --- を除く


def medical_office_section(recipes):
    start = recipes.index("\n## 医療事務\n")
    end = recipes.index("\n## ", start + 5)
    return recipes[start:end]


def push_templates(templates_md):
    existing = sa.api_get("templates", {"company": COMPANY}).get("rows", [])
    have = {(r.get("job_category", ""), r.get("type", "")) for r in existing}
    n = 0
    for ttype, heading in TEMPLATE_HEADINGS.items():
        if (JC, ttype) in have:
            print(f"  SKIP templates {JC}:{ttype} (exists)")
            continue
        body = code_block_after(templates_md, heading)
        assert "{ここに生成した文章を挿入}" in body, ttype
        print(f"  ADD  templates {JC}:{ttype} ({len(body)} chars)")
        post("templates", {
            "company": COMPANY, "job_category": JC, "type": ttype,
            "body": body.replace("\n", "\\n"), "version": "",
        })
        n += 1
    return n


def push_patterns():
    existing = sa.api_get("patterns", {"company": COMPANY}).get("rows", [])
    have = {
        (r.get("pattern_type", ""), r.get("employment_variant", ""))
        for r in existing if r.get("job_category", "") == JC
    }
    recipes = sa.parse_lcc_recipes(os.path.join(COMPANY_DIR, "recipes.md")).get(JC, {})
    if len(recipes) != 10:
        raise SystemExit(f"expected 10 {JC} patterns in recipes.md, got {sorted(recipes)}")
    n = 0
    for key in sorted(recipes):
        pt, _, variant = key.partition("_")
        if (pt, variant) in have:
            print(f"  SKIP patterns {JC}:{key} (exists; 内容の更新は server_admin.py sync {COMPANY})")
            continue
        features = recipes[key].get("features") or []
        row = {
            "company": COMPANY, "job_category": JC,
            "pattern_type": pt, "employment_variant": variant,
            "template_text": recipes[key]["text"],
            "feature_variations": "|".join(features),
            "display_name": sa.STANDARD_META.get(key, {}).get("display_name", ""),
            "target_description": sa.STANDARD_META.get(key, {}).get("target_description", ""),
            "match_rules": sa.json.dumps(sa.STANDARD_MATCH_RULES.get(key, []), ensure_ascii=False),
            "qualification_combo": "", "replacement_text": "",
        }
        print(f"  ADD  patterns {JC}:{key}: {row['template_text'][:40]}...")
        post("patterns", row)
        n += 1
    return n


def push_prompts(recipes_md):
    existing = sa.api_get("prompts", {"company": COMPANY}).get("rows", [])
    have = {(r.get("section_type", ""), r.get("job_category", "")) for r in existing}
    sec = medical_office_section(recipes_md)
    contents = {
        "station_features": (2, section_text(sec, "### 当院の特色（医療事務向け）")),
        "education": (3, EDUCATION_CONTENT),
        "ai_guide": (8, (
            "経験年数が4年以上の候補者には、パーソナライズ文中に具体的な経験年数を含めること"
            "（例: 「10年以上の医療事務経験」「5年にわたる〜」）\n"
            "締めは「〜と感じています。」で止め、招待調（「ぜひ一度お話しできましたら」）にしない"
            "（テンプレ側にCTAが2つある）\n"
            "勤務条件は求人票の事実（10:00〜15:00・土日祝休み・週2〜3日程度）だけを書く\n\n経歴別の接点対応表:\n"
            + section_text(sec, "#### 経歴別の接点対応表")
            + "\n\nNGパターン:\n" + section_text(sec, "#### NGパターン")
        )),
    }
    n = 0
    for st, (order, content) in contents.items():
        if (st, JC) in have:
            print(f"  SKIP prompts {st}/{JC} (exists)")
            continue
        print(f"  ADD  prompts {st}/{JC} order={order} ({len(content)} chars)")
        post("prompts", {
            "company": COMPANY, "section_type": st, "job_category": JC,
            "order": str(order), "content": content.replace("\n", "\\n"),
        })
        n += 1
    return n


def push_keywords():
    try:
        existing = sa.api_get("job_category_keywords").get("rows", [])
    except Exception as e:  # GET が未対応でも追加は試みる
        print(f"  WARN cannot list job_category_keywords: {e}")
        existing = []
    have = {
        (r.get("company", ""), r.get("job_category", ""), r.get("keyword", ""), r.get("source_fields", ""))
        for r in existing
    }
    n = 0
    for kw in KEYWORDS:
        key = (COMPANY, JC, kw["keyword"], kw["source_fields"])
        gkey = ("", JC, kw["keyword"], kw["source_fields"])
        if key in have or gkey in have:
            print(f"  SKIP keyword {kw['keyword']}/{kw['source_fields']} (exists)")
            continue
        print(f"  ADD  keyword {kw['keyword']}/{kw['source_fields']} → {JC}")
        post("job_category_keywords/append", {
            "company": COMPANY, "job_category": JC, **kw,
            "weight": "1", "enabled": "TRUE", "note": "2026-10 医療事務パート追加",
        })
        n += 1
    return n


def push_job_offers():
    existing = sa.api_get("job_offers", {"company": COMPANY}).get("rows", [])
    have = {str(r.get("id", "")).strip() for r in existing}
    n = 0
    for offer in JOB_OFFERS:
        if offer["id"] in have:
            print(f"  SKIP job_offers {offer['id']} (exists)")
            continue
        print(f"  ADD  job_offers {offer['id']} {offer['name']}")
        post("job_offers", offer)
        n += 1
    return n

def main():
    if sa.DRY_RUN:
        print("[DRY RUN] 書き込みは行いません")
    templates_md = read("templates.md")
    recipes_md = read("recipes.md")
    print("\n== templates ==");  t = push_templates(templates_md)
    print("\n== patterns ==");   p = push_patterns()
    print("\n== prompts ==");    q = push_prompts(recipes_md)
    print("\n== job_category_keywords =="); k = push_keywords()
    print("\n== job_offers ==");  j = push_job_offers()
    print(f"\nadded: templates={t} patterns={p} prompts={q} keywords={k} job_offers={j}")


if __name__ == "__main__":
    main()
