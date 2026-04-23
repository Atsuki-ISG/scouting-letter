/**
 * content script エントリ（ルーター）。
 *
 * 現在の URL を見て welme / comedical のアダプタを選択し、
 * chrome.storage から選択された会社を読み、Company を渡して init。
 *
 * サーバ呼び出しなし。テンプレ・パターンは BUNDLED_SCOUT_CONFIG から。
 */

import { welmeAdapter } from './adapters/welme';
import { comedicalAdapter } from './adapters/comedical';
import type { PlatformAdapter } from './adapters/types';
import { BUNDLED_SCOUT_CONFIG } from '../shared/bundled-company-config';
import { pickOccupation, type Company, type Occupation, type CandidateProfile } from '../shared/types';
import { createHistoryStore } from '../shared/history-store';

const ADAPTERS: PlatformAdapter[] = [welmeAdapter, comedicalAdapter];
const STORAGE_SELECTED_COMPANY = 'scout_selected_company_id';

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

function pickAdapter(url: string): PlatformAdapter | null {
  return ADAPTERS.find((a) => a.matchUrl(url)) ?? null;
}

async function getSelectedCompanyId(): Promise<string | null> {
  const raw = await new Promise<Record<string, unknown>>((resolve) =>
    chrome.storage.local.get(STORAGE_SELECTED_COMPANY, resolve)
  );
  const v = raw[STORAGE_SELECTED_COMPANY];
  return typeof v === 'string' ? v : null;
}

function pickCompanyForPlatform(
  platform: 'welme' | 'comedical',
  selectedId: string | null
): Company | null {
  const candidates = BUNDLED_SCOUT_CONFIG.companies.filter((c) => c.platform === platform);
  if (candidates.length === 0) return null;
  if (selectedId) {
    const exact = candidates.find((c) => c.companyId === selectedId);
    if (exact) return exact;
  }
  return candidates[0];
}

async function init() {
  const adapter = pickAdapter(location.href);
  if (!adapter) return;

  const selectedId = await getSelectedCompanyId();
  const company = pickCompanyForPlatform(adapter.platform, selectedId);
  if (!company) {
    // eslint-disable-next-line no-console
    console.warn(`[Scout] ${adapter.platform} に対応する会社設定が無い（BUNDLED_SCOUT_CONFIG）`);
    return;
  }

  const pickOccupationForProfile = (profile: CandidateProfile): Occupation => {
    const occ = pickOccupation(company, profile.qualifications);
    if (!occ) {
      throw new Error(`会社 ${company.companyId} に occupation が登録されていません`);
    }
    return occ;
  };

  adapter.init({
    company,
    historyStore,
    pickOccupation: pickOccupationForProfile,
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
