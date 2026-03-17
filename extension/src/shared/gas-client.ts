import { storage } from './storage';

export interface ScoutLogData {
  timestamp: string;
  member_id: string;
  company: string;
  job_offer_id: string;
  job_offer_label: string;
  template_type: string;
  personalized_text: string;
}

export const gasClient = {
  async logSentScout(data: ScoutLogData): Promise<void> {
    const enabled = await storage.isGASEnabled();
    if (!enabled) {
      console.log('[Scout Assistant] GAS disabled, skipping log');
      return;
    }

    const endpoint = await storage.getGASEndpoint();
    if (!endpoint) {
      console.log('[Scout Assistant] GAS endpoint not set, skipping log');
      return;
    }

    console.log('[Scout Assistant] Sending GAS log for', data.member_id);

    try {
      // GAS Web Appは302リダイレクトする。
      // redirect: 'manual' でもGASはdoPostを実行してからリダイレクトを返す。
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
        body: JSON.stringify({ action: 'logScout', data }),
        redirect: 'manual',
      });
      console.log('[Scout Assistant] GAS log sent: status=', res.status, 'type=', res.type);
    } catch (err) {
      console.warn('[Scout Assistant] GAS log failed:', err);
    }
  },

  async testConnection(): Promise<{ success: boolean; error?: string }> {
    const endpoint = await storage.getGASEndpoint();
    if (!endpoint) {
      return { success: false, error: 'URLが設定されていません' };
    }

    try {
      const res = await fetch(`${endpoint}?action=ping`);
      if (res.ok) {
        return { success: true };
      }
      return { success: false, error: `HTTP ${res.status}` };
    } catch (err) {
      return { success: false, error: err instanceof Error ? err.message : String(err) };
    }
  },
};
