import { Message, CandidateProfile } from '../shared/types';
import { EXTRACTION_INTERVAL_MS } from '../shared/constants';
import { SELECTORS, queryAllElements } from './selectors';
import { waitForOverlay, waitForOverlayClose, extractProfile, closeOverlay, getOverlayMemberId } from './scraper';
import { fillScoutText, fillJobOffer } from './form-filler';
import { extractConversation, isMessagePage, extractAllConversations, abortBatchExtraction } from './message-scraper';

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

/** 連続送信モードのフラグ */
let continuousSendActive = false;

/** 連続送信中のスキップを解決するためのコールバック */
let skipResolver: (() => void) | null = null;

/** メッセージリスナー */
chrome.runtime.onMessage.addListener(
  (message: Message, _sender, sendResponse) => {
    switch (message.type) {
      case 'START_EXTRACTION':
        console.log('[Scout Assistant] START_EXTRACTION received, count:', message.count);
        extractionAborted = false;
        startExtraction(message.count).catch((err) => {
          safeSendMessage({
            type: 'EXTRACTION_ERROR',
            error: err.message,
          });
        });
        sendResponse({ ok: true });
        return false;

      case 'GET_OVERLAY_MEMBER_ID': {
        const memberId = getOverlayMemberId();
        sendResponse({ memberId });
        return false;
      }

      case 'FILL_FORM': {
        handleFillForm(message.text, message.memberId, message.jobOfferId, message.jobOfferName).then(sendResponse);
        return true; // async response
      }

      case 'EXTRACT_CONVERSATION': {
        console.log('[Scout Assistant] EXTRACT_CONVERSATION received');
        if (!isMessagePage()) {
          sendResponse({ type: 'CONVERSATION_ERROR', error: 'メッセージページを開いてください' });
          return false;
        }
        const thread = extractConversation();
        if (thread) {
          sendResponse({ type: 'CONVERSATION_DATA', thread });
        } else {
          sendResponse({ type: 'CONVERSATION_ERROR', error: 'メッセージの抽出に失敗しました。会話を選択してから再度お試しください。' });
        }
        return false;
      }

      case 'EXTRACT_ALL_CONVERSATIONS': {
        console.log('[Scout Assistant] EXTRACT_ALL_CONVERSATIONS received');
        if (!isMessagePage()) {
          sendResponse({ type: 'CONVERSATION_ERROR', error: 'メッセージページを開いてください' });
          return false;
        }
        sendResponse({ ok: true });
        // 非同期で一括抽出（進捗はsendMessageで都度通知）
        extractAllConversations((msg) => {
          safeSendMessage(msg);
        });
        return false;
      }

      case 'STOP_EXTRACTION':
        extractionAborted = true;
        abortBatchExtraction();
        sendResponse({ ok: true });
        return false;

      case 'START_CONTINUOUS_SEND':
        startContinuousSend().catch((err) => {
          console.error('[Scout Assistant] Continuous send error:', err);
        });
        sendResponse({ ok: true });
        return false;

      case 'STOP_CONTINUOUS_SEND':
        continuousSendActive = false;
        if (skipResolver) {
          skipResolver();
          skipResolver = null;
        }
        sendResponse({ ok: true });
        return false;

      case 'SKIP_CURRENT_CANDIDATE':
        if (skipResolver) {
          skipResolver();
          skipResolver = null;
        }
        sendResponse({ ok: true });
        return false;

      default:
        return false;
    }
  }
);

/** overlay内のフォーム要素（求人input・テキストエリア）が出現するまで待機 */
function waitForFormElements(timeoutMs = 5000): Promise<void> {
  return new Promise((resolve, reject) => {
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

/** FILL_FORMハンドラ: overlayが開いていなければ自動で開いてから求人選択+テキストをセット */
async function handleFillForm(
  text: string,
  memberId?: string,
  jobOfferId?: string,
  jobOfferName?: string
): Promise<{ success: boolean; error?: string }> {
  // overlayが既に開いていればそのまま入力
  const existingOverlay = document.querySelector(SELECTORS.overlay);
  if (existingOverlay && !existingOverlay.classList.contains('u-is-hidden')) {
    if (jobOfferId && jobOfferName) {
      await fillJobOffer(jobOfferId, jobOfferName);
    }
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
      // 求人入力欄とテキストエリアの出現を待つ（overlay表示後に非同期で読み込まれるため）
      await waitForFormElements();
      // 求人を自動選択
      if (jobOfferId && jobOfferName) {
        await fillJobOffer(jobOfferId, jobOfferName);
      }
      return fillScoutText(text);
    } catch {
      return { success: false, error: 'スカウト画面の表示がタイムアウトしました' };
    }
  }

  return { success: false, error: 'スカウト画面が開いていません。先に候補者のスカウト画面を開いてください。' };
}

/** サイドパネルから次の候補者を取得 */
function getNextCandidate(): Promise<{ memberId: string; text: string } | null> {
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

/** overlay閉じ or スキップのいずれかを待つ */
function waitForOverlayCloseOrSkip(timeoutMs: number): Promise<'closed' | 'skipped'> {
  return new Promise((resolve) => {
    let resolved = false;

    // スキップ用のコールバックを登録
    skipResolver = () => {
      if (resolved) return;
      resolved = true;
      closeOverlay();
      resolve('skipped');
    };

    // overlay閉じの通常監視
    waitForOverlayClose(timeoutMs).then(() => {
      if (resolved) return;
      resolved = true;
      skipResolver = null;
      resolve('closed');
    });
  });
}

/** 連続送信ループ */
async function startContinuousSend(): Promise<void> {
  continuousSendActive = true;
  console.log('[Scout Assistant] Continuous send started');

  while (continuousSendActive) {
    // サイドパネルから次の候補者を取得
    const next = await getNextCandidate();
    if (!next) {
      console.log('[Scout Assistant] No more candidates, stopping continuous send');
      break;
    }

    console.log(`[Scout Assistant] Processing candidate: ${next.memberId}`);

    // 求人情報はサイドパネルのstorageから取得（Content Scriptからもアクセス可能）
    const stored = await chrome.storage.local.get('scout_selected_job_offer');
    const jobOffer = stored.scout_selected_job_offer as { id: string; name: string } | undefined;

    if (!jobOffer) {
      console.error('[Scout Assistant] No job offer selected. Please select a job offer in the side panel.');
      break;
    }

    // handleFillFormで入力（overlayを開いてテキストをセット）
    console.log(`[Scout Assistant] Calling handleFillForm for ${next.memberId}, jobOffer:`, jobOffer.id, jobOffer.name?.slice(0, 30));
    const result = await handleFillForm(
      next.text,
      next.memberId,
      jobOffer?.id,
      jobOffer?.name
    );
    console.log(`[Scout Assistant] handleFillForm result:`, result);

    if (!result.success) {
      console.error('[Scout Assistant] Fill form failed:', result.error);
      // カードが見つからない場合はスキップして次へ（ページに表示されていない候補者）
      safeSendMessage({ type: 'CANDIDATE_SENT', memberId: next.memberId });
      await sleep(300);
      continue;
    }

    // ユーザーの送信 or スキップを待つ
    const action = await waitForOverlayCloseOrSkip(0);

    if (!continuousSendActive) break;

    // DOM更新を待つ
    await sleep(500);

    if (action === 'skipped') {
      // スキップを通知（サイドパネルで skipped 状態に更新）
      safeSendMessage({ type: 'CANDIDATE_SENT', memberId: next.memberId });
      // Note: CANDIDATE_SENT + skipped status は CandidateList 側で
      // SKIP_CURRENT_CANDIDATE 発行時に先にステータスを更新済み
    } else {
      // 送信済みを通知
      safeSendMessage({ type: 'CANDIDATE_SENT', memberId: next.memberId });
    }
  }

  continuousSendActive = false;
  skipResolver = null;
  console.log('[Scout Assistant] Continuous send ended');
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
  console.log(`[Scout Assistant] Found ${cards.length} cards, will extract ${total}`);
  const profiles: CandidateProfile[] = [];

  for (let i = 0; i < total; i++) {
    if (extractionAborted) break;

    const scoutBtn = cards[i].querySelector(SELECTORS.scoutButton);
    console.log(`[Scout Assistant] Card ${i}: scoutBtn =`, scoutBtn ? 'found' : 'NOT FOUND', 'selector:', SELECTORS.scoutButton);
    if (!scoutBtn) continue;
    (scoutBtn as HTMLElement).click();
    console.log(`[Scout Assistant] Card ${i}: clicked scout button, waiting for overlay...`);

    const overlay = await waitForOverlay();
    console.log(`[Scout Assistant] Card ${i}: overlay appeared`);
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
