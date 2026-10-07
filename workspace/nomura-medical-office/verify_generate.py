#!/usr/bin/env python3
"""野村病院 医療事務（パート）の生成をサーバで実際に試す（push_server.py 実行後の確認用）。

ダミー候補者3名を /api/v1/generate/batch に送り、次を確認する。
  - template_type が パート_初回 / パート_再送 になり、generation_path が filtered_out でない
  - full_scout_text にプレースホルダ {ここに生成した文章を挿入} が残っていない
  - job_offer_id が 285319（求人登録が効いている）
  - 「[求人未登録]」「[テンプレート未設定]」の警告が出ていない
  - パーソナライズ文に禁止語（1日4〜8時間 / 社会保険完備 / 寮 / 引越し / 夜勤 / 月給）がない

Usage (リポジトリルートで実行):
  python3 workspace/nomura-medical-office/verify_generate.py

Environment: SCOUT_API_ROOT（既定: Cloud Run 本番の /api/v1）, SCOUT_API_KEY（既定: anycare）
AI生成パスは Gemini を1〜2回呼ぶ（数円程度）。
"""
import json
import os
import sys

import requests

API_ROOT = os.environ.get(
    "SCOUT_API_ROOT", "https://scout-api-1080076995871.asia-northeast1.run.app/api/v1"
)
API_KEY = os.environ.get("SCOUT_API_KEY", "anycare")

PROFILES = [
    {   # 経歴なし → 型はめ（型D_就業中）を想定
        "member_id": "TEST-MO-001", "age": "52歳", "gender": "女性",
        "qualifications": "", "experience_type": "", "experience_years": "",
        "employment_status": "就業中", "desired_job": "医療事務/受付",
        "desired_employment_type": "パート・バイト",
    },
    {   # 経歴あり → AI生成（医療機関の受付経験）を想定
        "member_id": "TEST-MO-002", "age": "45歳", "gender": "女性",
        "qualifications": "医療事務", "experience_type": "医療事務/受付",
        "experience_years": "8年", "employment_status": "離職中",
        "desired_job": "医療事務/受付", "desired_employment_type": "パート・バイト",
        "work_history_summary": "整形外科クリニックで受付・会計・レセプト業務を8年担当。電子カルテ入力、患者様の案内も担当。",
        "self_pr": "子育てが落ち着いたので平日日中に働ける職場を探しています。",
    },
    {   # 再送 → パート_再送 を想定
        "member_id": "TEST-MO-003", "age": "34歳",
        "qualifications": "", "experience_type": "一般事務", "experience_years": "4年",
        "employment_status": "就業中", "desired_job": "医療事務/受付",
        "desired_employment_type": "パート・バイト",
        "scout_sent_date": "2026/09/01",
    },
]

NG_WORDS = ["4〜8時間", "社会保険完備", "寮", "引越し", "夜勤", "月給", "{ここに生成した文章を挿入}"]


def main():
    body = {
        "company_id": "nomura-hospital",
        "profiles": PROFILES,
        "options": {"send_type": "auto", "job_category_filter": "medical_office"},
    }
    resp = requests.post(
        f"{API_ROOT}/generate/batch", json=body,
        headers={"X-API-Key": API_KEY, "Content-Type": "application/json"}, timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", data if isinstance(data, list) else [])
    ok = True
    for r in results:
        problems = []
        if r.get("generation_path") == "filtered_out":
            problems.append(f"filtered_out: {r.get('filter_reason')}")
        if r.get("job_category") != "medical_office":
            problems.append(f"job_category={r.get('job_category')}")
        if r.get("job_offer_id") != "285319":
            problems.append(f"job_offer_id={r.get('job_offer_id')!r}")
        warns = r.get("validation_warnings") or []
        if any("求人未登録" in w or "テンプレート未設定" in w for w in warns):
            problems.append(f"warnings={warns}")
        text = r.get("personalized_text", "")
        hits = [w for w in NG_WORDS if w in text]
        if hits:
            problems.append(f"NG語 in personalized_text: {hits}")
        if "{ここに生成した文章を挿入}" in (r.get("full_scout_text") or ""):
            problems.append("placeholder remains in full_scout_text")
        ok &= not problems
        print(f"\n=== {r.get('member_id')} [{r.get('template_type')}] path={r.get('generation_path')} "
              f"pattern={r.get('pattern_type')} job_offer_id={r.get('job_offer_id')}")
        print(f"warnings: {warns}")
        print(f"personalized ({len(text)}字): {text}")
        print("RESULT:", "OK" if not problems else "NG -> " + " / ".join(problems))
    if not results:
        print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
        ok = False
    print("\nALL OK" if ok else "\nSOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
