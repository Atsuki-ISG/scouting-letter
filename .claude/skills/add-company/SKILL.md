---
name: add-company
description: "新しい会社をスカウトシステムに追加する手順をガイドする。profile.md・templates.md・recipes.mdの作成からサーバー登録まで。トリガー例: 「新しい会社を追加」「会社をセットアップ」「/add-company」"
---

# add-company

新しい会社をスカウトシステムに追加する手順ガイド。

## 手順

### 1. ディレクトリ作成

`companies/[会社名]/` を作成。会社名はケバブケース（例: `ichigo-visiting-nurse`）。

### 2. profile.md 作成

会社情報・求人一覧をまとめる。既存会社を参考に同じ粒度で作成。

- 参考: `companies/lcc-visiting-nurse/profile.md`
- 求人IDを必ず含める（ジョブメドレーの管理画面やURLから取得）
- 複数施設がある場合は1ファイルにまとめる。種別が大きく異なる施設は別ディレクトリに分離

### 3. templates.md 作成

スカウト文テンプレート + フィルタリングルール + 行動指針。

- 参考: `companies/lcc-visiting-nurse/templates.md`
- テンプレート本文（件名・本文）はクライアントから提供してもらう
- フィルタリングルール・行動指針は既存会社をベースに職種に合わせて調整
- **プレースホルダーは `{ここに生成した文章を挿入}` に統一すること**（他の表記は使わない）

### 4. recipes.md 作成

型はめパターン + AI生成ガイド。

- 参考: `companies/ichigo-visiting-nurse/recipes.md`
- 型A〜G（経験年数×年齢のマトリクス）を職種に合わせて作成
- 特色バリエーションは会社の強みから3つ程度

### 5. サーバー登録（必須 — ここまでやらないと会社追加は未完了）

**ローカルファイルを作っただけでは拡張に表示されない。** Google Sheetsへの登録が必須。

```bash
# テンプレート・プロンプト等を一括登録
/server-admin init [会社名]

# recipes.mdのパターンをサーバーに反映
/server-admin sync [会社名]

# 求人を個別追加（profile.mdの求人IDを使用）
/server-admin add job_offers '{"company": "[会社名]", "job_category": "nurse", "id": "[求人ID]", "name": "[施設名] [職種]", "label": "[表示ラベル]", "employment_type": "正社員", "active": "TRUE"}'
```

登録後、`/server-admin show templates [会社名]` 等で登録されていることを確認する。

### 6. CLAUDE.md 更新

対象会社テーブルに追加。

### 7. 動作確認

Chrome拡張の会社ドロップダウンに新会社が表示されること、API生成が動くことを確認。
**ドロップダウンに表示されない場合、手順5のサーバー登録が漏れている。**

## 完了チェックリスト

以下をすべて満たすまで会社追加は完了としない:

- [ ] `companies/[会社名]/` に profile.md, templates.md, recipes.md がある
- [ ] templates.md のプレースホルダーが `{ここに生成した文章を挿入}` になっている
- [ ] `/server-admin init` でテンプレート・プロンプトがGoogle Sheetsに登録済み
- [ ] `/server-admin sync` でパターンがGoogle Sheetsに登録済み
- [ ] 求人がGoogle Sheetsに登録済み
- [ ] CLAUDE.md の対象会社テーブルに追加済み
- [ ] Chrome拡張の会社ドロップダウンに表示される
