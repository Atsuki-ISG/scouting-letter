---
name: csv-scout
description: プロフィールCSVから一括でスカウト文を生成し、Chrome拡張インポート用CSVとして出力
argument-hint: [会社名] [CSVパス] [resend?] [seishain?]
---

# バッチスカウト文生成スキル

プロフィール抽出済みCSVから一括でパーソナライズ文を生成し、Chrome拡張の送信アシストにインポートできるCSV形式で元ファイルを更新します。

## 引数

- 第1引数: 会社名（省略可）例: `ark-visiting-nurse`
  - 省略時: `companies/` 配下のディレクトリ一覧を確認し、1社のみなら自動選択、複数あればユーザーに選択を促す
- 第2引数: CSVファイルパス（省略可）
  - 省略時: `~/Downloads/` 内の `profiles_*.csv` で最新のファイルを自動検出
- オプション: `resend` → 再送モード、`seishain` → 正社員テンプレート強制

例:
```
/csv-scout
/csv-scout resend
/csv-scout ark-visiting-nurse /Users/aki/Downloads/profiles.csv
/csv-scout ark-visiting-nurse /Users/aki/Downloads/profiles.csv resend
```

## 実行手順

### 1. 引数パース

引数 `$ARGUMENTS` から会社名・CSVパス・オプションを取得。

**会社名の自動判定**:
1. 引数に会社名が含まれていない場合（引数がCSVパスで始まる場合）、`companies/` 配下のディレクトリを `ls` で一覧取得
2. 1社のみ → その会社を自動選択
3. 複数社 → ユーザーに選択を促す
4. 0社 → エラー

**CSVパスの自動判定**:
引数がファイルパス（`/` で始まる or `.csv` を含む）なら会社名ではなくCSVパスと判定。

**CSVパス省略時の自動検出**:
引数にCSVパスが含まれない場合:
1. `ls -t ~/Downloads/profiles_*.csv | head -1` で最新のプロフィールCSVを検出
2. 見つかったら「`[ファイル名]` を使用します」と表示して続行
3. 見つからなければエラー

### 2. ファイル読み込み（最小限）

```
- companies/[会社名]/templates.md
- knowledge/learnings.md
```

### 3. CSV読み込み・プロフィール解析

入力CSVの必須列: `member_id`
その他の列（`qualifications`, `experience_type`, `experience_years`, `desired_employment_type`, `self_pr`, `special_conditions`, `work_history_summary` 等）からパーソナライズの素材を抽出。

### 4. テンプレート判定（候補者ごと）

1. 引数に `seishain` → 正社員テンプレート
2. 引数に `resend` → 再送テンプレート（正社員/パートは下記で判定）
3. `desired_employment_type` に「正職員」を含む → **正社員テンプレート**（「パート・バイト」も同時に含まれていても正社員を優先）
4. 「パート・バイト」のみ（正職員を一切含まない）→ パートテンプレート

`template_type` の値:
- `パート_初回` / `パート_再送` / `正社員_初回` / `正社員_再送`

### 5. パーソナライズ文の一括生成

全候補者のパーソナライズ文を一括で生成する。generate-scoutスキルと同じルールを適用:

- 文字数目安: 初回 約100文字 / 再送 120〜150文字
- 必ず「プロフィールを拝見し、」で開始
- templates.mdの行動指針に厳密に従う
- learnings.mdの「改善履歴」を最優先で反映
- 核心ルール（後述）を必ず遵守

### 6. 出力: 元CSVを更新

元のCSVファイルに以下の3列を**追加**して上書き保存する:

| 列名 | 内容 |
|------|------|
| `template_type` | `パート_初回` 等 |
| `personalized_text` | パーソナライズ文 |
| `full_scout_text` | テンプレートにパーソナライズ文を挿入した完全版 |

**書き込みにはPythonのcsvモジュールを使用する**（改行・カンマのエスケープを正しく処理するため）。
元CSVがBOM付きUTF-8の場合は `utf-8-sig` で読み書きする。

```python
import csv

with open(path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    ...

with open(path, 'w', encoding='utf-8-sig', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=new_fieldnames)
    ...
```

### 7. 完了報告

```
✅ [N]件のスカウト文を生成しました
📄 出力: [CSVパス]
📋 Chrome拡張の「送信アシスト」→「CSVインポート」でインポートできます

| member_id | template_type | personalized_text（先頭30文字） |
|-----------|---------------|-------------------------------|
| ...       | ...           | ...                           |
```

## Chrome拡張インポート形式

Chrome拡張の `ImportPanel` が期待するCSV列:

```
member_id,template_type,personalized_text,full_scout_text
```

元CSVにプロフィール列が含まれていても、インポート時は上記4列のみ使用される（余分な列は無視される）。

## 核心ルール（必須遵守）

### learnings.mdから抽出した重要ルール

1. **経験年数が浅い場合**（1〜2年など）
   - 「〇年間」と明示しない
   - 研修制度などポジティブ面に焦点

2. **地理情報の重複回避**
   - 勤務地・訪問範囲はテンプレートに記載済み
   - パーソナライズ文では言及不要

3. **こだわり条件は参考程度**
   - 資格・経験で強い接点が作れる場合、こだわり条件への言及不要

4. **「感銘を受ける」の使用制限**
   - 経験そのものには使用禁止
   - 代替: 「心強く拝見」「注目しました」

5. **強力なキャリア（10年以上）**
   - 地理的接点より専門的接点を優先
   - 期待値をストレートに伝える

6. **情報が少ない場合**
   - 地理的要素のみに頼らない
   - 会社の強み（教育体制、成長環境）を前面に
   - 「ご一緒したい」「想いを強く感じ」などの送り手感情主体は不自然
   - 「成長をサポートできる環境がある」という相手へのオファー主体で締める

### 絶対NG

- 年齢・世代への言及（「〇代」「若手」「ベテラン」）
- 詳細な居住地への言及（「〇〇区」→「札幌市内」に）
- 憶測（「長く続けているはず」「〜されたいのですね」）
- 上から目線（「フォローします」「安心してください」「基礎を固めてこられた」）
- 不要な前置き（「現在離職中とのこと」「新たな環境で〜とお考えのタイミング」）
