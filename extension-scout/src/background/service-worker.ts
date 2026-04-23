/**
 * コメディカル拡張 service worker。
 *
 * 現状はアクションアイコンクリックで sidepanel を開くだけの極小実装。
 * 送信履歴等は chrome.storage.local を content script/sidepanel が
 * 直接読み書きするので、ここで仲介は不要。
 */

// アクションアイコン → sidepanel を開く
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {
  /* 既にセット済みでも気にしない */
});
