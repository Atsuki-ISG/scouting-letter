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

/** 候補者の送信ステータス */
export type CandidateStatus = 'ready' | 'sent' | 'skipped';

/** サイドパネルで管理する候補者 */
export interface CandidateItem {
  member_id: string;
  label: string;
  status: CandidateStatus;
  personalized_text: string;
  full_scout_text: string;
  template_type: string;
}

/** スカウト文の修正記録 */
export interface FixRecord {
  member_id: string;
  template_type: string;
  timestamp: string;
  before: string;
  after: string;
  reason: string;
}

/** メッセージ1通 */
export interface ConversationMessage {
  role: 'company' | 'candidate';
  date: string;
  text: string;
}

/** やりとりスレッド */
export interface ConversationThread {
  member_id: string;
  company: string;
  started: string;
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
  | { type: 'START_EXTRACTION'; count: number }
  | { type: 'STOP_EXTRACTION' }
  | { type: 'EXTRACTION_PROGRESS'; current: number; total: number; profile: CandidateProfile }
  | { type: 'EXTRACTION_COMPLETE'; profiles: CandidateProfile[] }
  | { type: 'EXTRACTION_ERROR'; error: string }
  | { type: 'GET_OVERLAY_MEMBER_ID' }
  | { type: 'OVERLAY_MEMBER_ID'; memberId: string | null }
  | { type: 'FILL_FORM'; text: string; memberId?: string }
  | { type: 'FILL_FORM_RESULT'; success: boolean; error?: string }
  | { type: 'OPEN_SIDE_PANEL' }
  | { type: 'EXTRACT_CONVERSATION' }
  | { type: 'CONVERSATION_DATA'; thread: ConversationThread }
  | { type: 'CONVERSATION_ERROR'; error: string };
