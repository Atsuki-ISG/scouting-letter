import { CandidateItem, CandidateProfile, ValidationResult, CompanyValidationConfig } from './types';
import { JobOffer } from './constants';

interface ValidationRule {
  id: string;
  severity: 'warning' | 'error';
  check(candidate: CandidateItem, profile: CandidateProfile | null, jobOffer: JobOffer | null, config: CompanyValidationConfig): string | null;
}

const rules: ValidationRule[] = [
  {
    id: 'age-range',
    severity: 'warning',
    check(_candidate, profile, _jobOffer, config) {
      if (!config.ageRange || !profile?.age) return null;
      const match = profile.age.match(/(\d+)/);
      if (!match) return null;
      const age = parseInt(match[1], 10);
      if (age < config.ageRange.min || age > config.ageRange.max) {
        return `年齢 ${age}歳 が対象範囲外（${config.ageRange.min}〜${config.ageRange.max}歳）`;
      }
      return null;
    },
  },
  {
    id: 'qualification',
    severity: 'error',
    check(_candidate, profile, jobOffer, config) {
      if (!config.qualificationRules || !profile?.qualifications || !jobOffer) return null;
      const rule = config.qualificationRules.find((r) => r.jobOfferId === jobOffer.id);
      if (!rule) return null;
      const quals = profile.qualifications;
      const hasRequired = rule.required.some((q) => quals.includes(q));
      if (!hasRequired) {
        return `資格不一致: ${rule.required.join('/')}のいずれかが必要`;
      }
      const hasExcluded = rule.excluded.some((q) => quals.includes(q));
      if (hasExcluded) {
        return `対象外資格に該当`;
      }
      return null;
    },
  },
  {
    id: 'profile-missing',
    severity: 'warning',
    check(_candidate, profile) {
      if (!profile) {
        return 'プロフィール未取得（バリデーション不完全）';
      }
      return null;
    },
  },
  {
    id: 'category-exclusion',
    severity: 'warning',
    check(candidate, profile, _jobOffer, config) {
      if (!config.categoryExclusions || !profile?.qualifications) return null;
      const jobCategory = candidate.job_category || 'nurse';
      const exclusions = config.categoryExclusions[jobCategory];
      if (!exclusions) return null;
      const quals = profile.qualifications;
      const matched = exclusions.filter((q) => quals.includes(q));
      if (matched.length > 0) {
        const displayName = config.categoryConfig?.[jobCategory]?.display_name || jobCategory;
        return `${matched.join('・')}は${displayName}求人の対象外です`;
      }
      return null;
    },
  },
  {
    id: 'employment-type-mismatch',
    severity: 'warning',
    check(candidate, profile) {
      if (!profile?.desired_employment_type || !candidate.template_type) return null;
      const desired = profile.desired_employment_type;
      const isSeishainTemplate = candidate.template_type.includes('正社員');
      const isPartTemplate = candidate.template_type.includes('パート');
      if (isSeishainTemplate && !desired.includes('正職員')) {
        return `正社員テンプレートですが希望は「${desired}」`;
      }
      if (isPartTemplate && !desired.includes('パート') && !desired.includes('バイト')) {
        return `パートテンプレートですが希望は「${desired}」`;
      }
      return null;
    },
  },
];

export function validateCandidate(
  candidate: CandidateItem,
  profile: CandidateProfile | null,
  jobOffer: JobOffer | null,
  config: CompanyValidationConfig
): ValidationResult[] {
  const results: ValidationResult[] = [];
  for (const rule of rules) {
    const message = rule.check(candidate, profile, jobOffer, config);
    if (message) {
      results.push({ ruleId: rule.id, severity: rule.severity, message });
    }
  }
  return results;
}
