import { Message } from '../shared/types';

/** サイドパネルを開く */
chrome.action.onClicked.addListener(async (tab) => {
  if (tab.id) {
    await chrome.sidePanel.open({ tabId: tab.id });
  }
});

/** メッセージルーティング: Side Panel → Content Script */
chrome.runtime.onMessage.addListener(
  (message: Message, sender, sendResponse) => {
    switch (message.type) {
      // サイドパネルからの抽出開始指示 → Content Scriptに転送
      case 'START_EXTRACTION':
      case 'STOP_EXTRACTION': {
        chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
          if (tabs[0]?.id) {
            chrome.tabs.sendMessage(tabs[0].id, message).catch(() => {});
          }
        });
        sendResponse({ ok: true });
        return false;
      }

      // フォーム入力指示 → アクティブタブのContent Scriptに転送
      case 'FILL_FORM': {
        chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
          if (tabs[0]?.id) {
            chrome.tabs.sendMessage(tabs[0].id, message, (response) => {
              sendResponse(response);
            });
          } else {
            sendResponse({ success: false, error: 'アクティブタブが見つかりません' });
          }
        });
        return true;
      }

      // overlay会員番号取得 → アクティブタブに転送
      case 'GET_OVERLAY_MEMBER_ID': {
        chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
          if (tabs[0]?.id) {
            chrome.tabs.sendMessage(tabs[0].id, message, (response) => {
              sendResponse(response);
            });
          } else {
            sendResponse({ memberId: null });
          }
        });
        return true;
      }

      // メッセージ抽出 → アクティブタブのContent Scriptに転送
      case 'EXTRACT_CONVERSATION': {
        chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
          if (tabs[0]?.id) {
            chrome.tabs.sendMessage(tabs[0].id, message, (response) => {
              sendResponse(response);
            });
          } else {
            sendResponse({ type: 'CONVERSATION_ERROR', error: 'アクティブタブが見つかりません' });
          }
        });
        return true;
      }

      case 'OPEN_SIDE_PANEL': {
        chrome.tabs.query({ active: true, currentWindow: true }, async (tabs) => {
          if (tabs[0]?.id) {
            await chrome.sidePanel.open({ tabId: tabs[0].id });
          }
        });
        sendResponse({ ok: true });
        return false;
      }

      default:
        return false;
    }
  }
);
