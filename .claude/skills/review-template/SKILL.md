---
name: review-template
description: 会社別スカウトテンプレートを診断し改善版を提案する。単体レビューから、分析結果・競合調査・ナレッジ・Gemini出力癖分析を統合した総合レビューまでモードで切り替え可能
user_invocable: true
---

# review-template

スカウトテンプレートを **3段階の深さ** でレビュー・再生成するスキル。
管理画面（`server/admin/`）の「診断 → 改善提案」と同じプロンプトを使用しつつ、Claude Code 側では**全材料統合**と**Gemini プロンプト改善提案**までカバーする。

## 呼び出し方（3モード）

```
# モードA: 単体レビュー（デフォルト・軽量）
/review-template [会社名] [テンプレ種別]
/review-template [会社名] [テンプレ種別] [改善指示]

# モードB: 総合レビュー（全材料統合 + 全テンプレ再生成 + 確認事項 + プロンプト改善案）
/review-template [会社名] --full
/review-template [会社名] --full --period=30d

# モードC: Gemini プロンプト改善案のみ（クセ分析）
/review-template [会社名] --prompts-only
```

引数不足時は対話で補完。会社名は `companies/` 配下のディレクトリ名。

---

## モードA: 単体レビュー（従来機能・変更なし）

### フロー

**Phase A-1: 読み込み**
- `companies/[会社名]/templates.md` から対象テンプレート本文を抽出
- `companies/[会社名]/profile.md` 読み込み
- `companies/[会社名]/history/` に分析サマリあれば任意で参照

**Phase A-2: 診断（Stage 1）**
- `server/prompts/diagnose_scout.md` を必ず Read
- 基準に厳密に従いMarkdown形式で出力:

```markdown
## 診断結果

### 3ゲート採点
| ゲート | ランク | 根拠 |
|---|---|---|
| Gate1（開封） | A/B/C | 冒頭30-50字の評価 |
| Gate2（読了） | A/B/C | 構成・認知負荷 |
| Gate3（返信） | A/B/C | CTA評価 |

### 弱い心理原則（該当なしなら明記）
### AI臭検出（危険表現は必ず報告）
### 構成問題
### 強み（残すべき要素）
### 優先度付き改善アクション（high最大3 / medium最大2）
### 改善対象（template/prompt/recipes）
```

**Phase A-3: 改善提案（Stage 2）**
- `server/prompts/improve_template.md` を必ず Read
- 動的変数の差し替え:
  - `{company_profile}` ← profile.md 全文
  - `{analysis_data}` ← 分析サマリ or「データなし」
  - `{directive_section}` ← ユーザー改善指示
  - `{original_body}` ← 対象テンプレ本文
- 改善版全文 + `<!-- 変更理由 -->` コメント + 変更サマリ + 期待効果

**出力ルール厳守**:
1. `{ここにパーソナライズ文を挿入}` or `{personalized_text}` 保持
2. 全文出力（差分ではない）
3. 変更箇所に `<!-- 変更理由 -->` コメント
4. 未変更箇所は一字一句維持
5. 新規プレースホルダー追加禁止

**Phase A-4: 適用選択**
- a) レビューのみ
- b) templates.md 上書き
- c) Sheets 反映 → `/server-admin push [会社名]` 案内

---

## モードB: 総合レビュー（`--full`）

全材料を統合して**全テンプレを再生成**＋**確認事項リスト**＋**プロンプト改善案**を出す。
今セッションで LCC に対して手動で行った作業を自動化したもの。

### Phase B-1: 材料集め

以下を **全て並行で読み込む**:

| 材料 | ソース | 必須度 |
|---|---|---|
| 会社プロファイル | `companies/[会社名]/profile.md` | 必須 |
| 現テンプレ全種 | `companies/[会社名]/templates.md` | 必須 |
| 型はめパターン | `companies/[会社名]/recipes.md` | 必須 |
| 修正履歴 | `companies/[会社名]/history/fixes/*.md` | 任意 |
| 良い事例 | `companies/[会社名]/history/examples.md` | 任意 |
| 議事録 | `companies/[会社名]/meetings/*.md` | 任意 |
| 全社ナレッジ | `knowledge/basics.md` `learnings.md` `personalization.md` `structure.md` | 必須 |
| 業態ナレッジ | `knowledge/visiting-nurse-concerns.md`（訪看系のみ） | 業態による |
| 分析レポート | `workspace/[会社名]-*report*.md`（最新） | 任意 |
| 競合調査 | `workspace/[会社名]-*competitor*.md`（最新） | 任意 |
| ナレッジプール | Sheets `ナレッジプール` シートの `company=[会社名]` かつ `status=approved` 行 | 任意 |

**材料不足時の扱い**:
- 分析レポートなし → 「`/analyze-replies [会社名]` を実行して分析データを作りますか？(y/n)」
- 競合調査なし → 「`/research-competitors [会社名]` を実行して競合データを作りますか？(y/n)」
- ナレッジプール pending 行あり → 「管理画面で承認してから進めますか？それとも pending を無視して続けますか？」
- ユーザーが `n` なら既存材料のみで続行

### Phase B-2: 統合診断

1. **全テンプレ一括診断**: `templates.md` 内の各テンプレ（職種×雇用形態×初回/再送/お気に入り）を `diagnose_scout.md` 基準で診断
2. **セグメント別弱点**: 分析レポートから「返信率が特に低い地域/年齢層/テンプレ種別」を特定
3. **差別化要素カバレッジ**: profile.md の差別化要素セクションを読み、各テンプレが武器をどれだけ活用しているかチェック
   - 武器ごとに「言及あり／なし／弱く言及」の3段階評価

### Phase B-3: ポジショニング再定義

1. 競合調査から LCC/当該会社固有の武器を抽出
2. ナレッジプールの approved フックを取得（`GET /admin/knowledge_pool?company=[会社名]&status=approved`）
3. 業態ナレッジ（例: `visiting-nurse-concerns.md` の7項目）と突合
4. **「どの武器を どのテンプレで どう打つか」**のマトリクスを作成

### Phase B-4: 確認事項リスト生成 ⭐

profile.md になくテンプレに書きたい情報を抽出。優先度順に整理して保存。

**優先度基準**:
- **優先度1**: 訪看最大不安（オンコール詳細、OJT 1ヶ月後のプロセス等）
- **優先度2**: 差別化要素の具体化（院内サテライトの連携実態、教育ST指定の恩恵等）
- **優先度3**: スカウト内で使える具体エピソード（before/after 数字、ケース構成比率等）

**保存先**:
- `companies/[会社名]/meetings/YYYY-MM-DD-info-gaps.md`
- 雛形参照: `companies/lcc-visiting-nurse/meetings/2026-04-17-info-gaps.md`（今セッションで手動作成した例）

### Phase B-5: Gemini 出力クセ分析

`workspace/` に**既存の Gemini 出力物**があれば、元データと対比して**サーバ側プロンプトのクセ**を検出。

**比較の対象**:
- 元テンプレ（profile.md で宣伝すべき要素が明確） vs 改善後テンプレ（Gemini 出力）
- 競合調査結果（ナレッジプール pending） vs 改善テンプレでの活用状況

**検出するクセのパターン**（要拡張可能）:
1. **実在スタッフの声削除**: 元テンプレにあった「〜できるようになった」等の社会的証明が消えている
2. **固有ファクトの一般語化**: 「東京都訪問看護教育ステーション指定」→「研修充実」へダウングレード
3. **固有名詞の削除**: 施設名・制度名・認定名の固有性が失われている
4. **差別化要素の見落とし**: profile.md にある武器が出力で全く言及されない
5. **AI臭表現の混入**: 「お持ちとのこと」「大変魅力的に」等（`diagnose_scout.md` の危険表現リスト参照）
6. **候補者評価の省略**: パーソナライズ文の前後が会社紹介で埋まり、候補者評価が薄い

**出力形式**（`05-prompt-fixes.md`）:
```markdown
# Gemini プロンプト改善提案

## 対象プロンプト: server/prompts/improve_template.md

### クセ1: 実在スタッフの声を削除する傾向
- 検出サンプル: [会社名]の[テンプレ種別]改善で、元テンプレの声3つ全てが削除された
- 影響: 社会的証明の核を失い、返信率に直結する要素が抜ける
- 追記案（プロンプト本体への追加）:

> ### 原則⑥ 元テンプレの強い要素は温存する
> 元テンプレートに「実在スタッフの声」「具体エピソード」「数字付き証明」が含まれる場合、
> それらは社会的証明の核として優先して残すこと。全面書き換え時にも温存する。
> 削除は、元の要素を明確に上回る代替（別のスタッフ声、別の数値証明等）を用意できる場合のみ許可する。

### クセ2: 東京都指定 → 「研修充実」ダウングレード
- 検出サンプル: 固有認定「東京都訪問看護教育ステーション指定」が「制度化された教育体制」等の一般語に置換される
- 追記案:

> ### 原則⑦ 固有名詞・公的認定は原文のまま使う
> 「東京都◯◯指定」「厚生労働省◯◯事業」「◯◯認定看護師」等の固有の認定・指定は、
> テンプレ生成時に必ず原文のまま使用する。一般語（「研修充実」「専門性重視」等）に
> 置き換えてはならない。固有名詞は権威・希少性の証拠として機能する。

## 対象プロンプト: server/prompts/diagnose_scout.md

### クセX: [...]
```

**対象プロンプトファイル**（クセが検出された順に提案を整理）:
- `server/prompts/improve_template.md` — 最も出力されるため最優先
- `server/prompts/diagnose_scout.md` — 診断側の見落とし
- `server/prompts/customer_report.md` — レポート側（抽象化されがち）
- `server/api/routes_admin.py` 内の競合調査ハードコードプロンプト（L6005付近）

### Phase B-6: 全テンプレ再生成

1. `improve_template.md` の原則 + 差別化要素マトリクス + 温存すべき要素リストを合成
2. 職種×雇用形態×初回/再送/お気に入りの**全テンプレ**を一貫したポジショニングで再生成
3. 情報ギャップは `○○` / `△△` / `□□` の仮置きで出力（Phase B-4 の確認事項と対応）
4. 各テンプレの変更理由を `<!-- -->` コメントで明示

### Phase B-7: 成果物まとめ＋適用選択

`workspace/[会社名]-review-YYYY-MM-DD/` 配下に以下を保存:

```
workspace/[会社名]-review-YYYY-MM-DD/
├── 00-summary.md         # 全体サマリ: 診断の結論 + 優先アクション
├── 01-positioning.md     # 差別化ポジション整理（武器×ターゲット層マトリクス）
├── 02-info-gaps.md       # 確認事項（meetings/ にもコピー）
├── 03-diagnoses/         # 各テンプレ診断
│   ├── nurse-seishain-first.md
│   ├── nurse-part-first.md
│   └── ...
├── 04-templates/         # 再生成テンプレ全文
│   ├── nurse-seishain-first.md
│   └── ...
├── 05-prompt-fixes.md    # Gemini プロンプト改善提案
└── 06-action-plan.md     # 次サイクル提案（送信戦略・KPI・PM依頼）
```

**適用選択**:
```
次のアクションを選んでください:
a) レビューのみ（このまま終了）
b) companies/[会社名]/templates.md に再生成テンプレを反映
c) companies/[会社名]/profile.md に差別化要素セクションを追加/更新
d) Sheets に push — /server-admin push [会社名] 案内
e) 確認事項（02-info-gaps.md）を PM 宛メール/Slack 文面に変換
f) server/prompts/*.md にプロンプト改善案を反映
g) 全部（b + c + d + e + f）
```

---

## モードC: プロンプト改善のみ（`--prompts-only`）

モードB の Phase B-1 〜 B-5 のみ実行。テンプレ再生成（B-6）と成果物フル保存（B-7）はスキップ。

**使う場面**: 「サーバの Gemini 出力に違和感がある。何がおかしいのか、プロンプトの何を直すべきか知りたい」

**出力**: `workspace/[会社名]-prompt-fixes-YYYY-MM-DD.md` 1ファイル。Phase B-5 の結果のみ。

---

## 使用するファイル一覧

### 読み取り対象（入力）

| 種類 | パス |
|---|---|
| 会社資産 | `companies/[会社名]/profile.md`, `templates.md`, `recipes.md`, `history/`, `meetings/` |
| 全社ナレッジ | `knowledge/*.md` |
| workspace 既存物 | `workspace/[会社名]-*.md`（レポート・競合調査） |
| Gemini プロンプト | `server/prompts/diagnose_scout.md`, `improve_template.md`, `customer_report.md` |
| サーバ内ハードコード prompt | `server/api/routes_admin.py`（L6005 付近の競合調査プロンプト） |
| Sheets 経由 | `ナレッジプール`, `送信データ`, `改善提案` シート |

### 書き込み対象（出力）

| 種類 | パス |
|---|---|
| 確認事項 | `companies/[会社名]/meetings/YYYY-MM-DD-info-gaps.md` |
| 総合レビュー成果物 | `workspace/[会社名]-review-YYYY-MM-DD/` 配下 |
| プロンプト改善案のみ | `workspace/[会社名]-prompt-fixes-YYYY-MM-DD.md` |
| 適用時 | `companies/[会社名]/templates.md`, `profile.md`（選択時のみ） |
| プロンプト反映時 | `server/prompts/*.md`（選択時のみ） |

---

## 原則との整合

- **管理画面と同じプロンプトを使う**: `server/prompts/` を直接 Read、複製しない
- **Markdown 出力**: admin UI の JSON とは別に、人が読む前提で構造化
- **後方互換性**: モードA（引数2つまで）は従来動作。`--full` `--prompts-only` フラグ時のみ新機能
- **会社別にファイルを閉じる**: 他社情報の混入を構造的に防止
- **テンプレ本文のみ編集**: templates.md 前半の「行動指針」「生成ルール」には触れない
- **憶測で書かない**: profile.md にない情報は `○○` 仮置きで確認事項に切り出す

---

## Gemini クセの継続改善サイクル

モードB/Cを繰り返すことで、サーバ側 Gemini プロンプトが継続改善される:

1. 管理画面で `improve_template` を実行
2. 出力が `workspace/` に残る or テンプレートに反映される
3. `/review-template [会社名] --prompts-only` でクセを検出
4. 改善案を `server/prompts/improve_template.md` に反映
5. 次回の Gemini 出力の質が上がる
6. 繰り返す

このサイクルが回ることで、**管理画面の AI 生成結果が複利的に賢くなる**。

---

## 関連スキル

| スキル | 関係 |
|---|---|
| `/analyze-replies` | モードB Phase 1 で材料補完が必要な時に呼び出し |
| `/research-competitors` | モードB Phase 1 で材料補完が必要な時に呼び出し |
| `/integrate-feedback` | 個別スカウト文の修正結果から recipes.md / templates.md / learnings.md を更新 |
| `/save-example` | 良い事例を会社別 examples.md に蓄積（モードB で参照する入力） |
| `/server-admin` | Sheets 反映時に案内 |

独立: `/generate-scout`, `/csv-scout`, `/add-company`
