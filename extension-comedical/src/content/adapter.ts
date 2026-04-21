/**
 * コメディカルドットコム (co-medical.com) DOM 操作レイヤー。
 *
 * 2026-04-21 実機調査ベース。
 *
 * WelMe との違い:
 *   - スカウト送信は別URL (/talks/) ではなく、同じ一覧ページ上の
 *     モーダル (section#modalAreaScoutMessage) で行う
 *   - 候補者プロフィールは カード (.scout_box) 内に登録情報として同居
 *     → プロフィール詳細画面を開かなくても必要情報が取れる
 *   - 実務経験フィールドあり → pattern-matcher の A/B1/B2/C/E も発火
 *   - 年齢は具体値（例「37歳(女性)」）
 */

import { emptyCandidateProfile, type CandidateProfile } from '../shared/types';

const HOST_RE = /^https?:\/\/([a-z0-9-]+\.)?co-medical\.com(\/|$)/i;
const SEARCH_PATH_RE = /\/manage\/freescout\/search\/\d+/;

export const CANDIDATE_CARD_SELECTOR = '.scout_box';
export const SEND_BUTTON_SELECTOR = 'a.btnScout';
export const MODAL_SELECTOR = 'section#modalAreaScoutMessage';
export const MODAL_ACTIVE_CLASS = 'is-show';
export const MODAL_TEXTAREA_SELECTOR = '#message_input';

export interface CandidateHandle {
  memberId: string;
  jobId: string;
  element: HTMLElement;
  sendButton: HTMLAnchorElement;
}

export function matchUrl(url: string): boolean {
  return HOST_RE.test(url);
}

export function isSearchPage(): boolean {
  return SEARCH_PATH_RE.test(location.pathname);
}

/**
 * ページ上の候補者カードを列挙する。
 * data-target="{jobId}/{memberId}" から ID を抽出。
 */
export function getCandidateList(): CandidateHandle[] {
  const cards = Array.from(
    document.querySelectorAll<HTMLElement>(CANDIDATE_CARD_SELECTOR)
  );
  return cards
    .map((card): CandidateHandle | null => {
      const sendButton = card.querySelector<HTMLAnchorElement>(SEND_BUTTON_SELECTOR);
      if (!sendButton) return null;
      const target = sendButton.getAttribute('data-target') || '';
      const [jobId, memberId] = target.split('/');
      if (!jobId || !memberId) return null;
      return { jobId, memberId, element: card, sendButton };
    })
    .filter((h): h is CandidateHandle => h !== null);
}

/**
 * 候補者カードからプロフィールを抽出する。
 * コメディカルは WelMe と違い、一覧カードに実務経験まで全部載っている。
 */
export function extractProfileFromCard(card: HTMLElement): CandidateProfile {
  const profile = emptyCandidateProfile();

  // スカウトボタンの data-target="{jobId}/{memberId}"
  const sendBtn = card.querySelector<HTMLElement>(SEND_BUTTON_SELECTOR);
  const target = sendBtn?.getAttribute('data-target') || '';
  const [, memberId] = target.split('/');
  if (memberId) profile.member_id = memberId;

  // H4 x 2個: "37歳(女性)" と "看護師"
  const h4s = Array.from(card.querySelectorAll('h4')).map((h) =>
    (h.textContent || '').trim()
  );
  for (const h of h4s) {
    const m = h.match(/^(\d+)歳\s*[(（]([^)）]+)[)）]\s*$/);
    if (m) {
      profile.age = `${m[1]}歳`;
      profile.gender = m[2].trim();
    } else if (h && !/歳/.test(h)) {
      // 資格（看護師、介護福祉士、理学療法士等）
      profile.qualifications = h;
    }
  }

  // 登録情報セクション: BR 区切りの「key：value」形式
  const regInfo = findSectionByHeading(card, '登録情報');
  if (regInfo) {
    const kv = parseBrSeparatedKeyValue(regInfo);
    profile.experience_years = kv['実務経験'] || '';
    profile.area = kv['現住所'] || '';
    profile.desired_area = kv['希望エリア'] || '';
    // 転職状況に相当する明示フィールドは無いので空。employment_status は
    // このままなら空 → pattern_matcher では「離職中」扱い。
    // 希望給与はプロフィール書き換えで使わないので格納しない。
  }

  // スキル・業務経験セクション: span のリスト（特徴カテゴリ用に保持）
  const skillDiv = findSectionByHeading(card, 'スキル・業務経験');
  if (skillDiv) {
    const skills = Array.from(skillDiv.querySelectorAll('.skill span'))
      .map((s) => (s.textContent || '').trim())
      .filter((s) => s);
    profile.special_conditions = skills.join('、');
  }

  return profile;
}

/** コメディカルでは「プロフィール詳細」を開かずカードから抽出するため、 */
/** 単独の extractProfile は「現在開いているモーダルの data-target から */
/** 対応カードを逆引き → そのカードで extractProfileFromCard」の形で使う。 */
export async function extractProfile(): Promise<CandidateProfile> {
  // 現在開いているモーダルから memberId を取り、対応するカードを探す
  const activeModal = document.querySelector<HTMLElement>(
    `${MODAL_SELECTOR}.${MODAL_ACTIVE_CLASS}`
  );
  if (!activeModal) return emptyCandidateProfile();

  const card = findCardForActiveModal();
  if (!card) return emptyCandidateProfile();
  return extractProfileFromCard(card);
}

/** モーダル内の form action から memberId を拾い、該当カードを返す */
export function findCardForActiveModal(): HTMLElement | null {
  const activeModal = document.querySelector<HTMLElement>(
    `${MODAL_SELECTOR}.${MODAL_ACTIVE_CLASS}`
  );
  if (!activeModal) return null;
  const form = activeModal.querySelector<HTMLFormElement>('form');
  const action = form?.action || '';
  // action pattern: /manage/freescout/detailsend/{jobId}/{memberId}/1/
  const m = action.match(/detailsend\/(\d+)\/(\d+)/);
  if (!m) return null;
  const [, , memberId] = m;
  const cards = Array.from(document.querySelectorAll<HTMLElement>(CANDIDATE_CARD_SELECTOR));
  return (
    cards.find((c) => {
      const t = c.querySelector(SEND_BUTTON_SELECTOR)?.getAttribute('data-target') || '';
      return t.endsWith(`/${memberId}`);
    }) ?? null
  );
}

export function getComposeTextarea(): HTMLTextAreaElement | null {
  return document.querySelector<HTMLTextAreaElement>(MODAL_TEXTAREA_SELECTOR);
}

/** モーダル内の「スカウト送信」ボタン（戻るボタンではない方） */
export function getSendButton(): HTMLButtonElement | null {
  const activeModal = document.querySelector<HTMLElement>(
    `${MODAL_SELECTOR}.${MODAL_ACTIVE_CLASS}`
  );
  if (!activeModal) return null;
  return (
    Array.from(activeModal.querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent?.trim() === 'スカウト送信'
    ) ?? null
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function findSectionByHeading(root: HTMLElement, heading: string): HTMLElement | null {
  const divs = Array.from(root.querySelectorAll<HTMLElement>('div'));
  return (
    divs.find((d) => {
      const h5 = d.querySelector('h5');
      return h5?.textContent?.trim() === heading;
    }) ?? null
  );
}

/**
 * コメディカルの「登録情報」は H5 + BR区切りの text node で構成される:
 *   <div>
 *     <h5>登録情報</h5>
 *     "実務経験：10年以上"<br/>
 *     "現住所：神奈川県..."<br/>
 *     ...
 *   </div>
 * これを { key: value } に変換する。
 */
function parseBrSeparatedKeyValue(section: HTMLElement): Record<string, string> {
  const result: Record<string, string> = {};
  let buffer = '';
  for (const node of Array.from(section.childNodes)) {
    if (node.nodeType === Node.TEXT_NODE) {
      buffer += (node.textContent || '').trim();
    } else if (node.nodeName === 'BR') {
      pushKv(result, buffer);
      buffer = '';
    }
    // H5 etc はスキップ
  }
  if (buffer) pushKv(result, buffer);
  return result;
}

function pushKv(bag: Record<string, string>, raw: string) {
  if (!raw) return;
  const m = raw.match(/^([^：:]+)[：:]\s*(.*)$/);
  if (m) {
    bag[m[1].trim()] = m[2].trim();
  }
}
