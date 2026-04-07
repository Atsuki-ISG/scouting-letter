/**
 * 単発送信の完了検出: 連続送信モード以外でオペレーターが手動で送信した場合も
 * 「送信済み」に自動で変更するためのトラッカー。
 *
 * 判定ロジック:
 *   1. overlay が開いている間、対象の会員番号を記憶
 *   2. 「スカウトを送信しました」モーダルが表示されたら「送信あり」フラグを立てる
 *   3. overlay が閉じたタイミングで、送信ありフラグが立っていれば CANDIDATE_SENT を送る
 *
 * 連続送信中は continuous-sender.ts が自前で CANDIDATE_SENT を発火するので、
 * ここでは isActive() を見て重複を避ける。
 */
import { safeSendMessage } from './helpers';
import { getOverlayMemberId } from './scraper';
import { isActive as isContinuousActive } from './continuous-sender';
import { refreshScoutQuota } from './scout-quota-scraper';

let currentMemberId: string | null = null;
let sentFlagForCurrent = false;

/** overlay が表示されているか */
function isOverlayOpen(): boolean {
  const overlay = document.querySelector('.c-side-cover');
  if (!overlay) return false;
  return !overlay.classList.contains('u-is-hidden');
}

/** 「スカウトを送信しました」モーダルが現在表示されているか */
function hasPostSendModal(): boolean {
  const modals = document.querySelectorAll('.c-modal.js-modal');
  for (const modal of modals) {
    if (modal.classList.contains('u-is-hidden')) continue;
    const body = modal.textContent || '';
    if (body.includes('スカウトを送信しました')) return true;
  }
  return false;
}

export function setupSingleSendTracker(): void {
  const observer = new MutationObserver(() => {
    // overlay の状態を追跡
    const open = isOverlayOpen();
    const memberId = open ? getOverlayMemberId() : null;

    if (open && memberId) {
      // 会員番号が変わったらフラグをリセット（次の候補者に切り替わった）
      if (memberId !== currentMemberId) {
        currentMemberId = memberId;
        sentFlagForCurrent = false;
      }
      // 送信完了モーダルを見たらフラグを立てる
      if (!sentFlagForCurrent && hasPostSendModal()) {
        sentFlagForCurrent = true;
      }
    } else {
      // overlay が閉じた
      if (currentMemberId && sentFlagForCurrent) {
        // 連続送信中は continuous-sender.ts が処理するのでスキップ
        if (!isContinuousActive()) {
          const memberId = currentMemberId;
          console.log(`[single-send] detected manual send complete: ${memberId}`);
          safeSendMessage({ type: 'CANDIDATE_SENT', memberId });
          // 残数も更新
          setTimeout(() => refreshScoutQuota(), 1500);
        }
      }
      currentMemberId = null;
      sentFlagForCurrent = false;
    }
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['class', 'style'],
  });
}
