/**
 * WelMe (kaigojob.com / welme.jp) プラットフォームアダプタ。
 *
 * フロー:
 *   /scouts/newcomers → 候補者一覧、ログのみ
 *   /talks/{uuid}     → プロフィール抽出→職種選択→型はめ→textarea 自動フィル
 *                        送信時に history.add
 */

import {
  matchUrl,
  extractProfile,
  getComposeTextarea,
  getSendButton,
  getCandidateList,
} from './welme-dom';
import { matchPattern } from '../../shared/pattern-matcher';
import type { AdapterContext, PlatformAdapter } from './types';
import type { CandidateProfile, Occupation } from '../../shared/types';

function log(...args: unknown[]) {
  // eslint-disable-next-line no-console
  console.log('[Scout/WelMe]', ...args);
}

function isListPage(): boolean {
  return /\/scouts\/newcomers(\?|$)/.test(location.pathname + location.search);
}

function isTalkPage(): boolean {
  return /\/talks\/[0-9a-f-]+/.test(location.pathname);
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

async function autoFillTalkPage(ctx: AdapterContext) {
  try {
    const profile = await extractProfile();
    if (!profile.member_id) {
      log('プロフィール抽出失敗。DOM構造が変わった可能性');
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
      log('textarea 未検出。DOM 構造変更を確認');
      return;
    }

    if (textarea.value.trim()) {
      log('textarea に既存入力あり、上書きせずスキップ');
      return;
    }

    setNativeValue(textarea, body);
    log(`自動フィル完了: occ=${occupation.id}, pattern=${patternType}, body=${body.length}字`);

    watchForSend(ctx, profile, occupation, patternType, body);
  } catch (e) {
    log('autoFillTalkPage エラー', e);
  }
}

function watchForSend(
  ctx: AdapterContext,
  profile: CandidateProfile,
  occupation: Occupation,
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

function routePage(ctx: AdapterContext) {
  if (isTalkPage()) {
    waitForDl().then(() => autoFillTalkPage(ctx));
  } else if (isListPage()) {
    log(`候補者一覧ページ (候補者 ${getCandidateList().length} 件)`);
  }
}

export const welmeAdapter: PlatformAdapter = {
  platform: 'welme',
  matchUrl,
  init(ctx: AdapterContext) {
    if (!matchUrl(location.href)) return;
    log(`init. company=${ctx.company.companyId}, occupations=${ctx.company.occupations.map((o) => o.id).join(',')}`);

    routePage(ctx);

    // SPA 内遷移対応
    let lastHref = location.href;
    new MutationObserver(() => {
      if (location.href !== lastHref) {
        lastHref = location.href;
        routePage(ctx);
      }
    }).observe(document.body, { childList: true, subtree: true });
  },
};
