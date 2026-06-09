/**
 * コメディカル.com 送信制約に合わせたテキストサニタイザのテスト。
 */

import { describe, expect, it } from 'vitest';
import {
  sanitizeForComedical,
  sanitizePatterns,
  sanitizeTemplates,
} from '../scripts/sanitize-for-comedical.js';

describe('sanitizeForComedical', () => {
  it('半角ハイフン「-」を削除する', () => {
    const r = sanitizeForComedical('正職員 - 面談確約 -');
    expect(r.text).toBe('正職員  面談確約 ');
    expect(r.counts.hyphen).toBe(2);
  });

  it('全角ハイフン「－」を削除する', () => {
    const r = sanitizeForComedical('年収520万円－650万円');
    expect(r.text).toBe('年収520万円650万円');
    expect(r.counts.hyphen).toBe(1);
  });

  it('カタカナ長音「ー」（U+30FC）は削除しない', () => {
    const r = sanitizeForComedical('サポート/プリセプター/ホーム/メリット');
    expect(r.text).toBe('サポート/プリセプター/ホーム/メリット');
    expect(r.counts.hyphen).toBe(0);
  });

  it('水平バー「―」（U+2015）を削除する', () => {
    const r = sanitizeForComedical('絶対にしない――2024年に新看護部長が就任');
    expect(r.text).toBe('絶対にしない2024年に新看護部長が就任');
    expect(r.counts.hyphen).toBe(2);
  });

  it('EM DASH「—」(U+2014) と EN DASH「–」(U+2013) も削除する', () => {
    const r = sanitizeForComedical('AAA—BBB–CCC');
    expect(r.text).toBe('AAABBBCCC');
    expect(r.counts.hyphen).toBe(2);
  });

  it('MINUS SIGN「−」(U+2212) も削除する', () => {
    const r = sanitizeForComedical('1−2=−1');
    expect(r.counts.hyphen).toBe(2);
  });

  it('U+2010, U+2011, U+2012 も削除する', () => {
    const r = sanitizeForComedical('‐A‑B‒C');
    expect(r.text).toBe('ABC');
    expect(r.counts.hyphen).toBe(3);
  });

  it('http URL を削除し warning を返す', () => {
    const r = sanitizeForComedical('詳細は https://example.com/jobs?id=123 をご覧ください');
    expect(r.text).toBe('詳細は  をご覧ください');
    expect(r.counts.url).toBe(1);
    expect(r.warnings.some((w) => w.includes('https://example.com'))).toBe(true);
  });

  it('https URL も削除する', () => {
    const r = sanitizeForComedical('http://test.jp と https://test.com の両方');
    expect(r.counts.url).toBe(2);
    expect(r.text).not.toContain('http');
  });

  it('6桁以上の数字を検出し warning を返す（自動修正なし）', () => {
    const r = sanitizeForComedical('お問い合わせ番号: 1234567 までご連絡');
    expect(r.text).toContain('1234567'); // 削除はしない
    expect(r.counts.longDigits).toBe(1);
    expect(r.warnings.some((w) => w.includes('1234567'))).toBe(true);
  });

  it('全角6桁以上の数字も検出する', () => {
    const r = sanitizeForComedical('番号１２３４５６７');
    expect(r.counts.longDigits).toBe(1);
  });

  it('5桁以下の数字は検出しない', () => {
    const r = sanitizeForComedical('年収520万円、年間休日128日、5,400円/月');
    expect(r.counts.longDigits).toBe(0);
  });

  it('複数の違反が混在する場合の集計', () => {
    const r = sanitizeForComedical('正職員-面談確約- https://example.com 番号1234567');
    expect(r.counts.hyphen).toBe(2);
    expect(r.counts.url).toBe(1);
    expect(r.counts.longDigits).toBe(1);
  });

  it('HTMLエンティティ &quot; を素のダブルクオートへ戻す', () => {
    const r = sanitizeForComedical('&quot;プレミアムスカウト&quot;のご案内');
    expect(r.text).toBe('"プレミアムスカウト"のご案内');
  });

  it('&amp; &lt; &gt; &#39; &apos; をデコードする', () => {
    const r = sanitizeForComedical('A&amp;B &lt;tag&gt; it&#39;s &apos;ok&apos;');
    expect(r.text).toBe("A&B <tag> it's 'ok'");
  });

  it('二重エスケープ &amp;quot; を1段デコードして &quot; に戻す', () => {
    const r = sanitizeForComedical('&amp;quot;');
    expect(r.text).toBe('&quot;');
  });

  it('エンティティを含まないテキストは変化しない', () => {
    const r = sanitizeForComedical('年収520万円、年休128日');
    expect(r.text).toBe('年収520万円、年休128日');
  });

  it('違反なしのテキストはそのまま返す', () => {
    const text = 'サポート/プリセプター/年収520万円/年休128日';
    const r = sanitizeForComedical(text);
    expect(r.text).toBe(text);
    expect(r.counts.hyphen).toBe(0);
    expect(r.counts.url).toBe(0);
    expect(r.counts.longDigits).toBe(0);
    expect(r.warnings).toHaveLength(0);
  });
});

describe('sanitizePatterns', () => {
  it('全パターンの template_text と feature_variations をサニタイズする', () => {
    const patterns = [
      {
        pattern_type: 'A',
        template_text: '正職員-面談確約-で対応',
        feature_variations: ['ケアミックス-病院', 'プリセプター-1対1'],
      },
    ];
    const r = sanitizePatterns(patterns);
    expect(r.patterns[0].template_text).toBe('正職員面談確約で対応');
    expect(r.patterns[0].feature_variations).toEqual(['ケアミックス病院', 'プリセプター1対1']);
    expect(r.totals.hyphen).toBe(4);
  });
});

describe('sanitizeTemplates', () => {
  it('全テンプレートの body をサニタイズする', () => {
    const templates = [
      { type: '正社員_初回', body: '『病棟看護師(正職員)- 面談確約 -』' },
      { type: '正社員_再送', body: '改めてご連絡' },
    ];
    const r = sanitizeTemplates(templates);
    expect(r.templates[0].body).toBe('『病棟看護師(正職員) 面談確約 』');
    expect(r.templates[1].body).toBe('改めてご連絡');
    expect(r.totals.hyphen).toBe(2);
  });
});
