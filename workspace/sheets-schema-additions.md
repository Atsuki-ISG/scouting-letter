# Sheets スキーマ追加設計

新骨格（α/δ + トーン + 振り分け）のために Google Sheets に追加するシート仕様。

## 現状の Sheets 構成（2026-04-24時点）

| シート名 | 用途 |
|---|---|
| テンプレート | スカウト文テンプレート本体 |
| パターン | 型はめパターン |
| プロンプト | プロンプトセクション（会社特色・教育体制・接点ガイド） |
| 求人 | 求人情報（給与・手当等の数字） |
| バリデーション | 候補者フィルタ条件 |
| プロフィール | 会社プロフィール（profile.md のSheets版） |
| 職種キーワード | 職種判定用キーワード |
| 修正フィードバック | オペレーター修正履歴 |
| ナレッジプール | 承認済みナレッジルール |
| 競合調査 | 競合求人分析結果 |
| 会話ログ | やりとりログ |
| 生成ログ | AI生成ログ |
| 改善提案 | テンプレ改善提案 |

## 追加する3シート

### 1. シート名: `トーン指示`

**目的**: 候補者属性に応じて生成プロンプトに注入するトーン指示テキストを管理。

| 列 | 型 | 説明 | 例 |
|---|---|---|---|
| tone_id | str | トーンID（プログラム内参照キー） | casual, compact, business, letter |
| display_name | str | 表示名（管理画面用） | カジュアル、コンパクト、ビジネス、お手紙 |
| instruction | str | tone_instruction として注入される本文 | (下記参照) |
| active | bool | 有効フラグ | TRUE/FALSE |
| updated_at | datetime | 最終更新日時 | 2026-04-24T10:00:00 |

**instruction の初期値（4行）**:

#### casual（カジュアル）
```
トーン: 親しみやすくフランク。ほどよい軽さ、LCCに近い温度感。ただし砕けすぎない。
文末: 「〜していただけます」「〜が活きると思います」「〜を期待しています」
感嘆符: 控えめ（ブロック内で1回まで）
距離感: 対等で明るい。相手の専門性を認めながら、カジュアルな敬語で語る
```

#### compact（コンパクト）
```
トーン: 要点のみ、装飾削ぎ落とし。短文中心で即読みできる構成。
文末: 「〜が活きます」「〜可能です」「〜を提供します」など断定に近い形
感嘆符: 使用禁止
距離感: ビジネスライクだが冷たくない。事実ベースで候補者評価→会社特色→利益を最短距離で繋ぐ
文字数: 全ブロック合計を3割程度圧縮、opening 80-100字、bridge 100-150字、facility_intro 120-180字
```

#### business（ビジネス）
```
トーン: 敬語を基調とした丁寧で客観的な文体。感情表現は控えめ、数字・事実ベースで語る。
文末: 「〜と存じます」「〜に活きるものと考えます」「〜を実現できる環境です」
感嘆符: 使用禁止
距離感: 一定の距離を保った丁寧な敬語。相手の専門性を正式に評価する姿勢
避ける語彙: 「〜してあげる」「〜で安心」「〜にぴったり」
```

#### letter（お手紙）
```
トーン: 個人宛の手紙のような温度感と寄り添い。相手の状況を気遣う言葉を入れる。
文末: 「〜していただけたら嬉しいです」「〜お過ごしいただけるよう」「〜をご提案したく」
感嘆符: 避ける（温度感は語彙で表現）
距離感: 近いが丁寧。候補者の状況（ブランク・育児中・環境変化等）を察した一言を自然に織り込む
例文スタイル: 「これまでの◯年のご経験、◯◯での日々のご判断は、当ステーションで訪問する利用者様一人ひとりに向き合う場面でそのまま活きると感じました。」
```

---

### 2. シート名: `振り分けルール`

**目的**: 候補者プロフィール → (skeleton, tone, attribute) の3値を決定するルールテーブル。
上から順に評価、最初にマッチしたルールで確定。

| 列 | 型 | 説明 | 例 |
|---|---|---|---|
| priority | int | 優先順（小さいほど上位） | 1, 2, 3... |
| name | str | ルール名（管理・ログ用） | "経歴なし", "ブランクあり" |
| condition | str | 評価式（後述のDSL） | `nursing_years == null AND total_years == null` |
| skeleton | enum | alpha / delta | alpha |
| tone | enum | casual / compact / business / letter | casual |
| attribute | enum | nursing_inexperienced / nursing_junior / nursing_veteran / blank_career / parenting / general | general |
| active | bool | 有効フラグ | TRUE |
| updated_at | datetime | 更新日時 | 2026-04-24T10:00:00 |

**初期ルール（14段）** — Phase 0 実データ検証で見えた盲点を踏まえて改訂:

| priority | name | condition | skeleton | tone | attribute |
|---|---|---|---|---|---|
| 1 | 経歴情報ゼロ | `nursing_years == null AND total_years == null` | alpha | casual | general |
| 2 | ブランクあり | `blank_years >= 1` | delta | letter | blank_career |
| 3 | 管理職経験・訪看有り | `management_keywords == true AND nursing_years >= 3` | alpha | business | nursing_veteran |
| 4 | 管理職経験・他科ベテラン | `management_keywords == true AND total_years >= 5` | alpha | business | nursing_veteran |
| 5 | 大手経験・中堅以上 | `big_corp_keywords == true AND total_years >= 5` | alpha | business | nursing_veteran |
| 6 | 高収入志向 | `"高収入" in special_conditions` | alpha | compact | nursing_veteran |
| 7 | 訪問看護未経験（他科経験あり） | `(nursing_years == null OR nursing_years == 0) AND total_years >= 1` | delta | casual | nursing_inexperienced |
| 8 | 訪問看護ベテラン | `nursing_years >= 3` | alpha | casual | nursing_veteran |
| 9 | 訪問看護経験浅 | `0 < nursing_years < 3` | delta | casual | nursing_junior |
| 10 | 若手・リッチPR | `age_group in ("20s-early", "20s-late", "30s-early") AND has_rich_pr` | delta | casual | nursing_junior |
| 11 | 30代後半・40代前半（中堅層） | `age_group in ("30s-late") AND total_years >= 5` | alpha | casual | nursing_veteran |
| 12 | 40代以上 | `age_group == "40s+"` | alpha | casual | nursing_veteran |
| 13 | 若手（PR薄） | `age_group in ("20s-early", "20s-late")` | alpha | casual | general |
| 14 | デフォルト | `true` | alpha | casual | general |

**改訂の根拠（Phase 0 実データ検証結果より）**:

- **rule 7 拡張**: `nursing_years == null` のみだと他科経験ありの訪看未経験者（Sample 1 の 41歳HCU13年、Sample 4 の 38歳病棟16年）を拾えなかった。`nursing_years in (null, 0)` 相当に拡張
- **rule 4 新設**: 管理職経験ありで訪看経験ゼロでも、総経験5年以上ならビジネス層扱いに
- **rule 11 新設**: 30s-late（35-39歳）＋ 総経験5年以上のベテラン層がデフォルト行きになっていた隙間を埋める
- **rule 10 条件強化**: `has_pr` → `has_rich_pr`（20字以上）に。「笑顔には自信があります」(12字)のような薄い PR で junior 扱いされるのを防ぐ
- **rule 13 新設**: 若手で PR 薄の候補者は general 扱いで sparse 生成に（junior 扱いは誤導）

**評価式DSL**:
- 比較演算子: `==`, `!=`, `>=`, `<=`, `>`, `<`
- 論理演算子: `AND`, `OR`
- 包含: `"高収入" in special_conditions`
- リスト要素チェック: `age_group in ("20s-early", "30s-early")`
- 真偽リテラル: `true`, `false`, `null`

### 3. シート名: `ヘッダープール`

**目的**: Hブロック（Option α のヘッダー、Option δ のH'求人ハイライト）の訴求軸テキストを会社・こだわり条件別に管理。

| 列 | 型 | 説明 | 例 |
|---|---|---|---|
| company_id | str | 会社ID | ichigo-visiting-nurse |
| pool_id | str | プールID | P01, P02... |
| trigger_condition | str | こだわり条件の一致パターン | "高収入", "残業少", "default" |
| skeleton | enum | alpha / delta（両方なら "both"） | both |
| tone | enum | 対応トーン（複数指定可、カンマ区切り） | casual,compact |
| header_text | str | ヘッダー本文 | 🌸【年収500-600万可】月給35-45万／オンコール手当月最大8万 |
| priority | int | 同条件内での優先順 | 1 |
| active | bool | 有効フラグ | TRUE |
| updated_at | datetime | 更新日時 | 2026-04-24T10:00:00 |

**いちご 初期プール（8個）**:

| pool_id | trigger_condition | tone | header_text |
|---|---|---|---|
| P01 | 高収入／年収アップ | casual,compact,business | 🌸【年収500-600万可】月給35-45万／オンコール手当月最大8万 |
| P02 | default | casual,compact,business | 🌸【富士見台サテライト2025年5月オープン】立ち上げメンバー募集／年収500-600万可 |
| P03 | ブランク可／未経験可／教育体制 | casual | 🌸訪問看護未経験歓迎／資格取得全額支援／同行訪問＋研修充実 |
| P04 | 残業少／土日休み／WLB | casual,letter | 🌸完全週休2日（土日祝）／年間休日120日以上／有給消化率ほぼ100% |
| P05 | 産休育休／託児所／時短 | letter,casual | 🌸時短勤務相談可／記念日休暇年3日／育児休暇取得実績あり |
| P06 | 資格取得支援／スキルアップ | casual,business | 🌸資格取得全額支援（セミナー・受験料・書籍購入）／昇給年6万 |
| P07 | 車通勤可／駅近 | casual | 🌸電動アシスト自転車・バイク・車貸与／交通費支給／副業OK |
| P08 | 残業少／定時帰り | casual,compact | 🌸残業ほぼなし／9:00-18:00定時／昇給年6万／有給ほぼ100% |

**letter トーン向け低絵文字版（任意追加）**:
| pool_id | trigger_condition | tone | header_text |
|---|---|---|---|
| P05-L | 産休育休／託児所／時短 | letter | 時短勤務相談可／記念日休暇年3日／育児休暇取得実績あり |

---

## sheets_client.py への追加（実装メモ）

```python
# db/sheets_client.py に追加
SHEET_TONE_INSTRUCTIONS = "トーン指示"
SHEET_ROUTING_RULES = "振り分けルール"
SHEET_HEADER_POOL = "ヘッダープール"

# _ALL_SHEETS リストに追加:
_ALL_SHEETS = [
    ...既存...,
    SHEET_TONE_INSTRUCTIONS,
    SHEET_ROUTING_RULES,
    SHEET_HEADER_POOL,
]

# 新規メソッド:
def get_tone_instruction(self, tone_id: str) -> str | None:
    """Return the instruction text for a given tone_id, or None if not found."""
    for row in self._cache.get(SHEET_TONE_INSTRUCTIONS, []):
        if row.get("tone_id") == tone_id and row.get("active", True):
            return row.get("instruction")
    return None

def get_routing_rules(self) -> list[dict]:
    """Return active routing rules sorted by priority (ascending)."""
    rows = [r for r in self._cache.get(SHEET_ROUTING_RULES, []) if r.get("active", True)]
    return sorted(rows, key=lambda r: int(r.get("priority", 999)))

def get_header_pool(self, company_id: str) -> list[dict]:
    """Return active header pool rows for the company."""
    return [
        r for r in self._cache.get(SHEET_HEADER_POOL, [])
        if r.get("company_id") == company_id and r.get("active", True)
    ]
```

---

## 管理画面への追加（admin/index.html）

3シートの CRUD UI を既存の管理画面パターンに沿って追加。
- タブ: 「トーン指示」「振り分けルール」「ヘッダープール」
- 既存の プロンプトセクション / ナレッジプール タブと同じ UX（追加・編集・削除・反映）

---

## 投入手順（いちごを対象に）

1. Sheets 側で3シートをスプレッドシートに作成（列ヘッダーを揃える）
2. 初期データ投入（本ドキュメントの表から）
3. `sheets_client.py` に定数とメソッド追加
4. `_ALL_SHEETS` に追加して一括ロード対象に
5. キャッシュ再読み込み or デプロイ
6. orchestrator から呼び出して動作確認

---

## 将来拡張（PhaseB以降）

- **振り分けルールの%振り分け**: 特定セグメント内で α/δ を A/B テストするための確率列追加
- **ヘッダープールの数字動的差替**: 求人シートの値を header_text 内の `{salary_range}` 等のプレースホルダーで自動置換
- **7社汎用化**: `company_id` 列で会社別プール、attribute マッピングも会社別
