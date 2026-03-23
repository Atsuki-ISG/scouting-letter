---
name: sync-patterns
description: "recipes.mdの型はめパターンをサーバ（Google Sheets）に反映・参照する。recipes.mdを編集した後のサーバ同期、サーバ上のパターン確認、ローカルとサーバの差分確認に使用。トリガー例: 「パターンを反映して」「サーバのパターン見せて」「recipes.mdの変更をサーバに同期」「/sync-patterns」"
---

# sync-patterns

recipes.md（ローカル）⇔ サーバ（Google Sheets）間のパターン同期・参照。

## コマンド

```bash
SCRIPT=".claude/skills/sync-patterns/scripts/sync_patterns.py"

# サーバの現在値を表示
python3 "$SCRIPT" show <company>

# ローカルとサーバの差分を表示
python3 "$SCRIPT" diff <company>

# recipes.md → サーバに反映（既存会社）
python3 "$SCRIPT" sync <company> [--dry-run]

# 新規会社のパターンを一括作成
python3 "$SCRIPT" create <company> [job_category] [--dry-run]
```

## 会社名

| 会社 | company引数 |
|------|------------|
| ARK訪問看護 | `ark-visiting-nurse` |
| LCC訪問看護 | `lcc-visiting-nurse` |
| 野村病院 | `nomura-hospital` |

## ワークフロー

### パターン文の修正を反映

1. `diff` で差分確認
2. `sync --dry-run` でプレビュー
3. `sync` で実行

### 新規会社の初回登録

1. `companies/<company>/recipes.md` を作成済みであること
2. サーバに会社が登録済みであること（管理画面 or init_company API）
3. `create <company> --dry-run` でプレビュー
4. `create <company>` で実行

### サーバの現在値を確認

`show <company>` でパターン一覧・テキスト・特色バリエーションを表示。

## 注意事項

- LCC訪問看護は `## 看護師` / `## リハビリ職` / `## 医療事務` のセクション分割を自動認識
- `--dry-run` は必ず先に実行して差分を確認すること
- `create` は既存パターンがある会社には実行不可（`sync` を使う）
- 依存: `requests`（`pip install requests`）
