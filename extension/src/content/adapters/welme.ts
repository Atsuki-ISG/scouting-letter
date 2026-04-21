/**
 * WelMe (welme.jp) 向け MediumAdapter
 *
 * 現時点は skeleton。実際のDOM構造は未調査のため、メソッドは
 * 空DOMで安全に null / 空配列 / 空プロフィールを返す最小実装。
 *
 * 次の段階で実候補者ページのHTMLを拾って fixture 化し、
 * extractProfile / getCandidateList / getComposeTextarea を実装する。
 */

import {
  emptyCandidateProfile,
  type CandidateHandle,
  type MediumAdapter,
} from '../../shared/medium-adapter';
import type { CandidateProfile } from '../../shared/types';

const WELME_HOST_RE = /^https?:\/\/([a-z0-9-]+\.)?welme\.jp(\/|$)/i;

export const welmeAdapter: MediumAdapter = {
  id: 'welme',
  displayName: 'WelMe',

  matchUrl(url: string): boolean {
    return WELME_HOST_RE.test(url);
  },

  getCandidateList(): CandidateHandle[] {
    // TODO: 候補者一覧ページのDOM調査後に実装
    return [];
  },

  async extractProfile(): Promise<CandidateProfile> {
    // TODO: 候補者プロフィールページのDOM調査後に実装
    return emptyCandidateProfile();
  },

  getComposeTextarea(): HTMLTextAreaElement | null {
    // TODO: スカウト送信画面の textarea セレクタ特定後に実装
    return null;
  },
};
