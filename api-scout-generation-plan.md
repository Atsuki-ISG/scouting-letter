# API経由スカウト文生成システム 実装計画

## Context

個人利用のChrome拡張（ジョブメドレー用スカウト文生成・送信）を社内展開する。
現在は「CSV抽出 → 外部AIで生成 → CSVインポート → 送信」の手動リレーが必要。
API統合で「抽出 → API生成 → 送信」の1フローを実現し、運用負荷を下げる。

- オペレーター6名+増加予定、管理者3名（非エンジニア含む）
- LLM: Gemini Pro（Vertex AI経由）
- 認証: Google Workspace（OAuth）
- Chrome拡張: 手動配布（ZIP）、今後も継続

---

## Phase 1+2: Cloud Run API + Chrome拡張統合（一括実装）

### アーキテクチャ

```
Chrome拡張（ジョブメドレー上で動作）
  ├─ プロフィール抽出（既存のまま）
  ├─ [NEW] API生成タブ: 抽出データ → Cloud Run → スカウト文受取
  ├─ 送信アシスト（既存のまま）
  └─ 設定: APIエンドポイント/APIキー入力

Cloud Run（FastAPI）
  ├─ POST /api/v1/generate         # 単一候補者生成
  ├─ POST /api/v1/generate/batch   # 一括生成（内部で10並列）
  ├─ GET  /api/v1/companies/{id}/config  # テンプレ・求人・バリデーション設定
  └─ Firestore: プロンプトセクション・テンプレート・型はめパターン・ログ
```

### 1. サーバー側（`server/`）

#### ディレクトリ構成

```
server/
├── Dockerfile
├── requirements.txt
├── main.py                       # FastAPIエントリポイント
├── config.py                     # 環境変数
├── auth/
│   └── api_key.py                # APIキー認証（Phase 1+2はこれだけ）
├── api/
│   ├── routes_generate.py        # /generate, /generate/batch
│   └── routes_companies.py       # /companies/{id}/config
├── models/
│   ├── profile.py                # CandidateProfile (Pydantic)
│   └── generation.py             # Request/Response
├── pipeline/
│   ├── orchestrator.py           # パイプライン全体制御 + 並列処理
│   ├── filter.py                 # フィルタリング（資格チェック等）
│   ├── template_resolver.py      # テンプレート判定（パート/正社員 × 初回/再送）
│   ├── job_category_resolver.py  # 資格→職種カテゴリ判定
│   ├── pattern_matcher.py        # 型はめパス（型A〜G + 資格修飾 + 特色ローテーション）
│   ├── ai_generator.py           # AI生成パス（Vertex AI Gemini Pro）
│   ├── prompt_builder.py         # プロンプトセクション組み立て
│   └── text_builder.py           # buildFullScoutText相当
├── db/
│   ├── firestore_client.py       # Firestore操作
│   └── seed.py                   # 既存recipes.md/templates.mdからFirestoreにデータ投入
└── tests/
    ├── test_filter.py
    ├── test_pattern_matcher.py
    └── test_orchestrator.py
```

#### APIエンドポイント

**POST /api/v1/generate**
```json
// Request
{
  "company_id": "ark-visiting-nurse",
  "profile": { /* CandidateProfileの全フィールド */ },
  "options": { "is_resend": false, "force_seishain": false }
}
// Response
{
  "member_id": "12345",
  "template_type": "パート_初回",
  "generation_path": "ai",       // "ai" | "pattern" | "filtered_out"
  "pattern_type": null,           // 型はめの場合: "A", "B1" 等
  "personalized_text": "...",
  "full_scout_text": "...",
  "job_offer_id": "1550716",
  "filter_reason": null,
  "validation_warnings": []
}
```

**POST /api/v1/generate/batch**
```json
// Request
{
  "company_id": "ark-visiting-nurse",
  "profiles": [ /* CandidateProfile[] */ ],
  "options": { "is_resend": false, "concurrency": 10 }
}
// Response
{
  "results": [ /* 上記レスポンスの配列 */ ],
  "summary": { "total": 50, "ai_generated": 30, "pattern_matched": 15, "filtered_out": 5 }
}
```

**GET /api/v1/companies/{company_id}/config**
- テンプレート一覧、求人一覧、バリデーション設定を一括返却
- Chrome拡張のハードコード（COMPANY_TEMPLATES, COMPANY_JOB_OFFERS, COMPANY_VALIDATION_CONFIG）をAPI取得に移行

#### Firestoreデータモデル

```
companies/{company_id}
  ├── name, slug, scout_sender_name
  ├── prompt_sections/{section_id}     # プロンプトのモジュール化
  │     section_type: "station_features" | "education" | "ai_guide" | ...
  │     scope: "global" | "company"
  │     job_category: "nurse" | "rehab" | "medical_office" | null
  │     content: string (Markdown)
  ├── templates/{template_id}
  │     type: "パート_初回" | "パート_再送" | "正社員_初回" | "正社員_再送"
  │     job_category: "nurse"
  │     body: string（{personalized_text}プレースホルダー含む）
  ├── patterns/{pattern_id}             # 型はめパターン
  │     pattern_type: "A" | "B1" | ... | "G"
  │     job_category: "nurse"
  │     target_condition: { age_min, age_max, exp_years_min, exp_years_max, employment_status }
  │     template_text: string
  │     feature_variations: string[]
  ├── qualification_modifiers/{id}       # 資格修飾
  │     qualification_combo: ["看護師", "保健師"]
  │     replacement_text: string
  ├── job_offers/{id}
  │     jobmedley_id, name, label, job_category, employment_type, active
  ├── validation_config                  # バリデーション設定
  │     age_range, qualification_rules
  └── examples/{id}                      # 良い例
        title, personalized_text, job_category

global_config/prompt_sections            # 全社共通セクション
  role_definition, tone_and_manner, common_rules, ng_expressions

generation_logs/{id}                     # 生成ログ
  company_id, member_id, template_type, generation_path,
  personalized_text, llm_model, llm_input_tokens, latency_ms, created_at

api_keys/{key_hash}                      # APIキー
  operator_email, company_ids[], created_at
```

#### 生成パイプライン（orchestrator.py）

```
receive_request(profile, company_id, options)
  → resolve_job_category(qualifications)    # 資格→職種判定
  → determine_template_type(options)        # パート/正社員 × 初回/再送
  → filter_candidate(profile)              # 資格・経験チェック
    → filtered_out: return { filter_reason }
  → route_path(profile)                    # 経歴あり→AI / なし→型はめ
    → [型はめ] pattern_matcher.match(age, exp_years, employment_status)
      → 資格修飾チェック → 特色ローテーション → personalized_text
    → [AI生成] prompt_builder.build() → ai_generator.generate()
      → personalized_text
  → text_builder.build_full(template, personalized_text)
  → log_generation(result)
  → return response
```

バッチ処理: `asyncio.Semaphore(concurrency)` で並列数制御。1候補者=1 Gemini API呼び出し。

#### プロンプト組み立て（prompt_builder.py）

Firestoreから各セクションを取得して結合:
```python
system_prompt = "\n\n---\n\n".join([
    global.role_definition,           # ① ロール定義
    global.tone_and_manner,           # ④ トーン＆マナー
    global.common_rules,              # ⑤ 共通ルール
    global.ng_expressions,            # ⑨ NG表現
    company.station_features[job_cat], # ② ステーション特色
    company.education[job_cat],        # ③ 教育体制
    company.patterns[job_cat],         # ⑥ 型はめパターン（参考として）
    company.qual_modifiers,            # ⑦ 資格修飾
    company.ai_guide[job_cat],         # ⑧ AI生成ガイド
    format_template(template),         # ⑩ テンプレート（該当1種）
    format_examples(examples),         # ⑪ 良い例（直近5件）
])
```

管理画面で各セクションを個別編集可能。

### 2. Chrome拡張側の変更

#### 新規ファイル

| ファイル | 内容 |
|---------|------|
| `extension/src/shared/api-client.ts` | Cloud Run APIクライアント（gas-client.tsと同パターン） |
| `extension/src/sidepanel/components/GeneratePanel.ts` | API生成タブUI |

#### 変更ファイル

| ファイル | 変更内容 |
|---------|---------|
| `extension/src/shared/types.ts` | `GenerateRequest`, `GenerateResponse`, `BatchGenerateResponse`, `CompanyConfig` 型追加 |
| `extension/src/shared/constants.ts` | `STORAGE_KEYS` に `API_ENDPOINT`, `API_KEY` 追加 |
| `extension/src/shared/storage.ts` | API設定の保存/取得メソッド追加 |
| `extension/src/shared/templates.ts` | API取得対応（ローカル→API→キャッシュの3段フォールバック） |
| `extension/src/sidepanel/index.html` | 「API生成」タブ追加 |
| `extension/src/sidepanel/index.ts` | GeneratePanelの初期化 |
| `extension/src/popup/` | APIエンドポイント/APIキー設定UI追加 |

#### api-client.ts（gas-client.tsと同パターン）

```typescript
export const apiClient = {
  async generate(profile, company, options): Promise<GenerateResponse>,
  async generateBatch(profiles, company, options): Promise<BatchGenerateResponse>,
  async getCompanyConfig(company): Promise<CompanyConfig>,
  async testConnection(): Promise<{ success: boolean; error?: string }>,
};
```

#### GeneratePanel UIフロー

```
[抽出タブ] → プロフィール抽出済み
     ↓
[API生成タブ]
  抽出済み: 50件
  オプション: [初回/再送] [正社員強制]
  [一括生成ボタン]

  生成中... 30/50 (AI: 20, 型はめ: 8, 除外: 2)
  ████████████████░░░░  60%

  ✓ 完了 → [送信タブへ]（CandidateList.setCandidates()に渡す）
```

### 3. LCC複数職種の汎用化

`job_category` をファーストクラスの概念にする:
- ARK: `nurse` のみ
- LCC: `nurse`, `rehab`, `medical_office`
- Firestoreの prompt_sections / patterns / templates 全てに `job_category` フィールド
- 候補者の資格 → `qualification_rules` → `job_offer` → `job_category` で自動判定
- 新職種追加はFirestoreにデータ追加のみ（コード変更不要）

### 4. 初期データ投入（seed.py）

既存ファイルからFirestoreにデータ移行:
- `companies/ark-visiting-nurse/recipes.md` → patterns, qualification_modifiers, prompt_sections
- `companies/ark-visiting-nurse/templates.md` → templates, prompt_sections (行動指針等)
- `companies/lcc-visiting-nurse/recipes.md` → 同上（3職種分）
- `extension/src/shared/templates.ts` → templates (テンプレート本文)
- `extension/src/shared/constants.ts` → job_offers, validation_config
- `test/api-prompt-test/system-prompt.md` → global_config/prompt_sections の元ネタ

---

## Phase 3: 管理画面（後日）

```
admin/
├── src/
│   ├── pages/
│   │   ├── CompanyList.tsx            # 会社一覧
│   │   ├── CompanyDetail.tsx          # 会社詳細（職種タブ付き）
│   │   ├── SectionEditor.tsx          # プロンプトセクション編集（Markdownエディタ）
│   │   ├── TemplateEditor.tsx         # テンプレート編集
│   │   ├── PatternEditor.tsx          # 型はめパターン編集
│   │   └── ExampleList.tsx            # 良い例管理
│   └── auth/
│       └── GoogleAuth.tsx             # Google OAuth
```

- Cloud Runで同居（`/admin`パスにSPA配信）
- Google OAuthで社内アカウント限定
- 会社ごとに職種タブ → 各セクション個別編集

## Phase 4: 運用改善（後日）

- 生成ログの可視化ダッシュボード
- 生成品質の自動チェック（NG表現検出）
- オペレーター別統計

---

## 実装順序（Phase 1+2）

### Step 1: サーバー基盤
1. `server/` ディレクトリ初期化、FastAPI + Dockerfile
2. Pydanticモデル定義（CandidateProfile, Request/Response）
3. Firestore接続 + データモデル作成
4. `seed.py` で既存データをFirestoreに投入
5. APIキー認証ミドルウェア

### Step 2: 生成パイプライン
6. `filter.py` — フィルタリングロジック
7. `job_category_resolver.py` — 資格→職種判定
8. `template_resolver.py` — テンプレート種別判定
9. `pattern_matcher.py` — 型はめ（全型 + 資格修飾 + ローテーション）
10. `prompt_builder.py` — プロンプトセクション組み立て
11. `ai_generator.py` — Vertex AI Gemini Pro呼び出し
12. `text_builder.py` — buildFullScoutText
13. `orchestrator.py` — パイプライン統合 + 並列処理

### Step 3: APIルート + デプロイ
14. `/generate`, `/generate/batch` ルート実装
15. `/companies/{id}/config` ルート実装
16. Cloud Runデプロイ設定 + テスト

### Step 4: Chrome拡張統合
17. `api-client.ts` 作成
18. 型・ストレージ・定数の追加
19. `GeneratePanel.ts` 作成
20. サイドパネルにタブ追加
21. 設定画面にAPI設定UI追加
22. E2Eテスト: 抽出→API生成→送信

---

## 検証方法

1. **型はめパス**: seed.pyで投入したパターンと、既存recipes.mdの型A〜Gの出力が完全一致するか確認
2. **AI生成パス**: `test/api-prompt-test/` のダミープロフィールでGemini Proの出力品質を確認
3. **バッチ処理**: 20件のダミーデータで並列生成、タイムアウトしないこと
4. **Chrome拡張E2E**: 抽出→API生成タブ→送信タブまでの一連フロー動作確認
5. **フォールバック**: API接続失敗時に既存のCSVインポートフローが引き続き使えること

---

## 重要ファイル（参照先）

| 用途 | ファイルパス |
|------|------------|
| テンプレート・buildFullScoutText移植元 | `extension/src/shared/templates.ts` |
| CandidateProfile型定義 | `extension/src/shared/types.ts` |
| 求人・バリデーション設定 | `extension/src/shared/constants.ts` |
| APIクライアントパターン参考 | `extension/src/shared/gas-client.ts` |
| ARKプロンプト資産 | `companies/ark-visiting-nurse/recipes.md`, `templates.md` |
| LCCプロンプト資産（複数職種） | `companies/lcc-visiting-nurse/recipes.md`, `templates.md` |
| API用プロンプトテスト | `test/api-prompt-test/system-prompt.md` |
| GeneratePanel接続先 | `extension/src/sidepanel/components/ImportPanel.ts`, `CandidateList.ts` |
