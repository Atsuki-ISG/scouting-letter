/**
 * コメディカルドットコム (co-medical.com) content script エントリ。
 *
 * フロー:
 *   1. /manage/freescout/search/{jobId}/ にアクセス
 *   2. 候補者カード (.scout_box) をスキャン、各 btnScout を監視
 *   3. ユーザーが「スカウト送信」を押す → モーダル (is-show) が開く
 *   4. モーダル内 #message_input にプロフィール由来の本文を自動フィル
 *   5. モーダル内「スカウト送信」クリックで history.add
 *
 * サーバ呼び出しなし。テンプレ・パターンは BUNDLED_COMPANY_CONFIG から。
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
} from './adapter';
import { matchPattern } from '../shared/pattern-matcher';
import { BUNDLED_COMPANY_CONFIG } from '../shared/bundled-company-config';
import { BUILD_CONFIG } from '../shared/build-config';
import { createHistoryStore } from '../shared/history-store';

const historyStore = createHistoryStore({
  async get(keys) {
    return new Promise((resolve) => chrome.storage.local.get(keys, resolve));
  },
  async set(items) {
    return new Promise<void>((resolve) =>
      chrome.storage.local.set(items, () => resolve())
    );
  },
  async remove(keys) {
    return new Promise<void>((resolve) =>
      chrome.storage.local.remove(keys, () => resolve())
    );
  },
});

function log(...args: unknown[]) {
  // eslint-disable-next-line no-console
  console.log(`[${BUILD_CONFIG.displayName}]`, ...args);
}

function buildScoutBody(personalized: string): string {
  const templates = BUNDLED_COMPANY_CONFIG.templates;
  const firstInitial = templates.find((t) => t.type.endsWith('_初回')) || templates[0];
  if (!firstInitial) return personalized;
  return firstInitial.body.replace('{ここに生成した文章を挿入}', personalized);
}

/**
 * モーダルが開いたときに呼ぶ。対応カードからプロフィール抽出→型はめ→
 * テンプレ本文の {ここに生成した文章を挿入} に埋め込み→textarea へ→
 * 送信ボタンに履歴記録リスナーを付ける。
 */
function onModalOpened() {
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

    const [patternType, personalized] = matchPattern(
      profile,
      BUNDLED_COMPANY_CONFIG.patterns,
      [],
      hashSeed(profile.member_id)
    );

    const body = buildScoutBody(personalized);

    const textarea = getComposeTextarea();
    if (!textarea) {
      log('textarea 未検出');
      return;
    }

    // コメディカル側のデフォルト文は上書きする（会社別テンプレ+型はめで置き換え）。
    setNativeValue(textarea, body);
    log(`自動フィル完了: pattern=${patternType}, body=${body.length}字`);

    const sendButton = getSendButton();
    if (sendButton) {
      sendButton.addEventListener(
        'click',
        () => {
          const tpl = BUNDLED_COMPANY_CONFIG.templates[0];
          historyStore
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

// ---------------------------------------------------------------------------
// モーダル出現監視
// ---------------------------------------------------------------------------
function observeModal() {
  const modal = document.querySelector(MODAL_SELECTOR);
  if (!modal) return;
  const obs = new MutationObserver(() => {
    if (modal.classList.contains(MODAL_ACTIVE_CLASS)) {
      queueMicrotask(onModalOpened);
    }
  });
  obs.observe(modal, { attributes: true, attributeFilter: ['class'] });
  log('モーダル監視開始');
}

function init() {
  if (!matchUrl(location.href)) return;
  log(`init. company=${BUILD_CONFIG.companyId}`);

  if (isSearchPage()) {
    if (document.querySelector(MODAL_SELECTOR)) {
      observeModal();
    } else {
      // モーダル要素がまだない場合、body を監視して出現を待つ
      const bodyObs = new MutationObserver(() => {
        if (document.querySelector(MODAL_SELECTOR)) {
          bodyObs.disconnect();
          observeModal();
        }
      });
      bodyObs.observe(document.body, { childList: true, subtree: true });
      setTimeout(() => bodyObs.disconnect(), 10_000);
    }
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
