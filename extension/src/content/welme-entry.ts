/**
 * WelMe (kaigojob.com) 向けの content script エントリ。
 *
 * ジョブメドレー版 (index.ts) と完全に別。サーバを一切呼ばず、
 * ビルド時に同梱された pattern/template から本文を組み立てて
 * textarea に入れるだけの最小実装。
 *
 * ページ別挙動:
 *   /scouts/newcomers → 候補者一覧の表示（sidepanel に件数通知）
 *   /talks/{uuid}     → プロフィールを抽出→型はめ→textarea 自動フィル
 *                        送信完了（URL遷移等）を検出して history.add
 */

import { welmeAdapter } from './adapters/welme';
import { matchPattern } from '../shared/pattern-matcher';
import { BUNDLED_COMPANY_CONFIG } from '../shared/bundled-company-config';
import { BUILD_CONFIG } from '../shared/build-config';
import { createHistoryStore } from '../shared/history-store';

declare const chrome: any;

const historyStore = createHistoryStore({
  async get(keys) {
    return new Promise((resolve) => chrome.storage.local.get(keys, resolve));
  },
  async set(items) {
    return new Promise<void>((resolve) => chrome.storage.local.set(items, () => resolve()));
  },
  async remove(keys) {
    return new Promise<void>((resolve) => chrome.storage.local.remove(keys, () => resolve()));
  },
});

function log(...args: unknown[]) {
  console.log(`[${BUILD_CONFIG.displayName}]`, ...args);
}

function isListPage(): boolean {
  return /\/scouts\/newcomers(\?|$)/.test(location.pathname + location.search);
}

function isTalkPage(): boolean {
  return /\/talks\/[0-9a-f-]+/.test(location.pathname);
}

/**
 * 本文を「1番目の初回テンプレート本文に、型はめ結果を埋めて」作成する。
 * 現状は "正社員_初回" テンプレを想定。テンプレが無ければ型はめ結果だけ返す。
 */
function buildScoutBody(personalized: string): string {
  const templates = BUNDLED_COMPANY_CONFIG.templates;
  const firstInitial = templates.find((t) => t.type.endsWith('_初回')) || templates[0];
  if (!firstInitial) return personalized;
  return firstInitial.body.replace('{ここに生成した文章を挿入}', personalized);
}

async function autoFillTalkPage() {
  try {
    const profile = await welmeAdapter.extractProfile();
    if (!profile.member_id) {
      log('プロフィール抽出失敗。DOM構造が変わった可能性');
      return;
    }

    const [patternType, personalized] = matchPattern(
      profile,
      BUNDLED_COMPANY_CONFIG.patterns,
      [], // qualification_modifiers は MVP 対象外
      // member_id を feature_rotation の種に使うと、同じ候補者は毎回同じ特色
      hashSeed(profile.member_id)
    );

    const body = buildScoutBody(personalized);

    const textarea = welmeAdapter.getComposeTextarea();
    if (!textarea) {
      log('textarea 未検出。DOM 構造変更を確認');
      return;
    }

    // 既にオペが手入力していたら上書きしない
    if (textarea.value.trim()) {
      log('textarea に既存入力あり、上書きせずスキップ');
      return;
    }

    setNativeValue(textarea, body);
    log(`自動フィル完了: pattern=${patternType}, body=${body.length}字`);

    // 送信監視（送信ボタンクリック時に history.add）
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
  // 送信ボタンを取得。is-disabled が外れた状態でクリックされたら記録
  const sendButton = Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(
    (b) => b.textContent?.trim() === '送信'
  );
  if (!sendButton) return;

  sendButton.addEventListener(
    'click',
    () => {
      // disabled なら送信されない（クリック即returnで記録しない）
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

/**
 * React 等が管理する input/textarea に value を設定するときは
 * ネイティブ setter を使わないと反映されない。
 */
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
// ページ判定＆初期化
// ---------------------------------------------------------------------------
function init() {
  if (!welmeAdapter.matchUrl(location.href)) return;

  log(`init. company=${BUILD_CONFIG.companyId}, medium=${BUILD_CONFIG.medium}`);

  if (isTalkPage()) {
    // SPA なので dl が遅延レンダされる可能性がある。observer で dl 出現を待つ
    waitForDl().then(() => autoFillTalkPage());
  } else if (isListPage()) {
    log(`候補者一覧ページ (候補者 ${welmeAdapter.getCandidateList().length} 件)`);
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

// SPA 内遷移にも対応（URL 変化時に init 再実行）
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
