# スカウト文パーソナライズ拡張 設計ドキュメント

**作成日**: 2026-04-23〜2026-04-24
**対象**: ジョブメドレー向け採用代行スカウト文生成システム
**執筆**: Claude Opus 4.7

---

## 目次

1. [概要・目的](#1-概要目的)
2. [背景と現状分析](#2-背景と現状分析)
3. [設計の全体像](#3-設計の全体像)
4. [骨格設計 Option α / δ](#4-骨格設計-option-α--δ)
5. [トーンシステム](#5-トーンシステム)
6. [H ブロック（ヘッダー）プール](#6-h-ブロックヘッダープール)
7. [振り分けロジック](#7-振り分けロジック)
8. [ブロック別プロンプト設計](#8-ブロック別プロンプト設計)
9. [Sheets スキーマ追加](#9-sheets-スキーマ追加)
10. [実装状況](#10-実装状況)
11. [運用フロー（Phase 計画）](#11-運用フローphase-計画)
12. [残課題・Open Questions](#12-残課題open-questions)
13. [参照ファイル一覧](#13-参照ファイル一覧)

---

## 1. 概要・目的

### ゴール

**スカウト文の「募集要項より前の部分」を候補者ごとにAI生成にする**。現状は 100-180字のパーソナライズ文だけがAI生成で、それ以外（タイトル・挨拶・橋渡し・会社理念）は固定テンプレート。この固定部分を候補者ごとに書き分けることで、テンプレ臭を排し返信率を上げる。

### 達成手段

| 層 | 仕組み |
|---|---|
| 骨格 | Option α（5ブロック・ヘッダーあり）と Option δ（4ブロック・本文冒頭融合）を候補者属性で使い分け |
| トーン | カジュアル／コンパクト／ビジネス／お手紙 の4種を候補者属性で切替 |
| ヘッダー | こだわり条件マッピングで訴求軸をプールから型はめ選択 |
| 振り分け | Sheets管理のルールテーブルで (skeleton, tone, attribute) を決定 |

### 設計原則

1. **複利構造**: 生成→送信→返信分析→ナレッジ蓄積のループが回るたびに質が上がる
2. **人間はジャッジのみ**: AIが抽出・生成を全部やり、人間は OK/NG 判断と送信ボタンだけ
3. **非エンジニアが編集可能**: Sheets 管理で PM・ディレクターが運用中に調整できる
4. **既存資産の最大活用**: personalized_scout パイプラインが既に稼働しており、それをベースに拡張

---

## 2. 背景と現状分析

### 現状のスカウト構造（いちご看護師正社員の例）

| # | ブロック | 現状 | 行 |
|---|---|---|---|
| ① | 🌸絵文字タイトル（求人条件訴求ヘッダー） | 固定 | [templates.md:60](../companies/ichigo-visiting-nurse/templates.md) |
| ② | 「はじめまして！〜と申します」挨拶 | 固定 | :62 |
| ③ | 「ご経歴を拝見し〜ご連絡いたしました」橋渡し | 固定 | :64 |
| ④ | **パーソナライズ文**（`{ここに生成した文章を挿入}`） | AI or 型はめ | :66 |
| ⑤ | 「今までのご経験は〜慣れていただけます」会社理念 | 固定 | :68 |
| ⑥ | ＜募集要項概要＞以下 | 固定 | :70〜 |

**目標**: ①〜⑤を候補者ごとに書き分ける、⑥以降はテンプレ固定のまま。

### ジョブメドレーのプレビュー仕様（実機確認済）

| デバイス | 見える本文冒頭 | 事業所名 |
|---|---|---|
| モバイル | 約50字（2行でtruncate） | 自動表示（緑・大） |
| PC | 約90字（3行でtruncate） | 自動表示 |

この制約が **骨格選択の根拠** になる。

### 既存 personalized_scout パイプライン

`server/pipeline/personalized_scout/` が既に L2/L3 として稼働中。ブロック名は：

| 既存ブロック | 役割 | 字数 |
|---|---|---|
| `opening` | 候補者固有導入 | 80-150字 |
| `bridge` | 経歴→求人への橋渡し | 120-200字 |
| `facility_intro` | 会社・施設紹介 | 150-250字 |
| `job_framing` | 求人フレーミング | 100-180字 |
| `closing_cta` | 行動喚起 | 80-120字 |

新設計と完全一致ではないが、プロンプト補正＋tone 注入＋ルーティングで新設計の意図をカバーできる。

### 既存テンプレート構造との関係

既存は `{ここに生成した文章を挿入}` の単一スロット方式（L1）。personalized_scout は `{opening}` `{bridge}` 等のブロック placeholder 方式（L2/L3）を既にサポート。

**新設計では L3 のブロック方式を使う**。テンプレ側を書き換えて placeholder を配置すれば、補正後のプロンプトで全ブロックが生成される。

---

## 3. 設計の全体像

### 3軸モデル

候補者ごとに決まるのは3つの軸：

```
候補者プロフィール（Chrome拡張抽出）
    ↓
[振り分けロジック（Sheets管理）]
    ↓
    ┌─────────────┬─────────────┬─────────────┐
    ↓             ↓             ↓             ↓
   骨格         トーン        属性           Hプール
   α or δ    casual/…/letter 未経験/…    P01/P02/…
```

- **骨格**: ブロック構成（α=5ブロック or δ=4ブロック）
- **トーン**: 文体（カジュアル / コンパクト / ビジネス / お手紙）
- **属性**: E ブロックで使う候補者タイプ（未経験／ベテラン／ブランク等）
- **Hプール**: ヘッダーの訴求軸（こだわり条件マッピング）

### 3軸の独立性

```
骨格選択 × トーン選択 × 属性選択 の直交
```

ブロック構造（骨格）はトーンで変わらない。ブロック内の文体だけが変わる。これで実装がシンプルになる（プロンプトに tone_instruction 変数を1つ注入するだけ）。

---

## 4. 骨格設計 Option α / δ

### Option α: H-A-B-C-E（5ブロック）

```
┌───────────────────────────────────────────┐
│ H ヘッダー行（求人条件訴求）               │ 固定 約46-60字 Gate1a
│   🌸絵文字＋差別化数字1-2軸                │
├───────────────────────────────────────────┤
│ A 冒頭接点（候補者固有×会社特色の1文）      │ AI生成 40-60字 Gate1b
│   経歴なし候補者はスキップ                  │
├───────────────────────────────────────────┤
│ B 挨拶・送信者名                           │ 固定 約30字
│   「はじめまして、いちごの柳田です。」     │
├───────────────────────────────────────────┤
│ C パーソナライズ本体                       │ AI生成 150-200字 Gate2
│   会社文脈→意味・利益・役割                 │ 経歴なしは型はめ
├───────────────────────────────────────────┤
│ E 安心材料（候補者属性別）                 │ AI選択＋固定 100-150字 Gate2-3
│   教育/OJT/オンコール/WLB から1-2個        │
├───────────────────────────────────────────┤
│ ＜募集要項概要＞以降はスコープ外           │
└───────────────────────────────────────────┘
```

**特徴**: ヘッダー訴求維持、Gate1a（条件訴求）特化、モバイルGate1b弱は受容。

### Option δ: A'-C-E-H'（4ブロック）

```
┌───────────────────────────────────────────┐
│ （事業所名）ジョブメドレー自動表示          │ Gate1a はここで担保
├───────────────────────────────────────────┤
│ A' 挨拶＋候補者接点の融合                  │ AI生成 80-120字 Gate1b
│   「はじめまして、いちごの柳田です。       │
│    [候補者固有×会社特色の1文]」            │
├───────────────────────────────────────────┤
│ C パーソナライズ本体                       │ AI生成 150-200字 Gate2
├───────────────────────────────────────────┤
│ E 安心材料（候補者属性別）                 │ AI選択＋固定 100-150字
├───────────────────────────────────────────┤
│ H' 求人ハイライト行                        │ 固定 約40-50字（要項直前）
├───────────────────────────────────────────┤
│ ＜募集要項概要＞以降はスコープ外           │
└───────────────────────────────────────────┘
```

**特徴**: モバイル50字枠で Gate1b 突破、エール訪問看護の実績あるスタイル、差別化訴求は要項直前に降格。

### α/δ の使い分け根拠

| 項目 | α | δ |
|---|---|---|
| Gate1a（条件訴求） | ◎ 最冒頭で強い | △ 事業所名のみ |
| モバイル Gate1b | ✕ | ◎ |
| PC Gate1b | △ | ◎ |
| 視覚的突出（絵文字） | ◎ | △ |
| クライアント訴求維持 | ◎ | △ |
| 経歴なし候補者対応 | ◎ スキップで安定 | △ A'融合が破綻リスク |
| 捏造リスク | 低 | 低 |

→ 属性によって使い分ける。

---

## 5. トーンシステム

### 4種のトーン

| トーン | 特徴 | 文末例 | 想定候補者 |
|---|---|---|---|
| **casual** | 親しみ・フランク敬語 | 「〜していただけます」 | 一般・若手〜中堅 |
| **compact** | 要点のみ・装飾少 | 「〜が活きます」 | 高年収志向・忙しい層 |
| **business** | 敬語・事実ベース | 「〜と存じます」 | 管理職・大手経験者 |
| **letter** | 寄り添い・温度感 | 「〜していただけたら嬉しいです」 | ブランク・育児中 |

### トーンは骨格と独立

ブロック構造（α/δ）はトーンで変わらない。変わるのは：

- 文体・敬語レベル
- 感嘆符・絵文字の有無
- ブロック内の文字数目安（±30%）
- 気遣い表現・温度感

### 実装

プロンプトに `{tone_instruction}` 変数を注入するだけ。Sheets「トーン指示」シートで4種のテキストを管理。

---

## 6. H ブロック（ヘッダー）プール

### コンセプト

ヘッダーは AI生成ではなく **候補者のこだわり条件 → プールから型はめ**。捏造リスクを完全排除しつつ、候補者に刺さる訴求軸を選べる。

### いちご 初期プール（8個）

| pool_id | trigger_condition | header_text |
|---|---|---|
| P01 | 高収入／年収アップ | 🌸【年収500-600万可】月給35-45万／オンコール手当月最大8万 |
| P02 | default（該当なし） | 🌸【富士見台サテライト2025年5月オープン】立ち上げメンバー募集／年収500-600万可 |
| P03 | ブランク可／未経験可 | 🌸訪問看護未経験歓迎／資格取得全額支援／同行訪問＋研修充実 |
| P04 | 残業少／土日休み | 🌸完全週休2日（土日祝）／年間休日120日以上／有給消化率ほぼ100% |
| P05 | 産休育休／時短 | 🌸時短勤務相談可／記念日休暇年3日／育児休暇取得実績あり |
| P06 | 資格取得支援 | 🌸資格取得全額支援（セミナー・受験料・書籍購入）／昇給年6万 |
| P07 | 車通勤可／駅近 | 🌸電動アシスト自転車・バイク・車貸与／交通費支給／副業OK |
| P08 | 残業少／定時帰り | 🌸残業ほぼなし／9:00-18:00定時／昇給年6万／有給ほぼ100% |

### マッピングルール

- 候補者のこだわり条件を読み → マッピング表で対応プールを決定
- 複数該当時は候補者の優先順位が取れれば上位、取れなければマッピング表上位
- こだわり条件なし or 該当なし → P02 デフォルト
- letter トーン向けは絵文字控えめ版も用意可能（P05-L 等）

### Option δ での H' も同じ仕組み

H'（要項直前ハイライト）も同プール機構を使う。位置が違うだけでロジック共通。

---

## 7. 振り分けロジック

### 概要

候補者プロフィールから `(skeleton, tone, attribute)` の3値を決定するルールテーブル。
Sheets 管理で上から順に評価、最初にマッチしたルールで確定。

### 初期11段ルール（仮説）

| # | name | condition | skeleton | tone | attribute |
|---|---|---|---|---|---|
| 1 | 経歴情報ゼロ | `nursing_years == null AND total_years == null` | alpha | casual | general |
| 2 | ブランクあり | `blank_years >= 1` | delta | letter | blank_career |
| 3 | 管理職・ベテラン | `management_keywords == true AND nursing_years >= 3` | alpha | business | nursing_veteran |
| 4 | 大手経験・中堅以上 | `big_corp_keywords == true AND total_years >= 5` | alpha | business | nursing_veteran |
| 5 | 高収入志向 | `"高収入" in special_conditions` | alpha | compact | nursing_veteran |
| 6 | 訪問看護未経験 | `nursing_years == null AND total_years >= 1` | delta | casual | nursing_inexperienced |
| 7 | 訪問看護ベテラン | `nursing_years >= 3` | alpha | casual | nursing_veteran |
| 8 | 訪問看護経験浅 | `0 < nursing_years < 3` | delta | casual | nursing_junior |
| 9 | 若手・自己PR豊富 | `age_group in ("20s-early","20s-late","30s-early") AND has_pr` | delta | casual | nursing_junior |
| 10 | 40代以上 | `age_group == "40s+"` | alpha | casual | nursing_veteran |
| 11 | デフォルト | `true` | alpha | casual | general |

### DSL 仕様

```
比較:   ==, !=, >=, <=, >, <
論理:   AND, OR（大小文字両対応）
否定:   NOT, not
包含:   "高収入" in special_conditions
リスト: age_group in ("20s-early", "30s-early")
リテラル: true, false, null, 整数, 文字列
```

### 入力コンテキスト変数

| 変数 | 型 | 説明 |
|---|---|---|
| `nursing_years` | int \| None | 訪問看護経験年数（推定） |
| `total_years` | int \| None | 総経験年数 |
| `has_pr` | bool | 自己PRあり |
| `blank_years` | int | ブランク年数 |
| `age_group` | str \| None | "20s-early"〜"40s+" |
| `employment_status` | str | 就業中／離職中 |
| `special_conditions` | list[str] | こだわり条件（正規化済） |
| `management_keywords` | bool | 主任・師長等のキーワード有無 |
| `big_corp_keywords` | bool | 大手病院キーワード有無 |

---

## 8. ブロック別プロンプト設計

### 役割分離（最重要）

v1 でサンプル加圧した際、A/A' と C の冒頭が候補者経歴で重複する問題が発生。v2 で役割を厳格分離：

| ブロック | 役割 | 冒頭の入り方 |
|---|---|---|
| **opening (A / A')** | 接点予告まで | 候補者経歴の事実を起点 |
| **bridge (C 相当)** | 意味・利益の展開 | **会社側の文脈から** |
| **facility_intro** | 会社紹介と接続 | profile.md 明記内容のみ |
| **job_framing** | 求人フレーミング | 希望条件を踏まえて |
| **closing_cta** | 行動喚起 | 候補者へのオファー主体 |

### 捏造防止の厳格ルール

全ブロック共通で以下を禁止：

1. 会社情報・求人情報に**明記されていない制度名**を作り出す（事例検討会・1on1・メンター制度・ラダー研修・S-QUE 等、業界一般でも明記なければNG）
2. 業界標準制度を「当ステーションにある」と断定する
3. 数値（手当額・月回数・研修期間・有給消化率）を概算で丸める
4. 施設名・事業所名・担当者名の漢字表記を間違える
5. 候補者経歴の数値改変（経験年数を「約」で丸めない）

### opening 文末パターン（利益表現禁止）

- ◎「〜と重なります」「〜と重なる場面が多いと感じました」
- ◎「〜が目に留まりました」「〜が印象的でした」
- ✕「〜で活きます」「〜で大きな力になります」← bridge の役割

### bridge 冒頭パターン（会社文脈から）

- ✕「X年のご経験は〜」（opening と重複）
- ◎「当ステーションの○○では〜」
- ◎「○○の現場では〜」

### サンプル検証結果（v2）

| 課題 | v1 | v2 |
|---|---|---|
| opening/bridge 冒頭重複 | 3サンプル全滅 | 解消 |
| 存在しない制度の生成 | 発生 | 排除 |
| 役割分離 | 曖昧 | 明確 |
| モバイル Gate1b（δ） | 突破 | 維持 |

サンプル全文は [workspace/ichigo-sample-scouts-v2.md](ichigo-sample-scouts-v2.md) 参照。

---

## 9. Sheets スキーマ追加

既存の Sheets に追加する3シート。

### シート1: トーン指示

| 列 | 内容 |
|---|---|
| tone_id | casual / compact / business / letter |
| display_name | 表示名 |
| instruction | プロンプトに注入する文体指示 |
| active | 有効フラグ |
| updated_at | 更新日時 |

### シート2: 振り分けルール

| 列 | 内容 |
|---|---|
| priority | 優先順（小さいほど上位） |
| name | ルール名 |
| condition | DSL評価式 |
| skeleton | alpha / delta |
| tone | casual / compact / business / letter |
| attribute | nursing_inexperienced / nursing_junior / nursing_veteran / blank_career / parenting / general |
| active | 有効フラグ |

### シート3: ヘッダープール

| 列 | 内容 |
|---|---|
| company_id | 会社ID |
| pool_id | プールID |
| trigger_condition | こだわり条件 |
| skeleton | alpha / delta / both |
| tone | 対応トーン（カンマ区切り） |
| header_text | ヘッダー本文 |
| priority | 同条件内の優先順 |
| active | 有効フラグ |

詳細: [workspace/sheets-schema-additions.md](sheets-schema-additions.md)

---

## 10. 実装状況

### 完了項目（2026-04-24）

| 項目 | ファイル | 内容 |
|---|---|---|
| プロンプト補正 | [server/pipeline/personalized_scout/prompt.py](../server/pipeline/personalized_scout/prompt.py) | 役割分離・捏造防止・トーン注入 |
| tone 伝播 | generator.py / pipeline.py | tone_instruction パラメータ追加 |
| Sheets 対応 | [server/db/sheets_client.py](../server/db/sheets_client.py) | 3シート分の定数・アクセサメソッド |
| 振り分けエンジン | [server/pipeline/routing.py](../server/pipeline/routing.py) | DSL評価・属性抽出・route() |
| 振り分け統合 | pipeline.py | route() 自動呼出し・tone 解決 |
| テスト | [server/tests/test_routing.py](../server/tests/test_routing.py) | 28件 |

### テスト結果

- 新規 28件 pass
- 全体 514件 pass（既存 486 + 新規 28）
- 既存テスト破壊なし

### コード変更サマリ

```diff
+ server/pipeline/routing.py          (新規 350行)
+ server/tests/test_routing.py        (新規 250行)
* server/pipeline/personalized_scout/prompt.py    (ブロック記述・ガイド補正・tone_instruction)
* server/pipeline/personalized_scout/generator.py (tone_instruction 伝播)
* server/pipeline/personalized_scout/pipeline.py  (route() 統合・routing メタ返却)
* server/db/sheets_client.py         (3シート対応)
```

### 未実装（意図的な省略）

- **Hプール自動差替**: pipeline での header_pool ルックアップ。現状はテンプレ本文に固定ヘッダー運用。動的差替が必要になったら追加
- **α/δ テンプレ切替の自動化**: skeleton 値は routing で決定できるが、pipeline はテンプレ選択で吸収する想定（α用とδ用のテンプレを Sheets に別行で持つ → template_row_index で切替）
- **管理画面UI**: 3シートの CRUD UI は未実装。初期データ投入は Sheets 直接編集

---

## 11. 運用フロー（Phase 計画）

### Phase 1: プロトタイプレビュー

1. Sheets に 3シート作成＋初期データ投入（PM/ディレクター）
2. いちごのテンプレに `{opening}{bridge}{facility_intro}{job_framing}{closing_cta}` を配置したL3版を新設
3. Gemini 実エンドポイントで L3生成の動作確認
4. **属性セグメント別に5-10候補者プロトタイプ生成**（α/δ両方・トーン4種）
5. PM・ディレクターでレビュー、骨格・プロンプト・振り分けルールを補正

### Phase 2: いちご本番 A/B運用

1. Phase 1 合格後、いちごで実運用開始
2. 2週間・各属性セグメント内で 100件以上送信目標
3. 返信率を (skeleton, tone, attribute) × 候補者属性 でクロス集計
4. 送信データシートに `version` タグ（alpha/delta）と `tone` `attribute` を追加して分析可能に

### Phase 3: ARK で骨格の再現性検証

1. Phase 2 で勝ち残った骨格を ARK に展開
2. ARK conversations 34件のエビデンスと照合
3. 会社依存の偏りがないか確認

### Phase 4: 他5社展開

LCC / an / 茅ヶ崎徳洲会 / ネオサミット湯河原 / 野村病院 に順次展開。

各社で：
- profile.md の完成度確認
- ヘッダープール（8-10個）の作成
- 属性マッピング調整（病院・有料老人ホームは別項目）
- バリデーション調整

---

## 12. 残課題・Open Questions

### 未解決の論点（PM/ディレクター判断待ち）

| # | 論点 | 優先度 |
|---|---|---|
| 1 | ③橋渡し「ご経歴を拝見し〜」削除はクライアント文化上許容されるか | 中 |
| 2 | 候補者名への呼びかけ「○○様」の可否 | 中 |
| 3 | 🌸絵文字の業態別運用（病院=🏥、有料老人ホーム=🌿） | 低 |
| 4 | letter トーンで H' 絵文字を排除するか | 低 |
| 5 | 損失フレーム導入の可否（訪問看護は不快感リスク） | 低 |

### 運用データで検証が必要な仮説

| # | 仮説 | 検証方法 |
|---|---|---|
| 1 | モバイル開封比率が年代で違う | Phase 2 の開封データで確認 |
| 2 | 「ベテラン＝条件訴求／若手＝個別対応」区分 | 属性別返信率クロス集計 |
| 3 | 「訪問看護未経験＝δ」の有効性 | 未経験セグメント内 α/δ A/B |
| 4 | compact トーンの有効性（Gate1b 捨てる設計） | 高収入志向セグメントで返信率比較 |

### 将来拡張

- 振り分けルールに `%` 列を追加して特定セグメント内A/Bをランダム化
- ヘッダープールで `{salary_range}` 等のプレースホルダー動的置換
- 管理画面から3シートの CRUD UI
- 会社・業態別の attribute マッピング細分化

---

## 13. 参照ファイル一覧

### 設計ドキュメント（workspace/）

| ファイル | 内容 |
|---|---|
| [scout-personalization-design.md](scout-personalization-design.md) | **本ドキュメント（設計の決定版）** |
| [ichigo-block-design-final.md](ichigo-block-design-final.md) | Option α 最終骨格 |
| [ichigo-block-design-final-delta.md](ichigo-block-design-final-delta.md) | Option δ 最終骨格 |
| [ichigo-block-design-v1.json](ichigo-block-design-v1.json) | v1.1 診断結果 JSON |
| [ichigo-block-design-review.md](ichigo-block-design-review.md) | v1.1 レビュー＋加圧テスト |
| [ichigo-routing-logic.md](ichigo-routing-logic.md) | 振り分けルールテーブル仕様 |
| [ichigo-sample-scouts-v1.md](ichigo-sample-scouts-v1.md) | v1 試作サンプル3本＋問題発見 |
| [ichigo-sample-scouts-v2.md](ichigo-sample-scouts-v2.md) | v2 試作サンプル3本（補正後） |
| [sheets-schema-additions.md](sheets-schema-additions.md) | Sheets 3シート詳細仕様 |

### プロンプト設計（server/prompts/）

| ファイル | 内容 |
|---|---|
| [design_block_structure.md](../server/prompts/design_block_structure.md) | Mode A 構成設計プロンプト |
| [block_a_alpha_hook.md](../server/prompts/block_a_alpha_hook.md) | A ブロック（α専用） |
| [block_a_delta_opening.md](../server/prompts/block_a_delta_opening.md) | A' ブロック（δ専用） |
| [block_c_personalized.md](../server/prompts/block_c_personalized.md) | C ブロック（α/δ共通） |
| [block_e_reassurance.md](../server/prompts/block_e_reassurance.md) | E ブロック（α/δ共通） |

### 実装コード（server/）

| ファイル | 変更内容 |
|---|---|
| [server/pipeline/routing.py](../server/pipeline/routing.py) | **新規** DSL評価エンジン |
| [server/pipeline/personalized_scout/prompt.py](../server/pipeline/personalized_scout/prompt.py) | ブロック記述・ライティングガイド補正・tone_instruction 対応 |
| [server/pipeline/personalized_scout/generator.py](../server/pipeline/personalized_scout/generator.py) | tone_instruction 伝播 |
| [server/pipeline/personalized_scout/pipeline.py](../server/pipeline/personalized_scout/pipeline.py) | route() 統合・routing メタ返却 |
| [server/db/sheets_client.py](../server/db/sheets_client.py) | 3シート対応（定数＋アクセサメソッド） |
| [server/tests/test_routing.py](../server/tests/test_routing.py) | **新規** 28ユニットテスト |

### 会社別資産

| ファイル | 用途 |
|---|---|
| [companies/ichigo-visiting-nurse/profile.md](../companies/ichigo-visiting-nurse/profile.md) | 会社プロフィール（Sheets に同期） |
| [companies/ichigo-visiting-nurse/templates.md](../companies/ichigo-visiting-nurse/templates.md) | 現行テンプレート（要 L3 化） |
| [companies/ichigo-visiting-nurse/recipes.md](../companies/ichigo-visiting-nurse/recipes.md) | 型はめパターン（経歴なし候補者用） |

---

## 付録: 設計判断の経緯

### なぜ α/δ の2骨格を並行するか

初期設計では α（H-A-B-C-E）を採用。しかしジョブメドレーのモバイルプレビュー実機確認で、ヘッダー46字がプレビュー枠をほぼ消費し A ブロックが見えない問題を発見。

δ（ヘッダー廃止・挨拶融合型）はエール訪問看護など他社で実績のあるスタイルで、モバイル50字枠で Gate1b を確実に突破できる。

「どちらが勝つか」を決めるのではなく、**候補者属性によって使い分ける**のが合理的という結論。

### なぜトーンを独立軸にしたか

当初は「骨格ごとに合うトーン」というマトリクスを考えたが、user の指摘「ブロック構成自体はあまり変わらない」により軌道修正。トーンはブロック内を埋める文体パラメータとして扱うことで：

- 実装がシンプル（tone_instruction 変数1つ）
- 骨格とトーンの組み合わせが 2×4 = 8通り自由に作れる
- 運用で調整しやすい

### なぜ既存パイプラインを活かしたか

`personalized_scout/` が既に L2/L3 として稼働しており、Sheets連携・Gemini呼出し・バリデーション・測定が実装済。新骨格専用パイプラインを作ると二重保守になるため、既存の opening/bridge/facility_intro/job_framing/closing_cta のプロンプトを補正して新設計の意図をカバーする方針に。

既存のブロック名（opening/bridge/…）と新設計のブロック名（H/A/B/C/E/A'/H'）が完全一致しないが、役割マッピング（opening≒A、bridge+facility_intro≒C、H/B は固定文として扱う）で吸収。

### なぜ Sheets 管理か

非エンジニアの PM・ディレクターが運用中に調整できる必要がある。振り分けルール・トーン指示・ヘッダープールは頻繁に見直される前提で、コード変更・デプロイを要求する設計は避けた。
