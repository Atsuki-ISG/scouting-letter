/**
 * メッセージページのDOM抽出（Phase B実装）
 *
 * DOM調査日: 2026-03-01
 * 企業メッセージ: .c-message__inner--companion クラスあり
 * 求職者メッセージ: .c-message__inner のみ
 * 日付: 各メッセージ直後のテキストノード "2026/02/26 13:45 求職者" 形式
 */

import { ConversationMessage, ConversationThread, Message } from '../shared/types';
import { MESSAGE_SELECTORS } from './message-selectors';

/**
 * メッセージページからやりとりスレッドを抽出
 */
export function extractConversation(): ConversationThread | null {
  const view = document.querySelector(MESSAGE_SELECTORS.messageView);
  if (!view) {
    console.log('[Scout Assistant] メッセージビューが見つかりません');
    return null;
  }

  // 会員番号を取得
  const memberId = extractMemberId();
  if (!memberId) {
    console.log('[Scout Assistant] 会員番号を取得できません');
    return null;
  }

  // メッセージ一覧を取得
  const messages = extractMessages();
  if (messages.length === 0) {
    console.log('[Scout Assistant] メッセージが見つかりません');
    return null;
  }

  // ヘッダーから候補者情報を取得
  const headerInfo = extractHeaderInfo();

  const thread: ConversationThread = {
    member_id: memberId,
    company: '', // サイドパネル側でstorageから補完
    started: messages[0].date,
    ...headerInfo,
    messages,
  };

  return thread;
}

/**
 * ヘッダーから会員番号を抽出
 * 形式: "03114222 | 53歳 女性" or "03114222  | 53歳 女性"
 */
function extractMemberId(): string | null {
  const el = document.querySelector(MESSAGE_SELECTORS.memberIdText);
  if (!el) return null;

  const text = el.textContent?.trim() || '';
  // "03114222 | 53歳 女性" → "03114222"
  const match = text.match(/^(\d+)/);
  return match ? match[1] : null;
}

/**
 * ヘッダーから候補者情報を抽出
 * 名前: "野口 いずみ"
 * 会員番号等: "03114222 | 53歳 女性"
 * 求人タイトル: "医療法人社団優希 アーク訪問看護ステーション 看護師/准看護師 (訪問看護師) パート・バイト 求人"
 */
function extractHeaderInfo(): {
  candidate_name?: string;
  candidate_age?: string;
  candidate_gender?: string;
  job_title?: string;
} {
  const sticky = document.querySelector(MESSAGE_SELECTORS.stickyHeader);
  if (!sticky) return {};

  // 候補者名: .ds-o-flex 内の最初の .u-fs-lh-medium-short.u-fw-bold
  const nameEl = sticky.querySelector(MESSAGE_SELECTORS.candidateName);
  const candidate_name = nameEl?.textContent?.trim() || undefined;

  // "03114222 | 53歳 女性" → 年齢・性別を抽出
  const idEl = sticky.querySelector(MESSAGE_SELECTORS.memberIdText);
  const idText = idEl?.textContent?.trim() || '';
  const ageGenderMatch = idText.match(/(\d+)歳\s*(男性|女性)/);
  const candidate_age = ageGenderMatch ? ageGenderMatch[1] + '歳' : undefined;
  const candidate_gender = ageGenderMatch ? ageGenderMatch[2] : undefined;

  // 求人タイトル: sticky内の最初の .u-fs-lh-medium-short.u-fw-bold（nameと別の要素）
  const titleEls = sticky.querySelectorAll('.u-fs-lh-medium-short.u-fw-bold');
  let job_title: string | undefined;
  for (const el of titleEls) {
    const text = el.textContent?.trim() || '';
    // 求人タイトルは "求人" を含むか、名前より長い
    if (text.includes('求人') || text.length > 20) {
      job_title = text;
      break;
    }
  }

  return { candidate_name, candidate_age, candidate_gender, job_title };
}

/**
 * 全メッセージを抽出
 */
function extractMessages(): ConversationMessage[] {
  const container = document.querySelector(MESSAGE_SELECTORS.messageListInner);
  if (!container) return [];

  const messageEls = container.querySelectorAll(MESSAGE_SELECTORS.messageItem);
  const messages: ConversationMessage[] = [];

  // 日付情報を親要素のHTMLから一括取得
  const dateInfos = extractDateInfos(container);

  messageEls.forEach((el, index) => {
    const inner = el.querySelector(MESSAGE_SELECTORS.messageInner);
    if (!inner) return;

    // 企業 or 求職者の判定
    const isCompany = inner.classList.contains(MESSAGE_SELECTORS.companionModifier);
    const role: 'company' | 'candidate' = isCompany ? 'company' : 'candidate';

    // メッセージ本文の取得
    const bodyEl = el.querySelector(MESSAGE_SELECTORS.messageBody);
    if (!bodyEl) return;

    const text = extractMessageText(bodyEl);
    if (!text) return;

    // 日付の取得
    const dateInfo = dateInfos[index];
    const date = dateInfo?.date || '';

    messages.push({ role, date, text });
  });

  return messages;
}

/**
 * メッセージ本文からテキストを抽出
 * ラベル（スカウト/応募/通常）は除外し、本文のみを返す
 */
function extractMessageText(bodyEl: Element): string {
  // bodyEl内の構造:
  // <div>
  //   <span class="u-disp-inline-table ..."><span class="c-label ...">通常</span>&nbsp;</span>
  //   <span><span>本文行1<br></span><span>本文行2<br></span>...</span>
  // </div>

  const div = bodyEl.querySelector('div');
  if (!div) return bodyEl.textContent?.trim() || '';

  // ラベルspanを除外して、2番目のspanからテキストを取得
  const spans = div.children;
  let textContent = '';

  for (let i = 0; i < spans.length; i++) {
    const span = spans[i] as HTMLElement;
    // ラベルを含むspanをスキップ
    if (span.querySelector(MESSAGE_SELECTORS.messageLabel)) continue;
    textContent += span.textContent || '';
  }

  return textContent.trim();
}

/**
 * コンテナのHTMLから日付情報を抽出
 * 日付は各.c-messageの外側に "2026/02/26 13:45 求職者" の形式で存在
 */
function extractDateInfos(container: Element): Array<{ date: string; isCandidate: boolean }> {
  const html = container.innerHTML;
  // "YYYY/MM/DD HH:MM" 形式を抽出（"求職者"付きの場合もある）
  const regex = /(\d{4})\/(\d{2})\/(\d{2})\s+(\d{2}:\d{2})(\s+求職者)?/g;
  const infos: Array<{ date: string; isCandidate: boolean }> = [];
  let match;

  while ((match = regex.exec(html)) !== null) {
    const dateStr = `${match[1]}-${match[2]}-${match[3]}`;
    const isCandidate = !!match[5];
    infos.push({ date: dateStr, isCandidate });
  }

  return infos;
}

/**
 * 現在のページがメッセージページかどうかを判定
 */
export function isMessagePage(): boolean {
  return location.pathname.includes('/messages');
}

/** 指定ミリ秒待機 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** メッセージビューが読み込まれるまで待機 */
async function waitForMessageView(timeoutMs = 5000): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const view = document.querySelector(MESSAGE_SELECTORS.messageView);
    if (view) return true;
    await sleep(200);
  }
  return false;
}

/** 一括抽出中断フラグ */
let batchAborted = false;

/** 一括抽出を中断 */
export function abortBatchExtraction(): void {
  batchAborted = true;
}

/**
 * サイドバーをスクロールして全会話を読み込む
 * 無限スクロールで逐次読み込まれるため、末尾までスクロールを繰り返す
 */
async function loadAllConversations(): Promise<void> {
  const scrollContainer = document.querySelector(MESSAGE_SELECTORS.infinityScroll);
  if (!scrollContainer) {
    console.log('[Scout Assistant] スクロールコンテナが見つかりません');
    return;
  }

  let prevCount = document.querySelectorAll(MESSAGE_SELECTORS.conversationLink).length;
  let stableRounds = 0;
  const maxStableRounds = 3;

  while (stableRounds < maxStableRounds) {
    scrollContainer.scrollTop = scrollContainer.scrollHeight;
    scrollContainer.dispatchEvent(new Event('scroll', { bubbles: true }));
    await sleep(1500);

    const currentCount = document.querySelectorAll(MESSAGE_SELECTORS.conversationLink).length;
    if (currentCount > prevCount) {
      prevCount = currentCount;
      stableRounds = 0;
    } else {
      stableRounds++;
    }
  }

  console.log(`[Scout Assistant] サイドバー読み込み完了: ${document.querySelectorAll(MESSAGE_SELECTORS.conversationLink).length}件`);
}

/**
 * サイドバーの全会話を順番にクリックして一括抽出
 * 進捗はchrome.runtime.sendMessageで都度サイドパネルに通知
 */
export async function extractAllConversations(
  sendProgress: (message: Message) => void
): Promise<void> {
  batchAborted = false;

  // まずサイドバーを全件読み込む
  await loadAllConversations();

  const links = document.querySelectorAll(MESSAGE_SELECTORS.conversationLink);
  const total = links.length;

  if (total === 0) {
    sendProgress({
      type: 'CONVERSATION_ERROR',
      error: '会話が見つかりません',
    });
    return;
  }

  console.log(`[Scout Assistant] 一括抽出開始: ${total}件`);
  let extracted = 0;

  for (let i = 0; i < total; i++) {
    if (batchAborted) {
      console.log('[Scout Assistant] 一括抽出が中断されました');
      break;
    }

    const link = links[i] as HTMLElement;
    link.click();

    // メッセージビューの読み込みを待機
    await sleep(500);
    const loaded = await waitForMessageView();
    if (!loaded) {
      console.log(`[Scout Assistant] ${i + 1}/${total}: メッセージビュー読み込みタイムアウト`);
      continue;
    }

    // DOM更新を少し待つ
    await sleep(300);

    const thread = extractConversation();
    if (thread) {
      extracted++;
      sendProgress({
        type: 'CONVERSATION_PROGRESS',
        current: extracted,
        total,
        thread,
      });
      console.log(`[Scout Assistant] ${i + 1}/${total}: ${thread.member_id} (${thread.messages.length}通)`);
    } else {
      console.log(`[Scout Assistant] ${i + 1}/${total}: 抽出スキップ`);
    }

    // 連続アクセス抑制
    if (i < total - 1) {
      await sleep(500);
    }
  }

  sendProgress({
    type: 'CONVERSATION_BATCH_COMPLETE',
    count: extracted,
  });

  console.log(`[Scout Assistant] 一括抽出完了: ${extracted}/${total}件`);
}
