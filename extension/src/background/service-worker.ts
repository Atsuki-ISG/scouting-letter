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

/** content script が注入されるジョブメドレーのURLか判定 */
function isJobMedleyUrl(url: string | undefined): boolean {
  if (!url) return false;
  return /^https:\/\/([^/]+\.)?job-medley\.com\//.test(url);
}

const NOT_JOBMEDLEY_ERROR = 'ジョブメドレーのタブで操作してください';
const CONTENT_SCRIPT_UNREACHABLE_ERROR =
  'ジョブメドレーのページと接続できません。拡張を更新・再読み込みした直後は、ジョブメドレーのページを再読み込み（F5）する必要があります。再読み込みしてからもう一度お試しください';

/**
 * アクティブタブのContent Scriptにメッセージを転送（レスポンスなし）。
 * 届かなかった場合は ok=false と理由を返す（呼び出し側がUIに出すかは任意）。
 * 典型的な失敗は「拡張更新後にページを再読み込みしていない」で、このとき
 * chrome.tabs.sendMessage は "Receiving end does not exist" で reject する。
 */
async function forwardToContentScript(message: Message): Promise<{ ok: boolean; error?: string }> {
  const tab = await getActiveTab();
  if (!tab?.id || !isJobMedleyUrl(tab.url)) {
    console.warn('[SW] Skip forward (not a job-medley tab):', message.type, tab?.url);
    return { ok: false, error: NOT_JOBMEDLEY_ERROR };
  }
  try {
    await chrome.tabs.sendMessage(tab.id, message);
    return { ok: true };
  } catch (err) {
    console.error('[SW] sendMessage failed:', err);
    return { ok: false, error: CONTENT_SCRIPT_UNREACHABLE_ERROR };
  }
}

/** アクティブタブのContent Scriptにメッセージを転送（レスポンスあり） */
async function forwardWithResponse(message: Message, fallbackResponse: unknown): Promise<unknown> {
  const tab = await getActiveTab();
  if (!tab?.id || !isJobMedleyUrl(tab.url)) {
    console.warn('[SW] Skip forward (not a job-medley tab):', message.type, tab?.url);
    if (fallbackResponse && typeof fallbackResponse === 'object') {
      return { ...(fallbackResponse as object), error: NOT_JOBMEDLEY_ERROR };
    }
    return fallbackResponse;
  }
  return chrome.tabs.sendMessage(tab.id, message);
}

/** メッセージルーティング: Side Panel → Content Script */
chrome.runtime.onMessage.addListener(
  (message: Message, sender, sendResponse) => {
    if (!isValidSender(sender)) {
      console.warn('[SW] Unauthorized message sender:', sender.url);
      return false;
    }

    switch (message.type) {
      // サイドパネルからの抽出開始指示 → Content Scriptに転送。
      // 届かなかった場合は無言で止めず、抽出エラーとしてサイドパネルに通知する
      case 'START_EXTRACTION': {
        console.log('[SW] Forwarding', message.type, 'to content script');
        forwardToContentScript(message).then((result) => {
          if (!result.ok) {
            chrome.runtime.sendMessage({ type: 'EXTRACTION_ERROR', error: result.error || CONTENT_SCRIPT_UNREACHABLE_ERROR } satisfies Message).catch(() => {});
          }
        });
        sendResponse({ ok: true });
        return false;
      }
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

      // サイドパネル → Content Script: 会社自動検出リクエスト
      case 'DETECT_COMPANY': {
        forwardToContentScript(message);
        sendResponse({ ok: true });
        return false;
      }

      // Content Script → サイドパネル（そのままbroadcast）
      case 'DEBUG_LOG':
      case 'CONFIRM_BEFORE_SEND':
      case 'DRY_RUN_COMPLETE':
      case 'JOB_OFFER_FAILED':
      case 'COMPANY_MISMATCH':
      case 'COMPANY_DETECTED':
      case 'CONTINUOUS_SEND_COMPLETE': {
        sendResponse({ ok: true });
        return false;
      }

      // 残数取得ワンクリック: 裏でジョブメドレーの検索画面を開き、
      // content script (scout-quota-scraper) が `今月のスカウト残数 X 通` を読んで
      // `QUOTA_SNAPSHOT_POSTED` を発行したらそのタブを閉じる。
      //
      // URL は `/customers/searches` を直接指定する。ルート `/` は残数表示がなく、
      // 検索画面のみに「今月のスカウト残数 XX 通」が出るため。
      //
      // タイムアウトは30秒。裏タブは Chrome が描画/JS実行を throttling するので
      // 15秒だと残数要素の出現 + API POST が間に合わないケースがある。
      // また API POST 中にタブが閉じられると fetch が abort され DOMException になる
      // ので、QUOTA_SNAPSHOT_POSTED を受けてからタブを閉じる順序は維持しつつ
      // 余裕を持たせる。
      case 'REQUEST_QUOTA_SNAPSHOT': {
        (async () => {
          try {
            const tab = await chrome.tabs.create({
              url: 'https://customers.job-medley.com/customers/searches',
              active: false,
            });
            if (!tab?.id) {
              sendResponse({ type: 'REQUEST_QUOTA_SNAPSHOT_RESULT', success: false, error: 'タブ作成に失敗' });
              return;
            }
            const tabId = tab.id;

            const result = await new Promise<{ success: boolean; remaining?: number; error?: string }>((resolve) => {
              const timer = setTimeout(() => {
                chrome.runtime.onMessage.removeListener(listener);
                resolve({ success: false, error: '30秒以内に残数を取得できませんでした。customers.job-medley.com にログインしているか確認してください。' });
              }, 30000);

              const listener = (msg: Message, _s: chrome.runtime.MessageSender) => {
                if (msg.type === 'QUOTA_SNAPSHOT_POSTED') {
                  clearTimeout(timer);
                  chrome.runtime.onMessage.removeListener(listener);
                  resolve({ success: true, remaining: msg.remaining });
                }
              };
              chrome.runtime.onMessage.addListener(listener);
            });

            // 後片付け: 裏タブを閉じる
            try {
              await chrome.tabs.remove(tabId);
            } catch {
              /* 既に閉じられていても無視 */
            }

            sendResponse({ type: 'REQUEST_QUOTA_SNAPSHOT_RESULT', ...result });
          } catch (err) {
            sendResponse({
              type: 'REQUEST_QUOTA_SNAPSHOT_RESULT',
              success: false,
              error: err instanceof Error ? err.message : String(err),
            });
          }
        })();
        return true;
      }

      // Content Script からの通知。サイドパネル等がリッスンして UI 更新に使う
      case 'QUOTA_SNAPSHOT_POSTED': {
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
