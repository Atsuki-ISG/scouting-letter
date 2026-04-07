import { Message } from '../shared/types';
import { STORAGE_KEYS } from '../shared/constants';
import { sleep, randomSleep } from '../shared/utils';
import { closeOverlay, waitForOverlayClose } from './scraper';
import { handleFillForm } from './fill-handler';
import { safeSendMessage, debugLog } from './helpers';

/** 求人選択失敗時の一時停止resolver */
let jobOfferResumeResolver: (() => void) | null = null;

/** サイドパネルから求人選択失敗の再開通知を受ける */
export function resumeAfterJobOfferFix(): void {
  if (jobOfferResumeResolver) {
    jobOfferResumeResolver();
    jobOfferResumeResolver = null;
  }
}

/** 連続送信の状態管理 */
let active = false;
let skipResolver: (() => void) | null = null;
let sendCompleteResolver: ((action: 'closed' | 'skipped') => void) | null = null;
let stopModalDismisser = false;
/** stop()で確認ポップアップ待ちをキャンセルするためのresolver */
let confirmCancelResolver: (() => void) | null = null;

export function isActive(): boolean {
  return active;
}

export function stop(): void {
  active = false;
  if (skipResolver) {
    skipResolver();
    skipResolver = null;
  }
  if (confirmCancelResolver) {
    confirmCancelResolver();
    confirmCancelResolver = null;
  }
}

export function skipCurrent(): void {
  if (skipResolver) {
    skipResolver();
    skipResolver = null;
  }
}

/** ドライランバナーをoverlayに注入 */
function injectDryRunBanner(): void {
  const overlay = document.querySelector('.c-side-cover');
  if (!overlay) return;
  const banner = document.createElement('div');
  banner.id = 'dry-run-banner';
  banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:999999;background:#ef4444;color:white;text-align:center;padding:8px;font-weight:bold;font-size:14px;';
  banner.textContent = 'テストモード - 送信しないでください';
  overlay.prepend(banner);
}

/** ドライランバナーを削除 */
function removeDryRunBanner(): void {
  document.getElementById('dry-run-banner')?.remove();
}

/** 送信後モーダルを繰り返しチェックして自動で閉じる（最大5分） */
async function pollAndDismissPostSendModal(): Promise<void> {
  stopModalDismisser = false;
  const maxPollingMs = 5 * 60 * 1000;
  const started = Date.now();
  while (!stopModalDismisser && (Date.now() - started) < maxPollingMs) {
    const modals = document.querySelectorAll('.c-modal.js-modal');
    for (const modal of modals) {
      if (modal.classList.contains('u-is-hidden')) continue;
      const body = modal.textContent || '';
      if (body.includes('スカウトを送信しました')) {
        const okBtn = modal.querySelector('button');
        if (okBtn) {
          console.log('[Scout Assistant] Dismissing post-send modal (polling)');
          okBtn.click();
          await sleep(500);
          console.log('[Scout Assistant] Closing overlay after modal dismiss');
          closeOverlay();
          await sleep(500);
          if (sendCompleteResolver) {
            console.log('[Scout Assistant] Resolving send complete');
            sendCompleteResolver('closed');
          }
          return;
        }
      }
    }
    await sleep(200);
  }
}

/** overlay閉じ or スキップ or 送信完了のいずれかを待つ */
function waitForOverlayCloseOrSkip(timeoutMs: number): Promise<'closed' | 'skipped'> {
  return new Promise((resolve) => {
    let resolved = false;

    const doResolve = (action: 'closed' | 'skipped') => {
      if (resolved) return;
      resolved = true;
      skipResolver = null;
      sendCompleteResolver = null;
      resolve(action);
    };

    skipResolver = () => {
      closeOverlay();
      doResolve('skipped');
    };

    sendCompleteResolver = doResolve;

    waitForOverlayClose(timeoutMs).then(() => {
      doResolve('closed');
    });
  });
}

/** サイドパネルから次の候補者を取得 */
function getNextCandidate(): Promise<{ memberId: string; text: string; searchTerm?: string; jobCategory?: string; employmentType?: string; categoryKeywords?: string[] } | null> {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: 'GET_NEXT_CANDIDATE' } satisfies Message, (response) => {
      if (response?.type === 'NEXT_CANDIDATE') {
        resolve(response.candidate || null);
      } else {
        resolve(null);
      }
    });
  });
}

/** サイドパネルに確認リクエストを送り、結果を待つ（stop()でキャンセル可能） */
function requestConfirmation(data: { memberId: string; text: string; jobOfferLabel: string; templateType: string; personalizedText: string; fullScoutText: string }): Promise<'ok' | 'ng' | 'cancelled'> {
  return new Promise((resolve) => {
    let resolved = false;
    const cleanup = () => {
      if (resolved) return;
      resolved = true;
      chrome.runtime.onMessage.removeListener(listener);
      confirmCancelResolver = null;
    };

    const listener = (msg: Message) => {
      if (msg.type === 'CONFIRM_RESPONSE') {
        cleanup();
        resolve(msg.result);
      }
    };
    chrome.runtime.onMessage.addListener(listener);

    confirmCancelResolver = () => {
      cleanup();
      resolve('cancelled');
    };

    safeSendMessage({
      type: 'CONFIRM_BEFORE_SEND',
      data: {
        member_id: data.memberId,
        label: data.templateType,
        template_type: data.templateType,
        personalized_text: data.personalizedText,
        full_scout_text: data.fullScoutText,
        jobOfferName: data.jobOfferLabel,
      },
    });
  });
}

/** 連続送信ループ */
export async function start(): Promise<void> {
  active = true;
  console.log('[Scout Assistant] Continuous send started');

  const dryRunResult = await chrome.storage.local.get(STORAGE_KEYS.DRY_RUN_MODE);
  const dryRun = !!dryRunResult[STORAGE_KEYS.DRY_RUN_MODE];
  if (dryRun) {
    debugLog('モード', 'success', 'ドライランモード有効');
  }

  while (active) {
    const next = await getNextCandidate();
    if (!next) {
      console.log('[Scout Assistant] No more candidates, stopping continuous send');
      break;
    }

    console.log(`[Scout Assistant] Processing candidate: ${next.memberId}`);

    const { searchTerm, jobCategory, employmentType, categoryKeywords } = next;

    // 求人自動選択の設定を確認
    const autoJobOfferResult = await chrome.storage.local.get(STORAGE_KEYS.AUTO_JOB_OFFER);
    const skipJobOffer = autoJobOfferResult[STORAGE_KEYS.AUTO_JOB_OFFER] === false;

    console.log(`[Scout Assistant] Calling handleFillForm for ${next.memberId}, jobCategory:`, jobCategory, employmentType, 'skipJobOffer:', skipJobOffer);
    const result = await handleFillForm(next.text, next.memberId, searchTerm, jobCategory, employmentType, skipJobOffer, categoryKeywords);
    console.log(`[Scout Assistant] handleFillForm result:`, result);

    if (!result.success) {
      console.error('[Scout Assistant] Fill form failed:', result.error);
      safeSendMessage({ type: 'CANDIDATE_SENT', memberId: next.memberId });
      await randomSleep(200, 600);
      continue;
    }

    // 求人選択失敗時は一時停止してユーザーに手動選択を促す
    if (result.jobOfferFailed) {
      debugLog('一時停止', 'error', '求人を手動で選択してから「再開」を押してください');
      console.log('[Scout Assistant] Job offer selection failed, pausing for manual selection');

      // 一時停止してユーザーの操作を待つ
      await new Promise<void>((resolve) => {
        jobOfferResumeResolver = resolve;
        // skipResolver経由での停止もサポート
        const origSkipResolver = skipResolver;
        skipResolver = () => {
          jobOfferResumeResolver = null;
          if (origSkipResolver) origSkipResolver();
          resolve();
        };
      });

      if (!active) break;
      debugLog('再開', 'success', '手動選択確認後に続行');
    }

    // ドライランモード
    if (dryRun) {
      injectDryRunBanner();
      debugLog('ドライラン', 'success', '2秒後に自動クローズ');
      await randomSleep(1500, 2500);
      removeDryRunBanner();
      closeOverlay();
      await waitForOverlayClose();
      safeSendMessage({ type: 'DRY_RUN_COMPLETE', memberId: next.memberId });
      await randomSleep(200, 600);
      continue;
    }

    // 確認ポップアップ
    console.log(`[Scout Assistant] Showing confirmation popup for ${next.memberId}`);
    debugLog('確認ポップアップ', 'pending', '確認中...');
    const confirmResult = await requestConfirmation({
      memberId: next.memberId,
      text: next.text,
      jobOfferLabel: jobCategory ? `${jobCategory}/${employmentType || ''}` : '',
      templateType: '',
      personalizedText: '',
      fullScoutText: next.text,
    });
    console.log(`[Scout Assistant] Confirmation result: ${confirmResult}`);

    if (confirmResult === 'cancelled') {
      debugLog('確認ポップアップ', 'success', '停止');
      closeOverlay();
      await waitForOverlayClose();
      break;
    }

    if (confirmResult === 'ng') {
      debugLog('確認ポップアップ', 'success', 'スキップ');
      closeOverlay();
      await waitForOverlayClose();
      safeSendMessage({ type: 'CANDIDATE_SENT', memberId: next.memberId });
      await randomSleep(300, 800);
      continue;
    }

    debugLog('確認ポップアップ', 'success', 'OK → 送信待ち');

    console.log(`[Scout Assistant] Waiting for overlay close or skip...`);
    debugLog('確認待ち', 'pending', '送信 or スキップを待機中');

    const modalDismisser = pollAndDismissPostSendModal();

    const action = await waitForOverlayCloseOrSkip(0);
    stopModalDismisser = true;
    console.log(`[Scout Assistant] Overlay action: ${action}, active: ${active}`);
    debugLog('確認待ち', 'success', action === 'skipped' ? 'スキップ' : '送信完了');

    if (!active) {
      console.log('[Scout Assistant] active is false, breaking');
      break;
    }

    await randomSleep(400, 1200);

    safeSendMessage({ type: 'CANDIDATE_SENT', memberId: next.memberId });
  }

  active = false;
  skipResolver = null;
  console.log('[Scout Assistant] Continuous send ended');
  safeSendMessage({ type: 'CONTINUOUS_SEND_COMPLETE' });

  // 送信完了後に残数をスナップショット（手動送信込みの真の値が取れる）
  try {
    const { refreshScoutQuota } = await import('./scout-quota-scraper');
    setTimeout(() => refreshScoutQuota(), 2000);
  } catch (err) {
    console.warn('[scout-quota] refresh after continuous send failed', err);
  }
}
