/**
 * WelMe sidepanel app. 極小UI。履歴表示・CSV出力・使い方ガイド。
 *
 * 「送信する」操作はここには無い。送信は /talks/ ページ上で
 * オペレータが WelMe の送信ボタンを押す（content script は自動フィル
 * するだけで、送信はユーザー操作のまま）。その方が誤送信事故が
 * 起きない。
 */

import { BUILD_CONFIG } from '../shared/build-config';
import { BUNDLED_COMPANY_CONFIG } from '../shared/bundled-company-config';
import {
  createHistoryStore,
  type HistoryEntry,
  type StorageLike,
} from '../shared/history-store';

declare const chrome: any;

// Storage — chrome.storage.local。dev 時（chrome 未定義）は localStorage フォールバック
function makeStorage(): StorageLike {
  if (typeof chrome !== 'undefined' && chrome?.storage?.local) {
    return {
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
    };
  }
  // Fallback: 開発中のブラウザ preview 等
  return {
    async get(keys) {
      const arr = Array.isArray(keys) ? keys : [keys];
      const out: Record<string, unknown> = {};
      for (const k of arr) {
        const raw = localStorage.getItem(k);
        if (raw !== null) out[k] = JSON.parse(raw);
      }
      return out;
    },
    async set(items) {
      for (const [k, v] of Object.entries(items)) {
        localStorage.setItem(k, JSON.stringify(v));
      }
    },
    async remove(keys) {
      const arr = Array.isArray(keys) ? keys : [keys];
      for (const k of arr) localStorage.removeItem(k);
    },
  };
}

const history = createHistoryStore(makeStorage());

// ---------------------------------------------------------------------------
// DOM bindings
// ---------------------------------------------------------------------------
function $(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`#${id} not found`);
  return el;
}

function setHeader() {
  // 「茅ヶ崎徳洲会病院 Scout (WelMe)」を分解
  const company = BUNDLED_COMPANY_CONFIG.displayName || 'Scout';
  $('hdr-title').textContent = company;
  $('hdr-sub').textContent = `WelMe · ${BUILD_CONFIG.companyId}`;
  // logo badge: 会社名の先頭1文字（漢字優先）
  const badge = $('hdr-badge');
  const firstKanji = company.match(/[\u4e00-\u9fff]/);
  badge.textContent = firstKanji ? firstKanji[0] : company.slice(0, 1);
  // footer
  $('ftr-build').textContent = BUILD_CONFIG.builtAt
    ? `build: ${BUILD_CONFIG.builtAt.slice(0, 16).replace('T', ' ')}`
    : 'build: dev';
}

function formatRelative(isoStr: string): string {
  const then = new Date(isoStr).getTime();
  const now = Date.now();
  const diff = Math.max(0, now - then);
  const min = Math.floor(diff / 60_000);
  if (min < 1) return 'たった今';
  if (min < 60) return `${min}分前`;
  const hour = Math.floor(min / 60);
  if (hour < 24) return `${hour}時間前`;
  const day = Math.floor(hour / 24);
  if (day < 7) return `${day}日前`;
  const d = new Date(isoStr);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function formatTime(isoStr: string): string {
  const d = new Date(isoStr);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

async function renderStatus() {
  $('today-count').textContent = String(await history.countToday());
  const last = await history.lastSentAt();
  $('last-sent').textContent = last ? formatRelative(last) : '—';
}

async function renderHistory() {
  const list = (await history.list()).slice(0, 30);
  const ul = $('history-list');
  const empty = $('history-empty');
  if (list.length === 0) {
    ul.innerHTML = '';
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  ul.innerHTML = list
    .map(
      (e) => `
      <li>
        <div class="mid">#${escapeHtml(e.memberId)}</div>
        <div class="body">
          <div class="body__top">${escapeHtml(e.age || '')} ${escapeHtml(e.qualifications || '')}</div>
          <div class="body__sub">型${escapeHtml(e.patternType || '-')} · ${escapeHtml(e.templateType || '-')}</div>
        </div>
        <div class="at">${formatTime(e.sentAt)}</div>
      </li>`
    )
    .join('');
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c] as string));
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------
async function onCsvExport() {
  const csv = await history.toCsv();
  const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const date = new Date().toISOString().slice(0, 10);
  a.href = url;
  a.download = `${BUILD_CONFIG.companyId}-welme-history-${date}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

async function onClear() {
  if (!confirm('送信履歴を全削除します。よろしいですか？')) return;
  await history.clear();
  await renderAll();
}

async function renderAll() {
  await Promise.all([renderStatus(), renderHistory()]);
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
async function main() {
  setHeader();
  $('btn-csv').addEventListener('click', onCsvExport);
  $('btn-clear').addEventListener('click', onClear);
  await renderAll();

  // chrome.storage 変更を監視して自動リフレッシュ
  if (typeof chrome !== 'undefined' && chrome?.storage?.onChanged) {
    chrome.storage.onChanged.addListener((changes: any, area: string) => {
      if (area === 'local' && changes.scout_history_v1) {
        renderAll();
      }
    });
  }
}

main();
