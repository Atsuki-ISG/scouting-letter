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
