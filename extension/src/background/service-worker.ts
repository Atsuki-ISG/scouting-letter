import { Message } from '../shared/types';
import { STORAGE_KEYS } from '../shared/constants';

/** インストール/更新時にデフォルト設定を書き込む（未設定の場合のみ） */
chrome.runtime.onInstalled.addListener(async () => {
  const result = await chrome.storage.local.get([STORAGE_KEYS.API_ENDPOINT, STORAGE_KEYS.API_KEY]);
  if (!result[STORAGE_KEYS.API_ENDPOINT]) {
    await chrome.storage.local.set({
      [STORAGE_KEYS.API_ENDPOINT]: 'https://scout-api-1080076995871.asia-northeast1.run.app',
    });
  }
  if (!result[STORAGE_KEYS.API_KEY]) {
    await chrome.storage.local.set({
      [STORAGE_KEYS.API_KEY]: 'anycare',
    });
  }
});

/** アイコンクリックでサイドパネルを開く（default_popup より優先） */
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

/** sender が自拡張機能であることを検証 */
function isValidSender(sender: chrome.runtime.MessageSender): boolean {
  return sender.id === chrome.runtime.id;
}

/** アクティブタブを取得 */
async function getActiveTab(): Promise<chrome.tabs.Tab | null> {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs[0] || null;
}

/** アクティブタブのContent Scriptにメッセージを転送（レスポンスなし） */
async function forwardToContentScript(message: Message): Promise<void> {
  const tab = await getActiveTab();
  if (tab?.id) {
    await chrome.tabs.sendMessage(tab.id, message).catch((err) => {
      console.error('[SW] sendMessage failed:', err);
    });
  }
}

/** アクティブタブのContent Scriptにメッセージを転送（レスポンスあり） */
async function forwardWithResponse(message: Message, fallbackResponse: unknown): Promise<unknown> {
  const tab = await getActiveTab();
  if (tab?.id) {
    return chrome.tabs.sendMessage(tab.id, message);
  }
  return fallbackResponse;
}

/** メッセージルーティング: Side Panel → Content Script */
chrome.runtime.onMessage.addListener(
  (message: Message, sender, sendResponse) => {
    if (!isValidSender(sender)) {
      console.warn('[SW] Unauthorized message sender:', sender.url);
      return false;
    }

    switch (message.type) {
      // サイドパネルからの抽出開始指示 → Content Scriptに転送
      case 'START_EXTRACTION':
      case 'STOP_EXTRACTION': {
        console.log('[SW] Forwarding', message.type, 'to content script');
        forwardToContentScript(message);
        sendResponse({ ok: true });
        return false;
      }

      // フォーム入力指示 → アクティブタブのContent Scriptに転送
      case 'FILL_FORM':
      case 'FILL_JOB_OFFER': {
        forwardWithResponse(message, { success: false, error: 'アクティブタブが見つかりません' })
          .then(sendResponse);
        return true;
      }

      // 施設情報抽出 → アクティブタブのContent Scriptに転送
      case 'EXTRACT_FACILITY_LIST':
      case 'EXTRACT_FACILITY_INFO':
      case 'STOP_FACILITY_EXTRACTION':
      // 求人抽出 → アクティブタブのContent Scriptに転送
      case 'EXTRACT_JOB_OFFERS': {
        forwardWithResponse(message, { success: false, offers: [], error: 'アクティブタブが見つかりません' })
          .then(sendResponse);
        return true;
      }

      // overlay会員番号取得 → アクティブタブに転送
      case 'GET_OVERLAY_MEMBER_ID': {
        forwardWithResponse(message, { memberId: null })
          .then(sendResponse);
        return true;
      }

      // メッセージ抽出 → アクティブタブのContent Scriptに転送
      case 'EXTRACT_CONVERSATION':
      case 'EXTRACT_ALL_CONVERSATIONS': {
        forwardWithResponse(message, { type: 'CONVERSATION_ERROR', error: 'アクティブタブが見つかりません' })
          .then(sendResponse);
        return true;
      }

      // 連続送信: サイドパネル→Content Script
      case 'START_CONTINUOUS_SEND':
      case 'STOP_CONTINUOUS_SEND':
      case 'SKIP_CURRENT_CANDIDATE':
      case 'RESUME_AFTER_JOB_OFFER':
      case 'CONFIRM_RESPONSE': {
        forwardToContentScript(message);
        sendResponse({ ok: true });
        return false;
      }

      // Content Script → サイドパネル（そのままbroadcast）
      case 'DEBUG_LOG':
      case 'CONFIRM_BEFORE_SEND':
      case 'DRY_RUN_COMPLETE':
      case 'JOB_OFFER_FAILED':
      case 'CONTINUOUS_SEND_COMPLETE': {
        sendResponse({ ok: true });
        return false;
      }

      case 'OPEN_SIDE_PANEL': {
        getActiveTab().then(async (tab) => {
          if (tab?.id) {
            await chrome.sidePanel.open({ tabId: tab.id });
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
