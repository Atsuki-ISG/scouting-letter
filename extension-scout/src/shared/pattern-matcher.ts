/**
 * 型はめ（pattern matching）— サーバなしで候補者プロフィールから
 * パーソナライズ文を組み立てる。
 *
 * 等価性の拘束:
 *   Python 版 (server/pipeline/pattern_matcher.py) と挙動を一致させる。
 *   既存の Python テスト (server/tests/test_pattern_matcher.py) が
 *   基準仕様。test/pattern-matcher.test.ts が TS 側の再現性を保証する。
 *
 * この拡張（ウェルミー等）は全部型はめでサーバを呼ばないため、
 * ここが生成の中核になる。
 */

import type { CandidateProfile } from './types';

export type AgeBracket = '40s+' | 'late_30s' | 'young';
export type EmploymentState = '就業中' | '離職中' | '在学中';

export interface MatchRule {
  employment?: EmploymentState;
  age_group?: AgeBracket | null;
  exp_min?: number | null;
  exp_max?: number | null;
}

export interface Pattern {
  pattern_type: string;
  template_text: string;
  feature_variations?: string[];
  employment_variant?: EmploymentState;
  match_rules?: MatchRule[];
  job_category?: string;
}

export interface QualificationModifier {
  qualification_combo: string[];
  replacement_text: string;
}

/** "44歳" → 44, 空 → null */
export function parseAge(ageStr: string | undefined | null): number | null {
  if (!ageStr) return null;
  const m = ageStr.match(/(\d+)/);
  return m ? parseInt(m[1], 10) : null;
}

/**
 * "10年以上" → 10, "3年" → 3, "6〜9年" → 6, "1年未満" → 0,
 * 空・"未入力"・"なし" → null
 */
export function parseExperienceYears(expStr: string | undefined | null): number | null {
  if (!expStr) return null;
  const trimmed = expStr.trim();
  if (trimmed === '' || trimmed === '未入力' || trimmed === 'なし') return null;
  const m = trimmed.match(/(\d+)/);
  if (!m) return null;
  const years = parseInt(m[1], 10);
  if (trimmed.includes('未満') && years <= 1) return 0;
  return years;
}

export function determineEmploymentState(profile: CandidateProfile): EmploymentState {
  const status = profile.employment_status || '';
  if (status.includes('在学中')) return '在学中';
  if (status.includes('就業中')) return '就業中';
  return '離職中';
}

export function determineAgeBracket(age: number | null): AgeBracket {
  if (age === null) return 'young';
  if (age >= 40) return '40s+';
  if (age >= 35) return 'late_30s';
  return 'young';
}

/**
 * ハードコードされた年齢×経験年数マトリクスでパターン型を決定する。
 * match_rules がパターン定義にあればそちらが優先（_selectPatternTypeFromRules）。
 */
export function selectPatternType(
  ageBracket: AgeBracket,
  experienceYears: number | null,
  employmentState: EmploymentState
): string {
  if (employmentState === '在学中') return 'G';

  const hasExp = experienceYears !== null && experienceYears > 0;

  if (hasExp) {
    const exp = experienceYears as number;
    if (exp >= 10) {
      return ageBracket === '40s+' || ageBracket === 'late_30s' ? 'A' : 'B1';
    }
    if (exp >= 6) return 'B1';
    if (exp >= 3) return 'B2';
    if (exp >= 1) {
      return ageBracket === '40s+' || ageBracket === 'late_30s' ? 'C' : 'E';
    }
    // experience_years == 0 (未満)
    if (employmentState === '就業中') {
      return ageBracket === 'young' ? 'F_就業中' : 'D_就業中';
    }
    return ageBracket === 'young' ? 'F_離職中' : 'D_離職中';
  }

  // No experience data
  if (ageBracket === '40s+' || ageBracket === 'late_30s') {
    return employmentState === '就業中' ? 'D_就業中' : 'D_離職中';
  }
  return employmentState === '就業中' ? 'F_就業中' : 'F_離職中';
}

const INVALID_TEXT_VALUES = new Set(['未入力', 'なし', '-', 'ー', '']);

function isMeaningful(value: string | undefined | null): boolean {
  if (!value) return false;
  const t = value.trim();
  if (!t) return false;
  return !INVALID_TEXT_VALUES.has(t);
}

/**
 * パターン経路を使うべきか。work_history/self_pr が両方空なら true。
 * WelMe 等の他媒体では常に true になる前提。
 */
export function shouldUsePattern(profile: CandidateProfile): boolean {
  return !isMeaningful(profile.work_history_summary) && !isMeaningful(profile.self_pr);
}

function matchRule(
  rule: MatchRule,
  ageBracket: AgeBracket,
  experienceYears: number | null,
  employmentState: EmploymentState
): boolean {
  if (rule.employment && employmentState !== rule.employment) return false;
  if (rule.age_group && ageBracket !== rule.age_group) return false;

  const hasExpMin = 'exp_min' in rule;
  const hasExpMax = 'exp_max' in rule;

  // "exp_min": null → matches when experience_years is None (no data)
  if (hasExpMin && rule.exp_min === null && !hasExpMax) {
    return experienceYears === null;
  }

  if (rule.exp_min !== undefined && rule.exp_min !== null) {
    if (experienceYears === null || experienceYears < rule.exp_min) return false;
  }
  if (rule.exp_max !== undefined && rule.exp_max !== null) {
    if (experienceYears === null) return false;
    if (experienceYears > rule.exp_max) return false;
  }
  return true;
}

function selectPatternTypeFromRules(
  patterns: Pattern[],
  ageBracket: AgeBracket,
  experienceYears: number | null,
  employmentState: EmploymentState
): string | null {
  const hasAnyRules = patterns.some((p) => p.match_rules && p.match_rules.length > 0);
  if (!hasAnyRules) return null;

  for (const p of patterns) {
    if (!p.match_rules || p.match_rules.length === 0) continue;
    for (const rule of p.match_rules) {
      if (matchRule(rule, ageBracket, experienceYears, employmentState)) {
        if (p.employment_variant) return `${p.pattern_type}_${p.employment_variant}`;
        if (
          (employmentState === '就業中' || employmentState === '離職中') &&
          (p.pattern_type === 'D' || p.pattern_type === 'F')
        ) {
          return `${p.pattern_type}_${employmentState}`;
        }
        return p.pattern_type;
      }
    }
  }
  return null;
}

function findPattern(
  patternType: string,
  patterns: Pattern[],
  employmentState: EmploymentState
): Pattern | null {
  // 1. Exact match including employment variant suffix
  for (const p of patterns) {
    if (p.pattern_type === patternType) {
      if (!p.employment_variant) return p;
      if (p.employment_variant === employmentState) return p;
    }
  }

  // 2. Base pattern type (strip employment suffix)
  const baseType = patternType.split('_')[0];
  for (const p of patterns) {
    if (p.pattern_type === baseType) {
      if (!p.employment_variant) return p;
      if (p.employment_variant === employmentState) return p;
    }
  }

  // 3. Fallback: any pattern with matching base
  for (const p of patterns) {
    if (p.pattern_type.startsWith(baseType)) return p;
  }

  return null;
}

function applyQualificationModifier(
  text: string,
  qualifications: string,
  modifiers: QualificationModifier[]
): string {
  if (!modifiers || modifiers.length === 0 || !qualifications) {
    return text.replace('{資格修飾}', '');
  }
  let modified = text;
  for (const m of modifiers) {
    if (m.qualification_combo.every((q) => qualifications.includes(q))) {
      const replacement = m.replacement_text || '';
      if (replacement) {
        if (modified.includes('{資格修飾}')) {
          modified = modified.replace('{資格修飾}', replacement);
        } else {
          modified = replacement + modified;
        }
      }
      break;
    }
  }
  return modified.replace('{資格修飾}', '');
}

/** 資格文字列から主職種名を解決する。 */
export function resolveJobName(qualifications: string): string {
  if (qualifications.includes('看護師')) return '看護師';
  if (qualifications.includes('理学療法士')) return '理学療法士';
  if (qualifications.includes('言語聴覚士')) return '言語聴覚士';
  if (qualifications.includes('作業療法士')) return '作業療法士';
  if (qualifications.includes('医療事務')) return '医療事務';
  return '';
}

/**
 * 候補者にパターンを当てはめてパーソナライズ文を生成する。
 * @returns [pattern_type, personalized_text, debug_info]
 * @throws 該当パターンが存在しないとき
 */
export function matchPattern(
  profile: CandidateProfile,
  patterns: Pattern[],
  qualificationModifiers: QualificationModifier[] = [],
  featureRotationIndex = 0
): [string, string, string] {
  const age = parseAge(profile.age);
  const experienceYears = parseExperienceYears(profile.experience_years);
  const employmentState = determineEmploymentState(profile);
  const ageBracket = determineAgeBracket(age);

  let patternType = selectPatternTypeFromRules(
    patterns,
    ageBracket,
    experienceYears,
    employmentState
  );
  if (patternType === null) {
    patternType = selectPatternType(ageBracket, experienceYears, employmentState);
  }

  const debugParts = [
    `age=${age}(${ageBracket})`,
    `exp=${experienceYears}`,
    `status=${employmentState}`,
    `pattern=${patternType}`,
  ];

  const pattern = findPattern(patternType, patterns, employmentState);
  if (pattern === null) {
    throw new Error(
      `パターン '${patternType}' が見つかりません (age=${age}, exp=${experienceYears}, status=${employmentState})`
    );
  }

  let personalized = pattern.template_text;
  const variations = pattern.feature_variations || [];
  let feature = '';
  if (variations.length > 0) {
    const idx = featureRotationIndex % variations.length;
    feature = variations[idx];
    debugParts.push(`feature_idx=${idx}/${variations.length}`);
  }
  personalized = personalized.replace('{特色}', feature);

  if (experienceYears !== null && experienceYears > 0) {
    personalized = personalized.replace('{N}', String(experienceYears));
  } else {
    personalized = personalized.replace('{N}', '');
  }

  const jobName = resolveJobName(profile.qualifications || '');
  personalized = personalized.replace('{職種名}', jobName);

  personalized = applyQualificationModifier(
    personalized,
    profile.qualifications || '',
    qualificationModifiers
  );

  return [patternType, personalized.trim(), debugParts.join(', ')];
}
