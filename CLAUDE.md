# スカウト文生成ナレッジベース

## 概要

ジョブメドレーの求職者プロフィールスクリーンショットから、介護・医療系向けのスカウト文を生成するためのナレッジベースです。

## 対象

- **プラットフォーム**: ジョブメドレー
- **業界**: 介護・医療系
- **目的**: 求職者に響くパーソナライズされたスカウト文の作成

## ディレクトリ構成

```
scouting-letter/
├── CLAUDE.md                           # このファイル
├── .claude/skills/
│   ├── generate-scout/                 # 1. スカウト文の生成
│   ├── integrate-feedback/             # 2. 修正の同期・ナレッジ反映
│   └── save-example/                   # 3. 良い例の保存
├── knowledge/                          # 共通ナレッジ（全社参照）
│   ├── basics.md                       # 基本ルール
│   ├── structure.md                    # 文章構成
│   ├── personalization.md              # パーソナライズのコツ
│   └── learnings.md                    # 過去の修正から得た共通ルール
└── companies/
    └── [会社名]/
        ├── profile.md                  # 会社プロファイル
        ├── templates.md                # 会社別テンプレート・生成ルール
        └── history/                    # 運用履歴
            ├── examples.md             # 良かった例のストック
            ├── responses.md            # 返答があった例（任意）
            └── fixes/                  # 修正履歴（月次ファイル）
                └── YYYY-MM.md
```

## 会社の管理方法

新しい会社を追加する場合:

1. `companies/` 配下に会社名のディレクトリを作成
2. `profile.md` に会社情報を記載
3. `templates.md` に職種別テンプレートと行動指針を記載
4. （任意）`history/` ディレクトリを作成して継続改善を開始

## スキルの使い方

1. 求職者のプロフィールスクリーンショットを用意
2. スクリーンショットを貼り付け
3. `/generate-scout [会社名]` を実行
4. 完成したスカウト文がクリップボードにコピーされる

例:
```
/generate-scout ark-visiting-nurse
```

## 良い例の保存

特に出来の良いパーソナライズ文を蓄積:
```
/save-example [会社名] [タイトル] [本文]
```

## 修正の反映

スカウト文を修正した後、以下のコマンドを実行してナレッジを同期:

```
/integrate-feedback [会社名] [会員番号] [修正理由] [修正前後]
```

このコマンドにより：
1. `history/fixes/YYYY-MM.md` への自動記録
2. `learnings.md` への反映
3. `generate-scout` スキルへの反映（必要に応じて）
が実行されます。

## 継続改善の運用フロー

### 改善サイクル（Phase 2: 安定期）

修正が発生した際は以下の手順で自動同期を行います。

1. **修正の実行**: 提示されたスカウト文を修正
2. **同期コマンドの実行**: 
   ```
   /integrate-feedback [会社名] [会員番号] [修正理由] [修正前後]
   ```
3. **自動反映の確認**:
   - `history/fixes/YYYY-MM.md` （会社別の月次履歴）
   - `knowledge/learnings.md` （全社共通ナレッジ）
   - `companies/[会社名]/templates.md` （会社別生成ルール）
   - `.claude/skills/generate-scout/SKILL.md` （生成スキル）
   これらが自動的に更新されます。

### 特別に良い例の蓄積

返信率が高そうなものや、会心のパーソナライズ文は以下で保存します：
```
/save-example [会社名] [タイトル] [本文]
```
保存先: `companies/[会社名]/history/examples.md`

---
*詳細な基本ルールや構成案は `knowledge/` 配下の各ファイルを参照してください。*
