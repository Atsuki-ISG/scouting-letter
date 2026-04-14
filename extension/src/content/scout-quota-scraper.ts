/**
 * ジョブメドレーの任意のページから「今月のスカウト残数 X 通」を抽出して
 * サーバの送信実績シートに POST する。
 *
 * 拡張側で送信した数だけでなく、手動送信を含む実残数を取れるのが利点。
 * 会社判定は detectCompanyFromPage → storage.getCompany の順でフォールバック。
 */
import { apiClient } from '../shared/api-client';
import { storage } from '../shared/storage';
import { detectCompanyFromPage } from './company-detector';

// 全角数字・カンマ・空白に寛容なマッチ
const REMAINING_RE = /今月のスカウト残数[\s\u00a0]*([0-9,]+)[\s\u00a0]*通/;

let lastReported = -1;
let inflight = false;

/** ページのテキストから残数を抽出。見つからなければ null */
function findRemaining(): number | null {
  // ヘッダー付近の要素を優先
  const candidates = document.querySelectorAll(
    'header, .c-header, .c-page-header, .c-search-result__header, .c-page__main, [class*="scout"], [class*="remain"], [class*="header"]'
  );
  for (const el of candidates) {
    const text = (el as HTMLElement).innerText || (el as HTMLElement).textContent || '';
    const m = text.match(REMAINING_RE);
    if (m) return parseInt(m[1].replace(/,/g, ''), 10);
  }
  // フォールバック: body 全体
  const bodyText = document.body?.innerText || document.body?.textContent || '';
  const m = bodyText.match(REMAINING_RE);
  return m ? parseInt(m[1].replace(/,/g, ''), 10) : null;
}

async function resolveCompanyId(): Promise<string | null> {
  // 1) ページDOMから自動判定
  try {
    const detected = await detectCompanyFromPage();
    if (detected) return detected;
  } catch (err) {
    console.warn('[scout-quota] detectCompanyFromPage failed', err);
  }
  // 2) 拡張で選択中の会社を使う（サイドパネルで選ばれている会社）
  try {
    const stored = await storage.getCompany();
    if (stored) return stored;
  } catch (err) {
    console.warn('[scout-quota] storage.getCompany failed', err);
  }
  return null;
}

/** 残数をスクレイプして API に送る。重複送信は抑制 */
async function reportOnce(): Promise<void> {
  if (inflight) return;

  const remaining = findRemaining();
  if (remaining == null || remaining < 0) return;
  if (remaining === lastReported) return;

  const companyId = await resolveCompanyId();
  if (!companyId) {
    console.log('[scout-quota] company not detected and storage empty, skipping');
    return;
  }

  inflight = true;
  try {
    await apiClient.postScoutQuotaSnapshot(companyId, remaining);
    lastReported = remaining;
    console.log(`[scout-quota] reported ${companyId} remaining=${remaining}`);
    // Service Worker 側で「残数取得ワンクリック」のタブ close シグナルに使う
    try {
      await chrome.runtime.sendMessage({
        type: 'QUOTA_SNAPSHOT_POSTED',
        companyId,
        remaining,
      });
    } catch (err) {
      // サイドパネルが開いていない等で受け手が居なくても致命的ではない
      console.debug('[scout-quota] broadcast failed (no receiver?)', err);
    }
  } catch (err) {
    console.warn('[scout-quota] post failed', err);
  } finally {
    inflight = false;
  }
}

/** 残数表示が現れるまで MutationObserver で監視。見つけたら一度だけ送る */
function watchForRemaining(): void {
  // 即時試行
  void reportOnce();

  // DOM変化を監視（SPA遷移・非同期描画対応）
  const observer = new MutationObserver(() => {
    void reportOnce();
  });
  if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    // 5分後に observer を停止して負荷を抑える
    setTimeout(() => observer.disconnect(), 5 * 60 * 1000);
  }
}

/** 初期化: ページロード後・URL変化後・送信完了後にスナップショットを試みる */
export function initScoutQuotaScraper(): void {
  // 初回（DOM安定後）
  setTimeout(() => watchForRemaining(), 1500);

  // SPA遷移検出: pushState/replaceState/popstate を監視
  const onUrlChange = () => {
    lastReported = -1;
    setTimeout(() => watchForRemaining(), 800);
  };
  const origPush = history.pushState;
  history.pushState = function (...args) {
    const ret = origPush.apply(this, args);
    onUrlChange();
    return ret;
  };
  const origReplace = history.replaceState;
  history.replaceState = function (...args) {
    const ret = origReplace.apply(this, args);
    onUrlChange();
    return ret;
  };
  window.addEventListener('popstate', onUrlChange);
}

/** 連続送信などのフックから呼び出す: 残数を強制再取得 */
export function refreshScoutQuota(): void {
  lastReported = -1;
  void reportOnce();
}
