# スカウト文生成ナレッジベース

## 言語
日本語で応答すること。

## 回答スタイル
- 挨拶・前置き・段階報告禁止。結論ファースト。
- 指摘すべきことは率直に指摘する。

## WHAT / WHY
ジョブメドレー（介護・医療系）の求職者に送るスカウト文を、生成・改善・送信するシステム。
Chrome拡張でプロフィール抽出 → AI生成 → 送信アシストまでの一連フローを支援する。

## 対象会社
| 会社名 | ディレクトリ |
|--------|-------------|
| ARK訪問看護 | `companies/ark-visiting-nurse/` |
| LCC訪問看護 | `companies/lcc-visiting-nurse/` |

## HOW - ファイル依存関係

各スキルが読むファイル:

| スキル | 読むファイル |
|--------|-------------|
| generate-scout | templates.md, learnings.md |
| csv-scout | **recipes.md**（最重要）, templates.md, examples.md |
| integrate-feedback | recipes.md → learnings.md → templates.md → SKILL.md（優先順） |
| analyze-replies | history/{conversations,replies}/*.yml |

csv-scout は learnings.md を読まない（recipes.md に必要な知見は反映済み）。

## HOW - 会社追加

`companies/[会社名]/` に以下を作成:
1. `profile.md` - 会社情報
2. `templates.md` - テンプレート + フィルタリングルール
3. `recipes.md` - 型はめパターン + AI生成ガイド（csv-scout用）

## HOW - Plan Mode
- プランファイルには意図（なぜ必要か）と選択理由を含めること。

## 参照先
- スキルの使い方・運用フロー → `.claude/rules/workflow.md`
- 各スキルの詳細 → `.claude/skills/[name]/SKILL.md`
