---
name: server-admin
description: "Google Sheets（サーバ）のスカウト設定を参照・編集する。テンプレート、パターン、プロンプト、バリデーション、求人、資格修飾の表示・同期・CRUD。トリガー例: 「サーバの設定見せて」「パターンを同期」「新しい会社をサーバに登録」「求人を追加」「/server-admin」"
---

# server-admin

Google Sheets（Cloud Run admin API経由）のスカウト設定を参照・編集するスキル。
`sync-patterns` の上位互換。

## スクリプト

```bash
SCRIPT=".claude/skills/server-admin/scripts/server_admin.py"
```

## コマンド一覧

### 参照

```bash
# 全会社一覧
python3 "$SCRIPT" companies

# 会社の全シートデータを表示
python3 "$SCRIPT" show <company>

# 特定シートのみ表示
python3 "$SCRIPT" show <company> templates
python3 "$SCRIPT" show <company> patterns
python3 "$SCRIPT" show <company> prompts
python3 "$SCRIPT" show <company> validation
python3 "$SCRIPT" show <company> qualifiers
python3 "$SCRIPT" show <company> job_offers
```

### パターン同期（recipes.md ⇔ サーバ）

```bash
# 差分確認
python3 "$SCRIPT" diff <company>

# recipes.md → サーバに反映（既存会社）
python3 "$SCRIPT" sync <company> --dry-run
python3 "$SCRIPT" sync <company>

# 新規会社のパターン一括作成（recipes.mdから）
python3 "$SCRIPT" create-patterns <company>
python3 "$SCRIPT" create-patterns <company> nurse --dry-run
```

### 新規会社登録

```bash
# profile.md + templates.md → generate_company API で一括登録
python3 "$SCRIPT" init <company> --dry-run
python3 "$SCRIPT" init <company>
```

前提: `companies/<company>/` に profile.md と templates.md が存在すること。
recipes.md があれば init 後に `sync` でパターンを上書きできる。

### 行の直接操作

```bash
# 行を更新
python3 "$SCRIPT" update <sheet> <row_index> '{"field": "value", ...}'

# 行を追加
python3 "$SCRIPT" add <sheet> '{"company": "xxx", "field": "value", ...}'

# 行を削除
python3 "$SCRIPT" delete <sheet> <row_index>
```

## シート名

| slug | Google Sheets シート名 |
|------|----------------------|
| templates | テンプレート |
| patterns | パターン（非QUAL行） |
| qualifiers | パターン（QUAL行） |
| prompts | プロンプト |
| validation | バリデーション |
| job_offers | 求人 |
| logs | 生成ログ |

## 会社一覧

| 会社 | company引数 |
|------|------------|
| ARK訪問看護 | `ark-visiting-nurse` |
| LCC訪問看護 | `lcc-visiting-nurse` |
| 野村病院 | `nomura-hospital` |
| いちご訪問看護 | `ichigo-visiting-nurse` |

## ワークフロー

### 新規会社の追加

1. `companies/<company>/` に profile.md, templates.md, recipes.md を作成
2. `init <company>` でサーバに登録（テンプレート + AI生成のパターン・プロンプト等）
3. `sync <company>` でrecipes.mdのパターンをサーバに上書き
4. 管理画面でプロンプト・バリデーション・求人を微調整

### パターン修正の反映

1. recipes.md を編集
2. `diff <company>` で差分確認
3. `sync <company> --dry-run` でプレビュー
4. `sync <company>` で反映

### サーバ設定の確認

`show <company>` で全データ、`show <company> patterns` で特定シートを確認。

## 注意事項

- `--dry-run` は破壊的操作の前に必ず実行
- `init` は既存会社には実行不可（テンプレートが存在するとエラー）
- `sync` はパターン（型A〜G）のみ。テンプレート・プロンプト等は管理画面で編集
- LCC訪問看護は `## 看護師` / `## リハビリ職` / `## 医療事務` のセクション分割を自動認識
- 依存: `requests`（`pip install requests`）
