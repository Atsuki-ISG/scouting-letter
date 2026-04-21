/**
 * MediumAdapter 契約テスト
 *
 * 全ての MediumAdapter 実装が満たすべき共通仕様。
 * 新しい adapter（welme, comedical等）を追加したら、ここに
 * import してテストケースを増やす。
 */

import { describe, expect, it, beforeEach } from 'vitest';
import {
  emptyCandidateProfile,
  type MediumAdapter,
} from '../src/shared/medium-adapter';
import { jobmedleyAdapter } from '../src/content/adapters/jobmedley';
import { welmeAdapter } from '../src/content/adapters/welme';

function runAdapterContract(name: string, adapter: MediumAdapter) {
  describe(`${name} 契約`, () => {
    beforeEach(() => {
      document.body.innerHTML = '';
    });

    it('id と displayName を持つ', () => {
      expect(adapter.id).toBeTruthy();
      expect(adapter.displayName).toBeTruthy();
    });

    it('matchUrl は string を受け boolean を返す', () => {
      expect(typeof adapter.matchUrl('https://example.com')).toBe('boolean');
    });

    it('空DOMで getCandidateList は空配列を返す', () => {
      expect(adapter.getCandidateList()).toEqual([]);
    });

    it('空DOMで extractProfile は空プロフィールを返す（エラーにしない）', async () => {
      const profile = await adapter.extractProfile();
      expect(profile.member_id).toBeDefined();
      expect(profile.is_favorite).toBe(false);
    });

    it('空DOMで getComposeTextarea は null を返す', () => {
      expect(adapter.getComposeTextarea()).toBeNull();
    });
  });
}

runAdapterContract('jobmedley', jobmedleyAdapter);
runAdapterContract('welme', welmeAdapter);

describe('emptyCandidateProfile', () => {
  it('全フィールドが空文字 or false で初期化される', () => {
    const p = emptyCandidateProfile();
    expect(p.member_id).toBe('');
    expect(p.qualifications).toBe('');
    expect(p.self_pr).toBe('');
    expect(p.is_favorite).toBe(false);
  });
});
