"""Test: 野村病院でパート生成ができるか検証

依存が重いので orchestrator は使わず、template_resolver のロジックと
テンプレート lookup のロジックを直接テストする。
"""

import sys
import types

# Mock heavy modules before importing pipeline code
for mod_name in (
    "google", "google.auth", "google.oauth2", "google.oauth2.service_account",
    "googleapiclient", "googleapiclient.discovery",
    "db.sheets_client", "db.sheets_writer",
    "pipeline.ai_generator", "pipeline.prompt_builder",
    "pipeline.prompt_validator", "monitoring.cost_tracker",
):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

# Provide stubs the pipeline imports need
sheets_mod = sys.modules["db.sheets_client"]
sheets_mod.sheets_client = None
sheets_mod.label_for_category = lambda jc: {"nurse": "看護師", "dietitian": "管理栄養士"}.get(jc, jc)
sheets_mod.label_for_categories = lambda jcs: [sheets_mod.label_for_category(j) for j in jcs]

from models.profile import CandidateProfile
from models.generation import GenerateOptions
from pipeline.template_resolver import resolve_template_type


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

PART_ONLY = CandidateProfile(
    member_id="P001",
    qualifications="看護師",
    age="35歳",
    experience_years="10年以上",
    employment_status="就業中",
    desired_employment_type="パート（非常勤）",
)

BOTH = CandidateProfile(
    member_id="P002",
    qualifications="看護師",
    age="40歳",
    experience_years="10年以上",
    employment_status="就業中",
    desired_employment_type="正職員（常勤）、パート（非常勤）",
)

EMPTY = CandidateProfile(
    member_id="P003",
    qualifications="看護師",
    age="30歳",
    experience_years="5年",
    employment_status="就業中",
    desired_employment_type="",
)

SEISHAIN = CandidateProfile(
    member_id="P004",
    qualifications="看護師",
    age="28歳",
    experience_years="3年",
    employment_status="就業中",
    desired_employment_type="正職員（常勤）",
)


def opts(**kw):
    return GenerateOptions(**kw)


# ---------------------------------------------------------------------------
# 1. template_resolver のテスト
# ---------------------------------------------------------------------------

def test_part_only():
    tt = resolve_template_type(PART_ONLY, opts(), "nurse")
    print(f"パートのみ希望 → {tt}")
    assert tt == "パート_初回"


def test_both_seishain_part():
    tt = resolve_template_type(BOTH, opts(), "nurse")
    print(f"正職員+パート希望 → {tt}")
    assert tt == "正社員_初回", f"正職員+パートは正社員が優先されるべき。実際: {tt}"


def test_empty_desired():
    tt = resolve_template_type(EMPTY, opts(), "nurse")
    print(f"希望なし → {tt}")
    assert tt == "パート_初回", f"希望なしはデフォルトでパート。実際: {tt}"


def test_seishain_only():
    tt = resolve_template_type(SEISHAIN, opts(), "nurse")
    print(f"正職員希望 → {tt}")
    assert tt == "正社員_初回"


def test_force_part():
    tt = resolve_template_type(SEISHAIN, opts(force_employment="パート"), "nurse")
    print(f"force=パート → {tt}")
    assert tt == "パート_初回"


def test_force_seishain():
    tt = resolve_template_type(PART_ONLY, opts(force_employment="正社員"), "nurse")
    print(f"force=正社員 → {tt}")
    assert tt == "正社員_初回"


# ---------------------------------------------------------------------------
# 2. テンプレート lookup シミュレーション
# ---------------------------------------------------------------------------

def _lookup_template(templates: dict, job_category: str, template_type: str) -> dict | None:
    """orchestrator._process_candidate のテンプレート検索ロジックを再現"""
    # Step 1: exact match
    data = templates.get(f"{job_category}:{template_type}")
    if data is not None:
        return data
    # Step 2: generic
    data = templates.get(template_type)
    if data is not None:
        return data
    # Step 3: base type
    base = template_type.split("_")[0] + "_初回"
    data = templates.get(f"{job_category}:{base}")
    if data is None:
        data = templates.get(base)
    if data is not None:
        return data
    # Step 4: employment fallback
    send_type = template_type.split("_", 1)[1] if "_" in template_type else "初回"
    for key, tpl in templates.items():
        if tpl.get("job_category") == job_category and tpl["type"].endswith(f"_{send_type}"):
            return tpl
    return None


# 正社員テンプレートのみの config
SEISHAIN_ONLY_TEMPLATES = {
    "nurse:正社員_初回": {
        "type": "正社員_初回",
        "job_category": "nurse",
        "body": "正社員テンプレート {personalized_text}",
    },
    "nurse:正社員_再送": {
        "type": "正社員_再送",
        "job_category": "nurse",
        "body": "正社員再送テンプレート {personalized_text}",
    },
}

# パートテンプレートありの config
WITH_PART_TEMPLATES = {
    **SEISHAIN_ONLY_TEMPLATES,
    "nurse:パート_初回": {
        "type": "パート_初回",
        "job_category": "nurse",
        "body": "パートテンプレート {personalized_text}",
    },
    "nurse:パート_再送": {
        "type": "パート_再送",
        "job_category": "nurse",
        "body": "パート再送テンプレート {personalized_text}",
    },
}

# body が空のパートテンプレート
EMPTY_BODY_TEMPLATES = {
    **SEISHAIN_ONLY_TEMPLATES,
    "nurse:パート_初回": {
        "type": "パート_初回",
        "job_category": "nurse",
        "body": "",  # 空！
    },
}


def test_lookup_part_seishain_only():
    """正社員テンプレートのみ → パート_初回 → フォールバックで正社員_初回"""
    result = _lookup_template(SEISHAIN_ONLY_TEMPLATES, "nurse", "パート_初回")
    print(f"\n正社員のみ / パート_初回 → {result['type'] if result else 'None'}")
    assert result is not None, "フォールバックで正社員が見つかるはず"
    assert result["type"] == "正社員_初回"


def test_lookup_part_with_part():
    """パートテンプレートあり → パート_初回 → 直接マッチ"""
    result = _lookup_template(WITH_PART_TEMPLATES, "nurse", "パート_初回")
    print(f"パートあり / パート_初回 → {result['type'] if result else 'None'}")
    assert result is not None
    assert result["type"] == "パート_初回"


def test_lookup_part_empty_body():
    """body が空のパートテンプレート → 見つかるが body が空"""
    result = _lookup_template(EMPTY_BODY_TEMPLATES, "nurse", "パート_初回")
    print(f"空body / パート_初回 → type={result['type'] if result else 'None'}, body='{result.get('body', '') if result else ''}'")
    assert result is not None, "テンプレート行自体は見つかる"
    assert result["body"] == "", "body は空"
    print("⚠️ テンプレート行はあるが body が空 → L2/L3パイプラインでは [テンプレート未設定] エラーになる")


def test_l2_load_template_body_with_empty():
    """L2/L3 の _load_template_body 相当のロジック — body空はNone扱い"""
    templates = EMPTY_BODY_TEMPLATES
    for key in (
        "nurse:パート_初回",
        "パート_初回",
        "nurse:パート_初回",
        "パート_初回",
    ):
        tdata = templates.get(key)
        if tdata and tdata.get("body"):
            print(f"L2 found: {key}")
            return
    print("L2: テンプレート body が空のため None 扱い → [テンプレート未設定] エラー")
    # This is the expected behavior - empty body means template not usable


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "-s"])
