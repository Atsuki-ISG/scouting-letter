"""既存YMLの返信データを sync_replies API 経由で取り込み、
未紐付け分を「未紐付け返信_<会社>」シートに蓄積する。

旧スクリプト import_replies_from_yaml.py との違い:
- 直接 Sheets を書かず、サーバ側 sync_replies エンドポイントを叩く
- send_data に未存在の member_id は新規行追加せず、未紐付けログに保存
- send_data の正規データを汚染しない

Usage:
    python3 scripts/backfill_replies_via_api.py <company_id> [--dry-run]
    python3 scripts/backfill_replies_via_api.py ark-visiting-nurse
    python3 scripts/backfill_replies_via_api.py ark-visiting-nurse --dry-run

Prerequisites:
- companies/<company_id>/history/conversations/*.yml が存在する
- SCOUT_API_BASE / SCOUT_API_KEY 環境変数（既定: 本番URL / "anycare"）
"""
from __future__ import annotations

import os
import sys
import glob
import json
import argparse
import urllib.request
from typing import Optional

import yaml


API_BASE = os.environ.get(
    "SCOUT_API_BASE",
    "https://scout-api-1080076995871.asia-northeast1.run.app/api/v1/admin",
)
API_KEY = os.environ.get("SCOUT_API_KEY", "anycare")

POSITIVE_KW = ["ぜひ", "お話を伺", "興味", "嬉しい", "感謝", "魅力", "楽しみ"]
NEGATIVE_KW = ["申し訳", "辞退", "見送", "通勤", "今回はご縁", "難しい", "お断り"]
QUESTION_KW = ["？", "?", "教えて", "確認", "質問"]
# 誤押下: 候補者最初が「応募」ラベルだが、後続メッセージで否定する
MISCLICK_KW = ["応募ではありません", "応募ではない", "応募ではなく",
               "間違え", "誤って", "押してしまい", "押し間違", "誤押"]


def is_misclick(msgs: list) -> bool:
    """候補者最初の応募ボタン押下 + 後続候補者メッセージで否定 → 誤押下と判定"""
    cands = [m for m in msgs if m.get("role") == "candidate"]
    if len(cands) < 2:
        return False
    if cands[0].get("label") != "応募":
        return False
    for m in cands[1:]:
        text = m.get("text", "") or ""
        if any(k in text for k in MISCLICK_KW):
            return True
    return False


def classify_category(text: str) -> str:
    """候補者返信本文からカテゴリ推定（簡易）"""
    has_neg = any(k in text for k in NEGATIVE_KW)
    has_pos = any(k in text for k in POSITIVE_KW)
    has_q = any(k in text for k in QUESTION_KW)
    if has_neg and not has_pos:
        return "辞退"
    if has_q and not has_pos:
        return "質問"
    if has_pos:
        return "興味あり"
    return "保留"


def conversation_to_reply(d: dict) -> Optional[dict]:
    """YML conversation → sync_replies の reply 1件 に変換。
    変換できない場合 None。"""
    msgs = d.get("messages") or []
    if not msgs:
        return None
    first_company = next((m for m in msgs if m.get("role") == "company"), None)
    first_candidate = next((m for m in msgs if m.get("role") == "candidate"), None)
    if not first_company or not first_candidate:
        return None

    # スカウト判定: label="スカウト" または旧YMLでrole=companyが先頭
    is_scout = (
        first_company.get("label") == "スカウト"
        or msgs[0].get("role") == "company"
    )
    if not is_scout:
        return None

    # 応募判定: 候補者の最初のメッセージのlabelが"応募"
    is_application = first_candidate.get("label") == "応募"

    # 誤押下判定: 応募ボタン押下後に否定メッセージあり → カテゴリを "誤押下" にする
    misclick = is_application and is_misclick(msgs)
    if misclick:
        category = "誤押下"
    else:
        category = classify_category(first_candidate.get("text", ""))

    return {
        "member_id": str(d.get("member_id", "")).strip(),
        "replied_at": str(first_candidate.get("date", "")).strip(),
        "applied_at": str(first_candidate.get("date", "")).strip() if is_application else "",
        "category": category,
        "status": "scout_application" if is_application else "scout_reply",
        "candidate_name": d.get("candidate_name", ""),
        "candidate_age": d.get("candidate_age", ""),
        "candidate_gender": d.get("candidate_gender", ""),
        "job_title": d.get("job_title", ""),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("company_id", help="例: ark-visiting-nurse")
    parser.add_argument("--dry-run", action="store_true", help="API呼び出しせず内容のみ表示")
    args = parser.parse_args()

    convs_dir = os.path.join(
        os.path.dirname(__file__), "..", "..",
        "companies", args.company_id, "history", "conversations",
    )
    convs_dir = os.path.normpath(convs_dir)
    if not os.path.isdir(convs_dir):
        print(f"ERR: {convs_dir} が存在しません")
        sys.exit(1)

    files = sorted(glob.glob(os.path.join(convs_dir, "*.yml")))
    print(f"対象YML: {len(files)} 件 in {convs_dir}")

    replies: list[dict] = []
    for f in files:
        try:
            with open(f) as fh:
                d = yaml.safe_load(fh)
        except Exception as e:
            print(f"  SKIP {os.path.basename(f)}: parse error {e}")
            continue
        if not d:
            continue
        r = conversation_to_reply(d)
        if r is None:
            print(f"  SKIP {os.path.basename(f)}: no scout/candidate pair")
            continue
        if not r["member_id"]:
            print(f"  SKIP {os.path.basename(f)}: empty member_id")
            continue
        replies.append(r)

    print(f"変換成功: {len(replies)} 件")
    by_status = {}
    for r in replies:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    print(f"内訳: {by_status}")

    if args.dry_run:
        print("--- DRY RUN: 最初の3件 ---")
        for r in replies[:3]:
            print(json.dumps(r, ensure_ascii=False))
        return

    # 本番API呼び出し
    body = json.dumps({"company": args.company_id, "replies": replies}).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/sync_replies",
        data=body,
        headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    print(f"POST {API_BASE}/sync_replies ...")
    with urllib.request.urlopen(req, timeout=120) as r:
        result = json.load(r)

    sr = result.get("scout_reply", {})
    sa = result.get("scout_application", {})
    print(f"scout_reply:       matched={len(sr.get('matched',[]))} unmatched={len(sr.get('unmatched',[]))}")
    print(f"scout_application: matched={len(sa.get('matched',[]))} unmatched={len(sa.get('unmatched',[]))}")
    print(f"direct_application: appended={result.get('direct_application',{}).get('appended', 0)}")


if __name__ == "__main__":
    main()
