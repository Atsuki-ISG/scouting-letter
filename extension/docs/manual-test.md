# Chrome拡張 マニュアルテスト手順書

## テスト実績

| テスト | 結果 | 実施日 | 備考 |
|--------|------|--------|------|
| Test 1: CSVインポート | OK | 2026-03-07 | 3名表示、template_typeバッジ正常 |
| Test 2: 個別送信（ドライラン） | OK | 2026-03-07 | パート→1550716、正社員→1550715 正しく選択 |
| Test 3: 連続送信（ドライラン） | OK | 2026-03-07 | 3名順次処理→自動停止 |
| Test 3b: NGスキップ | OK | 2026-03-07 | 確認ポップアップでキャンセル→次候補者に進行 |
| Test 4: 送信後モーダル処理 | 未実施 | - | 本番送信が必要 |
| Test 5: GAS連携 | 未実施 | - | |
| Test 6: プロフィール抽出 | 未実施 | - | |

### 注意事項
- ドライランモード有効時は確認ポップアップが表示されない（自動スキップ）
- NGスキップのテストはドライランモードをオフにして実施すること

## 前提

- Chrome拡張をビルド済み (`npm run build`)
- `chrome://extensions` で拡張を読み込み済み
- ジョブメドレーにログイン済み
- テスト用CSV: `extension/test/test-candidates.csv`（3名、正社員2名+パート1名）
  - 求人選択の正社員/パート切り替えテスト用に意図的に混在させている

## ログ確認方法

### コンソールログ（DevTools）
- **コンテンツスクリプト**: ジョブメドレーのタブで F12 → Console → `[Scout` でフィルタ
- **サイドパネル**: サイドパネル上で右クリック → 検証 → Console
- **Service Worker**: `chrome://extensions` → 拡張の「Service Worker」リンク → Console

### デバッグパネル（サイドパネル内）
- サイドパネル下部「デバッグログ有効化」にチェック
- リアルタイムでステップ・ステータスが表示される

---

## Test 1: CSVインポート

### 手順
1. サイドパネルを開く
2. 「送信アシスト」タブを選択
3. 「CSVインポート」ボタンをクリック
4. テスト用CSVを選択

### 期待ログ（サイドパネル Console）
```
候補者一覧を読み込みました: N件
```

### 確認項目
- [ ] 候補者一覧が正しく表示される
- [ ] `template_type` に応じたバッジ（正社員/パート、初回/再送）が表示される
- [ ] 対象求人が `template_type` から正しく判定される（正社員→正社員求人、パート→パート求人）

---

## Test 2: 個別送信（ドライラン）

### 手順
1. サイドパネルで「テストモード」にチェック
2. 「デバッグログ有効化」にチェック
3. ジョブメドレーの候補者検索ページを開く
4. 候補者一覧から1名をクリック

### 期待ログ（DevTools Console - ジョブメドレータブ）
```
[Scout Assistant] Fill form: memberId=XXXXXXXX
[Scout Assistant] Filling job offer: {id: "...", name: "..."}
[Scout Assistant] Found combobox trigger
[Scout Assistant] Job offer selected: ...
[Scout Assistant] Filling textarea with scout text
```

### 確認項目
- [ ] 確認ポップアップが表示される
- [ ] 会員番号が正しい
- [ ] 求人名が `template_type` に対応している（正社員候補→正社員求人）
- [ ] スカウト文が表示される
- [ ] 「送信」クリック後、フォームにテキストが入力される
- [ ] テストモードの赤バナーが表示される
- [ ] 2秒後に自動クローズされる（実送信なし）
- [ ] 候補者ステータスが「skipped」になる

---

## Test 3: 連続送信（ドライラン）

### 手順
1. サイドパネルで「テストモード」にチェック
2. 「デバッグログ有効化」にチェック
3. CSVインポートで2〜3名の候補者を読み込み
4. 「連続送信 開始」ボタンをクリック

### 期待ログ（デバッグパネル - 各候補者で以下が順に表示）
```
[pending] カード検索: XXXXXXXX
[success] カード発見
[pending] オーバーレイ待機
[success] オーバーレイ表示
[pending] 求人選択
[success] 求人選択完了
[pending] テキスト入力
[success] テキスト入力完了
[pending] テストモード - 送信スキップ
[success] テストモード完了
```

### 期待ログ（DevTools Console - ジョブメドレータブ）
```
[Scout Assistant] === Continuous send: processing candidate XXXXXXXX ===
[Scout Assistant] Searching for card: XXXXXXXX
[Scout Assistant] Found card, clicking scout button
[Scout Assistant] Overlay detected
[Scout Assistant] Fill form: memberId=XXXXXXXX
[Scout Assistant] Filling job offer: {id: "...", name: "..."}
[Scout Assistant] Job offer selected: ...
[Scout Assistant] DRY RUN MODE - skipping actual send
[Scout Assistant] Dry run complete, closing overlay
[Scout Assistant] === Continuous send: processing candidate YYYYYYYY ===
...
```

### 確認項目
- [ ] 1人目の処理が完了してから2人目に進む
- [ ] 各候補者で正しい求人が選択される（template_typeに応じて）
- [ ] テストモードのため実送信されない
- [ ] 全員処理後に「送信完了」メッセージが表示される
- [ ] デバッグパネルに全ステップが記録される

---

## Test 4: 送信後モーダル処理（本番モード）

**注意: 本番モードでは実際にスカウトが送信される。テスト専用アカウントでのみ実施。**

### 手順
1. テストモードを**オフ**
2. 連続送信を開始

### 期待ログ（DevTools Console）
```
[Scout Assistant] Polling for post-send modal...
[Scout Assistant] Found post-send modal, clicking OK
[Scout Assistant] Modal dismissed, closing overlay
[Scout Assistant] Overlay closed, moving to next candidate
```

### 確認項目
- [ ] 送信後の「スカウトを送信しました」モーダルが自動で閉じられる
- [ ] モーダル閉じ後にオーバーレイが閉じる
- [ ] 次の候補者に自動で進む（デッドロックしない）

---

## Test 5: GAS連携

### 手順
1. サイドパネルの設定でGASエンドポイントURLを入力
2. 「GAS連携有効」にチェック
3. 個別送信またはドライランで1名送信

### 期待ログ（サイドパネル Console）
```
GAS送信: {member_id: "...", status: "...", timestamp: "2026-...+09:00"}
GAS送信成功
```

### 確認項目
- [ ] スプレッドシートに行が追加される
- [ ] タイムスタンプがJST（+09:00）
- [ ] member_id, template_type, status が正しい

---

## Test 6: プロフィール抽出

### 手順
1. サイドパネルで「プロフィール抽出」タブを選択
2. ジョブメドレーの候補者検索ページを開く
3. 「抽出開始」ボタンをクリック

### 期待ログ（DevTools Console）
```
[Scout Assistant] Starting extraction...
[Scout Assistant] Found N candidate cards
[Scout Assistant] Processing card 1/N
[Scout Assistant] Opening overlay for member XXXXXXXX
[Scout Assistant] Extracting profile fields...
[Scout Assistant] Profile extracted: {member_id: "...", qualifications: "...", ...}
```

### 確認項目
- [ ] 進捗バーが表示される
- [ ] 全候補者の抽出完了後にCSVダウンロードが可能
- [ ] CSVに必要列（member_id, qualifications, experience_type等）が含まれる

---

## トラブルシューティング

| 症状 | 確認箇所 | よくある原因 |
|------|---------|------------|
| フォームにテキストが入らない | Content Console | textareaのセレクタ変更 |
| 求人が選択されない | Content Console の `Filling job offer` | COMPANY_JOB_OFFERSの設定ミス、comboboxのDOM変更 |
| 連続送信が次に進まない | Content Console の modal/overlay ログ | モーダルのDOM構造変更、sendCompleteResolverの未発火 |
| GASに記録されない | SidePanel Console | エンドポイントURL間違い、CORSエラー |
| デバッグパネルに何も出ない | Service Worker Console | DEBUG_LOGメッセージの転送漏れ |
