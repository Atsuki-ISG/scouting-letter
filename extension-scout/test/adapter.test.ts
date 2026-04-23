/**
 * コメディカルドットコム (co-medical.com) adapter テスト
 *
 * 2026-04-21 実機調査で得たDOM構造に基づく fixture。
 */

import { describe, expect, it, beforeEach } from 'vitest';
import {
  matchUrl,
  isSearchPage,
  getCandidateList,
  extractProfileFromCard,
  getComposeTextarea,
  getSendButton,
  findCardForActiveModal,
} from '../src/content/adapters/comedical-dom';

describe('matchUrl', () => {
  it('co-medical.com 配下にマッチ', () => {
    expect(matchUrl('https://co-medical.com/')).toBe(true);
    expect(matchUrl('https://www.co-medical.com/manage/scout/list/freescout/')).toBe(true);
  });

  it('他媒体にはマッチしない', () => {
    expect(matchUrl('https://kaigojob.com/')).toBe(false);
    expect(matchUrl('https://job-medley.com/')).toBe(false);
    expect(matchUrl('https://example.com/')).toBe(false);
  });
});

describe('isSearchPage', () => {
  beforeEach(() => {
    // jsdom で location.pathname を操作するために history を使う
    window.history.pushState({}, '', '/');
  });

  it('/manage/freescout/search/{id}/ で true', () => {
    window.history.pushState({}, '', '/manage/freescout/search/594248/');
    expect(isSearchPage()).toBe(true);
  });

  it('他パスで false', () => {
    window.history.pushState({}, '', '/manage/scout/list/freescout/');
    expect(isSearchPage()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 候補者カード用 fixture
// ---------------------------------------------------------------------------
function setupCard(opts?: { memberId?: string; jobId?: string; age?: string; gender?: string; qualifications?: string; experience?: string; area?: string }) {
  const o = {
    memberId: '368872',
    jobId: '594248',
    age: '37歳',
    gender: '女性',
    qualifications: '看護師',
    experience: '10年以上',
    area: '神奈川県横浜市中区',
    ...opts,
  };
  document.body.innerHTML = `
    <div class="scout_box">
      <div>
        <div class="tag_list"><p class="cat1">未読</p></div>
        <h4>${o.age}(${o.gender})</h4>
        <h4>${o.qualifications}</h4>
        <div>マッチングスコア <span class="f18 bold text-primary">93点</span></div>
      </div>
      <div>
        <h5>登録情報</h5>
        実務経験：${o.experience}<br>
        現住所：${o.area}<br>
        希望給与：月給20万円以上<br>
        希望エリア：神奈川県横浜市西区<br>
      </div>
      <div>
        <h5>スキル・業務経験</h5>
        <div class="skill">
          <span>回復期リハビリ病棟</span>
          <span>療養病棟</span>
        </div>
      </div>
      <div class="public_preference">
        <a href="javascript:void(0);" class="btn btn-primary btnScout" data-target="${o.jobId}/${o.memberId}">スカウト送信</a>
      </div>
    </div>
  `;
}

describe('getCandidateList', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('空DOMで空配列', () => {
    expect(getCandidateList()).toEqual([]);
  });

  it('.scout_box から memberId / jobId を抽出', () => {
    setupCard();
    const handles = getCandidateList();
    expect(handles).toHaveLength(1);
    expect(handles[0].memberId).toBe('368872');
    expect(handles[0].jobId).toBe('594248');
    expect(handles[0].element.classList.contains('scout_box')).toBe(true);
  });

  it('data-target が無いカードはスキップ', () => {
    setupCard();
    // 1枚目の data-target を消す
    document.querySelector('.btnScout')?.removeAttribute('data-target');
    expect(getCandidateList()).toHaveLength(0);
  });
});

describe('extractProfileFromCard', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('年齢・性別・資格を H4 から取得', () => {
    setupCard();
    const card = document.querySelector<HTMLElement>('.scout_box')!;
    const p = extractProfileFromCard(card);
    expect(p.member_id).toBe('368872');
    expect(p.age).toBe('37歳');
    expect(p.gender).toBe('女性');
    expect(p.qualifications).toBe('看護師');
  });

  it('登録情報から 実務経験・現住所・希望エリア を取得', () => {
    setupCard({ experience: '5年以上', area: '東京都新宿区' });
    const card = document.querySelector<HTMLElement>('.scout_box')!;
    const p = extractProfileFromCard(card);
    expect(p.experience_years).toBe('5年以上');
    expect(p.area).toBe('東京都新宿区');
    expect(p.desired_area).toBe('神奈川県横浜市西区');
  });

  it('スキル・業務経験を special_conditions に集約', () => {
    setupCard();
    const card = document.querySelector<HTMLElement>('.scout_box')!;
    const p = extractProfileFromCard(card);
    expect(p.special_conditions).toContain('回復期リハビリ病棟');
    expect(p.special_conditions).toContain('療養病棟');
  });

  it('全角括弧（の年齢表記もパース', () => {
    document.body.innerHTML = `
      <div class="scout_box">
        <h4>42歳（男性）</h4>
        <h4>介護福祉士</h4>
        <a class="btnScout" data-target="100/200">スカウト送信</a>
      </div>
    `;
    const card = document.querySelector<HTMLElement>('.scout_box')!;
    const p = extractProfileFromCard(card);
    expect(p.age).toBe('42歳');
    expect(p.gender).toBe('男性');
    expect(p.qualifications).toBe('介護福祉士');
  });
});

// ---------------------------------------------------------------------------
// モーダル関連
// ---------------------------------------------------------------------------
function setupModalWithCard(memberId = '368872') {
  document.body.innerHTML = `
    <div class="scout_box">
      <h4>37歳(女性)</h4>
      <h4>看護師</h4>
      <div><h5>登録情報</h5>実務経験：10年以上<br></div>
      <a class="btnScout" data-target="594248/${memberId}">スカウト送信</a>
    </div>
    <section id="modalAreaScoutMessage" class="modalArea is-show">
      <form action="https://www.co-medical.com/manage/freescout/detailsend/594248/${memberId}/1/" method="post">
        <textarea id="message_input" name="message">既存の文</textarea>
      </form>
      <button type="submit">戻る</button>
      <button type="submit">スカウト送信</button>
    </section>
  `;
}

describe('getComposeTextarea', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('モーダル内の #message_input を返す', () => {
    setupModalWithCard();
    const ta = getComposeTextarea();
    expect(ta).not.toBeNull();
    expect(ta?.id).toBe('message_input');
  });

  it('無ければ null', () => {
    expect(getComposeTextarea()).toBeNull();
  });
});

describe('getSendButton', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('is-show のモーダル内の「スカウト送信」ボタンを返す', () => {
    setupModalWithCard();
    const btn = getSendButton();
    expect(btn).not.toBeNull();
    expect(btn?.textContent?.trim()).toBe('スカウト送信');
  });

  it('モーダルが is-show でなければ null', () => {
    setupModalWithCard();
    document
      .querySelector('#modalAreaScoutMessage')
      ?.classList.remove('is-show');
    expect(getSendButton()).toBeNull();
  });
});

describe('findCardForActiveModal', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('form action の memberId から対応カードを逆引き', () => {
    setupModalWithCard('368872');
    const card = findCardForActiveModal();
    expect(card).not.toBeNull();
    expect(card?.classList.contains('scout_box')).toBe(true);
  });

  it('無ければ null', () => {
    expect(findCardForActiveModal()).toBeNull();
  });
});
