/** WelMe 拡張が扱う候補者プロフィール。
 *
 * WelMe (kaigojob.com) は自己PR・職務経歴・経験年数フィールドが存在
 * しないが、pattern-matcher のシグネチャに合わせて全フィールドを
 * 持たせる（空文字で埋める）。
 */
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
