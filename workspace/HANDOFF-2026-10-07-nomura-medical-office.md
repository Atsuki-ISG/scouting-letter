# 引き継ぎ — 野村病院 医療事務（パート）テンプレのサーバ反映（2026-10-07）

引き継ぎ元: クラウドセッション（Cloud Run の admin API へ接続不可のためサーバ反映だけ未実施）
ブランチ: `claude/nomura-medical-office-template` / PR: https://github.com/Atsuki-ISG/scouting-letter/pull/22 （ドラフト）

## 依頼の経緯

2026-10-06、PM（前三盛さん、cc 山本香里さん）から「野村病院はあと医療事務スタッフの採用だけ。支給の医療事務スカウト文をプロフィールでカスタムできるよう設定してほしい」。

## 状態

| 作業 | 状態 |
|---|---|
| ローカル資産（templates / recipes / profile / hearing / 議事録） | 完了。PR #22 に push 済み |
| ジョブメドレー求人票の取り込み（勤務 10〜15時・土日祝休み・未経験/無資格可 等） | 完了 |
| 求人ID の判明 | 医療事務パート **285319**（`/mc/285319/`）、薬剤師パート **1729377**（`/apo/1729377/`） |
| サーバ（Google スプレッドシート）反映 | 2026-10-07 完了（ローカルセッション）。途中で 500 が出たため `push_server.py` を行単位の有無判定＋間隔・再試行つきに修正して再実行。重複なし |
| 実サーバでの生成確認 | 2026-10-07 完了（`verify_generate.py` ALL OK、全文の改行復元も確認） |
| テンプレの求人票合わせ（#13） | 2026-10-08 完了。「1日4〜8時間ほど」→「10時〜15時」、「時給1,101円〜」→「時給1,101円」、「社会保険完備」→「労災保険あり (加入保険は法定通り)」。サーバ反映・生成確認済み。クライアントへの共有は未 |
| PR #22 のマージ | 未実施（ドラフトのまま） |

サーバに何も入っていないため、**現時点で医療事務は生成できない**（テンプレート未設定で filtered_out になる）。薬剤師はテンプレ登録済みで生成可能、求人未登録の警告のみ。

## 次のセッションでやること

前提: Cloud Run（`scout-api-1080076995871.asia-northeast1.run.app`）に接続できる環境。あっきーさんの Mac のローカルセッション、またはネットワーク許可ドメインにこのホストを追加したクラウド環境。

```bash
git fetch origin claude/nomura-medical-office-template
git checkout claude/nomura-medical-office-template

# 1. サーバ反映（冪等。既存行はスキップするので再実行可）
python3 workspace/nomura-medical-office/push_server.py --dry-run
#    末尾が「added: templates=3 patterns=10 prompts=3 keywords=3 job_offers=2」なら想定どおり
python3 workspace/nomura-medical-office/push_server.py

# 2. 反映結果を目視
python3 .claude/skills/server-admin/scripts/server_admin.py show nomura-hospital templates
python3 .claude/skills/server-admin/scripts/server_admin.py show nomura-hospital job_offers
python3 .claude/skills/server-admin/scripts/server_admin.py diff nomura-hospital

# 3. 実サーバで生成を試す（ダミー3名。Gemini を1〜2回呼ぶ）
python3 workspace/nomura-medical-office/verify_generate.py
#    最後に「ALL OK」が出ればよい
```

### push_server.py が書き込むもの

| シート | 内容 | 行数 |
|---|---|---|
| テンプレート | medical_office の パート_初回 / パート_再送 / パート_お気に入り（`templates.md` の「医療事務 パート …」見出し直後のコードブロック。改行は `\n` にエスケープ） | 3 |
| パターン | medical_office の型A〜G（`recipes.md` の「## 医療事務」から `server_admin.parse_lcc_recipes` で抽出） | 10 |
| プロンプト | medical_office の station_features / education / ai_guide | 3 |
| 職種キーワード | nomura-hospital 固有「医療事務」(qualification, desired)・「受付」(desired) → medical_office。`POST job_category_keywords/append` を使用 | 3 |
| 求人 | 285319（medical_office・パート）、1729377（pharmacist・パート） | 2 |

### 確認スクリプトの判定内容（verify_generate.py）

- job_category が medical_office、generation_path が filtered_out でない
- job_offer_id が 285319、警告に「求人未登録」「テンプレート未設定」がない
- full_scout_text にプレースホルダが残っていない
- パーソナライズ文に「4〜8時間」「社会保険完備」「寮」「引越し」「夜勤」「月給」がない

生成ログシートに `TEST-MO-001〜003` の3行が残る。気になれば管理画面から消す。

## 未検証で、詰まりそうな点

- **職種キーワードの一覧取得**: `push_server.py` は既存チェックのため `GET admin/job_category_keywords` を呼ぶ。失敗しても警告を出して追加に進む作り。重複行が入った場合は管理画面で削除する（判定結果は変わらない）
- **テンプレートの改行**: 本文の改行を `\n` 文字列にして POST している。`sheets_client.py` が読み込み時に `\\n` → 改行に戻す前提。`show` で本文が1行に潰れて見えるのは正常。生成結果の full_scout_text で改行が復元されていることを確認する
- **プロンプト order**: station_features=2 / education=3 / ai_guide=8（LCC の medical_office と同じ）
- **求人名**: 拡張は求人IDではなく「医療事務 or 受付」＋「パート or バイト」でジョブメドレーの求人プルダウンを選ぶ。求人名はプルダウンに同職種が複数ある時の絞り込みにしか使わない。野村病院の医療事務求人は1件なので影響なし
- **求人IDの裏取り**: URL の形（`/mc/` = 医療事務、`/apo/` = 薬剤師の求人ページ）から判断。ページ内容とは照合していない

## 実サーバ確認のあとに残るもの

- **拡張での確認**: 拡張で野村病院を選び職種「医療事務」を指定して数名生成 → 送信画面で求人欄に医療事務パートが自動で入るか
- **オペレーターへの周知**: 医療事務のスカウトは拡張で職種「医療事務」を明示指定する。看護師等の資格を持つ候補者は資格優先で看護師に判定されるため
- **PR #22**: ドラフト解除・マージ（server/ の変更はないのでデプロイは走らない）
- **クライアント確認（`companies/nomura-hospital/hearing.md`）**
  - #13（P0）支給スカウト文の「1日4〜8時間ほど」「社会保険完備」が求人票（10〜15時・労災保険／加入保険は法定通り）と食い違う。週20時間未満なら社保対象外で誇大表示の恐れ。テンプレは支給文どおり据え置き中
  - #14 求人票内の記載ゆれ（定年 60/65 と 65/75、寮完備 と 社宅・寮なし）
  - #12 募集人数・レセプト業務の有無
  - PM判断C: 看護師・薬剤師・管理栄養士のスカウトを止めるか（求人シートの active=FALSE）

## 主要ファイル

| ファイル | 内容 |
|---|---|
| `companies/nomura-hospital/templates.md` | 「# 医療事務（パート）」セクション（フィルタ・テンプレ3種）、末尾の接点例 |
| `companies/nomura-hospital/recipes.md` | 「## 医療事務」セクション（特色・ルール・型A〜G・AI生成ガイド） |
| `companies/nomura-hospital/profile.md` | 「### 医療事務/受付（パート・バイト）」（求人票ベースの確定情報） |
| `companies/nomura-hospital/hearing.md` | 確認事項 #12〜#14、PM判断C、反映済み履歴 |
| `companies/nomura-hospital/meetings/2026-10_医療事務スカウト文.md` | 支給文原文・変更点・求人票取り込み・食い違い一覧 |
| `workspace/nomura-medical-office/push_server.py` | サーバ反映スクリプト |
| `workspace/nomura-medical-office/verify_generate.py` | 実サーバ生成の確認スクリプト |
