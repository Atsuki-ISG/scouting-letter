/**
 * 設定取得の一元管理モジュール。
 * API → キャッシュ → フォールバック（constants.ts）の順で取得する。
 */
import { apiClient, CompanyConfig } from './api-client';
import { storage } from './storage';
import { FALLBACK_COMPANY_JOB_OFFERS, FALLBACK_VALIDATION_CONFIG, JobOffer } from './constants';
import { CompanyValidationConfig } from './types';

export const configProvider = {
  /**
   * 会社一覧を取得する。
   * API → キャッシュ → フォールバックの順。
   */
  async getCompanyList(): Promise<string[]> {
    // 1. APIから取得を試みる
    try {
      const companies = await apiClient.getCompanies();
      // キャッシュに保存
      const cache = await storage.getConfigCache();
      await storage.setConfigCache({
        timestamp: Date.now(),
        companies,
        configs: cache?.configs || {},
      });
      return companies;
    } catch {
      // API失敗
    }

    // 2. キャッシュから取得
    const cache = await storage.getConfigCache();
    if (cache && cache.companies.length > 0) {
      return cache.companies;
    }

    // 3. フォールバック
    return Object.keys(FALLBACK_COMPANY_JOB_OFFERS);
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
