# スキルの使い方・運用フロー

## 単体生成（スクリーンショットから1名ずつ）

1. 求職者のプロフィールスクリーンショットを用意
2. スクリーンショットを貼り付け
3. `/generate-scout [会社名]` を実行
4. 完成したスカウト文がクリップボードにコピーされる

例:
```
/generate-scout ark-visiting-nurse
```

## バッチ生成（CSVから一括）

Chrome拡張で抽出したプロフィールCSVから一括でスカウト文を生成:
```
/csv-scout [会社名] [CSVパス]
/csv-scout ark-visiting-nurse /Users/aki/Downloads/profiles.csv
```

- 元CSVに `template_type`, `personalized_text`, `full_scout_text` 列を追加して上書き
- Chrome拡張の「送信アシスト」→「CSVインポート」でそのまま読み込み可能
- オプション: `resend`（再送）、`seishain`（正社員テンプレート強制）

## 返信分析

蓄積されたやりとりデータを分析し、スカウト改善のナレッジを抽出:
```
/analyze-replies [会社名]
```

分析内容:
- 返信率・テンプレート別効果
- パーソナライズ文の傾向分析
- 求職者の返信パターン分類
- 改善提案の生成

## 良い例の保存

特に出来の良いパーソナライズ文を蓄積:
```
/save-example [会社名] [タイトル] [本文]
```
保存先: `companies/[会社名]/history/examples.md`

## 修正の反映

### Claude Code内で生成した場合

スカウト文を修正した後、以下のコマンドを実行してナレッジを同期:
```
/integrate-feedback [会社名] [会員番号] [修正理由] [修正前後]
```

自動反映先:
- `history/fixes/YYYY-MM.md` （会社別の月次履歴）
- `knowledge/learnings.md` （全社共通ナレッジ）
- `companies/[会社名]/templates.md` （会社別生成ルール）
- `.claude/skills/generate-scout/SKILL.md` （生成スキル）

### 一般のAIチャット（ChatGPT、Claude.aiなど）で生成した場合

1. AIが出力した「📝 learnings.md追加用（コピペ用）」セクションをコピー
2. Claude Codeで `/add-learning` を実行
3. コピーした内容を貼り付け → `knowledge/learnings.md` の「改善履歴」セクションに自動追加

## 継続改善サイクル

1. **修正の実行**: 提示されたスカウト文を修正
2. **同期**: `/integrate-feedback [会社名] [会員番号] [修正理由] [修正前後]`
3. **良い例の蓄積**: `/save-example [会社名] [タイトル] [本文]`
