/** 候補者プロフィール。WelMe/コメディカル共通の最大公約数。 */
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

export function emptyCandidateProfile(): CandidateProfile {
  return {
    member_id: '',
    gender: '',
    age: '',
    area: '',
    qualifications: '',
    experience_type: '',
    experience_years: '',
    employment_status: '',
    desired_job: '',
    desired_area: '',
    desired_employment_type: '',
    desired_start: '',
    self_pr: '',
    special_conditions: '',
    work_history_summary: '',
    scout_sent_date: '',
    is_favorite: false,
  };
}

export type Platform = 'welme' | 'comedical';

export interface BundledTemplate {
  type: string; // 正社員_初回 / 正社員_再送 / 正社員_お気に入り など
  body: string;
}

/** 1会社の中の職種単位。看護師、管理栄養士、PT、OT、相談支援専門員 など。 */
export interface Occupation {
  id: string; // 'nurse' / 'dietitian' / 'pt' / 'ot' / 'st' / 'care_manager' など
  displayName: string; // '看護師' / '管理栄養士'
  /** 候補者の qualifications にこれらのどれかが含まれれば自動選択される。 */
  matchQualifications: string[];
  patterns: import('./pattern-matcher').Pattern[];
  templates: BundledTemplate[];
}

export interface Company {
  companyId: string;
  displayName: string;
  platform: Platform;
  occupations: Occupation[];
}

export interface ScoutConfig {
  companies: Company[];
}

/** 候補者の資格文字列から、会社の occupations のうち最初にマッチしたものを返す。 */
export function pickOccupation(
  company: Company,
  qualifications: string
): Occupation | null {
  if (!company.occupations.length) return null;
  const q = qualifications || '';
  for (const occ of company.occupations) {
    if (occ.matchQualifications.some((kw) => q.includes(kw))) {
      return occ;
    }
  }
  // フォールバック: 最初の職種
  return company.occupations[0] || null;
}
