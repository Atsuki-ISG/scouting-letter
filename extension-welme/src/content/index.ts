/**
 * WelMe (kaigojob.com) content script エントリ。
 *
 * ページ別挙動:
 *   /scouts/newcomers → 候補者一覧ページ。ログのみ
 *   /talks/{uuid}     → プロフィール抽出→型はめ→textarea 自動フィル
 *                        送信時に history.add
 *
 * サーバ呼び出し一切なし。テンプレ・パターンは BUNDLED_COMPANY_CONFIG
 * から取得。履歴は chrome.storage.local。
 */

import {
  matchUrl,
  extractProfile,
  getComposeTextarea,
  getSendButton,
  getCandidateList,
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

function isListPage(): boolean {
  return /\/scouts\/newcomers(\?|$)/.test(location.pathname + location.search);
}

function isTalkPage(): boolean {
  return /\/talks\/[0-9a-f-]+/.test(location.pathname);
}

/**
 * 本文組み立て。1番目の初回テンプレートに型はめ結果を差し込む。
 */
function buildScoutBody(personalized: string): string {
  const templates = BUNDLED_COMPANY_CONFIG.templates;
  const firstInitial = templates.find((t) => t.type.endsWith('_初回')) || templates[0];
  if (!firstInitial) return personalized;
  return firstInitial.body.replace('{ここに生成した文章を挿入}', personalized);
}

async function autoFillTalkPage() {
  try {
    const profile = await extractProfile();
    if (!profile.member_id) {
      log('プロフィール抽出失敗。DOM構造が変わった可能性');
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
      log('textarea 未検出。DOM 構造変更を確認');
      return;
    }

    if (textarea.value.trim()) {
      log('textarea に既存入力あり、上書きせずスキップ');
      return;
    }

    setNativeValue(textarea, body);
    log(`自動フィル完了: pattern=${patternType}, body=${body.length}字`);

    watchForSend(profile, patternType, body);
  } catch (e) {
    log('autoFillTalkPage エラー', e);
  }
}

function watchForSend(
  profile: { member_id: string; age: string; qualifications: string },
  patternType: string,
  body: string
) {
  const sendButton = getSendButton();
  if (!sendButton) return;

  sendButton.addEventListener(
    'click',
    () => {
      if (sendButton.disabled || sendButton.classList.contains('is-disabled')) {
        log('送信ボタン無効のため記録スキップ');
        return;
      }
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

/** React 等が管理する textarea には native setter 経由で値を入れる必要がある。 */
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
// ページ判定 & 初期化
// ---------------------------------------------------------------------------
function init() {
  if (!matchUrl(location.href)) return;
  log(`init. company=${BUILD_CONFIG.companyId}`);

  if (isTalkPage()) {
    waitForDl().then(() => autoFillTalkPage());
  } else if (isListPage()) {
    log(`候補者一覧ページ (候補者 ${getCandidateList().length} 件)`);
  }
}

function waitForDl(timeoutMs = 10_000): Promise<void> {
  return new Promise((resolve) => {
    if (document.querySelector('dl.c-definition__list')) {
      resolve();
      return;
    }
    const obs = new MutationObserver(() => {
      if (document.querySelector('dl.c-definition__list')) {
        obs.disconnect();
        resolve();
      }
    });
    obs.observe(document.body, { childList: true, subtree: true });
    setTimeout(() => {
      obs.disconnect();
      resolve();
    }, timeoutMs);
  });
}

// SPA 内遷移対応
let lastHref = location.href;
new MutationObserver(() => {
  if (location.href !== lastHref) {
    lastHref = location.href;
    init();
  }
}).observe(document.body, { childList: true, subtree: true });

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
