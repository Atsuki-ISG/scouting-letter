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
import { FIELD_LABELS, getValueByLabel } from './selectors';

let currentMemberId: string | null = null;
let sentFlagForCurrent = false;

/** 手動送信記録用の軽量プロフィールスナップショット。
 *
 * extractProfile はタブ切替・複数の await を伴うためここでは使わない。
 * overlay 上で見えている値を同期で読み取り、サーバへ最小情報を送る。
 */
function captureLightProfile(overlay: Element): {
  member_id: string;
  age: string;
  qualifications: string;
  area: string;
  desired_employment_type: string;
} {
  return {
    member_id: getValueByLabel(overlay, FIELD_LABELS.memberId),
    age: getValueByLabel(overlay, FIELD_LABELS.age),
    qualifications: getValueByLabel(overlay, FIELD_LABELS.qualifications),
    area: getValueByLabel(overlay, FIELD_LABELS.area),
    desired_employment_type: getValueByLabel(overlay, FIELD_LABELS.desiredEmploymentType),
  };
}

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

// overlay が見えている間の最後のプロフィールスナップショット。
// overlay が閉じる瞬間にはDOMから値が消えているため、送信完了モーダルを
// 見たタイミングで保持しておく。
let lastProfileSnapshot: ReturnType<typeof captureLightProfile> | null = null;

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
        lastProfileSnapshot = null;
      }
      // 送信完了モーダルを見たらフラグを立てる + プロフィール捕捉
      if (!sentFlagForCurrent && hasPostSendModal()) {
        sentFlagForCurrent = true;
        const overlay = document.querySelector('.c-side-cover');
        if (overlay) {
          try {
            lastProfileSnapshot = captureLightProfile(overlay);
          } catch (err) {
            console.warn('[single-send] failed to capture profile snapshot', err);
          }
        }
      }
    } else {
      // overlay が閉じた
      if (currentMemberId && sentFlagForCurrent) {
        // 連続送信中は continuous-sender.ts が処理するのでスキップ
        if (!isContinuousActive()) {
          const memberId = currentMemberId;
          console.log(`[single-send] detected manual send complete: ${memberId}`);
          safeSendMessage({
            type: 'CANDIDATE_SENT',
            memberId,
            // Phase C: 手動送信を sheets に記録するための補助情報
            manualSendProfile: lastProfileSnapshot,
            sentAt: new Date().toISOString(),
          });
          // 残数も更新
          setTimeout(() => refreshScoutQuota(), 1500);
        }
      }
      currentMemberId = null;
      sentFlagForCurrent = false;
      lastProfileSnapshot = null;
    }
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['class', 'style'],
  });
}
