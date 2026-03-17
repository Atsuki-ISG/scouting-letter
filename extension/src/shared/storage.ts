import { CandidateItem, CandidateProfile, ConversationThread, FixRecord, ReplyRecord } from './types';
import { STORAGE_KEYS, DEFAULT_COMPANY, JobOffer } from './constants';

/** chrome.storage.local ラッパー */
export const storage = {
  async getCompany(): Promise<string> {
    const result = await chrome.storage.local.get(STORAGE_KEYS.COMPANY);
    return (result[STORAGE_KEYS.COMPANY] as string) || DEFAULT_COMPANY;
  },

  async setCompany(company: string): Promise<void> {
    await chrome.storage.local.set({ [STORAGE_KEYS.COMPANY]: company });
  },

  async getCandidates(): Promise<CandidateItem[]> {
    const result = await chrome.storage.local.get(STORAGE_KEYS.CANDIDATES);
    return (result[STORAGE_KEYS.CANDIDATES] as CandidateItem[] | undefined) || [];
  },

  async setCandidates(candidates: CandidateItem[]): Promise<void> {
    await chrome.storage.local.set({ [STORAGE_KEYS.CANDIDATES]: candidates });
  },

  async updateCandidateStatus(
    memberId: string,
    status: CandidateItem['status']
  ): Promise<void> {
    const candidates = await this.getCandidates();
    const index = candidates.findIndex((c) => c.member_id === memberId);
    if (index !== -1) {
      candidates[index].status = status;
      await this.setCandidates(candidates);
    }
  },

  async getExtractedProfiles(): Promise<CandidateProfile[]> {
    const result = await chrome.storage.local.get(STORAGE_KEYS.EXTRACTED_PROFILES);
    return (result[STORAGE_KEYS.EXTRACTED_PROFILES] as CandidateProfile[] | undefined) || [];
  },

  async setExtractedProfiles(profiles: CandidateProfile[]): Promise<void> {
    await chrome.storage.local.set({ [STORAGE_KEYS.EXTRACTED_PROFILES]: profiles });
  },

  async getFixRecords(): Promise<FixRecord[]> {
    const result = await chrome.storage.local.get(STORAGE_KEYS.FIX_RECORDS);
    return (result[STORAGE_KEYS.FIX_RECORDS] as FixRecord[] | undefined) || [];
  },

  async addFixRecord(record: FixRecord): Promise<void> {
    const records = await this.getFixRecords();
    records.push(record);
    await chrome.storage.local.set({ [STORAGE_KEYS.FIX_RECORDS]: records });
  },

  async clearFixRecords(): Promise<void> {
    await chrome.storage.local.remove(STORAGE_KEYS.FIX_RECORDS);
  },

  // --- 返信スカウト記録 ---

  async getReplyRecords(): Promise<ReplyRecord[]> {
    const result = await chrome.storage.local.get(STORAGE_KEYS.REPLY_RECORDS);
    return (result[STORAGE_KEYS.REPLY_RECORDS] as ReplyRecord[] | undefined) || [];
  },

  async addReplyRecord(record: ReplyRecord): Promise<void> {
    const records = await this.getReplyRecords();
    records.push(record);
    await chrome.storage.local.set({ [STORAGE_KEYS.REPLY_RECORDS]: records });
  },

  async clearReplyRecords(): Promise<void> {
    await chrome.storage.local.remove(STORAGE_KEYS.REPLY_RECORDS);
  },

  // --- やりとりスレッド ---

  async getConversations(): Promise<ConversationThread[]> {
    const result = await chrome.storage.local.get(STORAGE_KEYS.CONVERSATIONS);
    return (result[STORAGE_KEYS.CONVERSATIONS] as ConversationThread[] | undefined) || [];
  },

  async addConversation(thread: ConversationThread): Promise<void> {
    const threads = await this.getConversations();
    // 同じmember_idのスレッドがあれば上書き
    const index = threads.findIndex((t) => t.member_id === thread.member_id);
    if (index !== -1) {
      threads[index] = thread;
    } else {
      threads.push(thread);
    }
    await chrome.storage.local.set({ [STORAGE_KEYS.CONVERSATIONS]: threads });
  },

  async removeConversation(memberId: string): Promise<void> {
    const threads = await this.getConversations();
    const filtered = threads.filter((t) => t.member_id !== memberId);
    await chrome.storage.local.set({ [STORAGE_KEYS.CONVERSATIONS]: filtered });
  },

  async clearConversations(): Promise<void> {
    await chrome.storage.local.remove(STORAGE_KEYS.CONVERSATIONS);
  },

  // --- 選択中の求人 ---

  async getSelectedJobOffer(): Promise<JobOffer | null> {
    const result = await chrome.storage.local.get(STORAGE_KEYS.SELECTED_JOB_OFFER);
    return (result[STORAGE_KEYS.SELECTED_JOB_OFFER] as JobOffer | undefined) || null;
  },

  async setSelectedJobOffer(offer: JobOffer | null): Promise<void> {
    if (offer) {
      await chrome.storage.local.set({ [STORAGE_KEYS.SELECTED_JOB_OFFER]: offer });
    } else {
      await chrome.storage.local.remove(STORAGE_KEYS.SELECTED_JOB_OFFER);
    }
  },

  // --- デバッグ・ドライラン ---

  async isDryRunMode(): Promise<boolean> {
    const result = await chrome.storage.local.get(STORAGE_KEYS.DRY_RUN_MODE);
    return !!result[STORAGE_KEYS.DRY_RUN_MODE];
  },

  async setDryRunMode(enabled: boolean): Promise<void> {
    await chrome.storage.local.set({ [STORAGE_KEYS.DRY_RUN_MODE]: enabled });
  },

  async isDebugLogEnabled(): Promise<boolean> {
    const result = await chrome.storage.local.get(STORAGE_KEYS.DEBUG_LOG_ENABLED);
    return !!result[STORAGE_KEYS.DEBUG_LOG_ENABLED];
  },

  async setDebugLogEnabled(enabled: boolean): Promise<void> {
    await chrome.storage.local.set({ [STORAGE_KEYS.DEBUG_LOG_ENABLED]: enabled });
  },

  // --- 求人自動選択 ---

  async isAutoJobOfferEnabled(): Promise<boolean> {
    const result = await chrome.storage.local.get(STORAGE_KEYS.AUTO_JOB_OFFER);
    // デフォルトはON
    return result[STORAGE_KEYS.AUTO_JOB_OFFER] !== false;
  },

  async setAutoJobOffer(enabled: boolean): Promise<void> {
    await chrome.storage.local.set({ [STORAGE_KEYS.AUTO_JOB_OFFER]: enabled });
  },

  // --- GAS連携 ---

  async getGASEndpoint(): Promise<string> {
    const result = await chrome.storage.local.get(STORAGE_KEYS.GAS_ENDPOINT);
    return (result[STORAGE_KEYS.GAS_ENDPOINT] as string) || '';
  },

  async setGASEndpoint(url: string): Promise<void> {
    await chrome.storage.local.set({ [STORAGE_KEYS.GAS_ENDPOINT]: url });
  },

  async isGASEnabled(): Promise<boolean> {
    const result = await chrome.storage.local.get(STORAGE_KEYS.GAS_ENABLED);
    return !!result[STORAGE_KEYS.GAS_ENABLED];
  },

  async setGASEnabled(enabled: boolean): Promise<void> {
    await chrome.storage.local.set({ [STORAGE_KEYS.GAS_ENABLED]: enabled });
  },

  async clear(): Promise<void> {
    await chrome.storage.local.remove([
      STORAGE_KEYS.CANDIDATES,
      STORAGE_KEYS.EXTRACTED_PROFILES,
    ]);
  },
};
