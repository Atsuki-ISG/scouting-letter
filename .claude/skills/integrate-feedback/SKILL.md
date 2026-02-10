---
name: integrate-feedback
description: 修正記録からナレッジを抽出し、スキルやドキュメントに反映
argument-hint: [会社名（省略時は全会社）]
---

# フィードバック統合スキル

修正記録（fixes）から学びを抽出し、ナレッジとスキルに反映します。

## 実行手順

1. **修正内容の記録（fixes への追記）**
   - 新規の修正がある場合、該当会社の `companies/[会社名]/history/fixes/YYYY-MM.md` に記録
   - ファイルが存在しない場合は新規作成し、月間記録としてまとめる

2. **修正記録の読み込みと学びの抽出**
   - 記録された内容、または既存の `fixes/YYYY-MM.md` から以下を抽出:
     - **問題点**: 修正前の何が問題だったか
     - **修正ポイント**: どう改善したか
     - **学び**: 今後に活かすパターン

3. **重複チェック**
   - `knowledge/learnings.md` の既存パターンと照合
   - 類似パターンがあれば統合、なければ新規追加

4. **ナレッジへの反映**
   - `knowledge/learnings.md` の「パターン別の接点例」に追加
   - 「改善履歴」セクションに日付と概要を記録

5. **generate-scoutスキルへの反映**（重要度が高い場合）
   - `.claude/skills/generate-scout/SKILL.md` の該当セクションに追加
   - 「絶対NG」「効果的」「パーソナライズの手法」など

6. **personalization.mdへの反映**（該当する場合）
   - `knowledge/personalization.md` の関連セクションを更新

7. **会社別 templates.md への反映**（会社固有の学びの場合）
   - `companies/[会社名]/templates.md` の「生成ルール」や「パーソナライズ文の作成ポイント」を更新
   - 会社固有の強みや、その会社での優先順位（例：経験豊富なら地理的要素は不要）を反映

8. **完了報告**
   - 反映した内容のサマリーを出力
   - 更新したファイル一覧を表示

## 出力フォーマット

```
## 反映完了

### 抽出した学び
- [学びの内容]

### 更新したファイル
- `knowledge/learnings.md`: [追加内容]
- `.claude/skills/generate-scout/SKILL.md`: [追加内容]（該当時のみ）
- `knowledge/personalization.md`: [追加内容]（該当時のみ）
```

## 判断基準

### generate-scoutへの反映基準

以下に該当する場合は `generate-scout/SKILL.md` にも反映:
- 「絶対NG」に追加すべき表現パターン
- 繰り返し発生する修正パターン
- パーソナライズの新しい手法

### personalization.mdへの反映基準

以下に該当する場合は `knowledge/personalization.md` にも反映:
- パーソナライズレベルの新しい例
- 「行間を読む」パターンの追加
- 「情報がない場合」の対処法の改善

## 注意事項

- 既存のパターンと重複する場合は追加せず、必要に応じて既存を更新
- 会社固有の学びは積極的に `companies/[会社名]/templates.md` へ反映し、スキル生成時の精度を高める
- 反映後は必ず差分を確認して報告
