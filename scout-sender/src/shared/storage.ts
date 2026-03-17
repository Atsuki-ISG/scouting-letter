import { CandidateProfile } from './types';
import { STORAGE_KEYS } from './constants';

/** chrome.storage.local ラッパー */
export const storage = {
  async getExtractedProfiles(): Promise<CandidateProfile[]> {
    const result = await chrome.storage.local.get(STORAGE_KEYS.EXTRACTED_PROFILES);
    return (result[STORAGE_KEYS.EXTRACTED_PROFILES] as CandidateProfile[] | undefined) || [];
  },

  async setExtractedProfiles(profiles: CandidateProfile[]): Promise<void> {
    await chrome.storage.local.set({ [STORAGE_KEYS.EXTRACTED_PROFILES]: profiles });
  },
};
