import { CandidateProfile } from '../shared/types';
import { EXTRACTION_INTERVAL_MS } from '../shared/constants';
import { randomSleep } from '../shared/utils';
import { SELECTORS, queryAllElements } from './selectors';
import { waitForOverlay, waitForOverlayClose, extractProfile, closeOverlay } from './scraper';
import { safeSendMessage } from './helpers';

/** 抽出を中断するためのフラグ */
let aborted = false;

export function abort(): void {
  aborted = true;
}

/** カード要素から「気になる」バッジを検出 */
function detectFavorite(card: Element): boolean {
  const text = card.textContent || '';
  return text.includes('「気になる」した求職者');
}

/** カード要素からスカウト送信日を抽出 */
function extractScoutSentDate(card: Element): string {
  const allText = card.querySelectorAll('*');
  for (const el of allText) {
    const text = el.textContent?.trim() || '';
    if (text.startsWith('スカウト送信日')) {
      const lines = text.split('\n').map((l) => l.trim()).filter(Boolean);
      if (lines.length >= 2) {
        return lines.slice(1).join(', ');
      }
      const next = el.nextElementSibling;
      if (next) {
        return next.textContent?.trim() || '';
      }
      return text.replace('スカウト送信日', '').trim();
    }
  }
  return '';
}

/** プロフィール一括抽出 */
export async function startExtraction(count: number, startMemberId?: string): Promise<void> {
  aborted = false;
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
  console.log(`[Scout Assistant] Found ${cards.length} cards, startIndex=${startIndex}, will extract ${total}`);
  const profiles: CandidateProfile[] = [];

  for (let i = 0; i < total; i++) {
    const cardIndex = startIndex + i;
    if (aborted) break;

    const scoutSentDate = extractScoutSentDate(cards[cardIndex]);
    const isFavorite = detectFavorite(cards[cardIndex]);

    const scoutBtn = cards[cardIndex].querySelector(SELECTORS.scoutButton);
    console.log(`[Scout Assistant] Card ${cardIndex}: scoutBtn =`, scoutBtn ? 'found' : 'NOT FOUND', 'selector:', SELECTORS.scoutButton);
    if (!scoutBtn) continue;
    (scoutBtn as HTMLElement).click();
    console.log(`[Scout Assistant] Card ${cardIndex}: clicked scout button, waiting for overlay...`);

    const overlay = await waitForOverlay();
    console.log(`[Scout Assistant] Card ${cardIndex}: overlay appeared`);
    const profile = await extractProfile(overlay);
    profile.scout_sent_date = scoutSentDate;
    profile.is_favorite = isFavorite;
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
      await randomSleep(EXTRACTION_INTERVAL_MS, EXTRACTION_INTERVAL_MS * 4);
    }
  }

  safeSendMessage({
    type: 'EXTRACTION_COMPLETE',
    profiles,
  });
}
