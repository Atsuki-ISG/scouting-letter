/**
 * WelMe (ウェルミージョブ) adapter テスト
 *
 * ドメインは kaigojob.com（旧カイゴジョブ時代からのURL）。ブランド名は
 * 「ウェルミージョブ」。2026-04 実機調査で得たDOM構造に基づき fixture
 * を作っている。
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { welmeAdapter } from '../../src/content/adapters/welme';

describe('welmeAdapter', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  describe('matchUrl', () => {
    it('kaigojob.com 配下の URL にマッチ', () => {
      expect(welmeAdapter.matchUrl('https://kaigojob.com/')).toBe(true);
      expect(welmeAdapter.matchUrl('https://www.kaigojob.com/employer/KJ-0097841/scouts/newcomers')).toBe(true);
      expect(welmeAdapter.matchUrl('https://www.kaigojob.com/employer/KJ-0097841/talks/abc')).toBe(true);
    });

    it('welme.jp（将来のドメイン）にもマッチ', () => {
      expect(welmeAdapter.matchUrl('https://welme.jp/')).toBe(true);
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

  describe('getCandidateList: 候補者一覧ページ', () => {
    beforeEach(() => {
      // 実ページで観測した table 構造（簡略版）
      document.body.innerHTML = `
        <table class="e-management-table scout__index-table">
          <tbody>
            <tr>
              <td class="is-left"><label class="e-checkbox"><input type="checkbox"><span></span></label></td>
              <td class="is-left">ID 83051094<div class="hy-tags"><span class="e-tag is-primary">マッチ</span></div>神奈川県藤沢市 | 30-34歳 男性<div class="tags is-block"><span class="tag is-light">看護師</span></div></td>
              <td class="is-left"></td>
              <td class="is-left"></td>
              <td class="is-centered"><button class="e-button is-info">スカウトする</button></td>
            </tr>
            <tr>
              <td class="is-left"><label class="e-checkbox"><input type="checkbox"><span></span></label></td>
              <td class="is-left">ID 79087831<div>神奈川県藤沢市 | 50-54歳 女性</div><span class="tag is-light">主任介護支援専門員</span></td>
              <td class="is-left"></td>
              <td class="is-left"></td>
              <td class="is-centered"><button class="e-button is-info">スカウトする</button></td>
            </tr>
          </tbody>
        </table>
      `;
    });

    it('2行から memberId を抽出', () => {
      const handles = welmeAdapter.getCandidateList();
      expect(handles).toHaveLength(2);
      expect(handles[0].memberId).toBe('83051094');
      expect(handles[1].memberId).toBe('79087831');
    });

    it('element は tr 要素', () => {
      const handles = welmeAdapter.getCandidateList();
      expect(handles[0].element.tagName).toBe('TR');
    });
  });

  describe('extractProfile: /talks/{uuid} ページ', () => {
    beforeEach(() => {
      // 実スカウト画面で観測した dl 構造
      document.body.innerHTML = `
        <dl class="c-definition__list c-definition__list--small c-definition__list--reverse-weight">
          <dt class="c-definition__term">ID</dt><dd class="c-definition__description">83051094</dd>
          <dt class="c-definition__term">基本情報</dt><dd class="c-definition__description">神奈川県藤沢市: 30-34歳 男性</dd>
          <dt class="c-definition__term">保有資格</dt><dd class="c-definition__description">看護師</dd>
          <dt class="c-definition__term">現職</dt><dd class="c-definition__description"></dd>
          <dt class="c-definition__term">職歴</dt><dd class="c-definition__description"></dd>
          <dt class="c-definition__term">希望職種</dt><dd class="c-definition__description">看護師・准看護師</dd>
          <dt class="c-definition__term">希望勤務地</dt><dd class="c-definition__description">神奈川県 藤沢市、神奈川県 横浜市西区、東京都 品川区</dd>
          <dt class="c-definition__term">希望雇用形態</dt><dd class="c-definition__description">正社員、契約社員</dd>
          <dt class="c-definition__term">希望年収</dt><dd class="c-definition__description">650万円</dd>
          <dt class="c-definition__term">転職状況</dt><dd class="c-definition__description">良い転職先なら辞めたい</dd>
          <dt class="c-definition__term">勤務可能時間</dt><dd class="c-definition__description">日勤</dd>
          <dt class="c-definition__term">勤務可能曜日</dt><dd class="c-definition__description"></dd>
        </dl>
      `;
    });

    it('member_id を ID から抽出', async () => {
      const p = await welmeAdapter.extractProfile();
      expect(p.member_id).toBe('83051094');
    });

    it('基本情報から area / age / gender を分解', async () => {
      const p = await welmeAdapter.extractProfile();
      expect(p.area).toBe('神奈川県藤沢市');
      expect(p.age).toBe('30-34歳');
      expect(p.gender).toBe('男性');
    });

    it('保有資格 → qualifications', async () => {
      const p = await welmeAdapter.extractProfile();
      expect(p.qualifications).toBe('看護師');
    });

    it('就業状況: 現職空 かつ 転職状況「辞めたい」系 → 就業中', async () => {
      const p = await welmeAdapter.extractProfile();
      expect(p.employment_status).toBe('就業中');
    });

    it('希望職種/勤務地/雇用形態が入る', async () => {
      const p = await welmeAdapter.extractProfile();
      expect(p.desired_job).toBe('看護師・准看護師');
      expect(p.desired_employment_type).toBe('正社員、契約社員');
      expect(p.desired_area).toContain('神奈川県');
    });

    it('職歴・自己PRは空（WelMeは項目自体が無い）', async () => {
      const p = await welmeAdapter.extractProfile();
      expect(p.work_history_summary).toBe('');
      expect(p.self_pr).toBe('');
    });
  });

  describe('extractProfile: 就業状況判定', () => {
    const makeDl = (genkShoku: string, tenshoku: string) => `
      <dl class="c-definition__list">
        <dt class="c-definition__term">ID</dt><dd class="c-definition__description">1</dd>
        <dt class="c-definition__term">基本情報</dt><dd class="c-definition__description">東京都: 30-34歳 男性</dd>
        <dt class="c-definition__term">現職</dt><dd class="c-definition__description">${genkShoku}</dd>
        <dt class="c-definition__term">転職状況</dt><dd class="c-definition__description">${tenshoku}</dd>
      </dl>
    `;

    it('現職に値がある → 就業中', async () => {
      document.body.innerHTML = makeDl('〇〇病院', '');
      expect((await welmeAdapter.extractProfile()).employment_status).toBe('就業中');
    });

    it('現職空 + 転職状況「求職中」 → 離職中', async () => {
      document.body.innerHTML = makeDl('', '求職中');
      expect((await welmeAdapter.extractProfile()).employment_status).toBe('離職中');
    });

    it('現職空 + 転職状況空 → 離職中（デフォルト）', async () => {
      document.body.innerHTML = makeDl('', '');
      expect((await welmeAdapter.extractProfile()).employment_status).toBe('離職中');
    });
  });

  describe('getComposeTextarea', () => {
    it('#scout-talk-message-input が取れる', () => {
      document.body.innerHTML = '<textarea id="scout-talk-message-input"></textarea>';
      const t = welmeAdapter.getComposeTextarea();
      expect(t).not.toBeNull();
      expect(t?.id).toBe('scout-talk-message-input');
    });
  });
});
