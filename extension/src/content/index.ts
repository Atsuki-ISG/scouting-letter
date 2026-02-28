import { Message, CandidateProfile } from '../shared/types';
import { EXTRACTION_INTERVAL_MS } from '../shared/constants';
import { SELECTORS, queryAllElements } from './selectors';
import { waitForOverlay, waitForOverlayClose, extractProfile, closeOverlay, getOverlayMemberId } from './scraper';
import { fillScoutText } from './form-filler';
import { extractConversation, isMessagePage } from './message-scraper';

/** 指定ミリ秒待機 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** サイドパネルが閉じている場合のエラーを無視して送信 */
function safeSendMessage(message: Message): void {
  chrome.runtime.sendMessage(message).catch(() => {});
}

/** 抽出を中断するためのフラグ */
let extractionAborted = false;

/** メッセージリスナー */
chrome.runtime.onMessage.addListener(
  (message: Message, _sender, sendResponse) => {
    switch (message.type) {
      case 'START_EXTRACTION':
        extractionAborted = false;
        startExtraction(message.count).catch((err) => {
          safeSendMessage({
            type: 'EXTRACTION_ERROR',
            error: err.message,
          });
        });
        sendResponse({ ok: true });
        return false;

      case 'STOP_EXTRACTION':
        extractionAborted = true;
        sendResponse({ ok: true });
        return false;

      case 'GET_OVERLAY_MEMBER_ID': {
        const memberId = getOverlayMemberId();
        sendResponse({ memberId });
        return false;
      }

      case 'FILL_FORM': {
        handleFillForm(message.text, message.memberId).then(sendResponse);
        return true; // async response
      }

      case 'EXTRACT_CONVERSATION': {
        if (!isMessagePage()) {
          sendResponse({
            type: 'CONVERSATION_ERROR',
            error: 'メッセージページを開いてください',
          });
          return false;
        }
        const thread = extractConversation();
        if (thread) {
          sendResponse({ type: 'CONVERSATION_DATA', thread });
        } else {
          sendResponse({
            type: 'CONVERSATION_ERROR',
            error: '自動抽出はPhase B（3月）で実装予定です。手動入力モードをご利用ください。',
          });
        }
        return false;
      }

      default:
        return false;
    }
  }
);

/** FILL_FORMハンドラ: overlayが開いていなければ自動で開いてからテキストをセット */
async function handleFillForm(
  text: string,
  memberId?: string
): Promise<{ success: boolean; error?: string }> {
  // overlayが既に開いていればそのまま入力
  const existingOverlay = document.querySelector(SELECTORS.overlay);
  if (existingOverlay && !existingOverlay.classList.contains('u-is-hidden')) {
    return fillScoutText(text);
  }

  // memberIdが指定されていれば、該当カードのスカウトボタンをクリック
  if (memberId) {
    const cards = queryAllElements(document, SELECTORS.candidateCard);
    let targetCard: Element | null = null;

    for (const card of cards) {
      const checkbox = card.querySelector(SELECTORS.memberCheckbox) as HTMLInputElement | null;
      if (checkbox && checkbox.value === memberId) {
        targetCard = card;
        break;
      }
    }

    if (!targetCard) {
      return { success: false, error: `会員番号 ${memberId} のカードが見つかりません` };
    }

    const scoutBtn = targetCard.querySelector(SELECTORS.scoutButton) as HTMLElement | null;
    if (!scoutBtn) {
      return { success: false, error: 'スカウトボタンが見つかりません' };
    }

    scoutBtn.click();

    try {
      await waitForOverlay();
      // コンテンツ読み込みを少し待つ
      await new Promise((r) => setTimeout(r, 500));
      return fillScoutText(text);
    } catch {
      return { success: false, error: 'スカウト画面の表示がタイムアウトしました' };
    }
  }

  return { success: false, error: 'スカウト画面が開いていません。先に候補者のスカウト画面を開いてください。' };
}

/** overlay表示を監視して、会員番号変更をサイドパネルに通知 */
function setupOverlayObserver(): void {
  let lastMemberId: string | null = null;

  const observer = new MutationObserver(() => {
    const memberId = getOverlayMemberId();
    if (memberId && memberId !== lastMemberId) {
      lastMemberId = memberId;
      safeSendMessage({
        type: 'OVERLAY_MEMBER_ID',
        memberId,
      });
    } else if (!memberId && lastMemberId) {
      lastMemberId = null;
    }
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['style', 'class'],
  });
}

/** プロフィール一括抽出 */
async function startExtraction(count: number): Promise<void> {
  const cards = queryAllElements(document, SELECTORS.candidateCard);
  const total = Math.min(count, cards.length);
  const profiles: CandidateProfile[] = [];

  for (let i = 0; i < total; i++) {
    if (extractionAborted) break;

    const scoutBtn = cards[i].querySelector(SELECTORS.scoutButton);
    if (!scoutBtn) continue;
    (scoutBtn as HTMLElement).click();

    const overlay = await waitForOverlay();
    const profile = await extractProfile(overlay);
    profiles.push(profile);

    safeSendMessage({
      type: 'EXTRACTION_PROGRESS',
      current: i + 1,
      total,
      profile,
    });

    closeOverlay();
    await waitForOverlayClose();

    if (i < total - 1) {
      await sleep(EXTRACTION_INTERVAL_MS);
    }
  }

  safeSendMessage({
    type: 'EXTRACTION_COMPLETE',
    profiles,
  });
}

// 初期化
setupOverlayObserver();
console.log('[Scout Assistant] Content script loaded');
