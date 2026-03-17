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

/** Content Script ↔ Service Worker メッセージ */
export type Message =
  | { type: 'START_EXTRACTION'; count: number; startMemberId?: string }
  | { type: 'STOP_EXTRACTION' }
  | { type: 'EXTRACTION_PROGRESS'; current: number; total: number; profile: CandidateProfile }
  | { type: 'EXTRACTION_COMPLETE'; profiles: CandidateProfile[] }
  | { type: 'EXTRACTION_ERROR'; error: string }
  | { type: 'OPEN_SIDE_PANEL' };
