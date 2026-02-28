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

/** ストレージキー */
export const STORAGE_KEYS = {
  COMPANY: 'scout_company',
  CANDIDATES: 'scout_candidates',
  EXTRACTED_PROFILES: 'scout_extracted_profiles',
  FIX_RECORDS: 'scout_fix_records',
  REPLY_RECORDS: 'scout_reply_records',
  CONVERSATIONS: 'scout_conversations',
} as const;
