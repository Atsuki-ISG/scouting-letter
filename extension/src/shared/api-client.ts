import { storage } from './storage';
import type {
  CandidateProfile,
  ConversationThread,
  FixRecord,
  PersonalizationStats,
} from './types';

export interface GenerateOptions {
  is_resend?: boolean;
  force_employment?: string;  // "パート" | "正社員" | undefined (auto)
  job_category_filter?: string;  // "nurse" | "rehab_pt" | "rehab_st" | "rehab_ot" | "medical_office" | undefined (all)
}

export interface GenerateResponse {
  member_id: string;
  template_type: string;
  generation_path: 'ai' | 'pattern' | 'filtered_out';
  pattern_type?: string;
  personalized_text: string;
  full_scout_text: string;
  job_offer_id?: string;
  job_category?: string;
  filter_reason?: string;
  validation_warnings: string[];
  is_favorite?: boolean;
}

export interface BatchGenerateResponse {
  results: GenerateResponse[];
  summary: {
    total: number;
    ai_generated: number;
    pattern_matched: number;
    filtered_out: number;
  };
}

/** Developer-mode: L2/L3 structured personalized generation */
export interface PersonalizedGenerateOptions {
  level: 'L2' | 'L3';
  is_resend?: boolean;
  force_employment?: string;
  job_category_filter?: string;
  template_row_index?: number;
}

export interface PersonalizedGenerateResponse {
  member_id: string;
  template_type: string;
  generation_path: 'ai_structured' | 'filtered_out';
  personalized_text: string;
  full_scout_text: string;
  block_contents: Record<string, string>;
  personalization_stats: PersonalizationStats;
  job_category?: string;
  is_favorite: boolean;
  validation_warnings: string[];
  filter_reason?: string;
}

export interface CompanyConfig {
  templates: Record<string, { type: string; job_category: string; body: string }>;
  job_offers: Array<{ id: string; name: string; label: string; job_category: string; employment_type: string }>;
  job_categories?: Array<{ id: string; display_name: string }>;
  employment_types?: Array<{ id: string; display_name: string }>;
  company_display_name?: string;
  validation_config: {
    age_range?: { min: number; max: number };
    qualification_rules?: Record<string, unknown>;
    category_exclusions?: Record<string, string[]>;
    category_config?: Record<string, { display_name: string; search_term: string; keywords: string[] }>;
  };
}

/** Default timeout for API calls (ms) */
const API_TIMEOUT_MS = 120_000; // 2 minutes for batch generation
const HEALTH_TIMEOUT_MS = 10_000;

function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, { ...init, signal: controller.signal }).finally(() => clearTimeout(timer));
}

function formatApiError(status: number, text: string): string {
  if (status === 429) return 'API枠超過（レート制限）。しばらく待ってから再試行してください';
  if (status === 401) return 'APIキーが無効です。設定を確認してください';
  if (status === 503) return 'サーバーが一時的に利用できません。しばらく待ってから再試行してください';
  return `APIエラー ${status}: ${text}`;
}

export const apiClient = {
  async getEndpoint(): Promise<string> {
    return await storage.getAPIEndpoint();
  },

  async getHeaders(): Promise<Record<string, string>> {
    const apiKey = await storage.getAPIKey();
    return {
      'Content-Type': 'application/json',
      'X-API-Key': apiKey,
    };
  },

  async generate(
    companyId: string,
    profile: CandidateProfile,
    options?: GenerateOptions
  ): Promise<GenerateResponse> {
    const endpoint = await this.getEndpoint();
    const headers = await this.getHeaders();
    const res = await fetchWithTimeout(`${endpoint}/api/v1/generate`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ company_id: companyId, profile, options }),
    }, API_TIMEOUT_MS);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(formatApiError(res.status, text));
    }
    return res.json();
  },

  async generateBatch(
    companyId: string,
    profiles: CandidateProfile[],
    options?: GenerateOptions & { concurrency?: number }
  ): Promise<BatchGenerateResponse> {
    const endpoint = await this.getEndpoint();
    const headers = await this.getHeaders();
    const res = await fetchWithTimeout(`${endpoint}/api/v1/generate/batch`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        company_id: companyId,
        profiles,
        options: {
          is_resend: options?.is_resend,
          force_employment: options?.force_employment,
          job_category_filter: options?.job_category_filter,
        },
        concurrency: options?.concurrency ?? 10,
      }),
    }, API_TIMEOUT_MS);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(formatApiError(res.status, text));
    }
    return res.json();
  },

  async getCompanies(): Promise<string[]> {
    const data = await this.getCompaniesWithKeywords();
    return data.map(c => c.id);
  },

  async getCompaniesWithKeywords(): Promise<Array<{ id: string; detection_keywords: string[]; display_name?: string }>> {
    const endpoint = await this.getEndpoint();
    const headers = await this.getHeaders();
    const res = await fetchWithTimeout(`${endpoint}/api/v1/companies`, {
      method: 'GET',
      headers,
    }, HEALTH_TIMEOUT_MS);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(formatApiError(res.status, text));
    }
    const data = await res.json();
    // 後方互換: 旧形式(string[])も新形式(object[])も対応
    const companies = data.companies || [];
    if (companies.length > 0 && typeof companies[0] === 'string') {
      return companies.map((id: string) => ({ id, detection_keywords: [], display_name: id }));
    }
    return companies;
  },

  async getCompanyConfig(companyId: string): Promise<CompanyConfig> {
    const endpoint = await this.getEndpoint();
    const headers = await this.getHeaders();
    const res = await fetchWithTimeout(`${endpoint}/api/v1/companies/${companyId}/config`, {
      method: 'GET',
      headers,
    }, HEALTH_TIMEOUT_MS);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(formatApiError(res.status, text));
    }
    return res.json();
  },

  async postScoutQuotaSnapshot(companyId: string, remaining: number): Promise<void> {
    const endpoint = await this.getEndpoint();
    if (!endpoint) return;
    const headers = await this.getHeaders();
    try {
      await fetchWithTimeout(`${endpoint}/api/v1/admin/scout_quota_snapshot`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ company_id: companyId, remaining }),
      }, HEALTH_TIMEOUT_MS);
    } catch (err) {
      console.warn('[scout-quota] failed to post snapshot', err);
    }
  },

  async recordManualSend(
    company: string,
    payload: {
      member_id: string;
      sent_at: string;
      qualifications?: string;
      age?: string;
      area?: string;
      desired_employment_type?: string;
    },
  ): Promise<{ status: string; recorded: boolean; reason?: string }> {
    const endpoint = await this.getEndpoint();
    const headers = await this.getHeaders();
    const res = await fetchWithTimeout(`${endpoint}/api/v1/admin/record_manual_send`, {
      method: 'POST',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ company_id: company, ...payload }),
    }, HEALTH_TIMEOUT_MS);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(formatApiError(res.status, text));
    }
    return res.json();
  },

  async syncFixes(
    company: string,
    fixes: FixRecord[],
  ): Promise<{ status: string; appended: number; skipped_duplicate: number }> {
    const endpoint = await this.getEndpoint();
    const headers = await this.getHeaders();
    const res = await fetchWithTimeout(`${endpoint}/api/v1/admin/sync_fixes`, {
      method: 'POST',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ company, fixes }),
    }, HEALTH_TIMEOUT_MS);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(formatApiError(res.status, text));
    }
    return res.json();
  },

  async syncReplies(company: string, replies: Array<{ member_id: string; replied_at: string; category: string }>): Promise<{ status: string; updated: number }> {
    const endpoint = await this.getEndpoint();
    const headers = await this.getHeaders();
    const res = await fetchWithTimeout(`${endpoint}/api/v1/admin/sync_replies`, {
      method: 'POST',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ company, replies }),
    }, API_TIMEOUT_MS);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(formatApiError(res.status, text));
    }
    return res.json();
  },

  async generatePersonalized(
    companyId: string,
    profile: CandidateProfile,
    options: PersonalizedGenerateOptions,
  ): Promise<PersonalizedGenerateResponse> {
    const endpoint = await this.getEndpoint();
    const headers = await this.getHeaders();
    const res = await fetchWithTimeout(
      `${endpoint}/api/v1/generate/personalized`,
      {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          company_id: companyId,
          profile,
          options,
        }),
      },
      API_TIMEOUT_MS,
    );
    if (!res.ok) {
      const text = await res.text();
      throw new Error(formatApiError(res.status, text));
    }
    return res.json();
  },

  async postConversationLogs(
    company: string,
    threads: ConversationThread[],
    source: string = 'extension_manual',
  ): Promise<{ status: string; appended: number; updated: number }> {
    const endpoint = await this.getEndpoint();
    const headers = await this.getHeaders();
    const res = await fetchWithTimeout(
      `${endpoint}/api/v1/admin/conversation_logs`,
      {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ company, threads, source }),
      },
      HEALTH_TIMEOUT_MS,
    );
    if (!res.ok) {
      const text = await res.text();
      throw new Error(formatApiError(res.status, text));
    }
    return res.json();
  },

  async testConnection(): Promise<{ success: boolean; error?: string }> {
    try {
      const endpoint = await this.getEndpoint();
      if (!endpoint) {
        return { success: false, error: 'APIエンドポイントが設定されていません' };
      }
      const apiKey = await storage.getAPIKey();
      if (!apiKey) {
        return { success: false, error: 'パスワードが設定されていません' };
      }
      const headers = await this.getHeaders();
      const res = await fetchWithTimeout(`${endpoint}/health`, { headers }, HEALTH_TIMEOUT_MS);
      if (res.ok) return { success: true };
      return { success: false, error: `HTTP ${res.status}` };
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        return { success: false, error: '接続タイムアウト。エンドポイントを確認してください' };
      }
      return { success: false, error: err instanceof Error ? err.message : String(err) };
    }
  },
};
