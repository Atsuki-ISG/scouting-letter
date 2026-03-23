# スカウト文生成・送信システム

## 思想

「送るだけで賢くなるスカウトマシン」を作る。

- **複利構造**: 生成→送信→返信分析→ナレッジ蓄積のループが回るたびに、スカウト文の質が上がる
- **人間はジャッジだけ**: AIが抽出・生成・分析を全部やる。人間は「OK/NG」の判断と送信ボタンだけ
- **小さい部品の組み合わせ**: 独立したスキルとパイプラインの組み合わせで動く。どこからでも始められ、どこでも止められる
- **痛みから育てる**: 最初から完璧を目指さない。使って不便を感じたら改善する

## 基本情報

- プラットフォーム: ジョブメドレー（介護・医療系求人）
- 対象: 求職者へのスカウト文の生成・改善・送信
- 利用者: オペレーター6名+、管理者3名（非エンジニア含む）

## 対象会社

| 会社名 | ディレクトリ | 備考 |
|--------|-------------|------|
| ARK訪問看護 | `companies/ark-visiting-nurse/` | |
| LCC訪問看護 | `companies/lcc-visiting-nurse/` | |
| いちご訪問看護 | `companies/ichigo-visiting-nurse/` | 3施設（介護NS/リハビリST/富士見台サテライト） |
| いちごの里 | `companies/ichigo-care-home/` | 有料老人ホーム。profile.mdのみ |

## 回答スタイル

- 日本語で応答
- 挨拶・前置き・段階報告禁止。結論ファースト
- 指摘すべきことは率直に指摘する

## 構成

### リポジトリ内（git管理）

| ディレクトリ | 役割 |
|---|---|
| `companies/[会社名]/` | 会社別資産（profile.md, templates.md, recipes.md, history/） |
| `knowledge/` | 全社共通ナレッジ（learnings.md, basics.md等） |
| `extension/` | Chrome拡張（プロフィール抽出・送信アシスト・API連携） |
| `server/` | Cloud Run API（スカウト文生成パイプライン・管理画面） |
| `test/` | プロンプトテスト・ダミーデータ |
| `.claude/skills/` | Claude Codeスキル（generate-scout, csv-scout, analyze-replies等） |
| `.claude/rules/` | ワークフロー・運用方針 |

### リポジトリ外（Claude Code自動管理・git対象外）

| ディレクトリ | 役割 |
|---|---|
| `~/.claude/projects/.../memory/` | 会話を跨ぐ永続メモリ。MEMORY.mdがインデックス |

## ファイル依存関係

各スキルが読むファイル:

| スキル | 読むファイル |
|--------|-------------|
| generate-scout | templates.md, learnings.md |
| csv-scout | **recipes.md**（最重要）, templates.md, examples.md |
| integrate-feedback | recipes.md → learnings.md → templates.md → SKILL.md（優先順） |
| analyze-replies | history/{conversations,replies}/*.yml |

csv-scout は learnings.md を読まない（recipes.md に必要な知見は反映済み）。

## 会社追加

`/add-company` スキルで一連の手順をガイド。手動で行う場合は以下:

1. `companies/[会社名]/` に profile.md, templates.md, recipes.md を作成
2. `/server-admin init [会社名]` → `/server-admin sync [会社名]` でサーバー登録
3. 求人は `/server-admin add job_offers` で個別追加

## Plan Mode

- プランファイルには意図（なぜ必要か）と選択理由を含めること

## サーバー構成（`server/`）

Cloud Run上のFastAPI。スカウト文生成API + 管理画面。

| コンポーネント | 役割 |
|---|---|
| `pipeline/` | 生成パイプライン（フィルタ→テンプレート判定→型はめ/AI生成→テキスト組み立て） |
| `db/sheets_client.py` | Google Sheetsからの設定読み込み（メモリキャッシュ） |
| `db/sheets_writer.py` | Google Sheetsへの書き込み（管理画面用） |
| `admin/index.html` | 管理画面SPA（テンプレート・パターン・求人等のCRUD） |
| `api/` | APIルート（生成・会社設定・管理CRUD） |

データソース: Google スプレッドシート（6シート: テンプレート、パターン、資格修飾、プロンプト、求人、バリデーション）

## Chrome拡張（`extension/`）

ジョブメドレーのスカウト画面上で動作。プロフィール抽出→API生成→連続送信の一連のフローをブラウザ上で完結させる。
会社・求人・設定はAPI経由で動的取得するため、新会社追加時に拡張のコード変更は不要。

- 実装詳細 → `memory/MEMORY.md`（Chrome拡張セクション）
- ビルド → `npm run build`（`extension/` 配下）

## 管理画面（`server/admin/`）

Cloud Run上のSPA。非エンジニアの管理者がブラウザからテンプレート・パターン・プロンプト・求人等のスカウト設定を編集できる。

- 実装詳細 → `memory/flow-admin-ui.md`

## Tips

- MD→PDF変換 → Chrome headlessを使う。`md-to-pdf`はハングする。詳細は `memory/feedback_md_to_pdf.md`

## 参照先

- スキルの使い方・運用フロー → `.claude/rules/workflow.md`
- 各スキルの詳細 → `.claude/skills/[name]/SKILL.md`
- デプロイ手順 → `server/DEPLOY.md`
- API化の実装計画 → `api-scout-generation-plan.md`
