# デプロイ手順書

## 前提

- Googleアカウント（Google Workspace）を持っている
- `gcloud` CLIがインストール済み（未インストールなら https://cloud.google.com/sdk/docs/install）

---

## Step 1: GCPプロジェクト作成

### 1-1. Google Cloud Consoleにアクセス

https://console.cloud.google.com/ にアクセスしてログイン。

### 1-2. プロジェクト作成

1. 画面上部のプロジェクト選択メニュー → 「新しいプロジェクト」
2. プロジェクト名: `scout-generation`（任意）
3. 「作成」をクリック
4. 作成されたプロジェクトに切り替わったことを確認

### 1-3. 課金を有効化

1. ナビゲーションメニュー → 「お支払い」
2. 請求先アカウントをリンク（初回は無料トライアル$300あり）

### 1-4. gcloud CLIの設定

```bash
gcloud auth login
gcloud config set project scout-generation
```

---

## Step 2: 必要なAPIの有効化

Google Cloud Consoleの「APIとサービス」→「ライブラリ」から以下を有効化。
またはコマンドで一括有効化:

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com \
  sheets.googleapis.com
```

| API | 用途 |
|-----|------|
| Cloud Run Admin API | Cloud Runデプロイ |
| Artifact Registry API | Dockerイメージ保存 |
| Vertex AI API | Gemini Pro呼び出し |
| Google Sheets API | スプレッドシートからの設定読み込み |

---

## Step 3: サービスアカウント作成

Cloud Runのサービスアカウントに必要な権限を付与する。

### 3-1. サービスアカウント作成

```bash
gcloud iam service-accounts create scout-api \
  --display-name="Scout Generation API"
```

### 3-2. 権限付与

```bash
PROJECT_ID=$(gcloud config get-value project)

# Vertex AI（Gemini呼び出し）
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:scout-api@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

### 3-3. サービスアカウントキー作成（ローカルテスト用）

```bash
gcloud iam service-accounts keys create server/sa-key.json \
  --iam-account=scout-api@${PROJECT_ID}.iam.gserviceaccount.com
```

> ⚠️ `sa-key.json` は `.gitignore` に追加すること。Cloud Run上では不要（自動認証される）。

---

## Step 4: Google スプレッドシートの準備

### 4-1. スプレッドシート作成

Google スプレッドシートで新規作成し、以下の6シートを作る:

| シート名 | 列（1行目にヘッダー） |
|---------|----------------------|
| テンプレート | company, job_category, type, body |
| パターン | company, job_category, pattern_type, employment_variant, template_text, feature_variations |
| 資格修飾 | company, qualification_combo, replacement_text |
| プロンプト | company, section_type, job_category, order, content |
| 求人 | company, job_category, id, name, label, employment_type, active |
| バリデーション | company, age_min, age_max, qualification_rules |

### 4-2. データ入力のポイント

- **body / template_text / content**: 改行は `\n` で表記
- **feature_variations**: `|` 区切り（例: `特色A|特色B|特色C`）
- **qualification_combo**: カンマ区切り（例: `看護師,保健師`）
- **qualification_rules**: JSON形式（例: `[{"jobOfferId":"1550716","required":["看護師","准看護師"],"excluded":[]}]`）
- **active**: `TRUE` または `FALSE`

### 4-3. サービスアカウントにスプレッドシートを共有

1. スプレッドシートの「共有」ボタンをクリック
2. サービスアカウントのメールアドレスを入力:
   `scout-api@{PROJECT_ID}.iam.gserviceaccount.com`
3. 権限: **閲覧者**（読み取りのみで十分）
4. 「送信」

### 4-4. スプレッドシートIDをメモ

スプレッドシートのURL:
`https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit`

`{SPREADSHEET_ID}` の部分をメモする。

---

## Step 5: Cloud Runにデプロイ

### 5-1. 環境変数を準備

```bash
export PROJECT_ID=$(gcloud config get-value project)
export SPREADSHEET_ID="ここにスプレッドシートID"
export API_KEY_DEV="開発用の任意の文字列"
export API_KEYS="オペレーター用キー1,オペレーター用キー2"
```

### 5-2. ソースからデプロイ（Dockerfileあり）

```bash
cd server/

gcloud run deploy scout-api \
  --source . \
  --region asia-northeast1 \
  --service-account scout-api@${PROJECT_ID}.iam.gserviceaccount.com \
  --set-env-vars "PROJECT_ID=${PROJECT_ID},SPREADSHEET_ID=${SPREADSHEET_ID},API_KEY_DEV=${API_KEY_DEV},API_KEYS=${API_KEYS},LOCATION=asia-northeast1" \
  --allow-unauthenticated \
  --memory 512Mi \
  --timeout 120 \
  --min-instances 0 \
  --max-instances 5
```

- `--allow-unauthenticated`: Chrome拡張からAPIキー認証で呼ぶため、IAM認証は不要
- `--region asia-northeast1`: 東京リージョン
- 初回はArtifact Registry APIの有効化を聞かれるので `y` で承認

### 5-3. デプロイ完了確認

デプロイ完了後、URLが表示される:
```
Service URL: https://scout-api-xxxxx-an.a.run.app
```

### 5-4. 動作確認

```bash
# ヘルスチェック
curl https://scout-api-xxxxx-an.a.run.app/health

# 設定読み込み確認（API_KEY_DEVで認証）
curl -H "X-API-Key: ${API_KEY_DEV}" \
  https://scout-api-xxxxx-an.a.run.app/api/v1/companies/ark-visiting-nurse/config

# 設定リロード
curl -X POST -H "X-API-Key: ${API_KEY_DEV}" \
  https://scout-api-xxxxx-an.a.run.app/api/v1/reload
```

---

## Step 6: 管理画面の確認

デプロイ後、ブラウザで以下にアクセス:

```
https://scout-api-xxxxx-an.a.run.app/admin/
```

1. 初回アクセス時にAPIキーの入力を求められる → Step 5で設定したキーを入力
2. 会社を選択
3. 各タブ（テンプレート、パターン、求人等）でデータを確認・編集可能

管理画面からの編集はGoogleスプレッドシートに直接反映される。
スプレッドシートを直接編集した場合は「キャッシュ更新」ボタンを押す。

---

## Step 7: Chrome拡張の設定

1. Chrome拡張のアイコンをクリック → ポップアップ
2. **API設定**セクション:
   - APIエンドポイント: `https://scout-api-xxxxx-an.a.run.app`
   - APIキー: Step 5で設定したキー
3. 「接続テスト」で成功を確認

---

## Step 8: ローカルテスト（任意）

Cloud Runにデプロイする前にローカルで動作確認したい場合:

```bash
cd server/

# 環境変数設定
export GOOGLE_APPLICATION_CREDENTIALS=sa-key.json
export PROJECT_ID=scout-generation
export SPREADSHEET_ID=ここにスプレッドシートID
export API_KEY_DEV=test-key

# 依存インストール
pip install -r requirements.txt

# 起動
uvicorn main:app --reload --port 8080
```

ブラウザで http://localhost:8080/docs にアクセスするとSwagger UIでAPI仕様を確認・テストできる。

---

## 設定変更時の反映方法

### スプレッドシートのデータを変更した場合

コードの再デプロイ不要。以下のいずれかで反映:

```bash
# 方法1: reload APIを叩く
curl -X POST -H "X-API-Key: ${API_KEY_DEV}" \
  https://scout-api-xxxxx-an.a.run.app/api/v1/reload

# 方法2: CACHE_TTL_SECONDSを設定（例: 300秒）している場合は自動反映
```

### コードを変更した場合

```bash
cd server/
gcloud run deploy scout-api --source . --region asia-northeast1
```

---

## コスト目安

| サービス | 月額目安 |
|---------|---------|
| Cloud Run | 無料枠内（月200万リクエストまで無料） |
| Vertex AI (Gemini 2.0 Flash) | ~$0.5/月（3,000件AI生成想定） |
| Google Sheets API | 無料 |
| Artifact Registry | ~$0.1/月（イメージ保存） |
| **合計** | **~$1/月** |

---

## トラブルシューティング

### Cloud Runのログを見る

```bash
gcloud run services logs read scout-api --region asia-northeast1 --limit 50
```

### スプレッドシートの読み込みエラー

- サービスアカウントのメールアドレスがスプレッドシートに共有されているか確認
- SPREADSHEET_ID が正しいか確認

### Gemini APIのエラー

- Vertex AI APIが有効化されているか確認
- サービスアカウントに `roles/aiplatform.user` が付与されているか確認
- リージョン（LOCATION）が正しいか確認
