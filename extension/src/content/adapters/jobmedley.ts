/**
 * ジョブメドレー (job-medley.com) 向け MediumAdapter
 *
 * 既存の scraper / selectors を薄くラップしているだけ。
 * 本格的な抽出・送信フローは従来どおり content/index.ts の各モジュール
 * が直接処理する。このアダプタは「候補者の列挙」「textarea特定」など
 * 媒体非依存にしたい基本操作の窓口。
 */

import {
  emptyCandidateProfile,
  type CandidateHandle,
  type MediumAdapter,
} from '../../shared/medium-adapter';
import type { CandidateProfile } from '../../shared/types';
import { SELECTORS } from '../selectors';

const JOBMEDLEY_HOST_RE = /^https?:\/\/([a-z0-9-]+\.)?job-medley\.com(\/|$)/i;

export const jobmedleyAdapter: MediumAdapter = {
  id: 'jobmedley',
  displayName: 'ジョブメドレー',

  matchUrl(url: string): boolean {
    return JOBMEDLEY_HOST_RE.test(url);
  },

  getCandidateList(): CandidateHandle[] {
    const cards = Array.from(
      document.querySelectorAll<HTMLElement>(SELECTORS.candidateCard)
    );
    return cards
      .map((card) => {
        const checkbox = card.querySelector<HTMLInputElement>(
          SELECTORS.memberCheckbox
        );
        const memberId = checkbox?.value?.trim() ?? '';
        if (!memberId) return null;
        const label =
          card.querySelector('[data-member-label]')?.textContent?.trim() ||
          undefined;
        return { memberId, element: card, label } satisfies CandidateHandle;
      })
      .filter((h): h is CandidateHandle => h !== null);
  },

  async extractProfile(): Promise<CandidateProfile> {
    // 実際の overlay ベース抽出は scraper.extractProfile が担うが、
    // この adapter では呼び出し契約を満たす最小実装のみ提供。
    // content/index.ts 側の抽出フローが従来どおり scraper を呼ぶ。
    return emptyCandidateProfile();
  },

  getComposeTextarea(): HTMLTextAreaElement | null {
    return document.querySelector<HTMLTextAreaElement>(
      SELECTORS.scoutTextarea
    );
  },
};
