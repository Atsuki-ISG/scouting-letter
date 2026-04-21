/**
 * WelMe adapter テスト
 *
 * 現時点は skeleton 段階。DOM構造が特定できたら、実際の候補者ページの
 * HTMLサンプルを fixture として食わせて extractProfile を検証する。
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { welmeAdapter } from '../../src/content/adapters/welme';

describe('welmeAdapter', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  describe('matchUrl', () => {
    it('welme.jp 配下の URL にマッチする', () => {
      expect(welmeAdapter.matchUrl('https://welme.jp/dashboard')).toBe(true);
      expect(welmeAdapter.matchUrl('https://www.welme.jp/candidates/123')).toBe(true);
    });

    it('他媒体のURLにはマッチしない', () => {
      expect(welmeAdapter.matchUrl('https://job-medley.com/')).toBe(false);
      expect(welmeAdapter.matchUrl('https://example.com/')).toBe(false);
    });
  });

  describe('id / displayName', () => {
    it('id は welme', () => {
      expect(welmeAdapter.id).toBe('welme');
    });

    it('displayName は人間向け文字列', () => {
      expect(welmeAdapter.displayName.length).toBeGreaterThan(0);
    });
  });

  describe('空DOM挙動', () => {
    it('getCandidateList は空配列を返す', () => {
      expect(welmeAdapter.getCandidateList()).toEqual([]);
    });

    it('extractProfile は空プロフィールを返す（エラーにしない）', async () => {
      const profile = await welmeAdapter.extractProfile();
      expect(profile.member_id).toBe('');
      expect(profile.is_favorite).toBe(false);
    });

    it('getComposeTextarea は null を返す', () => {
      expect(welmeAdapter.getComposeTextarea()).toBeNull();
    });
  });
});
