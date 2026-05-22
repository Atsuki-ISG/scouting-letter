/**
 * コメディカル.com 送信制約に合わせたテキスト整形。
 *
 * 制約（2026-05-21 オペレーター報告）:
 *   1. 6桁以上の連続数字（半角・全角）は送信不可
 *   2. http から始まるアルファベット文字列（URL）は送信不可
 *   3. ハイフン/ダッシュ系の記号は送信不可:
 *        - U+002D HYPHEN-MINUS         "-"
 *        - U+FF0D FULLWIDTH HYPHEN     "－"
 *        - U+2010 HYPHEN                "‐"
 *        - U+2011 NON-BREAKING HYPHEN   "‑"
 *        - U+2012 FIGURE DASH           "‒"
 *        - U+2013 EN DASH               "–"
 *        - U+2014 EM DASH               "—"
 *        - U+2015 HORIZONTAL BAR        "―"
 *        - U+2212 MINUS SIGN            "−"
 *      ※ カタカナ長音「ー」（U+30FC）は送信OK（別文字扱い）
 *
 * 方針:
 *   - ハイフン/ダッシュ系は削除
 *   - URL は削除＋warning に積む
 *   - 6桁数字は自動修正不能なので warning のみ。テンプレート側で書き直しを促す。
 *
 * @typedef {object} SanitizeResult
 * @property {string} text サニタイズ後のテキスト
 * @property {string[]} warnings 自動修正できなかった違反箇所のメッセージ
 * @property {object} counts 修正カウント { hyphen: number, url: number, longDigits: number }
 */

// ハイフン/ダッシュ系。カタカナ長音「ー」(U+30FC) は対象外。
// U+002D, U+FF0D, U+2010-U+2015, U+2212
const HYPHEN_RE = /[-－‐-―−]/g;
const URL_RE = /https?:\/\/[A-Za-z0-9._\-\/?=&%#~+]+/g;
const LONG_DIGITS_RE = /[0-9０-９]{6,}/g;

/**
 * テキストをコメディカル.com 送信可能形にサニタイズする。
 * @param {string} text
 * @returns {SanitizeResult}
 */
export function sanitizeForComedical(text) {
  if (typeof text !== 'string') {
    return { text, warnings: [], counts: { hyphen: 0, url: 0, longDigits: 0 } };
  }

  const counts = { hyphen: 0, url: 0, longDigits: 0 };
  const warnings = [];

  // 1. URL を検出して削除
  const urls = text.match(URL_RE);
  if (urls) {
    counts.url = urls.length;
    for (const u of urls) warnings.push(`URL を削除: "${u}"`);
  }
  let result = text.replace(URL_RE, '');

  // 2. 6桁以上の数字を検出（修正はしない）
  const digits = result.match(LONG_DIGITS_RE);
  if (digits) {
    counts.longDigits = digits.length;
    for (const d of digits) warnings.push(`6桁以上の数字（要手動修正）: "${d}"`);
  }

  // 3. ハイフン「-」「－」を削除（長音「ー」U+30FC は対象外）
  const hyphenMatches = result.match(HYPHEN_RE);
  if (hyphenMatches) counts.hyphen = hyphenMatches.length;
  result = result.replace(HYPHEN_RE, '');

  return { text: result, warnings, counts };
}

/**
 * Pattern[] の全テキスト要素をサニタイズし、結果と総警告を返す。
 * @param {import('../src/shared/pattern-matcher').Pattern[]} patterns
 * @returns {{ patterns: import('../src/shared/pattern-matcher').Pattern[], warnings: string[], totals: object }}
 */
export function sanitizePatterns(patterns) {
  const out = [];
  const warnings = [];
  const totals = { hyphen: 0, url: 0, longDigits: 0 };
  for (const p of patterns) {
    const t = sanitizeForComedical(p.template_text);
    addTotals(totals, t.counts);
    for (const w of t.warnings) warnings.push(`[型${p.pattern_type}${p.employment_variant ? '/' + p.employment_variant : ''}] ${w}`);
    const features = (p.feature_variations || []).map((f) => {
      const r = sanitizeForComedical(f);
      addTotals(totals, r.counts);
      for (const w of r.warnings) warnings.push(`[型${p.pattern_type} 特色] ${w}`);
      return r.text;
    });
    out.push({ ...p, template_text: t.text, feature_variations: features });
  }
  return { patterns: out, warnings, totals };
}

/**
 * Template[] の body をサニタイズ。
 * @param {Array<{type: string, body: string}>} templates
 */
export function sanitizeTemplates(templates) {
  const out = [];
  const warnings = [];
  const totals = { hyphen: 0, url: 0, longDigits: 0 };
  for (const t of templates) {
    const r = sanitizeForComedical(t.body);
    addTotals(totals, r.counts);
    for (const w of r.warnings) warnings.push(`[テンプレ ${t.type}] ${w}`);
    out.push({ ...t, body: r.text });
  }
  return { templates: out, warnings, totals };
}

function addTotals(dst, src) {
  dst.hyphen += src.hyphen;
  dst.url += src.url;
  dst.longDigits += src.longDigits;
}
