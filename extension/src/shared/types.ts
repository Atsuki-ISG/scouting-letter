/** 施設情報（求人プレビューから抽出） */
export interface FacilityJobInfo {
  /** 求人タイトル（募集職種 + 雇用形態） */
  title: string;
  /** 募集職種 */
  jobType: string;
  /** 仕事内容 */
  jobDescription: string;
  /** 給与 */
  salary: string;
  /** 待遇・福利厚生 */
  benefits: string;
  /** 勤務時間 */
  workingHours: string;
  /** 休日 */
  holidays: string;
  /** 全テキスト（パース失敗時のフォールバック） */
  rawText: string;
}

/** 施設情報 */
export interface FacilityInfo {
  /** 施設名 */
  facilityName: string;
  /** 施設ID */
  facilityId: string;
  /** 所在地 */
  address: string;
  /** 施設種別（病院、クリニック等） */
  facilityType: string;
  /** 代表メッセージ */
  representativeMessage: string;
  /** 施設の特徴・紹介文 */
  description: string;
  /** 求人一覧（プレビューから取得） */
  jobs: FacilityJobInfo[];
  /** ページから取得した生テキスト（デバッグ用） */
  rawPageText: string;
}

/** サイドバーの施設リスト項目 */
export interface FacilityListItem {
  facilityId: string;
  name: string;
}

/** 抽出されたプロフィールデータ */
export interface CandidateProfile {
  member_id: string;
  gender: string;
  age: string;
  area: string;
  qualifications: string;
  experience_type: string;
  experience_years: string;
  employment_status: string;
  desired_job: string;
  desired_area: string;
  desired_employment_type: string;
  desired_start: string;
  self_pr: string;
  special_conditions: string;
  work_history_summary: string;
  scout_sent_date: string;
  is_favorite: boolean;
}

/** CSV列の順序 */
export const PROFILE_CSV_COLUMNS: (keyof CandidateProfile)[] = [
  'member_id',
  'gender',
  'age',
  'area',
  'qualifications',
  'experience_type',
  'experience_years',
  'employment_status',
  'desired_job',
  'desired_area',
  'desired_employment_type',
  'desired_start',
  'self_pr',
  'special_conditions',
  'work_history_summary',
  'scout_sent_date',
  'is_favorite',
];

/** 生成されたスカウト文データ */
export interface ScoutEntry {
  member_id: string;
  template_type: string;
  personalized_text: string;
  full_scout_text: string;
}

export const SCOUT_CSV_COLUMNS: (keyof ScoutEntry)[] = [
  'member_id',
  'template_type',
  'personalized_text',
  'full_scout_text',
];

/** デバッグログエントリ */
export interface DebugLogEntry {
  timestamp: string;
  step: string;
  status: 'pending' | 'success' | 'error';
  detail?: string;
}

/** バリデーション結果 */
export interface ValidationResult {
  ruleId: string;
  severity: 'warning' | 'error';
  message: string;
}

/** 会社別バリデーション設定 */
export interface CompanyValidationConfig {
  ageRange?: { min: number; max: number };
  qualificationRules?: { jobOfferId: string; required: string[]; excluded: string[] }[];
  /** カテゴリ別資格除外 例: { "nurse": ["准看護師"] } */
  categoryExclusions?: Record<string, string[]>;
  /** カテゴリ別設定 例: { "nurse": { display_name: "看護師", search_term: "看護", keywords: ["看護師"] } } */
  categoryConfig?: Record<string, { display_name: string; search_term: string; keywords: string[] }>;
}

/** 送信前確認データ */
export interface ConfirmationData {
  member_id: string;
  label: string;
  template_type: string;
  personalized_text: string;
  full_scout_text: string;
  jobOfferName: string;
  /** バリデーション警告（ポップアップ表示用） */
  validationWarnings?: string[];
  /** プロフィール要約（パーソナライズ文との照合用） */
  profileSummary?: {
    qualifications: string;
    experience: string;
    desiredEmploymentType: string;
    area: string;
    selfPr: string;
    hasWorkHistory: boolean;
  };
}

/** 候補者の送信ステータス */
export type CandidateStatus = 'ready' | 'sent' | 'skipped';

/** パーソナライズ率計測（developer mode の新パーソナライズ生成が返す） */
export interface PersonalizationStats {
  level: 'L1' | 'L2' | 'L3' | string;
  total_chars: number;
  personalized_chars: number;
  fixed_chars: number;
  /** 0..1 */
  ratio: number;
  per_block_chars: Record<string, number>;
}

/** サイドパネルで管理する候補者 */
export interface CandidateItem {
  member_id: string;
  label: string;
  status: CandidateStatus;
  personalized_text: string;
  full_scout_text: string;
  template_type: string;
  job_category?: string;
  validationResults?: ValidationResult[];
  is_favorite?: boolean;
  /** developer-mode の L2/L3 生成時にのみ存在する */
  block_contents?: Record<string, string>;
  personalization_stats?: PersonalizationStats;
}

/** スカウト文の修正記録 */
export interface FixRecord {
  /** クライアント側で採番する一意ID（重複送信防止）。Phase Aから追加 */
  id?: string;
  member_id: string;
  template_type: string;
  timestamp: string;
  before: string;
  after: string;
  reason: string;
  /** trueの間はサーバ未送信。リトライボタンで送り直す対象 */
  _unsynced?: boolean;
}

/** メッセージ1通 */
export interface ConversationMessage {
  role: 'company' | 'candidate';
  date: string;
  text: string;
  /** ジョブメドレーDOMの.c-labelテキスト（"スカウト" "応募" "通常" "スカウト辞退" 等）。応募判定に使う */
  label?: string;
}

/** やりとりスレッド */
export interface ConversationThread {
  member_id: string;
  company: string;
  started: string;
  candidate_name?: string;
  candidate_age?: string;
  candidate_gender?: string;
  job_title?: string;
  messages: ConversationMessage[];
}

/** 返信スカウト記録 */
export interface ReplyRecord {
  member_id: string;
  company: string;
  template_type: string;
  date_sent: string;
  date_replied: string;
  profile: Partial<CandidateProfile>;
  personalized_text: string;
  replied: true;
}

/** ストレージに保存するデータ */
export interface StorageData {
  company: string;
  candidates: CandidateItem[];
  extractedProfiles: CandidateProfile[];
  fixRecords: FixRecord[];
  replyRecords: ReplyRecord[];
  conversations: ConversationThread[];
}

/** Content Script ↔ Service Worker メッセージ */
export type Message =
  | { type: 'START_EXTRACTION'; count: number; startMemberId?: string }
  | { type: 'STOP_EXTRACTION' }
  | { type: 'EXTRACTION_PROGRESS'; current: number; total: number; profile: CandidateProfile }
  | { type: 'EXTRACTION_COMPLETE'; profiles: CandidateProfile[] }
  | { type: 'EXTRACTION_ERROR'; error: string }
  | { type: 'GET_OVERLAY_MEMBER_ID' }
  | { type: 'OVERLAY_MEMBER_ID'; memberId: string | null }
  | { type: 'FILL_FORM'; text: string; memberId?: string; searchTerm?: string; jobCategory?: string; employmentType?: string; skipJobOffer?: boolean; categoryKeywords?: string[] }
  | { type: 'FILL_FORM_RESULT'; success: boolean; error?: string }
  | { type: 'FILL_JOB_OFFER'; searchTerm: string; jobCategory: string; employmentType: string; memberId?: string }
  | { type: 'OPEN_SIDE_PANEL' }
  | { type: 'EXTRACT_CONVERSATION' }
  | { type: 'EXTRACT_ALL_CONVERSATIONS'; limit?: number }
  | { type: 'CONVERSATION_DATA'; thread: ConversationThread }
  | { type: 'CONVERSATION_PROGRESS'; current: number; total: number; thread: ConversationThread }
  | { type: 'CONVERSATION_BATCH_COMPLETE'; count: number }
  | { type: 'CONVERSATION_ERROR'; error: string }
  | { type: 'START_CONTINUOUS_SEND' }
  | { type: 'STOP_CONTINUOUS_SEND' }
  | { type: 'GET_NEXT_CANDIDATE' }
  | { type: 'NEXT_CANDIDATE'; candidate: { memberId: string; text: string; searchTerm?: string; jobCategory?: string; employmentType?: string } | null }
  | {
      type: 'CANDIDATE_SENT';
      memberId: string;
      // Phase C: 手動送信(JOBMEDLEY UI 直接操作)を Sheets に記録するための補助情報。
      // continuous-sender からは送られない。single-send-tracker のみ付与。
      manualSendProfile?: {
        member_id: string;
        age: string;
        qualifications: string;
        area: string;
        desired_employment_type: string;
      } | null;
      sentAt?: string;
    }
  | { type: 'SKIP_CURRENT_CANDIDATE' }
  | { type: 'DEBUG_LOG'; entry: DebugLogEntry }
  | { type: 'DRY_RUN_COMPLETE'; memberId: string }
  | { type: 'CONFIRM_BEFORE_SEND'; data: ConfirmationData }
  | { type: 'CONFIRM_RESPONSE'; result: 'ok' | 'ng' }
  | { type: 'JOB_OFFER_FAILED'; memberId?: string; error: string }
  | { type: 'COMPANY_MISMATCH'; companyId: string; keywords: string[] }
  | { type: 'COMPANY_DETECTED'; companyId: string }
  | { type: 'DETECT_COMPANY' }
  | { type: 'RESUME_AFTER_JOB_OFFER' }
  | { type: 'CONTINUOUS_SEND_COMPLETE' }
  | { type: 'EXTRACT_JOB_OFFERS' }
  | { type: 'EXTRACT_FACILITY_LIST' }
  | { type: 'EXTRACT_FACILITY_INFO'; facilityIds: string[] }
  | { type: 'STOP_FACILITY_EXTRACTION' }
  | { type: 'FACILITY_INFO_RESULT'; success: boolean; facility: FacilityInfo | null; error?: string }
  | { type: 'REQUEST_QUOTA_SNAPSHOT'; companyId: string }
  | { type: 'REQUEST_QUOTA_SNAPSHOT_RESULT'; success: boolean; remaining?: number; error?: string }
  | { type: 'QUOTA_SNAPSHOT_POSTED'; companyId: string; remaining: number };
