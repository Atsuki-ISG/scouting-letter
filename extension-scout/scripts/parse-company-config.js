/**
 * companies/[会社名]/{recipes,templates}.md を拡張バンドル用 JSON に変換する。
 *
 * 複数職種対応（1つの会社に看護師＋管理栄養士など）。
 *
 * recipes.md 解析戦略:
 *   パターン1（多職種）: H2 `## 看護師` / `## 管理栄養士` で職種スコープを切り、
 *                       各スコープ内に H3 `### 型はめパターン(xxx)` を持つ形。
 *                       型定義は H4 `#### 型X: ...`。
 *   パターン2（単一職種・既存）: H2 `## 型はめパターン` をトップレベルで持ち、
 *                              その下に H3 `### 型X:` を並べる形（chigasaki互換）。
 *                              occupation は 'default' で生成。
 *
 * templates.md 解析戦略:
 *   H2/H3 で `〇〇 初回テンプレート` / `〇〇 再送テンプレート` / `〇〇 お気に入り(テンプレート)?`
 *   `〇〇` から職種を抽出（「正社員」「正職員」「パート」「非常勤」の手前）。
 *   お気に入りセクションは「テンプレート」接尾辞が無くても許容。
 *   本文: 直後の `本文:` ラベル配下の fenced code block（無ければ最初の fenced block）。
 *
 * @typedef {import('../src/shared/pattern-matcher').Pattern} Pattern
 * @typedef {object} BundledTemplate
 * @property {string} type
 * @property {string} body
 * @typedef {object} ParsedOccupation
 * @property {string} id
 * @property {string} displayName
 * @property {string[]} matchQualifications
 * @property {Pattern[]} patterns
 * @property {BundledTemplate[]} templates
 */

/** 職種名の正規化: 表示名 → (id, canonical表示, 資格マッチキーワード) */
const OCCUPATION_CANON = [
  { id: 'nurse', display: '看護師', keywords: ['看護師', '准看護師', '病棟看護'], matchQualifications: ['看護師', '准看護師'] },
  { id: 'dietitian', display: '管理栄養士', keywords: ['管理栄養士', '栄養士'], matchQualifications: ['管理栄養士'] },
  { id: 'pt', display: '理学療法士', keywords: ['理学療法士'], matchQualifications: ['理学療法士'] },
  { id: 'ot', display: '作業療法士', keywords: ['作業療法士'], matchQualifications: ['作業療法士'] },
  { id: 'st', display: '言語聴覚士', keywords: ['言語聴覚士'], matchQualifications: ['言語聴覚士'] },
  { id: 'rehab', display: 'リハビリ職', keywords: ['リハビリ職'], matchQualifications: ['理学療法士', '作業療法士', '言語聴覚士'] },
  { id: 'counselor', display: '相談支援専門員', keywords: ['相談支援専門員'], matchQualifications: ['相談支援専門員'] },
  { id: 'caregiver', display: '介護職', keywords: ['介護職', '介護福祉士'], matchQualifications: ['介護福祉士'] },
  { id: 'medical_clerk', display: '医療事務', keywords: ['医療事務'], matchQualifications: ['医療事務'] },
];

function canonicalizeOccupation(rawName) {
  if (!rawName) return { id: 'default', display: 'default', matchQualifications: [] };
  const s = String(rawName).trim();
  for (const o of OCCUPATION_CANON) {
    for (const k of o.keywords) {
      if (s.includes(k)) return { id: o.id, display: o.display, matchQualifications: o.matchQualifications };
    }
  }
  return { id: s.replace(/[\s\/（）()]/g, '_'), display: s, matchQualifications: [s] };
}

/**
 * recipes.md から職種別のパターンを抽出する。
 * @param {string} md
 * @returns {{ id: string, displayName: string, matchQualifications: string[], patterns: Pattern[] }[]}
 */
export function parseOccupationsFromRecipes(md) {
  const occupations = [];

  const h3Matches = [...md.matchAll(/^###\s*型はめパターン[^\n]*$/gm)];
  if (h3Matches.length > 0) {
    for (const h3m of h3Matches) {
      const parentH2 = findPreviousHeading(md, h3m.index, 2);
      const rawName = parentH2 ? parentH2.title : 'default';
      const canon = canonicalizeOccupation(rawName);

      const sectionStart = h3m.index + h3m[0].length;
      const sectionEnd = findNextHeadingPos(md, sectionStart, [2, 3]);
      const chunk = md.slice(sectionStart, sectionEnd);

      const patterns = parsePatternsFromChunk(chunk, 4);
      occupations.push({
        id: canon.id,
        displayName: canon.display,
        matchQualifications: canon.matchQualifications,
        patterns,
      });
    }
    return dedupeOccupations(occupations);
  }

  const h2m = md.match(/^##\s*型はめパターン[^\n]*$/m);
  if (h2m) {
    const sectionStart = md.indexOf(h2m[0]) + h2m[0].length;
    const sectionEnd = findNextHeadingPos(md, sectionStart, [2]);
    const chunk = md.slice(sectionStart, sectionEnd);
    const patterns = parsePatternsFromChunk(chunk, 3);
    occupations.push({
      id: 'default',
      displayName: 'default',
      matchQualifications: [],
      patterns,
    });
  }

  return occupations;
}

/**
 * templates.md から職種別の初回/再送/お気に入りテンプレを抽出する。
 * @param {string} md
 * @returns {{ occupationRawName: string, type: string, body: string }[]}
 */
export function parseTemplatesFromTemplates(md) {
  const result = [];
  const sectionRe = /^#{2,3}\s*([^\n]*?)(初回|再送|お気に入り)(?:テンプレート)?[^\n]*$/gm;
  const sections = [];
  let m;
  while ((m = sectionRe.exec(md)) !== null) {
    sections.push({
      kind: m[2],
      header: m[1].trim(),
      start: m.index,
      headerEnd: m.index + m[0].length,
    });
  }
  for (let i = 0; i < sections.length; i++) {
    sections[i].end = i + 1 < sections.length ? sections[i + 1].start : md.length;
  }

  for (const sec of sections) {
    const chunk = md.slice(sec.headerEnd, sec.end);
    const bodyIdx = chunk.search(/^本文\s*[:：]\s*$/m);
    const scope = bodyIdx === -1 ? chunk : chunk.slice(bodyIdx);
    const body = extractFirstCodeBlock(scope);
    if (body === null) continue;

    const isSeishain = /正職員|正社員/.test(sec.header);
    const isPart = /パート|非常勤/.test(sec.header);
    const employment = isSeishain ? '正社員' : isPart ? 'パート' : '正社員';
    const occRaw = sec.header.replace(/(正職員|正社員|パート|非常勤).*$/, '').trim();
    const type = `${employment}_${sec.kind}`;

    result.push({ occupationRawName: occRaw, type, body: body.trim() });
  }
  return result;
}

/**
 * recipes + templates を束ねて、会社の全 Occupation を返す。
 *
 * マージ規則:
 *   - recipes が 'default' のみ（職種スコープなし）で templates が名前付き職種を持つ場合:
 *     default の patterns を全ての名前付き職種に broadcast する。
 *   - recipes に明示的な職種スコープがある場合:
 *     templates と id で突き合わせる。どちらか片方にしかない職種も含める。
 *   - パターンが無い職種は、兄弟の「リハビリ職」がいれば流用する（an対応）。
 *
 * @param {string} recipesMd
 * @param {string} templatesMd
 * @returns {ParsedOccupation[]}
 */
export function parseOccupations(recipesMd, templatesMd) {
  const recipeOccs = parseOccupationsFromRecipes(recipesMd);
  const tmplRows = parseTemplatesFromTemplates(templatesMd);

  const templatesByOccId = new Map();
  for (const t of tmplRows) {
    const canon = canonicalizeOccupation(t.occupationRawName);
    if (!templatesByOccId.has(canon.id)) {
      templatesByOccId.set(canon.id, { canon, templates: [] });
    }
    templatesByOccId.get(canon.id).templates.push({ type: t.type, body: t.body });
  }

  // ケースA: recipes が 'default' のみ
  if (recipeOccs.length === 1 && recipeOccs[0].id === 'default') {
    const defaultPatterns = recipeOccs[0].patterns;
    const namedTmpls = [...templatesByOccId.entries()].filter(([id]) => id !== 'default');

    if (namedTmpls.length === 0) {
      return [
        {
          id: 'default',
          displayName: 'default',
          matchQualifications: [],
          patterns: defaultPatterns,
          templates: templatesByOccId.get('default')?.templates || [],
        },
      ];
    }
    return namedTmpls.map(([id, { canon, templates }]) => ({
      id,
      displayName: canon.display,
      matchQualifications: canon.matchQualifications,
      patterns: defaultPatterns,
      templates,
    }));
  }

  // ケースB: recipes が明示的な職種スコープ
  const allIds = new Set([
    ...recipeOccs.map((o) => o.id),
    ...templatesByOccId.keys(),
  ]);
  allIds.delete('default');

  const merged = [];
  const rehab = recipeOccs.find((o) => o.id === 'rehab');
  for (const id of allIds) {
    const r = recipeOccs.find((o) => o.id === id);
    const t = templatesByOccId.get(id);
    const displayName = r?.displayName || t?.canon.display || id;
    const matchQualifications = (r && r.matchQualifications.length > 0)
      ? r.matchQualifications
      : (t ? t.canon.matchQualifications : []);

    // patterns: 本人 > rehab（PT/OT/ST用）
    let patterns = r?.patterns || [];
    if (patterns.length === 0 && rehab && ['pt', 'ot', 'st'].includes(id)) {
      patterns = rehab.patterns;
    }

    merged.push({
      id,
      displayName,
      matchQualifications,
      patterns,
      templates: t?.templates || [],
    });
  }

  // テンプレ無しの職種は使えないので除外（rehab は PT/OT に流用済み）
  return merged.filter((o) => o.templates.length > 0);
}

// ---------------------------------------------------------------------------
// 内部ヘルパー
// ---------------------------------------------------------------------------

function findPreviousHeading(md, pos, level) {
  const re = new RegExp(`^#{${level}}\\s+([^\\n]+)$`, 'gm');
  let lastMatch = null;
  let m;
  while ((m = re.exec(md)) !== null) {
    if (m.index >= pos) break;
    lastMatch = { title: m[1].trim(), position: m.index };
  }
  return lastMatch;
}

function findNextHeadingPos(md, startPos, levels) {
  const levelRe = levels.map((l) => `#{${l}}`).join('|');
  const re = new RegExp(`^(?:${levelRe})\\s+[^\\n]+$`, 'gm');
  re.lastIndex = startPos;
  const m = re.exec(md);
  return m ? m.index : md.length;
}

function parsePatternsFromChunk(chunk, headingLevel) {
  const sectionRe = new RegExp(`^#{${headingLevel}}\\s*型([A-Z0-9]+)(?:[:：]\\s*([^\\n]+))?`, 'gm');
  const sections = [];
  let m;
  while ((m = sectionRe.exec(chunk)) !== null) {
    sections.push({ type: m[1], start: m.index, headerEnd: m.index + m[0].length });
  }
  for (let i = 0; i < sections.length; i++) {
    sections[i].end = i + 1 < sections.length ? sections[i + 1].start : chunk.length;
  }

  const result = [];
  for (const sec of sections) {
    const sub = chunk.slice(sec.headerEnd, sec.end);
    const features = extractFeatureVariations(sub);

    const variantRe = /^(就業中|離職中)\s*[:：]\s*$/gm;
    const variantMatches = [...sub.matchAll(variantRe)];
    if (variantMatches.length > 0) {
      for (const vm of variantMatches) {
        const startAfterLabel = vm.index + vm[0].length;
        const block = extractFirstCodeBlock(sub.slice(startAfterLabel));
        if (block !== null) {
          result.push({
            pattern_type: sec.type,
            employment_variant: vm[1],
            template_text: block.trim(),
            feature_variations: features,
          });
        }
      }
      continue;
    }

    const block = extractFirstCodeBlock(sub);
    if (block !== null) {
      result.push({
        pattern_type: sec.type,
        template_text: block.trim(),
        feature_variations: features,
      });
    }
  }
  return result;
}

function extractFirstCodeBlock(text) {
  const re = /```[^\n]*\n([\s\S]*?)\n?```/m;
  const m = text.match(re);
  return m ? m[1] : null;
}

function extractFeatureVariations(chunk) {
  const idx = chunk.search(/^特色バリエーション\s*[:：]\s*$/m);
  if (idx === -1) return [];
  const after = chunk.slice(idx);
  const endIdx = after.indexOf('\n\n', 1);
  const listScope = endIdx === -1 ? after : after.slice(0, endIdx);
  const items = [];
  const re = /^-\s+(.+)$/gm;
  let m;
  while ((m = re.exec(listScope)) !== null) {
    items.push(m[1].trim());
  }
  return items;
}

function dedupeOccupations(occs) {
  const byId = new Map();
  for (const o of occs) {
    if (byId.has(o.id)) {
      const existing = byId.get(o.id);
      existing.patterns.push(...o.patterns);
    } else {
      byId.set(o.id, { ...o, patterns: [...o.patterns] });
    }
  }
  return [...byId.values()];
}

// 旧互換
export function parsePatternsFromRecipes(md) {
  const occs = parseOccupationsFromRecipes(md);
  return occs.flatMap((o) => o.patterns);
}
