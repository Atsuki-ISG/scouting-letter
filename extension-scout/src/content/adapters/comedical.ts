/**
 * コメディカルドットコム (co-medical.com) プラットフォームアダプタ。
 *
 * フロー:
 *   /manage/freescout/search/{jobId}/ 上のカードでスカウト送信モーダルが開く
 *   → モーダル内 #message_input にプロフィール由来の本文を自動フィル
 *   → モーダル内「スカウト送信」クリック時に history.add
 */

import {
  matchUrl,
  isSearchPage,
  findCardForActiveModal,
  extractProfileFromCard,
  getComposeTextarea,
  getSendButton,
  MODAL_SELECTOR,
  MODAL_ACTIVE_CLASS,
} from './comedical-dom';
import { matchPattern } from '../../shared/pattern-matcher';
import type { AdapterContext, PlatformAdapter } from './types';
import type { Occupation } from '../../shared/types';

function log(...args: unknown[]) {
  // eslint-disable-next-line no-console
  console.log('[Scout/コメディカル]', ...args);
}

function buildScoutBody(occupation: Occupation, personalized: string): string {
  const templates = occupation.templates;
  const firstInitial = templates.find((t) => t.type.endsWith('_初回')) || templates[0];
  if (!firstInitial) return personalized;
  return firstInitial.body.replace('{ここに生成した文章を挿入}', personalized);
}

function setNativeValue(el: HTMLTextAreaElement, value: string) {
  const proto = Object.getPrototypeOf(el);
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
  setter?.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

function hashSeed(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

function onModalOpened(ctx: AdapterContext) {
  try {
    const card = findCardForActiveModal();
    if (!card) {
      log('対応カードが見つからない');
      return;
    }
    const profile = extractProfileFromCard(card);
    if (!profile.member_id) {
      log('member_id 抽出失敗');
      return;
    }

    const occupation = ctx.pickOccupation(profile);

    const [patternType, personalized] = matchPattern(
      profile,
      occupation.patterns,
      [],
      hashSeed(profile.member_id)
    );

    const body = buildScoutBody(occupation, personalized);

    const textarea = getComposeTextarea();
    if (!textarea) {
      log('textarea 未検出');
      return;
    }

    setNativeValue(textarea, body);
    log(`自動フィル完了: occ=${occupation.id}, pattern=${patternType}, body=${body.length}字`);

    const sendButton = getSendButton();
    if (sendButton) {
      sendButton.addEventListener(
        'click',
        () => {
          const tpl = occupation.templates[0];
          ctx.historyStore
            .add({
              memberId: profile.member_id,
              age: profile.age,
              qualifications: profile.qualifications,
              templateType: tpl?.type || '',
              patternType,
              sentAt: new Date().toISOString(),
              body,
            })
            .then(() => log(`history.add 完了 member=${profile.member_id}`))
            .catch((e) => log('history.add 失敗', e));
        },
        { once: true }
      );
    }
  } catch (e) {
    log('onModalOpened エラー', e);
  }
}

function observeModal(ctx: AdapterContext) {
  const modal = document.querySelector(MODAL_SELECTOR);
  if (!modal) return;
  const obs = new MutationObserver(() => {
    if (modal.classList.contains(MODAL_ACTIVE_CLASS)) {
      queueMicrotask(() => onModalOpened(ctx));
    }
  });
  obs.observe(modal, { attributes: true, attributeFilter: ['class'] });
  log('モーダル監視開始');
}

export const comedicalAdapter: PlatformAdapter = {
  platform: 'comedical',
  matchUrl,
  init(ctx: AdapterContext) {
    if (!matchUrl(location.href)) return;
    log(`init. company=${ctx.company.companyId}, occupations=${ctx.company.occupations.map((o) => o.id).join(',')}`);

    if (!isSearchPage()) return;

    if (document.querySelector(MODAL_SELECTOR)) {
      observeModal(ctx);
    } else {
      const bodyObs = new MutationObserver(() => {
        if (document.querySelector(MODAL_SELECTOR)) {
          bodyObs.disconnect();
          observeModal(ctx);
        }
      });
      bodyObs.observe(document.body, { childList: true, subtree: true });
      setTimeout(() => bodyObs.disconnect(), 10_000);
    }
  },
};
