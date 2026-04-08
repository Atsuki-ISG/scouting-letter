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
- [ ] **送信通数管理 Phase D-2**: Cloud Scheduler から `stale_quota_companies` を叩いて Google Chat 通知
- [ ] **送信通数管理 Phase D-3**: Gmail API 経由でジョブメドレー残数通知メールを自動 ingest（メール存在確認必要）
- [x] ~~送信履歴の行編集 (PATCH) UI~~ — 完了。`PATCH /admin/send_data/{company_id}/{row_index}` を追加し、管理画面の送信履歴タブに「編集」ボタンを追加。日時はimmutable、ヘッダードリフト時は409で拒否、`sheets_writer.update_cells_by_name` 経由で監査ログに前値スナップショットを残す。テスト12件すべてpass
- [ ] **送信ペース予測** — 月次目標 / 残数スナップショット履歴 / 当月の経過日数から「このペースだと月末何通」を算出してダッシュボードに表示。Phase A の履歴データが活きる
- [x] ~~分析結果・改善提案の顧客向けレポートエクスポート~~ — 完了。管理画面「分析」タブに「顧客向けレポート出力」ボタンを追加。`POST /api/v1/admin/export_report` が顧客向けに絞ったクロス集計（内部の パターン/生成パス/テンプレートVer/曜日/時間帯 は除外）+ AI所感（JSON形式に強制、AIっぽい表現禁止プロンプト）をサーバ側でMarkdown整形して返却。編集可能モーダルで .md ダウンロード / コピー / **Google Docs で開く** が選べる。Google Docs は事前に PM が共有した Drive フォルダに作成（env `REPORTS_DRIVE_FOLDER_ID`、SA を Editor 共有）。新ファイル: `server/db/docs_exporter.py`, `server/prompts/customer_report.md`, `server/tests/test_routes_admin_export_report.py` (8件 pass)
- [x] ~~一括テンプレート展開+確認UI~~ — 完了。2モード構成:
  - **モードA (テンプレート展開)**: 同会社/他会社の他職種・他型に展開、hunk単位の✓採用/✗却下 + target単位の3状態承認 (承認/保留/破棄)、承認分のみ `batch_update_templates` で Sheets に書き戻し
  - **モードB (プロンプト反映)**: 差分をプロンプトシート提案に変換して `改善提案` シートに pending 追加、既存の修正フィードバックタブで個別承認 → プロンプトシート反映
  - 差分は improve_template 既存の `computeLineDiff` / `computeWordDiff` を流用、`mergeAcceptedHunks` を共通ヘルパーに抽出
  - 「他会社含む」トグル + 5種のプリセット（同職種全型/同型全職種/同会社全て/全社同型/全て）
  - 副産物: バージョンインクリメント不具合を修正。`batch_update_templates` が header を strip しない・body 比較で改行表記揺れを吸収しない問題で version が "2" に張り付いていた。`_bump_template_body` helper に一本化、`update_cells_by_name` に `strict_columns` オプション追加してサイレント skip を禁止。テスト25件追加 (全 235 pass)

## 拡張

- [x] ~~お気に入り候補者の検出~~ — 完了済み（2026-04-02実装）。カード+overlay両方から検出、`is_favorite`フラグでサーバの「お気に入り」テンプレ選択にも連動、UIに★バッジ表示
- [ ] **スカウト返信の通知** — 返信が来たら通知する仕組み（メールフィルター設定はユーザ側で対応）

## インフラ・運用

- [ ] **Google Chat コスト通知** — Gemini API利用状況をGoogle Chat webhookで定期通知 → `memory/google-chat-cost-notification.md`

## コンテンツ改善

- [ ] **「お気に入り」テンプレの本文を専用化** — 現状、全社の `_お気に入り` テンプレ本文が `_初回` と完全同一。「気になる」を押した相手に対して「はじめまして / 突然のご連絡 / ご経歴を拝見し」が出てしまい違和感。冒頭2段落と末尾CTAを「感謝 + 面談確約強調 + 行動コスト低減」に書き換える。ark でドラフト3パターン用意済み（A:淡々/B:熱量/C:簡潔）→ 1社で承認後に他6社展開

## データ修正

- [ ] **LCC訪問看護: 医療事務の求人未登録** — テンプレートはあるが対応する求人がSheetsにないため、拡張の求人自動選択ができない
