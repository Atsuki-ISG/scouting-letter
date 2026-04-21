/**
 * JobMedley adapter テスト
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { jobmedleyAdapter } from '../../src/content/adapters/jobmedley';

describe('jobmedleyAdapter', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  describe('matchUrl', () => {
    it('job-medley.com 配下にマッチ', () => {
      expect(jobmedleyAdapter.matchUrl('https://job-medley.com/')).toBe(true);
      expect(
        jobmedleyAdapter.matchUrl('https://customers.job-medley.com/searches')
      ).toBe(true);
    });

    it('他媒体にはマッチしない', () => {
      expect(jobmedleyAdapter.matchUrl('https://welme.jp/')).toBe(false);
      expect(jobmedleyAdapter.matchUrl('https://example.com/')).toBe(false);
    });
  });

  describe('getCandidateList', () => {
    it('空DOMで空配列', () => {
      expect(jobmedleyAdapter.getCandidateList()).toEqual([]);
    });

    it('候補者カードの memberId を拾う', () => {
      document.body.innerHTML = `
        <div class="c-search-member-card">
          <input name="member-select" value="12345" />
        </div>
        <div class="c-search-member-card">
          <input name="member-select" value="67890" />
        </div>
      `;
      const handles = jobmedleyAdapter.getCandidateList();
      expect(handles).toHaveLength(2);
      expect(handles[0].memberId).toBe('12345');
      expect(handles[1].memberId).toBe('67890');
    });

    it('memberId が空のカードはスキップ', () => {
      document.body.innerHTML = `
        <div class="c-search-member-card">
          <input name="member-select" value="" />
        </div>
        <div class="c-search-member-card">
          <input name="member-select" value="11111" />
        </div>
      `;
      const handles = jobmedleyAdapter.getCandidateList();
      expect(handles).toHaveLength(1);
      expect(handles[0].memberId).toBe('11111');
    });
  });

  describe('getComposeTextarea', () => {
    it('textarea[name="body"] を返す', () => {
      document.body.innerHTML = '<textarea name="body"></textarea>';
      expect(jobmedleyAdapter.getComposeTextarea()).not.toBeNull();
    });

    it('なければ null', () => {
      expect(jobmedleyAdapter.getComposeTextarea()).toBeNull();
    });
  });
});
