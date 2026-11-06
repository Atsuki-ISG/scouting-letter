#!/usr/bin/env python3
"""野村病院 作業療法士（正社員）の生成をサーバで実際に試す（push_server.py 実行後の確認用）。

ダミー候補者3名を /api/v1/generate/batch に送り、次を確認する。
  - job_category が rehab_ot、generation_path が filtered_out でない
  - 経験7年×40代の型はめが型Aではなく型B1になる（「10年以上」と誤記しない）
  - full_scout_text にプレースホルダ {ここに生成した文章を挿入} が残っていない
  - job_offer_id が 1759407（求人登録が効いている）
  - 「[求人未登録]」「[テンプレート未設定]」の警告が出ていない
  - パーソナライズ文に禁止語（寮 / お祝い金 / 引越し / 夜勤 / 同行訪問 / 時給）がない

Usage (リポジトリルートで実行):
  python3 workspace/nomura-ot/verify_generate.py

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
JOB_OFFER_ID = "1759407"

PROFILES = [
    {   # 経歴なし・40代×経験7年 → 型はめ（型B1）を想定。型Aの「10年以上」が出たら誤り
        "member_id": "TEST-OT-001", "age": "46歳", "gender": "女性",
        "qualifications": "作業療法士", "experience_type": "作業療法士", "experience_years": "7年",
        "employment_status": "就業中", "desired_job": "作業療法士",
        "desired_employment_type": "正職員",
    },
    {   # 経歴あり → AI生成（精神科デイケア）を想定
        "member_id": "TEST-OT-002", "age": "38歳", "gender": "男性",
        "qualifications": "作業療法士", "experience_type": "作業療法士",
        "experience_years": "9年", "employment_status": "就業中",
        "desired_job": "作業療法士", "desired_employment_type": "正職員",
        "work_history_summary": "回復期リハビリ病院で5年、その後精神科デイケアで4年勤務。集団プログラムの企画運営、退院後の生活支援、多職種カンファレンスを担当。",
        "self_pr": "患者様が地域で自分らしく暮らせるよう支援することにやりがいを感じています。",
    },
    {   # 再送・パート希望 → 正社員_再送 へのフォールバック（警告つき）を想定
        "member_id": "TEST-OT-003", "age": "29歳",
        "qualifications": "作業療法士", "experience_type": "作業療法士", "experience_years": "2年",
        "employment_status": "離職中", "desired_job": "作業療法士",
        "desired_employment_type": "パート・バイト",
        "scout_sent_date": "2026/10/01",
    },
]

NG_WORDS = ["寮", "お祝い金", "引越し", "夜勤", "同行訪問", "時給", "{ここに生成した文章を挿入}"]


def main():
    body = {
        "company_id": "nomura-hospital",
        "profiles": PROFILES,
        "options": {"send_type": "auto", "job_category_filter": "rehab_ot"},
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
        if r.get("job_category") != "rehab_ot":
            problems.append(f"job_category={r.get('job_category')}")
        if r.get("job_offer_id") != JOB_OFFER_ID:
            problems.append(f"job_offer_id={r.get('job_offer_id')!r}")
        if not str(r.get("template_type", "")).startswith("正社員_"):
            problems.append(f"template_type={r.get('template_type')}")
        warns = r.get("validation_warnings") or []
        if any("求人未登録" in w or "テンプレート未設定" in w for w in warns):
            problems.append(f"warnings={warns}")
        text = r.get("personalized_text", "")
        hits = [w for w in NG_WORDS if w in text]
        if hits:
            problems.append(f"NG語 in personalized_text: {hits}")
        if r.get("member_id") == "TEST-OT-001" and "10年以上" in text:
            problems.append("経験7年に「10年以上」が出ている（型Aの誤適用）")
        full = r.get("full_scout_text") or ""
        if "{ここに生成した文章を挿入}" in full:
            problems.append("placeholder remains in full_scout_text")
        if "作業療法士 (正社員) - 面談確約 -" not in full:
            problems.append("full_scout_text が作業療法士テンプレになっていない")
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
