/**
 * TS 版 pattern matcher のテスト
 *
 * Python 版 (server/pipeline/pattern_matcher.py) の挙動を完全に
 * 再現することを目的とする。既存の Python テスト
 * (server/tests/test_pattern_matcher.py) と同等のケースをカバー。
 */

import { describe, expect, it } from 'vitest';
import {
  parseAge,
  parseExperienceYears,
  determineEmploymentState,
  determineAgeBracket,
  selectPatternType,
  shouldUsePattern,
  resolveJobName,
  matchPattern,
  type Pattern,
} from '../src/shared/pattern-matcher';
import { emptyCandidateProfile } from '../src/shared/types';

describe('parseAge', () => {
  it('"44歳" → 44', () => expect(parseAge('44歳')).toBe(44));
  it('"25" → 25', () => expect(parseAge('25')).toBe(25));
  it('空文字 → null', () => expect(parseAge('')).toBeNull());
  it('undefined → null', () => expect(parseAge(undefined)).toBeNull());
  it('数字なし → null', () => expect(parseAge('年齢')).toBeNull());
});

describe('parseExperienceYears', () => {
  it('"10年以上" → 10', () => expect(parseExperienceYears('10年以上')).toBe(10));
  it('"3年" → 3', () => expect(parseExperienceYears('3年')).toBe(3));
  it('"6〜9年" → 6', () => expect(parseExperienceYears('6〜9年')).toBe(6));
  it('"1年未満" → 0', () => expect(parseExperienceYears('1年未満')).toBe(0));
  it('"未入力" → null', () => expect(parseExperienceYears('未入力')).toBeNull());
  it('空文字 → null', () => expect(parseExperienceYears('')).toBeNull());
});

describe('determineEmploymentState', () => {
  it('就業中', () => {
    const p = { ...emptyCandidateProfile(), employment_status: '就業中' };
    expect(determineEmploymentState(p)).toBe('就業中');
  });
  it('在学中', () => {
    const p = { ...emptyCandidateProfile(), employment_status: '在学中' };
    expect(determineEmploymentState(p)).toBe('在学中');
  });
  it('離職中（デフォルト）', () => {
    const p = { ...emptyCandidateProfile(), employment_status: '離職中' };
    expect(determineEmploymentState(p)).toBe('離職中');
  });
  it('空は離職中扱い', () => {
    expect(determineEmploymentState(emptyCandidateProfile())).toBe('離職中');
  });
});

describe('determineAgeBracket', () => {
  it('40 → 40s+', () => expect(determineAgeBracket(40)).toBe('40s+'));
  it('44 → 40s+', () => expect(determineAgeBracket(44)).toBe('40s+'));
  it('35 → late_30s', () => expect(determineAgeBracket(35)).toBe('late_30s'));
  it('39 → late_30s', () => expect(determineAgeBracket(39)).toBe('late_30s'));
  it('34 → young', () => expect(determineAgeBracket(34)).toBe('young'));
  it('null → young', () => expect(determineAgeBracket(null)).toBe('young'));
});

describe('selectPatternType (matrix)', () => {
  it('在学中 → G', () => {
    expect(selectPatternType('young', 0, '在学中')).toBe('G');
  });
  it('10年以上 × 40s+ → A', () => {
    expect(selectPatternType('40s+', 10, '就業中')).toBe('A');
  });
  it('10年以上 × young → B1', () => {
    expect(selectPatternType('young', 12, '就業中')).toBe('B1');
  });
  it('6年 → B1', () => {
    expect(selectPatternType('young', 6, '就業中')).toBe('B1');
  });
  it('3年 → B2', () => {
    expect(selectPatternType('young', 3, '就業中')).toBe('B2');
  });
  it('1年 × 40s+ → C', () => {
    expect(selectPatternType('40s+', 1, '就業中')).toBe('C');
  });
  it('1年 × young → E', () => {
    expect(selectPatternType('young', 1, '就業中')).toBe('E');
  });
  it('0年 × young × 就業中 → F_就業中', () => {
    expect(selectPatternType('young', 0, '就業中')).toBe('F_就業中');
  });
  it('0年 × 40s+ × 離職中 → D_離職中', () => {
    expect(selectPatternType('40s+', 0, '離職中')).toBe('D_離職中');
  });
  it('経験不明 × 40s+ × 就業中 → D_就業中', () => {
    expect(selectPatternType('40s+', null, '就業中')).toBe('D_就業中');
  });
  it('経験不明 × young × 離職中 → F_離職中', () => {
    expect(selectPatternType('young', null, '離職中')).toBe('F_離職中');
  });
});

describe('shouldUsePattern', () => {
  it('work_history / self_pr なし → true', () => {
    expect(shouldUsePattern(emptyCandidateProfile())).toBe(true);
  });
  it('work_history あり → false', () => {
    const p = { ...emptyCandidateProfile(), work_history_summary: '10年勤務' };
    expect(shouldUsePattern(p)).toBe(false);
  });
  it('self_pr あり → false', () => {
    const p = { ...emptyCandidateProfile(), self_pr: '患者様に寄り添う' };
    expect(shouldUsePattern(p)).toBe(false);
  });
  it('"未入力" は無効値扱い', () => {
    const p = { ...emptyCandidateProfile(), work_history_summary: '未入力', self_pr: 'なし' };
    expect(shouldUsePattern(p)).toBe(true);
  });
});

describe('resolveJobName', () => {
  it('看護師', () => expect(resolveJobName('看護師')).toBe('看護師'));
  it('准看護師も看護師にマッチ', () => expect(resolveJobName('准看護師')).toBe('看護師'));
  it('理学療法士', () => expect(resolveJobName('理学療法士')).toBe('理学療法士'));
  it('該当なし', () => expect(resolveJobName('保育士')).toBe(''));
});

describe('matchPattern (integration)', () => {
  const patterns: Pattern[] = [
    {
      pattern_type: 'A',
      template_text: '10年以上のご経験を拝見しました。{特色}当ステーションで力になると考えております。',
      feature_variations: ['利用者様に寄り添う', 'きめ細かなケア'],
    },
    {
      pattern_type: 'B2',
      template_text: '看護師として{N}年のご経験をお持ちとのこと、{特色}期待しております。',
      feature_variations: ['医師との連携'],
    },
    {
      pattern_type: 'D',
      employment_variant: '就業中',
      template_text: '現在も臨床でご活躍の点に注目しました。{特色}期待しております。',
      feature_variations: ['認知症対応'],
    },
  ];

  it('10年以上×40歳以上 → Aパターン使用', () => {
    const profile = {
      ...emptyCandidateProfile(),
      age: '44歳',
      experience_years: '10年以上',
      qualifications: '看護師',
      employment_status: '就業中',
    };
    const [type, text] = matchPattern(profile, patterns);
    expect(type).toBe('A');
    expect(text).toContain('10年以上のご経験');
    expect(text).toContain('利用者様'); // feature[0]
  });

  it('{N} / {特色} プレースホルダが埋まる', () => {
    const profile = {
      ...emptyCandidateProfile(),
      age: '28歳',
      experience_years: '3年',
      qualifications: '看護師',
      employment_status: '就業中',
    };
    const [type, text] = matchPattern(profile, patterns);
    expect(type).toBe('B2');
    expect(text).toContain('3年のご経験');
    expect(text).toContain('医師との連携');
  });

  it('employment_variant で就業中パターンを選ぶ', () => {
    const profile = {
      ...emptyCandidateProfile(),
      age: '42歳',
      experience_years: '',
      qualifications: '看護師',
      employment_status: '就業中',
    };
    const [type, text] = matchPattern(profile, patterns);
    expect(type).toBe('D_就業中');
    expect(text).toContain('現在も臨床');
  });

  it('feature_rotation_index でローテーション', () => {
    const profile = {
      ...emptyCandidateProfile(),
      age: '44歳',
      experience_years: '10年以上',
      employment_status: '就業中',
      qualifications: '看護師',
    };
    const [, text0] = matchPattern(profile, patterns, [], 0);
    const [, text1] = matchPattern(profile, patterns, [], 1);
    expect(text0).toContain('利用者様');
    expect(text1).toContain('きめ細かなケア');
  });

  it('パターン不一致は例外', () => {
    const profile = {
      ...emptyCandidateProfile(),
      age: '30歳',
      experience_years: '3年',
      employment_status: '就業中',
    };
    const sparse: Pattern[] = [{ pattern_type: 'A', template_text: 'x', feature_variations: [] }];
    expect(() => matchPattern(profile, sparse)).toThrow();
  });
});
