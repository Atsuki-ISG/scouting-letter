/**
 * companies/[会社名]/{recipes,templates}.md を拡張バンドル用 JSON に変換する。
 *
 * 想定フォーマット（他社も合わせて揃える必要あり）:
 *
 *   recipes.md: `## 型はめパターン` 以下に `### 型{X}: ...` セクション。
 *     各セクション内:
 *       - fenced code block → template_text
 *       - `就業中:` / `離職中:` の下にそれぞれ fenced block → employment_variant 付きで分離
 *       - `特色バリエーション:` の下の bullet list → feature_variations
 *
 *   templates.md: `### 〇〇 正職員 初回テンプレート` / `再送テンプレート` セクション。
 *     `本文:` の下の fenced code block → body
 *     `件名:` は無視（WelMe等はsubjectフィールドなし）
 *
 * @typedef {import('../src/shared/pattern-matcher').Pattern} Pattern
 * @typedef {object} Template
 * @property {string} type
 * @property {string} body
 */

/**
 * recipes.md から型はめパターンを抽出する。
 * @param {string} md
 * @returns {Pattern[]}
 */
export function parsePatternsFromRecipes(md) {
  const result = [];
  // Find the 型はめパターン section
  const patternSectionIdx = md.search(/^## 型はめパターン/m);
  if (patternSectionIdx === -1) return [];
  const body = md.slice(patternSectionIdx);

  // Split by ### 型X: headers
  const sectionRe = /^###\s*型([A-Z0-9]+)(?:[:：]\s*([^\n]+))?/gm;
  const sections = [];
  let m;
  while ((m = sectionRe.exec(body)) !== null) {
    sections.push({ type: m[1], start: m.index, headerEnd: m.index + m[0].length });
  }
  // Attach end positions
  for (let i = 0; i < sections.length; i++) {
    sections[i].end = i + 1 < sections.length ? sections[i + 1].start : body.length;
  }

  for (const sec of sections) {
    const chunk = body.slice(sec.headerEnd, sec.end);
    const features = extractFeatureVariations(chunk);

    // Look for employment-variant subsections (就業中: / 離職中:)
    const variantRe = /^(就業中|離職中)\s*[:：]\s*$/gm;
    const variantMatches = [...chunk.matchAll(variantRe)];
    if (variantMatches.length > 0) {
      for (const vm of variantMatches) {
        const startAfterLabel = vm.index + vm[0].length;
        const block = extractFirstCodeBlock(chunk.slice(startAfterLabel));
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

    // No variants → single code block
    const block = extractFirstCodeBlock(chunk);
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

/**
 * templates.md から初回/再送テンプレートの本文を抽出する。
 * @param {string} md
 * @returns {Template[]}
 */
export function parseTemplatesFromTemplates(md) {
  const result = [];
  // H2 (##) or H3 (###) — 会社によって見出しレベルが違うので両対応
  const sectionRe = /^#{2,3}\s*([^\n]+?)(初回|再送|お気に入り)テンプレート[^\n]*$/gm;
  const sections = [];
  let m;
  while ((m = sectionRe.exec(md)) !== null) {
    sections.push({
      kind: m[2], // 初回|再送|お気に入り
      header: m[1].trim(), // 例: "看護師 正職員 "
      start: m.index,
      headerEnd: m.index + m[0].length,
    });
  }
  for (let i = 0; i < sections.length; i++) {
    sections[i].end = i + 1 < sections.length ? sections[i + 1].start : md.length;
  }

  for (const sec of sections) {
    const chunk = md.slice(sec.headerEnd, sec.end);
    // 本文: の下の fenced block
    const bodyIdx = chunk.search(/^本文\s*[:：]\s*$/m);
    const scope = bodyIdx === -1 ? chunk : chunk.slice(bodyIdx);
    const body = extractFirstCodeBlock(scope);
    if (body === null) continue;

    // Map header words into canonical type key
    const isSeishain = /正職員|正社員/.test(sec.header);
    const isPart = /パート|非常勤/.test(sec.header);
    const employment = isSeishain ? '正社員' : isPart ? 'パート' : '正社員';
    const type = `${employment}_${sec.kind}`;

    result.push({ type, body: body.trim() });
  }
  return result;
}

/**
 * fenced code block (` ``` ... ``` `) の最初の中身を抽出する。
 * @param {string} text
 * @returns {string | null}
 */
function extractFirstCodeBlock(text) {
  const re = /```[^\n]*\n([\s\S]*?)\n?```/m;
  const m = text.match(re);
  return m ? m[1] : null;
}

/**
 * `特色バリエーション:` の下の bullet list を抽出する。
 * @param {string} chunk
 * @returns {string[]}
 */
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
