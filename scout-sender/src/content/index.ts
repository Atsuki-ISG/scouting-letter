import { Message, CandidateProfile } from '../shared/types';
import { EXTRACTION_INTERVAL_MS } from '../shared/constants';
import { SELECTORS, queryAllElements } from './selectors';
import { waitForOverlay, waitForOverlayClose, extractProfile, closeOverlay } from './scraper';

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
        startExtraction(message.count, message.startMemberId).catch((err) => {
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

      default:
        return false;
    }
  }
);

/** プロフィール一括抽出 */
async function startExtraction(count: number, startMemberId?: string): Promise<void> {
  const cards = queryAllElements(document, SELECTORS.candidateCard);

  let startIndex = 0;
  if (startMemberId) {
    const idx = cards.findIndex((card) => {
      const checkbox = card.querySelector(SELECTORS.memberCheckbox) as HTMLInputElement | null;
      return checkbox?.value === startMemberId;
    });
    if (idx === -1) {
      safeSendMessage({ type: 'EXTRACTION_ERROR', error: `会員番号 ${startMemberId} がリストに見つかりません` });
      return;
    }
    startIndex = idx;
  }

  const available = cards.length - startIndex;
  const total = Math.min(count, available);
  const profiles: CandidateProfile[] = [];

  for (let i = 0; i < total; i++) {
    const cardIndex = startIndex + i;
    if (extractionAborted) break;

    const scoutBtn = cards[cardIndex].querySelector(SELECTORS.scoutButton);
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

console.log('[Scout Sender] Content script loaded');
