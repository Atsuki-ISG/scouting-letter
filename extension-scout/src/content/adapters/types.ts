import type { Company, CandidateProfile, Occupation } from '../../shared/types';
import type { HistoryStore } from '../../shared/history-store';

export interface AdapterContext {
  /** 現在選択されている会社設定。プラットフォームはこのアダプタと一致する前提。 */
  company: Company;
  historyStore: HistoryStore;
  /** 候補者プロフィールから職種を選ぶ。資格でマッチ→最初の occupation にフォールバック。 */
  pickOccupation: (profile: CandidateProfile) => Occupation;
}

export interface PlatformAdapter {
  platform: 'welme' | 'comedical';
  matchUrl(url: string): boolean;
  init(ctx: AdapterContext): void;
}
