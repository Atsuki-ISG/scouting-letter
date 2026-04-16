/** ローカル時刻文字列を返す（YYYY-MM-DDTHH:mm:ss+09:00 形式） */
export function localTimestamp(): string {
  const now = new Date();
  const off = -now.getTimezoneOffset();
  const sign = off >= 0 ? '+' : '-';
  const hh = String(Math.floor(Math.abs(off) / 60)).padStart(2, '0');
  const mm = String(Math.abs(off) % 60).padStart(2, '0');
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}${sign}${hh}:${mm}`;
}

/** ローカル日付文字列を返す（YYYY-MM-DD 形式） */
export function localDate(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** 抽出間隔（ms）- overlay閉じ後の最小待機 */
export const EXTRACTION_INTERVAL_MS = 50;

/** overlay表示の最大待機時間（ms） */
export const OVERLAY_WAIT_TIMEOUT_MS = 5000;

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

/** template_typeから適切な求人を判定 */
export function resolveJobOffer(templateType: string, jobOffers: JobOffer[]): JobOffer | undefined {
  if (jobOffers.length === 0) return undefined;
  if (jobOffers.length === 1) return jobOffers[0];

  const isKeiyaku = templateType.includes('契約');
  const isSeishain = templateType.includes('正社員');
  const keiyakuOffer = jobOffers.find((j) => j.name.includes('契約'));
  const seishainOffer = jobOffers.find((j) => j.name.includes('正職員'));
  const partOffer = jobOffers.find((j) => j.name.includes('パート'));

  if (isKeiyaku && keiyakuOffer) return keiyakuOffer;
  if (isSeishain && seishainOffer) return seishainOffer;
  if (!isSeishain && !isKeiyaku && partOffer) return partOffer;

  return undefined;
}

/** 会社別の求人リスト（API取得不可時のフォールバック） */
export const FALLBACK_COMPANY_JOB_OFFERS: Record<string, JobOffer[]> = {
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
  DRY_RUN_MODE: 'scout_dry_run_mode',
  DEBUG_LOG_ENABLED: 'scout_debug_log_enabled',
  GAS_ENDPOINT: 'scout_gas_endpoint',
  GAS_ENABLED: 'scout_gas_enabled',
  AUTO_JOB_OFFER: 'scout_auto_job_offer',
  API_ENDPOINT: 'scout_api_endpoint',
  API_KEY: 'scout_api_key',
  CONFIG_CACHE: 'scout_config_cache',
  GENERATE_SETTINGS: 'scout_generate_settings',
  DETECTION_KEYWORDS: 'scout_detection_keywords',
  DEV_MODE: 'scout_dev_mode',
  EXTRACT_LIMIT: 'scout_extract_limit',
  QUOTA_LAST_FETCH: 'scout_quota_last_fetch',
} as const;

/** 会社IDから施設名キーワード（求人ドロップダウンのテキストに含まれるべき文字列） */
export const COMPANY_FACILITY_KEYWORDS: Record<string, string[]> = {
  'ark-visiting-nurse': ['アーク', '優希'],
  'lcc-visiting-nurse': ['LCC', 'ＬＣＣ'],
  'ichigo-visiting-nurse': ['いちご'],
  'chigasaki-tokushukai': ['茅ヶ崎徳洲会', '徳洲会'],
  'nomura-hospital': ['野村病院'],
  'an-visiting-nurse': ['ａｎ訪問看護', 'an訪問看護'],
};

/** 会社別バリデーション設定（API取得不可時のフォールバック） */
import { CompanyValidationConfig } from './types';

export const FALLBACK_VALIDATION_CONFIG: Record<string, CompanyValidationConfig> = {
  'ark-visiting-nurse': {
    ageRange: { min: 20, max: 59 },
    qualificationRules: [
      { jobOfferId: '1550716', required: ['看護師', '准看護師'], excluded: [] },
      { jobOfferId: '1550715', required: ['看護師'], excluded: [] },
    ],
    categoryExclusions: { nurse: ['准看護師'] },
    categoryConfig: {
      nurse: { display_name: '看護師', search_term: '看護', keywords: ['看護師', '准看護師'] },
    },
  },
  'lcc-visiting-nurse': {
    ageRange: { min: 20, max: 65 },
    qualificationRules: [
      { jobOfferId: '638104', required: ['看護師', '准看護師'], excluded: [] },
      { jobOfferId: '1146892', required: ['理学療法士'], excluded: [] },
      { jobOfferId: '1328672', required: ['言語聴覚士'], excluded: [] },
    ],
    categoryExclusions: { nurse: ['准看護師'] },
    categoryConfig: {
      nurse: { display_name: '看護師', search_term: '看護', keywords: ['看護師', '准看護師'] },
      rehab_pt: { display_name: '理学療法士', search_term: '理学療法', keywords: ['理学療法士'] },
      rehab_st: { display_name: '言語聴覚士', search_term: '言語聴覚', keywords: ['言語聴覚士'] },
    },
  },
};
