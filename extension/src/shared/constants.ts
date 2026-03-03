/** 抽出間隔（ms）- レート制限回避 */
export const EXTRACTION_INTERVAL_MS = 800;

/** overlay表示の最大待機時間（ms） */
export const OVERLAY_WAIT_TIMEOUT_MS = 5000;

/** タブ切替後のコンテンツ読み込み待機時間（ms） */
export const TAB_LOAD_WAIT_MS = 500;

/** MutationObserverのタイムアウト（ms） */
export const MUTATION_OBSERVER_TIMEOUT_MS = 10000;

/** デフォルト会社名 */
export const DEFAULT_COMPANY = 'ark-visiting-nurse';

/** 求人情報 */
export interface JobOffer {
  id: string;
  name: string;
  label: string; // ドロップダウン表示用の短縮名
}

/** 会社別の求人リスト */
export const COMPANY_JOB_OFFERS: Record<string, JobOffer[]> = {
  'ark-visiting-nurse': [
    {
      id: '1550716',
      name: '北海道 医療法人社団優希 アーク訪問看護ステーション 看護師/准看護師 (訪問看護師) パート・バイト',
      label: '看護師 パート',
    },
    {
      id: '1550715',
      name: '北海道 医療法人社団優希 アーク訪問看護ステーション 看護師/准看護師 (訪問看護師) 正職員',
      label: '看護師 正社員',
    },
  ],
  'lcc-visiting-nurse': [
    {
      id: '638104',
      name: '東京都 LCC訪問看護ステーション 本社 看護師/准看護師  正職員',
      label: '看護師 正社員',
    },
    {
      id: '1146892',
      name: '東京都 LCC訪問看護ステーション 本社 理学療法士  正職員',
      label: '理学療法士 正社員',
    },
    {
      id: '1328672',
      name: '東京都 LCC訪問看護ステーション 本社 言語聴覚士  正職員',
      label: '言語聴覚士 正社員',
    },
  ],
};

/** ストレージキー */
export const STORAGE_KEYS = {
  COMPANY: 'scout_company',
  CANDIDATES: 'scout_candidates',
  EXTRACTED_PROFILES: 'scout_extracted_profiles',
  FIX_RECORDS: 'scout_fix_records',
  REPLY_RECORDS: 'scout_reply_records',
  CONVERSATIONS: 'scout_conversations',
  SELECTED_JOB_OFFER: 'scout_selected_job_offer',
} as const;
