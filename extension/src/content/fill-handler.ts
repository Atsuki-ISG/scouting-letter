import { randomSleep } from '../shared/utils';
import { SELECTORS, queryAllElements } from './selectors';
import { waitForOverlay, waitForOverlayClose } from './scraper';
import { fillScoutText, fillJobOffer } from './form-filler';
import { debugLog } from './helpers';

/** overlay内のフォーム要素（求人input・テキストエリア）が出現するまで待機 */
function waitForFormElements(timeoutMs = 5000): Promise<void> {
  return new Promise((resolve) => {
    const start = Date.now();
    const check = () => {
      const jobInput = document.querySelector(SELECTORS.jobOfferInput);
      const textarea = document.querySelector(SELECTORS.scoutTextarea);
      if (jobInput && textarea) {
        resolve();
        return;
      }
      if (Date.now() - start > timeoutMs) {
        // タイムアウトしても続行（フォーム要素がない求人もありうる）
        resolve();
        return;
      }
      setTimeout(check, 100);
    };
    check();
  });
}

/** カードからスカウトボタンをクリックしてoverlayを開く共通処理 */
async function openOverlayForMember(
  memberId: string
): Promise<{ success: true } | { success: false; error: string }> {
  const cards = queryAllElements(document, SELECTORS.candidateCard);
  const normalizeId = (id: string) => id.replace(/^0+/, '');
  const targetId = normalizeId(memberId);

  let targetCard: Element | null = null;
  for (const card of cards) {
    const checkbox = card.querySelector(SELECTORS.memberCheckbox) as HTMLInputElement | null;
    if (checkbox && normalizeId(checkbox.value) === targetId) {
      targetCard = card;
      break;
    }
  }

  if (!targetCard) {
    const foundIds = cards.map(c => (c.querySelector(SELECTORS.memberCheckbox) as HTMLInputElement | null)?.value).filter(Boolean);
    console.log('[Scout Assistant] Found member IDs:', foundIds.join(', '));
    return { success: false, error: `会員番号 ${memberId} のカードが見つかりません（${cards.length}件中）` };
  }

  const scoutBtn = targetCard.querySelector(SELECTORS.scoutButton) as HTMLElement | null;
  if (!scoutBtn) {
    console.log('[Scout Assistant] Card found but no scout button. Card HTML:', targetCard.innerHTML.slice(0, 200));
    return { success: false, error: 'スカウトボタンが見つかりません' };
  }

  scoutBtn.click();

  try {
    await waitForOverlay();
    await waitForFormElements();
    return { success: true };
  } catch {
    return { success: false, error: 'スカウト画面の表示がタイムアウトしました' };
  }
}

/** FILL_JOB_OFFERハンドラ: overlayを開いてから求人だけ選択 */
export async function handleFillJobOffer(
  jobOfferId: string,
  jobOfferName: string,
  memberId?: string
): Promise<{ success: boolean; error?: string }> {
  // overlayが既に開いていればそのまま求人選択
  const existingOverlay = document.querySelector(SELECTORS.overlay);
  if (existingOverlay && !existingOverlay.classList.contains('u-is-hidden')) {
    await waitForFormElements();
    return fillJobOffer(jobOfferId, jobOfferName);
  }

  if (memberId) {
    const openResult = await openOverlayForMember(memberId);
    if (!openResult.success) return openResult;
    return fillJobOffer(jobOfferId, jobOfferName);
  }

  return { success: false, error: 'スカウト画面が開いていません' };
}

/** FILL_FORMハンドラ: overlayが開いていなければ自動で開いてからテキストをセット */
export async function handleFillForm(
  text: string,
  memberId?: string,
  jobOfferId?: string,
  jobOfferName?: string
): Promise<{ success: boolean; error?: string }> {
  // overlayが既に開いていればそのまま入力
  const existingOverlay = document.querySelector(SELECTORS.overlay);
  if (existingOverlay && !existingOverlay.classList.contains('u-is-hidden')) {
    if (jobOfferId && jobOfferName) {
      debugLog('求人選択', 'pending');
      const jobResult = await fillJobOffer(jobOfferId, jobOfferName);
      debugLog('求人選択', jobResult.success ? 'success' : 'error', jobResult.success ? jobOfferName : jobResult.error);
      // 求人選択後のReact再レンダリングを待つ（揺らぎ付き）
      await randomSleep(250, 600);
    }
    debugLog('本文セット', 'pending');
    const result = await fillScoutText(text);
    debugLog('本文セット', result.success ? 'success' : 'error', result.success ? `${text.length}文字` : result.error);
    return result;
  }

  // memberIdが指定されていれば、該当カードのスカウトボタンをクリック
  if (memberId) {
    debugLog('カード検索', 'pending', memberId);
    console.log(`[Scout Assistant] Looking for member ${memberId}`);

    const openResult = await openOverlayForMember(memberId);
    if (!openResult.success) {
      debugLog('カード検索', 'error', openResult.error);
      return openResult;
    }

    debugLog('カード検索', 'success', 'カード発見');

    // 求人を自動選択
    if (jobOfferId && jobOfferName) {
      debugLog('求人選択', 'pending');
      const jobResult = await fillJobOffer(jobOfferId, jobOfferName);
      debugLog('求人選択', jobResult.success ? 'success' : 'error', jobResult.success ? jobOfferName : jobResult.error);
      // 求人選択後のReact再レンダリングを待つ（揺らぎ付き）
      await randomSleep(250, 600);
    }

    debugLog('本文セット', 'pending');
    const result = await fillScoutText(text);
    debugLog('本文セット', result.success ? 'success' : 'error', result.success ? `${text.length}文字` : result.error);
    return result;
  }

  return { success: false, error: 'スカウト画面が開いていません。先に候補者のスカウト画面を開いてください。' };
}
