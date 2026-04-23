/**
 * Scout Assistant sidepanel. プラットフォーム（WelMe/コメディカル）を
 * 現在タブのURLから検出し、対応する会社リストをドロップダウンに出す。
 * 履歴表示・CSV出力・会社切替が主機能。
 */

import { BUILD_CONFIG } from '../shared/build-config';
import { BUNDLED_SCOUT_CONFIG } from '../shared/bundled-company-config';
import {
  createHistoryStore,
  type StorageLike,
} from '../shared/history-store';
import type { Company, Platform } from '../shared/types';

declare const chrome: any;

const STORAGE_SELECTED_COMPANY = 'scout_selected_company_id';

const PLATFORM_MATCHERS: { platform: Platform; test: (url: string) => boolean; label: string }[] = [
  {
    platform: 'welme',
    test: (u) => /^https?:\/\/([a-z0-9-]+\.)?(kaigojob\.com|welme\.jp)(\/|$)/i.test(u),
    label: 'WelMe',
  },
  {
    platform: 'comedical',
    test: (u) => /^https?:\/\/([a-z0-9-]+\.)?co-medical\.com(\/|$)/i.test(u),
    label: 'コメディカル',
  },
];

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

const storage = makeStorage();
const history = createHistoryStore(storage);

function $(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`#${id} not found`);
  return el;
}

async function detectPlatformFromActiveTab(): Promise<Platform | null> {
  if (typeof chrome === 'undefined' || !chrome?.tabs) return null;
  try {
    const tabs: any[] = await new Promise((resolve) =>
      chrome.tabs.query({ active: true, currentWindow: true }, resolve)
    );
    const url = tabs[0]?.url || '';
    for (const m of PLATFORM_MATCHERS) if (m.test(url)) return m.platform;
    return null;
  } catch {
    return null;
  }
}

function platformLabel(p: Platform | null): string {
  if (!p) return '未対応サイト';
  return PLATFORM_MATCHERS.find((m) => m.platform === p)?.label || p;
}

async function getSelectedCompanyId(): Promise<string | null> {
  const raw = await storage.get(STORAGE_SELECTED_COMPANY);
  const v = raw[STORAGE_SELECTED_COMPANY];
  return typeof v === 'string' ? v : null;
}

async function setSelectedCompanyId(id: string): Promise<void> {
  await storage.set({ [STORAGE_SELECTED_COMPANY]: id });
}

function companiesForPlatform(platform: Platform | null): Company[] {
  if (!platform) return [];
  return BUNDLED_SCOUT_CONFIG.companies.filter((c) => c.platform === platform);
}

function renderCompanyDropdown(companies: Company[], selectedId: string | null) {
  const sel = $('sel-company') as HTMLSelectElement;
  sel.innerHTML = '';
  if (companies.length === 0) {
    const opt = document.createElement('option');
    opt.textContent = '— 会社なし —';
    opt.disabled = true;
    sel.appendChild(opt);
    sel.disabled = true;
    return;
  }
  sel.disabled = false;
  for (const c of companies) {
    const opt = document.createElement('option');
    opt.value = c.companyId;
    opt.textContent = c.displayName;
    if (c.companyId === selectedId) opt.selected = true;
    sel.appendChild(opt);
  }
  if (!companies.find((c) => c.companyId === selectedId)) {
    sel.selectedIndex = 0;
  }
}

function renderOccupationSummary(company: Company | null) {
  const el = $('occupation-summary');
  if (!company || company.occupations.length === 0) {
    el.textContent = '—';
    return;
  }
  if (company.occupations.length === 1) {
    el.textContent = company.occupations[0].displayName;
    return;
  }
  el.textContent = company.occupations
    .map((o) => `${o.displayName}(${o.matchQualifications.join('/') || '—'})`)
    .join(' / ');
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

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c] as string));
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

async function onCsvExport() {
  const csv = await history.toCsv();
  const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const date = new Date().toISOString().slice(0, 10);
  const selectedId = (await getSelectedCompanyId()) || 'scout';
  a.href = url;
  a.download = `${selectedId}-history-${date}.csv`;
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

async function refreshPlatformAndCompany() {
  const platform = await detectPlatformFromActiveTab();
  $('hdr-platform').textContent = platformLabel(platform);
  $('hdr-platform').dataset.state = platform ? 'active' : 'idle';

  const companies = companiesForPlatform(platform);
  const selectedId = await getSelectedCompanyId();
  renderCompanyDropdown(companies, selectedId);

  const current = companies.find((c) => c.companyId === selectedId) || companies[0] || null;
  if (current && current.companyId !== selectedId) {
    await setSelectedCompanyId(current.companyId);
  }
  $('hdr-title').textContent = current?.displayName || 'Scout Assistant';
  $('hdr-sub').textContent = current ? `${platformLabel(platform)} · ${current.companyId}` : '対応サイトを開いてください';
  $('hdr-badge').textContent = (current?.displayName || 'S').match(/[\u4e00-\u9fff]/)?.[0] || 'S';

  renderOccupationSummary(current);
}

async function main() {
  $('ftr-build').textContent = BUILD_CONFIG.builtAt
    ? `build: ${BUILD_CONFIG.builtAt.slice(0, 16).replace('T', ' ')}`
    : 'build: dev';
  $('btn-csv').addEventListener('click', onCsvExport);
  $('btn-clear').addEventListener('click', onClear);

  const sel = $('sel-company') as HTMLSelectElement;
  sel.addEventListener('change', async () => {
    await setSelectedCompanyId(sel.value);
    await refreshPlatformAndCompany();
  });

  await refreshPlatformAndCompany();
  await renderAll();

  // タブ切り替えを監視して自動リフレッシュ
  if (typeof chrome !== 'undefined' && chrome?.tabs?.onActivated) {
    chrome.tabs.onActivated.addListener(() => refreshPlatformAndCompany());
  }
  if (typeof chrome !== 'undefined' && chrome?.tabs?.onUpdated) {
    chrome.tabs.onUpdated.addListener((_tabId: any, info: any) => {
      if (info.url || info.status === 'complete') refreshPlatformAndCompany();
    });
  }
  if (typeof chrome !== 'undefined' && chrome?.storage?.onChanged) {
    chrome.storage.onChanged.addListener((changes: any, area: string) => {
      if (area === 'local' && changes.scout_history_v1) renderAll();
    });
  }
}

main();
