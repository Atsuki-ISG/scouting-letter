# 運用フロー

## ディレクター業務

### 品質管理

1. オペレーターが送信したスカウト文をサンプルレビュー
2. `quality/criteria.md` の基準に照らしてチェック
3. `quality/scoring.md` のランクで評価（S/A/B/C/D）
4. レビュー結果を `quality/reviews/YYYY-MM/` に記録
5. 共通の問題パターンがあれば `/integrate-feedback` でナレッジに反映
6. S判定のスカウト文は `/save-example` で蓄積

### テンプレート改善

1. `/review-template [会社名] [テンプレート種別]` でテンプレートを診断し改善版を生成
   - `server/prompts/diagnose_scout.md` の基準で3ゲート・心理原則・AI臭・構成を診断
   - `server/prompts/improve_template.md` の原則で改善版全文を出力
2. 出力を確認し、必要なら `companies/[会社名]/templates.md` に反映
3. サーバにも反映する場合は `/server-admin push [会社名]`
4. 管理画面の「診断 → 改善提案」フローと同じプロンプトを使用しているため、ブラウザ経由でもCLI経由でも結果は同等

### ミーティング → 改善反映

1. オペレーターや PM とのミーティングを実施
2. 議事録を `companies/[会社名]/meetings/` に保存
3. アクションアイテムを抽出し反映先を判断:
   - 品質基準の変更 → `quality/criteria.md`
   - テンプレート・パターンの改善 → `companies/[会社名]/templates.md` or `recipes.md`
   - 教育資料の更新 → `training/`

### 教育・オンボーディング

- オペレーター教育資料: `training/`
- 良いスカウト事例: `training/good-examples/`
- スカウトの基礎: `training/scout-fundamentals/`

### 作業スペース

- 調査・分析の一時ファイル: `workspace/`
- 確定したら適切なディレクトリ（quality/, companies/, training/等）に移動

---

# スキルの使い方・運用フロー（オペレーター向け）

## API生成（Chrome拡張から直接）— メインフロー

Chrome拡張のサイドパネルからCloud Run APIを呼び出し、スカウト文を一括生成する。
オペレーターの標準ワークフロー。

### フロー

1. Chrome拡張で候補者プロフィールを抽出（抽出タブ）
2. 「API生成」タブで一括生成ボタンを押す
3. Cloud Run API がプロフィールを受け取り、パーソナライズ文を生成
   - 経歴あり → Gemini Pro による AI生成
   - 経歴なし → 型はめパターンで機械的に生成
4. 生成結果が送信タブに自動セット → そのまま連続送信

### 設定

- APIエンドポイント / APIキーはポップアップ設定画面で入力
- 会社選択で自動的に対応する求人・テンプレート・バリデーション設定を取得

### エンドポイント

| メソッド | パス | 用途 |
|---------|------|------|
| POST | `/api/v1/generate` | 単一候補者生成 |
| POST | `/api/v1/generate/batch` | 一括生成（内部で10並列） |
| GET | `/api/v1/companies/{id}/config` | 会社設定一括取得 |

---

## Claude Codeスキル — 開発・検証・ナレッジ改善用

API化後も以下の用途で維持する:
- テンプレート・プロンプトの改善サイクル（`/integrate-feedback`, `/analyze-replies`）
- API障害時のフォールバック生成（`/csv-scout`）
- 新会社・新職種のセットアップ検証

### 単体生成（スクリーンショットから1名ずつ）

1. 求職者のプロフィールスクリーンショットを用意
2. スクリーンショットを貼り付け
3. `/generate-scout [会社名]` を実行
4. 完成したスカウト文がクリップボードにコピーされる

例:
```
/generate-scout ark-visiting-nurse
```

### バッチ生成（CSVから一括）

Chrome拡張で抽出したプロフィールCSVから一括でスカウト文を生成:
```
/csv-scout [会社名] [CSVパス]
/csv-scout ark-visiting-nurse /Users/aki/Downloads/profiles.csv
```

- 元CSVに `template_type`, `personalized_text`, `full_scout_text` 列を追加して上書き
- Chrome拡張の「送信アシスト」→「CSVインポート」でそのまま読み込み可能
- オプション: `resend`（再送）、`seishain`（正社員テンプレート強制）

### 返信分析

蓄積されたやりとりデータを分析し、スカウト改善のナレッジを抽出:
```
/analyze-replies [会社名]
```

分析内容:
- 返信率・テンプレート別効果
- パーソナライズ文の傾向分析
- 求職者の返信パターン分類
- 改善提案の生成

### 良い例の保存

特に出来の良いパーソナライズ文を蓄積:
```
/save-example [会社名] [タイトル] [本文]
```
保存先: `companies/[会社名]/history/examples.md`

### 修正の反映

#### Claude Code内で生成した場合

スカウト文を修正した後、以下のコマンドを実行してナレッジを同期:
```
/integrate-feedback [会社名] [会員番号] [修正理由] [修正前後]
```

自動反映先:
- `history/fixes/YYYY-MM.md` （会社別の月次履歴）
- `knowledge/learnings.md` （全社共通ナレッジ）
- `companies/[会社名]/templates.md` （会社別生成ルール）
- `.claude/skills/generate-scout/SKILL.md` （生成スキル）

#### 一般のAIチャット（ChatGPT、Claude.aiなど）で生成した場合

1. AIが出力した「📝 learnings.md追加用（コピペ用）」セクションをコピー
2. Claude Codeで `/add-learning` を実行
3. コピーした内容を貼り付け → `knowledge/learnings.md` の「改善履歴」セクションに自動追加

### Chrome拡張の配布

オペレーターへ拡張を配布する際は `shared/` ディレクトリにzipを作成する。

**ビルド & zip作成手順:**
```bash
cd extension && npm run build
cd ..
zip -r shared/scout-extension-$(date +%Y%m%d).zip scout_extension/ -x "*.map"
# ※ cd extension 後に zip を作るとファイル名は scout-extension-YYYYMMDD.zip で shared/ に出力
```

- `npm run build` で `extension/scout_extension/` を生成
- **zipには `scout_extension/` ディレクトリを含めること**（中のファイルだけでなくディレクトリごと）
- ファイル名は `scout-extension-YYYYMMDD.zip`（日付で世代管理）
- `shared/` に配置してオペレーターに共有
- 古いzipは削除して最新のみ残す（git履歴で辿れる）

**オペレーターへの連絡項目:**
- 配布時は [shared/Chrome拡張_インストールガイド.pdf](../../shared/Chrome拡張_インストールガイド.pdf) の「更新手順」を案内
- UIや操作に変更がある場合は [shared/Chrome拡張_取扱説明書.pdf](../../shared/Chrome拡張_取扱説明書.pdf) も更新して再配布
- 破壊的変更（必須項目の追加等）はSlack/メールで別途周知

### 継続改善サイクル

1. **修正の実行**: 提示されたスカウト文を修正
2. **同期**: `/integrate-feedback [会社名] [会員番号] [修正理由] [修正前後]`
3. **良い例の蓄積**: `/save-example [会社名] [タイトル] [本文]`
