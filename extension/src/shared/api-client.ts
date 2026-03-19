import { storage } from './storage';
import type { CandidateProfile } from './types';

export interface GenerateOptions {
  is_resend?: boolean;
  force_seishain?: boolean;
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

export interface CompanyConfig {
  templates: Record<string, { type: string; job_category: string; body: string }>;
  job_offers: Array<{ id: string; name: string; label: string; job_category: string; employment_type: string }>;
  validation_config: {
    age_range?: { min: number; max: number };
    qualification_rules?: Record<string, unknown>;
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
        options: { is_resend: options?.is_resend, force_seishain: options?.force_seishain },
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
    return data.companies;
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
