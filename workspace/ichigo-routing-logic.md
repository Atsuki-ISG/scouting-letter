# 振り分けロジック設計

候補者プロフィールから `(skeleton, tone, attribute)` の3値を決定するルールテーブル。
Sheets 管理で非エンジニア編集可能にする。

## 入力

| 変数 | 型 | 説明 | ソース |
|---|---|---|---|
| nursing_years | int or null | 訪問看護経験年数 | Chrome拡張抽出 |
| total_years | int or null | 看護師としての総経験年数 | Chrome拡張抽出 |
| has_pr | bool | 自己PRの有無 | Chrome拡張抽出 |
| blank_years | int | 直近のブランク年数 | 計算（現時点 − 最終職歴終了） |
| age_group | enum or null | "20s-early", "20s-late", "30s-early", "30s-late", "40s+", null | 年齢推定 |
| special_conditions | list of str | こだわり条件 | Chrome拡張抽出 |
| employment_status | enum | "employed", "unemployed", "unknown" | Chrome拡張抽出 |
| management_keywords | bool | 「主任」「師長」「管理者」等の職歴有無 | 職歴テキストから判定 |
| big_corp_keywords | bool | 大手病院・大手チェーン名の職歴有無 | 職歴テキストから判定 |

## 出力

```
{
  "skeleton": "alpha" | "delta",
  "tone": "casual" | "compact" | "business" | "letter",
  "attribute": "nursing_inexperienced" | "nursing_junior" | "nursing_veteran" | "blank_career" | "parenting" | "general"
}
```

## ルールテーブル（初期仮説）

優先順位は上から適用。最初にマッチしたルールで確定。

| 優先 | 条件 | skeleton | tone | attribute |
|---|---|---|---|---|
| 1 | nursing_years == null AND total_years == null | alpha | casual | general |
| 2 | blank_years >= 1 | delta | letter | blank_career |
| 3 | management_keywords == true AND nursing_years >= 3 | alpha | business | nursing_veteran |
| 4 | big_corp_keywords == true AND total_years >= 5 | alpha | business | nursing_veteran |
| 5 | "高収入" in special_conditions | alpha | compact | nursing_veteran |
| 6 | nursing_years == null AND total_years >= 1 | delta | casual | nursing_inexperienced |
| 7 | nursing_years >= 3 | alpha | casual | nursing_veteran |
| 8 | 0 < nursing_years < 3 | delta | casual | nursing_junior |
| 9 | age_group in ("20s-early", "20s-late", "30s-early") AND has_pr | delta | casual | nursing_junior |
| 10 | age_group == "40s+" | alpha | casual | nursing_veteran |
| 11 | (デフォルト) | alpha | casual | general |

## エッジケース

- 年齢推定が null → 年齢ベースのルール（9, 10）はスキップ
- こだわり条件が「残業なし／土日休み」も含むなら Hプール P04/P08 優先選択（E attribute は別軸で判定）
- 複数属性に該当する場合は優先順位上のルールが勝つ
- デフォルト（ルール11）は安全側の α × casual × general

## 実装方式

- Sheets「振り分けルール」シートで管理（列: 優先順, 条件式, skeleton, tone, attribute）
- 条件式は簡易DSL（「nursing_years >= 3」「blank_years >= 1」等）
- Python側でルール評価エンジン（1本のループで上から評価、最初のマッチで return）
- ルール評価ロジックは `server/pipeline/routing.py` に新設

## 検証

1. 過去の送信データから候補者属性を逆算し、各ルールが想定通り発火するか確認
2. エッジケース候補者（年齢不明・職歴短い・ブランク長い）で期待通りの振り分けになるか確認
3. ルール変更時は Sheets 編集＋再デプロイ不要（再読み込みで反映）

## 今後の調整方針

- 初期は仮説ベース、運用2-4週間後に返信率データでルール見直し
- 特定属性セグメント内で（skeleton, tone）を A/B テストしたい場合は、ルールテーブルに「%」列を追加してランダム振り分けも可能にする
