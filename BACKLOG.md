# バックログ

やりたいこと・未対応の課題を一元管理する。
優先度や着手タイミングはディレクター判断。

---

## 表示・UI

- [x] ~~職種カテゴリ・会社名を日本語表記に統一~~ — 完了。pipeline メッセージ・拡張ドロップダウン・確認ポップアップ・管理画面を日本語化。会社の display_name はSheetsプロフィール列で管理（既存7社の display_name 投入は手動作業）

## 改善サイクル

- [x] ~~Phase 3: 職種カテゴリ解決失敗の自動提案ワークフロー (集計＋承認で1行追加)~~ — 完了。`GET /admin/job_category_failures` で 生成ログ の `failure_*` を (会社, stage, 候補カテゴリ) でグルーピングし、サンプルtextから候補トークンを抽出。新タブ「職種解決失敗」で各サンプル横の「候補抽出」ボタン → モーダルでキーワード/職種/対象会社を確認 → `POST /admin/job_category_keywords/append` で職種キーワードシートに1行追記。Stage 5 (AI フォールバック) の判断はこのタブで観察してから
- [x] ~~修正フィードバックの集約と改善サイクル (Phase A: 蓄積+一覧UI)~~ — 完了。即時送信API・Sheets蓄積・管理画面新タブ・取込/スキップ/差戻
- [x] ~~修正フィードバック Phase B~~ — 完了。3ターゲット対応:
  - **第一弾 (職種キーワード)**: append-only。Gemini が `keyword/job_category/scope_company` を提案 → 承認で `職種キーワード` シートに append、紐付く修正フィードバックを自動で取込済に
  - **第二弾 (プロンプト追加)**: append-only。`station_features/education/ai_guide` のみ対象。content の改行を Sheets 用に `\n` リテラル化して append
  - **第三弾 (型はめパターン)**: 既存行 update。Gemini が `pattern_type/job_category/employment_variant/new_feature` を提案 → 承認で対象 pattern 行の `feature_variations` に `|` 区切りで追記。`update_cells_by_name` 経由で監査ログに前値スナップショット
  - 管理画面: 修正フィードバックタブにターゲット別グループで提案表示。承認ボタン押下時にそのターゲット用フィールドを読み取って overrides 送信。生成時はプロンプトでターゲット選択。テスト19件（全79件pass）

## 管理画面

- [x] ~~送信通数の詳細管理~~ — 完了。Phase A〜D で「更新の仕組み」を改善
  - A: 残数スナップショット履歴化（送信実績履歴シート + ミニ折れ線）
  - B: 送信履歴の手動修正・削除UI（管理画面の送信履歴タブ）
  - C: 手動送信を拡張で検知してサーバに記録（single-send-tracker → record_manual_send API）
  - D-1: 古い残数の可視化（dashboard staleness バナー + 行ハイライト）
- [x] ~~送信通数管理 Phase D-2~~ — 完了。`POST /api/v1/admin/cron/stale-quota` を追加、Cloud Scheduler で 9:00 JST に叩く。該当ゼロなら無通知（朝のノイズ防止）。セットアップ手順は `server/DEPLOY.md` の「Cloud Scheduler 登録」節
- [x] ~~送信履歴の行編集 (PATCH) UI~~ — 完了。`PATCH /admin/send_data/{company_id}/{row_index}` を追加し、管理画面の送信履歴タブに「編集」ボタンを追加。日時はimmutable、ヘッダードリフト時は409で拒否、`sheets_writer.update_cells_by_name` 経由で監査ログに前値スナップショットを残す。テスト12件すべてpass
- [x] ~~分析結果・改善提案の顧客向けレポートエクスポート~~ — 完了。管理画面「分析」タブに「顧客向けレポート出力」ボタンを追加。`POST /api/v1/admin/export_report` が顧客向けに絞ったクロス集計（内部の パターン/生成パス/テンプレートVer/曜日/時間帯 は除外）+ AI所感（JSON形式に強制、AIっぽい表現禁止プロンプト）をサーバ側でMarkdown整形して返却。編集可能モーダルで .md ダウンロード / コピー / **Google Docs で開く** が選べる。Google Docs は事前に PM が共有した Drive フォルダに作成（env `REPORTS_DRIVE_FOLDER_ID`、SA を Editor 共有）。新ファイル: `server/db/docs_exporter.py`, `server/prompts/customer_report.md`, `server/tests/test_routes_admin_export_report.py` (8件 pass)
- [x] ~~一括テンプレート展開+確認UI~~ — 完了。2モード構成:
  - **モードA (テンプレート展開)**: 同会社/他会社の他職種・他型に展開、hunk単位の✓採用/✗却下 + target単位の3状態承認 (承認/保留/破棄)、承認分のみ `batch_update_templates` で Sheets に書き戻し
  - **モードB (プロンプト反映)**: 差分をプロンプトシート提案に変換して `改善提案` シートに pending 追加、既存の修正フィードバックタブで個別承認 → プロンプトシート反映
  - 差分は improve_template 既存の `computeLineDiff` / `computeWordDiff` を流用、`mergeAcceptedHunks` を共通ヘルパーに抽出
  - 「他会社含む」トグル + 5種のプリセット（同職種全型/同型全職種/同会社全て/全社同型/全て）
  - 副産物: バージョンインクリメント不具合を修正。`batch_update_templates` が header を strip しない・body 比較で改行表記揺れを吸収しない問題で version が "2" に張り付いていた。`_bump_template_body` helper に一本化、`update_cells_by_name` に `strict_columns` オプション追加してサイレント skip を禁止。テスト25件追加 (全 235 pass)

## 拡張

- [x] ~~お気に入り候補者の検出~~ — 完了済み（2026-04-02実装）。カード+overlay両方から検出、`is_favorite`フラグでサーバの「お気に入り」テンプレ選択にも連動、UIに★バッジ表示
- [x] ~~スカウト返信の通知~~ — 完了。メール転送で対応
- [ ] **他媒体向けChrome拡張の作成（ウェルミー / コメディカル.com 等）** — 現状はジョブメドレー専用。医療・介護系の他媒体にも展開する。
  - **スコープ**: 超シンプル仕様。**抽出 / 生成（型はめのみ）/ 送信** の3機能に絞る
    - AI生成は載せない（型はめ固定）→ Gemini 呼び出し不要、サーバ負荷・応答遅延・生成ゆらぎの問題を回避
    - お気に入り検出・会社自動判定・高度なバリデーション等のジョブメドレー版で積み上げた機能は **一旦載せない**。必要になったら段階的に足す
  - **配布単位**: **会社ごとに別ビルドで配布**（1拡張=1会社）
    - 会社選択ドロップダウンを作らず、会社ID をビルド時に埋め込む
    - `extension/src/config/company.ts` 的な定数に `COMPANY_ID` / `MEDIUM` を注入する簡易ビルド
    - オペレーターが会社を取り違える事故を構造的に防ぐ & UI がさらにシンプルになる
    - 配布 zip は `shared/{company_id}-{medium}-extension-YYYYMMDD.zip` の命名で世代管理
  - **必要作業**:
    - 各媒体のスカウト画面・候補者一覧のDOM調査（セレクタ・非同期読み込みタイミング）
    - プロフィール抽出ロジックの媒体別分岐（`extension/src/content/extractors/` を媒体別ファイルに分割）
    - 型はめAPI（`/api/v1/generate` の `section_mode=template_only` 的な切り替え、または新エンドポイント）
    - 送信アシストの媒体別対応
    - manifest の `matches` に各媒体ドメインを追加
    - ビルドスクリプトに `--company` `--medium` フラグを足して manifest の `name` / `config/company.ts` を差し替え

## インフラ・運用

- [x] ~~Google Chat コスト通知~~ — 完了（2026-03-24デプロイ済み）。`server/monitoring/` に実装、日次レポート9:00 JST + $100超えアラート

## 管理画面 (UX)

- [x] ~~テンプレート改善提案の編集可能化~~ — 完了。diffActions に「編集 / 下書き保存」ボタン追加、編集モードに入ると採用済みhunkをマージした本文が textarea に出て直接編集可能。編集内容は `POST /api/v1/admin/improvement_drafts` でサーバ（`改善下書き` シート）に upsert 保存、ブラウザを閉じても復元可能。テンプレート選択時に下書きがあれば「🗒 下書きあり（N分前）」バッジが出る。適用時に下書きは `status=applied` に soft delete。テスト17件追加

## コンテンツ改善

- [ ] **野村病院のスカウト文章の改善** — 現行テンプレートの見直し。返信率・応募率が期待より低い or 読みにくい箇所がある想定。`/analyze-replies nomura-hospital` で傾向を見てから improve_template で改善提案 → 手動で反映



- [x] ~~「お気に入り」テンプレの本文を専用化~~ — 完了。全6社15行を更新/追加。冒頭2段落は「この度は、〇〇に興味をお寄せいただき、ありがとうございます」+「『気になる』をお知らせくださったことを踏まえ」に統一、CTA は「本スカウトを受け取られた方には**面談確約**」に統一（お気に入りだから面談確約ではなく、本スカウト受信者全員に面談確約の扱い）。
  - ark/ichigo/chigasaki/an は ark パターンで冒頭＋CTA 差し替え（計7行）
  - LCC は既存の「プレミアムスカウト」設計を活かし、冒頭に「お気に入り+書類選考スキップ」ヘッダー＋感謝段落を追加、各行の職種別本文はそのまま温存（7行）
  - ネオ・サミット湯河原は `正社員_お気に入り` 行が未作成だったため新規追加（row 57）
  - **注意**: サーバの `POST /templates` は追記成功後の `sheets_client.reload()` で 500 を返すケースあり。`show` で書き込み結果を確認すること。重複行ができたら delete で削除

