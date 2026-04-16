/**
 * 設定取得の一元管理モジュール。
 * API → キャッシュ → フォールバック（constants.ts）の順で取得する。
 */
import { apiClient, CompanyConfig } from './api-client';
import { storage } from './storage';
import { FALLBACK_COMPANY_JOB_OFFERS, FALLBACK_VALIDATION_CONFIG, STORAGE_KEYS, COMPANY_FACILITY_KEYWORDS, JobOffer } from './constants';
import { CompanyValidationConfig } from './types';

export interface CompanyListEntry {
  id: string;
  display_name: string;
}

/** 会社リストキャッシュの鮮度しきい値（ミリ秒）。
 *  これ未満なら API を叩かずキャッシュを返す（「フレッシュ」扱い）。
 *  storage 側の TTL(1時間) より短い: こちらは「無通信で返していい期間」、
 *  storage の TTL は「キャッシュを破棄する期間」。 */
const COMPANY_LIST_FRESH_MS = 5 * 60 * 1000;

export const configProvider = {
  /**
   * 会社一覧をIDで取得する（後方互換）。
   */
  async getCompanyList(): Promise<string[]> {
    const entries = await this.getCompanyListWithDisplayNames();
    return entries.map(e => e.id);
  },

  /**
   * 会社一覧を表示名つきで取得する。
   * 鮮度内のキャッシュがあれば即返す。古い/無い/forceRefresh なら API を叩く。
   *
   * @param forceRefresh true なら TTL を無視して必ず API から再取得
   */
  async getCompanyListWithDisplayNames(forceRefresh = false): Promise<CompanyListEntry[]> {
    // 0. 鮮度内のキャッシュがあればそのまま返す（API を叩かない）
    if (!forceRefresh) {
      const cache = await storage.getConfigCache();
      if (cache && Date.now() - cache.timestamp < COMPANY_LIST_FRESH_MS) {
        const entries = this.entriesFromCache(cache.companies);
        // キャッシュに display_name が入っていれば採用、無ければ API にフォールスルー
        if (entries.some(e => e.display_name !== e.id)) {
          return entries;
        }
      }
    }

    // 1. APIから取得
    try {
      const companiesWithKw = await apiClient.getCompaniesWithKeywords();
      const entries: CompanyListEntry[] = companiesWithKw.map(c => ({
        id: c.id,
        display_name: c.display_name || c.id,
      }));
      // キャッシュに display_name ごと保存
      const cache = await storage.getConfigCache();
      await storage.setConfigCache({
        timestamp: Date.now(),
        companies: entries.map(e => ({ id: e.id, display_name: e.display_name })),
        configs: cache?.configs || {},
      });
      // 検出キーワードをstorageに保存（Content Scriptが使用）
      const kwMap: Record<string, string[]> = {};
      for (const c of companiesWithKw) {
        if (c.detection_keywords.length > 0) {
          kwMap[c.id] = c.detection_keywords;
        }
      }
      await chrome.storage.local.set({ [STORAGE_KEYS.DETECTION_KEYWORDS]: kwMap });
      return entries;
    } catch {
      // API失敗
    }

    // 2. 古くなったキャッシュでも使う（API失敗時）
    const cache = await storage.getConfigCache();
    if (cache && cache.companies.length > 0) {
      return this.entriesFromCache(cache.companies);
    }

    // 3. フォールバック
    return Object.keys(FALLBACK_COMPANY_JOB_OFFERS).map(id => ({ id, display_name: id }));
  },

  /** ConfigCache.companies を CompanyListEntry[] に正規化する（旧形式=string[] 互換） */
  entriesFromCache(companies: unknown[]): CompanyListEntry[] {
    return companies.map(c => {
      if (typeof c === 'string') return { id: c, display_name: c };
      const obj = c as { id?: string; display_name?: string };
      const id = obj.id ?? String(c);
      return { id, display_name: obj.display_name || id };
    });
  },

  /**
   * 会社設定を取得する。
   */
  async getCompanyConfig(companyId: string): Promise<CompanyConfig | null> {
    // 1. APIから取得
    try {
      const config = await apiClient.getCompanyConfig(companyId);
      // キャッシュに保存
      const cache = await storage.getConfigCache();
      const configs = cache?.configs || {};
      configs[companyId] = config;
      await storage.setConfigCache({
        timestamp: Date.now(),
        companies: cache?.companies || [],
        configs,
      });
      return config;
    } catch {
      // API失敗
    }

    // 2. キャッシュから取得
    const cache = await storage.getConfigCache();
    if (cache?.configs[companyId]) {
      return cache.configs[companyId];
    }

    return null;
  },

  /**
   * 求人リストを取得する。
   * API/キャッシュから取れなければフォールバック定数を使用。
   */
  async getJobOffers(companyId: string): Promise<JobOffer[]> {
    const config = await this.getCompanyConfig(companyId);
    if (config && config.job_offers.length > 0) {
      return config.job_offers.map((jo) => ({
        id: jo.id,
        name: jo.name,
        label: jo.label,
      }));
    }
    return FALLBACK_COMPANY_JOB_OFFERS[companyId] || [];
  },

  /**
   * バリデーション設定を取得する。
   * API/キャッシュから取れなければフォールバック定数を使用。
   */
  async getValidationConfig(companyId: string): Promise<CompanyValidationConfig | null> {
    const config = await this.getCompanyConfig(companyId);
    if (config?.validation_config) {
      const vc = config.validation_config;
      const result: CompanyValidationConfig = {};
      if (vc.age_range) {
        result.ageRange = { min: vc.age_range.min, max: vc.age_range.max };
      }
      if (vc.qualification_rules) {
        // APIのqualification_rulesは { "求人ID": { required: [...], excluded: [...] } } 形式
        const rules: CompanyValidationConfig['qualificationRules'] = [];
        for (const [jobOfferId, rule] of Object.entries(vc.qualification_rules as Record<string, { required?: string[]; excluded?: string[] }>)) {
          rules.push({
            jobOfferId,
            required: rule.required || [],
            excluded: rule.excluded || [],
          });
        }
        if (rules.length > 0) {
          result.qualificationRules = rules;
        }
      }
      if (vc.category_exclusions) {
        result.categoryExclusions = vc.category_exclusions as Record<string, string[]>;
      }
      if (vc.category_config) {
        result.categoryConfig = vc.category_config as Record<string, { display_name: string; search_term: string; keywords: string[] }>;
      }
      return result;
    }
    return FALLBACK_VALIDATION_CONFIG[companyId] || null;
  },
};
