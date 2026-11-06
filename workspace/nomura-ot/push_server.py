#!/usr/bin/env python3
"""野村病院 作業療法士（正社員）をサーバ（Google Sheets）に登録する。

2026-11 クライアント支給文の取り込み分。ローカルの companies/nomura-hospital/ の
templates.md / recipes.md を読み、以下をサーバに追加する（冪等: 行単位で既存ならスキップ）。

  1. テンプレート: rehab_ot の 正社員_初回 / 正社員_再送 / 正社員_お気に入り（3行）
  2. パターン:     rehab_ot の 型A〜G（10行。server_admin.py create-patterns 相当）
                   型Aの match_rules は [{"exp_min": 10}]（2026-10-18 に他社で直した内容と同じ。
                   STANDARD_MATCH_RULES のままだと 40代×経験6〜9年に「10年以上」が出る）
  3. プロンプト:   rehab_ot の station_features / education / ai_guide（3行）
  4. 求人:         作業療法士（正職員）求人ID 1759407  https://job-medley.com/ot/1759407/

職種キーワード・validation の category_config は追加しない（作業療法士はサーバの
資格マップに組み込み済みで、拡張は求人選択時に job_category を明示して渡すため）。

Usage (リポジトリルートで実行):
  python3 workspace/nomura-ot/push_server.py --dry-run
  python3 workspace/nomura-ot/push_server.py

Environment: SCOUT_API_BASE / SCOUT_API_KEY（server_admin.py と同じ）
"""
import importlib.util
import json
import os
import re
import time

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
SA_PATH = os.path.join(ROOT, ".claude", "skills", "server-admin", "scripts", "server_admin.py")
COMPANY = "nomura-hospital"
JC = "rehab_ot"
COMPANY_DIR = os.path.join(ROOT, "companies", COMPANY)

spec = importlib.util.spec_from_file_location("server_admin", SA_PATH)
sa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sa)

# POST 1回ごとにサーバが全シートを読み直す（_safe_reload）ため、連続で書くと
# Sheets API の回数制限に当たり 500 になる。間隔を空け、5xx は待ってから再試行する。
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


def get_rows(sheet, params=None):
    """GET が断続的に空を返すため、空なら待って再取得する。"""
    for _ in range(5):
        rows = sa.api_get(sheet, params).get("rows", [])
        if rows:
            return rows
        time.sleep(10)
    raise SystemExit(f"GET {sheet} が空のまま。サーバ側の状態を確認してから再実行すること")


TEMPLATE_HEADINGS = {
    "正社員_初回": "## 作業療法士 正社員 初回テンプレート",
    "正社員_再送": "## 作業療法士 正社員 再送テンプレート",
    "正社員_お気に入り": "## 作業療法士 正社員 お気に入り",
}

# STANDARD_MATCH_RULES の型Aは 40代×経験6年以上も含むため上書きする
MATCH_RULE_OVERRIDES = {"A": [{"exp_min": 10}]}
META_OVERRIDES = {"A": {"target_description": "経験10年+"}}

EDUCATION_CONTENT = (
    "- 未経験可・ブランク可・新卒可・年齢不問。精神科領域が初めての方、ブランクから復職を目指す方も歓迎\n"
    "- 研修制度あり（支給文: 充実した教育・研修体制、一人ひとり丁寧にサポート）\n"
    "- 歓迎要件は精神科作業療法に興味がある方、医療機関での勤務経験がある方（求人票）\n"
    "- 勤務は日勤 8:00〜17:00（休憩60分）、時間外ほぼなし、時短勤務相談可\n"
    "- ※求人票の教育欄「同行訪問を行い独り立ち」、給与内訳の「夜勤手当」は他職種の文言の流用とみられる。書かないこと\n"
    "- ※寮は求人票内で記載が食い違う（タイトルは寮完備、事業所情報は社宅・寮なし）。入社お祝い金・引越し手当は作業療法士の求人にない。いずれも書かないこと"
)

JOB_OFFERS = [
    {
        "company": COMPANY,
        "job_category": JC,
        "id": "1759407",
        "name": "山口県 医療法人天秋会 野村病院 精神科病院の作業療法士 作業療法士 正職員",
        "label": "作業療法士 正社員",
        "employment_type": "正職員",
        "active": "TRUE",
    },
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


def ot_section(recipes):
    start = recipes.index("\n## 作業療法士\n")
    end = recipes.index("\n## ", start + 5)
    return recipes[start:end]


def push_templates(templates_md):
    existing = get_rows("templates")
    have = {
        (r.get("job_category", ""), r.get("type", ""))
        for r in existing if r.get("company") == COMPANY
    }
    n = 0
    for ttype, heading in TEMPLATE_HEADINGS.items():
        if (JC, ttype) in have:
            print(f"  SKIP templates {JC}:{ttype} (exists)")
            continue
        body = code_block_after(templates_md, heading)
        assert body.count("{ここに生成した文章を挿入}") == 1, ttype
        print(f"  ADD  templates {JC}:{ttype} ({len(body)} chars)")
        post("templates", {
            "company": COMPANY, "job_category": JC, "type": ttype,
            "body": body.replace("\n", "\\n"), "version": "",
        })
        n += 1
    return n


def parse_ot_patterns():
    # server_admin.py の LCC_CATEGORY_MAP に「作業療法士」見出しが無いため、この実行の間だけ差し替える
    original = sa.LCC_CATEGORY_MAP
    sa.LCC_CATEGORY_MAP = {"作業療法士": JC}
    try:
        return sa.parse_lcc_recipes(os.path.join(COMPANY_DIR, "recipes.md")).get(JC, {})
    finally:
        sa.LCC_CATEGORY_MAP = original


def push_patterns():
    existing = get_rows("patterns")
    have = {
        (r.get("pattern_type", ""), r.get("employment_variant", ""))
        for r in existing if r.get("company") == COMPANY and r.get("job_category", "") == JC
    }
    recipes = parse_ot_patterns()
    if len(recipes) != 10:
        raise SystemExit(f"expected 10 {JC} patterns in recipes.md, got {sorted(recipes)}")
    n = 0
    for key in sorted(recipes):
        pt, _, variant = key.partition("_")
        if (pt, variant) in have:
            print(f"  SKIP patterns {JC}:{key} (exists)")
            continue
        features = recipes[key].get("features") or []
        if "{特色}" in recipes[key]["text"] and not features:
            raise SystemExit(f"{key}: {{特色}} があるのに特色バリエーションが空")
        meta = {**sa.STANDARD_META.get(key, {}), **META_OVERRIDES.get(key, {})}
        rules = MATCH_RULE_OVERRIDES.get(key, sa.STANDARD_MATCH_RULES.get(key, []))
        row = {
            "company": COMPANY, "job_category": JC,
            "pattern_type": pt, "employment_variant": variant,
            "template_text": recipes[key]["text"],
            "feature_variations": "|".join(features),
            "display_name": meta.get("display_name", ""),
            "target_description": meta.get("target_description", ""),
            "match_rules": json.dumps(rules, ensure_ascii=False),
            "qualification_combo": "", "replacement_text": "",
        }
        print(f"  ADD  patterns {JC}:{key} rules={row['match_rules']} : {row['template_text'][:40]}...")
        post("patterns", row)
        n += 1
    return n


def push_prompts(recipes_md):
    existing = get_rows("prompts")
    have = {
        (r.get("section_type", ""), r.get("job_category", ""))
        for r in existing if r.get("company") == COMPANY
    }
    sec = ot_section(recipes_md)
    contents = {
        "station_features": (2, section_text(sec, "### 当院の特色（作業療法士向け）")),
        "education": (3, EDUCATION_CONTENT),
        "ai_guide": (8, (
            "経験年数が4年以上の候補者には、パーソナライズ文中に具体的な経験年数を含めること"
            "（例: 「10年以上の作業療法のご経験」「5年にわたる〜」）\n"
            "締めは「〜と感じています。」で止め、招待調（「ぜひ一度お話しできましたら」）にしない"
            "（テンプレ側にCTAが2つある）\n"
            "テンプレに「＼主なお仕事内容／」の列挙があるため、仕事内容を並べ直さない。接点として1つ選ぶのは可\n"
            "経歴にない精神科経験を前提にしない\n\n経歴別の接点対応表:\n"
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


def push_job_offers():
    existing = get_rows("job_offers")
    have = {str(r.get("id", "")).strip() for r in existing if r.get("company") == COMPANY}
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
    print("\n== job_offers ==");  j = push_job_offers()
    print(f"\nadded: templates={t} patterns={p} prompts={q} job_offers={j}")


if __name__ == "__main__":
    main()
