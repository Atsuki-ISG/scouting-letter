# デプロイ手順書（scout-api / Cloud Run）

> このドキュメントは **実運用の現状** を記述する。手順が実態と食い違うと本番を壊すため、
> deploy.yml・config.py を変更したら必ずここも更新すること。

## 概要

| 項目 | 値 |
|------|----|
| サービス名 | `scout-api`（Cloud Run） |
| リージョン | `asia-northeast1`（東京） |
| GCPプロジェクト | `scout-generation-490709` |
| デプロイ方法 | **GitHub Actions 自動**（`server/**` を main に push） |
| 認証（API） | `X-API-Key` ヘッダー = `ADMIN_PASSWORD` 1本（GitHub Secret） |
| データソース | Google スプレッドシート（6シート、ID は deploy.yml に記載） |
| 生成AI | Vertex AI 経由の Gemini（本番は `GEMINI_API_KEY` を使わず、ランタイムSAのADC認証） |
| インスタンス | min-instances 2 / メモリ 1Gi / リクエストtimeout 300s |
| 設定キャッシュ | `CACHE_TTL_SECONDS=300`（最大5分で全インスタンス自動反映） |

真実のソースは 2 ファイル:
- インフラ設定（env・リージョン・インスタンス）→ [.github/workflows/deploy.yml](../../.github/workflows/deploy.yml)
- アプリの既定値 → [config.py](config.py)

---

## 通常のデプロイ（自動）

**`server/` 配下を変更して main に push するだけ**。GitHub Actions が Cloud Run にデプロイする。

```bash
git add server/...
git commit -m "..."
git push origin main   # → .github/workflows/deploy.yml が起動
```

- トリガー: `server/**` または `.github/workflows/deploy.yml` の変更を main に push。手動起動は GitHub の Actions 画面から `workflow_dispatch` でも可。
- ワークフローは Workload Identity Federation（`WIF_PROVIDER` / `WIF_SERVICE_ACCOUNT`）で GCP 認証し、`gcloud run deploy scout-api --source .` を実行する。
- ビルドは `server/Dockerfile`。`server/.dockerignore` で `sa-key.json` 等を除外している。
- 進捗・失敗は GitHub の **Actions** タブで確認。`gcloud` をローカルで叩く必要は通常ない。

---

## 環境変数（deploy.yml で管理）

env は deploy.yml の `--update-env-vars` に列挙されている。**`--update-env-vars` はマージ更新**（既存を消さない）なので、手でデプロイするときも既存 env は保持される。

| 変数 | 値 / 出所 | 用途 |
|------|-----------|------|
| `SPREADSHEET_ID` | deploy.yml に直書き | 設定シートのID |
| `PROJECT_ID` | `scout-generation-490709` | Vertex AI プロジェクト |
| `LOCATION` | `global` | Vertex AI のロケーション（Cloud Run リージョンとは別物） |
| `GEMINI_MODEL` | `gemini-3-flash-preview` | 生成モデル |
| `GEMINI_FALLBACK_MODELS` | `gemini-2.5-flash` | 429時のフォールバック |
| `GEMINI_THINKING_BUDGET` | `2048` | thinking トークン上限 |
| `ADMIN_PASSWORD` | **GitHub Secret** | API/管理画面の認証キー |
| `GOOGLE_CHAT_WEBHOOK_URL` | **GitHub Secret** | コストアラート通知先 |
| `REPORTS_DRIVE_FOLDER_ID` | deploy.yml に直書き | レポート出力先 Drive フォルダ |
| `CACHE_TTL_SECONDS` | `300` | 設定キャッシュの有効期間（秒） |

- `GEMINI_API_KEY` は本番では **削除**（`--remove-env-vars`）。これにより ai_generator が Vertex AI 経路（ADC 認証）になる。ローカルで Developer API を使いたいときだけ設定する。
- `LATEST_EXTENSION_VERSION` は未設定なら config.py の既定（拡張の現行版）を使う。拡張を更新配布したら config.py かこの env を合わせて上げる。

GitHub Secrets（Settings → Secrets and variables → Actions）:
`ADMIN_PASSWORD`, `GOOGLE_CHAT_WEBHOOK_URL`, `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT`。

---

## 認証（現状）

- API も管理画面も、認証は `X-API-Key: <ADMIN_PASSWORD>` の **1本のみ**（[auth/api_key.py](auth/api_key.py)）。
- オペレーター（拡張）と管理者（管理画面）が同じキーを共有する。**このキーで管理系CRUD・破壊的操作まで全部叩ける**点は認識しておくこと（生成用と管理用の分離は現状していない）。
- キーを変えるときは GitHub Secret `ADMIN_PASSWORD` を更新 → 再デプロイ → 拡張・管理画面の設定にも新キーを配布。

---

## 設定（スプレッドシート）変更の反映

コードの再デプロイは不要。

- **自動**: `CACHE_TTL_SECONDS=300` のため、シート変更・新規行は **最大5分で全インスタンスに自動反映**される。
- **即時**: すぐ反映したいときは reload を叩く。ただし min-instances 2 なので **1回のreloadは1インスタンスにしか当たらない**。確実に全台へ効かせたいなら数回叩くか、5分待って自動反映に任せる。

```bash
curl -X POST -H "X-API-Key: <ADMIN_PASSWORD>" \
  https://<service-url>/api/v1/reload
```

管理画面からの編集は Sheets に直接書き込まれる。反映は上記と同じ（TTLで自動 or リロード）。

---

## 緊急時の手動デプロイ

GitHub Actions が使えないときのみ。**deploy.yml と同じフラグを使うこと**（env を落とさないため `--update-env-vars`。`--set-env-vars` は全置換になり ADMIN_PASSWORD 等が消えるので使わない）。

```bash
cd server
gcloud run deploy scout-api \
  --source . \
  --region asia-northeast1 \
  --allow-unauthenticated \
  --update-env-vars "CACHE_TTL_SECONDS=300"   # 変えたい env だけをマージ指定 \
  --memory 1Gi --timeout 300 --min-instances 2 --quiet
```

ADMIN_PASSWORD 等の Secret 由来 env は既に Cloud Run 側に載っているので、マージ更新なら再指定不要。

---

## 初回セットアップ（一度きり・参照用）

新しい GCP プロジェクトで一から立てる場合のみ。既存の本番では不要。

1. GCP プロジェクト作成 + 課金有効化
2. API 有効化: `run` / `artifactregistry` / `aiplatform` / `sheets`
   ```bash
   gcloud services enable run.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com sheets.googleapis.com
   ```
3. Cloud Run のランタイムSA（deploy.yml では未指定＝デフォルトの Compute SA）に権限付与:
   - `roles/aiplatform.user`（Gemini 呼び出し）
   - スプレッドシートを **そのSAのメールに閲覧者共有**（Sheets API はIAMではなく共有設定で読む）
4. スプレッドシート作成（6シート）。列見本:
   | シート | 主な列 |
   |--------|--------|
   | テンプレート | company, job_category, type, body, version |
   | パターン | company, job_category, pattern_type, employment_variant, template_text, feature_variations |
   | プロンプト | company, section_type, job_category, order, content |
   | 求人 | company, job_category, id, name, label, employment_type, active |
   | バリデーション | company, age_min, age_max, qualification_rules, category_config |
   | プロフィール | company, content, detection_keywords, display_name ほか |
5. GitHub Secrets（`ADMIN_PASSWORD` / `GOOGLE_CHAT_WEBHOOK_URL` / `WIF_PROVIDER` / `WIF_SERVICE_ACCOUNT`）を設定
6. deploy.yml の `SPREADSHEET_ID` / `PROJECT_ID` を新環境に合わせる
7. main に push → 自動デプロイ

> ローカルテスト用のSA鍵（`sa-key.json`）は `.gitignore` 済み・`.dockerignore` 済み。**本番イメージには含めない**（Cloud Run はランタイムSAで自動認証）。

---

## ローカル開発

```bash
cd server
export GOOGLE_APPLICATION_CREDENTIALS=sa-key.json   # ローカルはSA鍵でADC
export PROJECT_ID=scout-generation-490709
export SPREADSHEET_ID=<スプレッドシートID>
export ADMIN_PASSWORD=dev-test-key                   # ローカルの認証キー
# 生成もローカルで試すなら Developer API を使う:
# export GEMINI_API_KEY=<キー>
pip install -r requirements.txt
uvicorn main:app --reload --port 8080
```

http://localhost:8080/docs で Swagger UI。テスト実行は `python3 -m pytest`。

---

## Cloud Scheduler（残数鮮度チェック通知）

毎朝 9:00 JST に残数スナップショットの鮮度を確認して通知:

```bash
SERVICE_URL=$(gcloud run services describe scout-api --region asia-northeast1 --format='value(status.url)')
gcloud scheduler jobs create http daily-stale-quota \
    --schedule="0 9 * * *" --time-zone="Asia/Tokyo" \
    --http-method=POST \
    --uri="${SERVICE_URL}/api/v1/admin/cron/stale-quota" \
    --headers="X-API-Key=<ADMIN_PASSWORD>" \
    --location="asia-northeast1"
```

- 該当会社がゼロなら通知しない（朝のノイズ防止）
- 閾値変更: `?max_hours=48`
- 手動実行: `gcloud scheduler jobs run daily-stale-quota --location=asia-northeast1`

---

## コスト目安

| サービス | 月額目安 |
|---------|---------|
| Cloud Run（min-instances 2 常時起動） | 数百円〜（常時2台のアイドル課金あり） |
| Vertex AI (Gemini Flash) | ~$0.5/月（3,000件生成想定） |
| Google Sheets / Drive API | 無料 |
| **合計** | **数百円〜/月** |

> min-instances 2 はコールドスタート回避のため。コスト削減より応答安定を優先している。

---

## トラブルシューティング

**Cloud Run のログ**
```bash
gcloud run services logs read scout-api --region asia-northeast1 --limit 50
```
- 旧版拡張の警告 `Outdated extension: version=...` もここに出る。

**設定を変えたのに反映されない**
- min-instances 2 のため reload は1台にしか効かない。5分待つ（自動反映）か複数回 reload。

**スプレッドシート読み込みエラー**
- ランタイムSAのメールにスプレッドシートが共有されているか / `SPREADSHEET_ID` が正しいか。

**Gemini エラー**
- Vertex AI API 有効化 / ランタイムSAに `roles/aiplatform.user` / `LOCATION` と `PROJECT_ID` が正しいか。
- 本番で `GEMINI_API_KEY` が残っていると Developer API 経路に落ちる。deploy.yml の `--remove-env-vars` を確認。

**デプロイが動かない**
- GitHub Actions タブで失敗ログを確認。`WIF_PROVIDER`/`WIF_SERVICE_ACCOUNT` Secret とパス条件（`server/**`）を確認。
