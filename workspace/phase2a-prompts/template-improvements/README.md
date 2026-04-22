# テンプレート改善版 INDEX（2026-04-22 自動生成）

LCC 水準のテンプレ構成（preview最適化ヘッダー + 独自強み訴求 + 求人要項スマート化）を非LCC 6社に水平展開した改善版。**Sheets には未反映**。ユーザーの diff レビュー後、承認分のみ push する運用。

## 生成物

| 会社 | 改善templates | DIFFサマリ | テンプレ数 | 行数 before→after |
|---|---|---|---|---|
| ARK訪問看護 | [ark-visiting-nurse-templates.md](ark-visiting-nurse-templates.md) | [DIFF](ark-visiting-nurse-DIFF.md) | 6本（看護師正社員・パート×初回/再送＋お気に入り2） | 500→453（-47） |
| 茅ヶ崎徳洲会 | [chigasaki-tokushukai-templates.md](chigasaki-tokushukai-templates.md) | [DIFF](chigasaki-tokushukai-DIFF.md) | 3本（初回・再送【新設】・お気に入り） | 160→274（+114、再送新設分） |
| an訪問看護 | [an-visiting-nurse-templates.md](an-visiting-nurse-templates.md) | [DIFF](an-visiting-nurse-DIFF.md) | 16本（看護師/OT/PT 正社員×2、OT/PT/相談 パート×2、お気に入り4） | 50874→952行 |
| いちご訪問看護 | [ichigo-visiting-nurse-templates.md](ichigo-visiting-nurse-templates.md) | [DIFF](ichigo-visiting-nurse-DIFF.md) | 6本（看護師正社員×2、パート×2、お気に入り2） | 3本→6本拡充 |
| 大和ハウスLS | [daiwa-house-ls-templates.md](daiwa-house-ls-templates.md) | [DIFF](daiwa-house-ls-DIFF.md) | 3本（入居相談員 初回・再送・お気に入り） | 287行 |
| 野村病院 | [nomura-hospital-templates.md](nomura-hospital-templates.md) | [DIFF](nomura-hospital-DIFF.md) | 6本（看護師 初回/再送/お気に入り、管理栄養士 初回/再送/お気に入り） | 473行 |

合計 **40本** のテンプレ改善／新設。

## 共通の改善軸（LCC を model case に）

1. **preview最適化ヘッダー**: 会社名・職種・雇用形態・給与レンジは JM preview で別表示されるため本文重複させず、独自強み 3-4点を約75字以内に凝縮
2. **Distinctive value 段落**: 会社固有の構造的強みを事実ベースで1段落説明
3. **求人要項の6セクション統一**: 仕事内容／給与／勤務時間／休日／福利厚生／所在地 に分割、bullet spam 廃止
4. **お気に入りテンプレの件名＋本文分離**: ``` ブロックを分離する既存仕様を維持
5. **トーン・デコレーション統一**: LCC/an/いちご＝🌸、ARK＝【 】、茅ヶ崎/野村＝■、大和ハウス＝【 】（企業トーンに合わせ）

## 売り文句プール（ヘッダー生成材料）

各社の売り文句プール（JMタグ付き）は [../header-personalization-matrix.md](../header-personalization-matrix.md) §5（ARK）§6（LCC）§6-A〜6-E（5社）に整備済。合計 **約124件**。

## 次のアクション（ユーザー）

1. **diff レビュー**: 各社の改善版 templates.md を現行と比較し、強み訴求・事実精度・トーンを確認
2. **[要確認] 項目のPMヒアリング**: 各DIFFに記載された確認項目（特に担当者名・雇用形態・年収数字）をクライアントに確認
3. **push script 作成**: 承認後、`push_lcc_templates.py` を雛形に各社の `push_[company]_templates.py` を作成、row_index マッピングで Sheets 反映

## [要確認] 項目総数（PMヒアリング対象）

- ARK: 6件（担当者名・年間休日・オンコール・医療費還付詳細・認定看護師関与・同行期間）
- 茅ヶ崎: 6件（中途離職率・医療費減免実績・小学生預かり実績・172床新病棟・年休110日カウンター・グループ評判対応）
- an: 7件（看護師パート時給・残業月5時間算出・7時間勤務明文化・有給計測年度・オンコール内訳・40-50代数・相談支援員人数）
- いちご: 8件（看護師パート時給・運営会社名・担当者名・index_1待遇差・オンコール内訳・昇給実績・リハ職テンプレ要否・年間休日日数）
- 大和ハウスLS: 7件（奨励金達成者比率・10件超過設計・転居補助実績・現場裁量実態・住宅棟→ケア棟移行・グループ割引詳細・有給日数）
- 野村病院: 9件（うち最優先2件: 担当者名未定、管理栄養士雇用形態齟齬）

合計 **約43件** の要確認事項。
