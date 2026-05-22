/**
 * companies/[会社名]/{recipes,templates}.md を読んで拡張バンドル用の
 * JSON に変換するパーサのテスト。
 *
 * 入力は実際の chigasaki-tokushukai のファイルをフィクスチャに使う。
 * 他社も同じフォーマットに揃えることが前提（parse は厳格）。
 */

import { describe, expect, it } from 'vitest';
import {
  parsePatternsFromRecipes,
  parseTemplatesFromTemplates,
} from '../scripts/parse-company-config.js';

const SAMPLE_RECIPES = `# レシピ

## 型はめパターン

### 型A: 豊富な経験への期待

対象: 経験10年+ / 40代〜×経験6年+

\`\`\`
10年以上のご経歴を拝見し、{特色}当院において大きな力になると考えています。
\`\`\`

特色バリエーション:
- 急性期から地域包括ケアまで幅広い
- 救急搬送の落ち着いた環境

### 型B1: 確かな経験×特色

対象: 経験6〜9年

\`\`\`
看護師として{N}年のご経験、{特色}当院において大きな力になると考えています。
\`\`\`

特色バリエーション:
- 2病棟で幅広く

### 型D: 経験前提

対象: 40代〜 × 経験未入力

就業中:
\`\`\`
現在もご活躍中の経験、{特色}活かしていただけます。
\`\`\`

離職中:
\`\`\`
これまで培われた経験は、{特色}活かしていただけます。
\`\`\`

特色バリエーション:
- 幅広い患者様に対応する

### 型G: 在学中

\`\`\`
ご在学中の挑戦を、{特色}期待しています。
\`\`\`

特色バリエーション:
- 丁寧な研修体制で
`;

describe('parsePatternsFromRecipes', () => {
  it('型A/B1/D(就業中,離職中)/G を抽出', () => {
    const patterns = parsePatternsFromRecipes(SAMPLE_RECIPES);
    const types = patterns.map((p) => [p.pattern_type, p.employment_variant || null]);
    expect(types).toEqual([
      ['A', null],
      ['B1', null],
      ['D', '就業中'],
      ['D', '離職中'],
      ['G', null],
    ]);
  });

  it('template_text を正しく拾う', () => {
    const patterns = parsePatternsFromRecipes(SAMPLE_RECIPES);
    const a = patterns.find((p) => p.pattern_type === 'A');
    expect(a?.template_text).toContain('10年以上のご経歴を拝見し');
    expect(a?.template_text).toContain('{特色}');
  });

  it('feature_variations を bullet list から抽出', () => {
    const patterns = parsePatternsFromRecipes(SAMPLE_RECIPES);
    const a = patterns.find((p) => p.pattern_type === 'A');
    expect(a?.feature_variations).toEqual([
      '急性期から地域包括ケアまで幅広い',
      '救急搬送の落ち着いた環境',
    ]);
  });

  it('型D の 就業中/離職中 variant は同じ feature_variations を共有する', () => {
    const patterns = parsePatternsFromRecipes(SAMPLE_RECIPES);
    const dOn = patterns.find((p) => p.pattern_type === 'D' && p.employment_variant === '就業中');
    const dOff = patterns.find((p) => p.pattern_type === 'D' && p.employment_variant === '離職中');
    expect(dOn?.feature_variations).toEqual(['幅広い患者様に対応する']);
    expect(dOff?.feature_variations).toEqual(['幅広い患者様に対応する']);
  });

  it('型G は feature_variations があれば持つ', () => {
    const patterns = parsePatternsFromRecipes(SAMPLE_RECIPES);
    const g = patterns.find((p) => p.pattern_type === 'G');
    expect(g?.feature_variations).toEqual(['丁寧な研修体制で']);
  });
});

const SAMPLE_TEMPLATES = `# テンプレート

## テンプレート

### 看護師 正職員 初回テンプレート

件名:
\`\`\`
【茅ヶ崎】お試し
\`\`\`

本文:
\`\`\`
はじめまして、〇〇病院の採用担当です。

{ここに生成した文章を挿入}

＜募集要項＞
...
\`\`\`

### 看護師 正職員 再送テンプレート

本文:
\`\`\`
度々のご連絡失礼いたします。

{ここに生成した文章を挿入}

ご検討のほどよろしくお願いします。
\`\`\`
`;

describe('parseTemplatesFromTemplates', () => {
  it('初回/再送の本文を抽出', () => {
    const templates = parseTemplatesFromTemplates(SAMPLE_TEMPLATES);
    expect(templates).toHaveLength(2);
    expect(templates[0].type).toBe('正社員_初回');
    expect(templates[0].body).toContain('はじめまして、〇〇病院');
    expect(templates[0].body).toContain('{ここに生成した文章を挿入}');
    expect(templates[1].type).toBe('正社員_再送');
    expect(templates[1].body).toContain('度々のご連絡');
  });

  it('件名は無視して本文のみ抽出', () => {
    const templates = parseTemplatesFromTemplates(SAMPLE_TEMPLATES);
    expect(templates[0].body).not.toContain('お試し');
  });
});

// ---------------------------------------------------------------------------
// 複数職種形式（佐藤病院・an訪問看護など）
// ---------------------------------------------------------------------------

const SAMPLE_RECIPES_MULTIJOB = `# レシピ

## 共通ルール

- 全職種共通のルール

## 看護師

### 当院の特色（看護師向け）

- 病床数116

### 型はめパターン（看護師）

#### 型A: 豊富な経験

対象: 経験10年+

\`\`\`
看護師として10年以上のご経歴、{特色}活かせます。
\`\`\`

特色バリエーション:
- ケアミックスで幅広い
- 落ち着いた急性期

#### 型B1: 経験×特色

対象: 経験6〜9年

\`\`\`
看護師として{N}年、{特色}活かせます。
\`\`\`

特色バリエーション:
- 多職種連携

### AI生成ガイド（看護師）

| 表 |

## リハビリ職（PT/OT）

### 型はめパターン（リハビリ職）

#### 型A: 豊富な経験

\`\`\`
PTとして10年以上のご経歴、{特色}活かせます。
\`\`\`

特色バリエーション:
- 急性期から在宅まで
`;

describe('parsePatternsFromRecipes (複数職種形式)', () => {
  it('jobFilter="看護師" で看護師のみ抽出', () => {
    const patterns = parsePatternsFromRecipes(SAMPLE_RECIPES_MULTIJOB, '看護師');
    const types = patterns.map((p) => p.pattern_type);
    expect(types).toEqual(['A', 'B1']);
    expect(patterns[0].template_text).toContain('看護師として10年以上');
    expect(patterns[0].feature_variations).toEqual(['ケアミックスで幅広い', '落ち着いた急性期']);
  });

  it('jobFilter=null で全職種抽出', () => {
    const patterns = parsePatternsFromRecipes(SAMPLE_RECIPES_MULTIJOB, null);
    expect(patterns).toHaveLength(3);
  });

  it('jobFilter="リハビリ" でリハビリ職のみ抽出', () => {
    const patterns = parsePatternsFromRecipes(SAMPLE_RECIPES_MULTIJOB, 'リハビリ');
    expect(patterns).toHaveLength(1);
    expect(patterns[0].template_text).toContain('PTとして10年以上');
  });

  it('看護師セクションがリハビリ職の型を巻き込まない', () => {
    const patterns = parsePatternsFromRecipes(SAMPLE_RECIPES_MULTIJOB, '看護師');
    for (const p of patterns) {
      expect(p.template_text).not.toContain('PTとして');
    }
  });
});

const SAMPLE_TEMPLATES_MULTIJOB = `# テンプレート

## 看護師_正社員_初回テンプレート

\`\`\`
はじめまして、佐藤病院の影山です。
{ここに生成した文章を挿入}
\`\`\`

## 看護師_正社員_再送テンプレート

\`\`\`
度々のご連絡失礼します。
{ここに生成した文章を挿入}
\`\`\`

## PT_正社員_初回テンプレート

\`\`\`
はじめまして、PT用テンプレート。
{ここに生成した文章を挿入}
\`\`\`

## OT_正社員_初回テンプレート

\`\`\`
はじめまして、OT用テンプレート。
{ここに生成した文章を挿入}
\`\`\`
`;

describe('parseTemplatesFromTemplates (職種フィルタ)', () => {
  it('jobFilter="看護師" で看護師のテンプレートのみ抽出', () => {
    const templates = parseTemplatesFromTemplates(SAMPLE_TEMPLATES_MULTIJOB, '看護師');
    expect(templates).toHaveLength(2);
    expect(templates[0].type).toBe('正社員_初回');
    expect(templates[0].body).toContain('佐藤病院の影山');
    expect(templates[1].type).toBe('正社員_再送');
  });

  it('jobFilter=null だと全テンプレート抽出', () => {
    const templates = parseTemplatesFromTemplates(SAMPLE_TEMPLATES_MULTIJOB, null);
    expect(templates).toHaveLength(4);
  });

  it('PT/OT は jobFilter="看護師" で除外される', () => {
    const templates = parseTemplatesFromTemplates(SAMPLE_TEMPLATES_MULTIJOB, '看護師');
    for (const t of templates) {
      expect(t.body).not.toContain('PT用');
      expect(t.body).not.toContain('OT用');
    }
  });
});
