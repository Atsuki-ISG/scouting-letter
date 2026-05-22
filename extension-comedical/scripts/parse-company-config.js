/**
 * companies/[会社名]/{recipes,templates}.md を拡張バンドル用 JSON に変換する。
 *
 * 想定フォーマット（2形式に対応）:
 *
 *   単一職種形式（茅ヶ崎徳洲会など）:
 *     recipes.md: `## 型はめパターン` 以下に `### 型{X}: ...` セクション
 *     templates.md: `### 〇〇 正職員 初回テンプレート` セクション
 *
 *   複数職種形式（佐藤病院・an訪問看護など）:
 *     recipes.md: `### 型はめパターン（{職種}）` を職種ごとに配置、その下に `#### 型{X}: ...`
 *     templates.md: `## {職種}_正社員_初回テンプレート` 等（職種接頭辞付き）
 *     → jobFilter（例: "看護師"）で該当職種のみ抽出
 *
 *   共通:
 *     - fenced code block → template_text / body
 *     - `就業中:` / `離職中:` の下にそれぞれ fenced block → employment_variant 付きで分離
 *     - `特色バリエーション:` の下の bullet list → feature_variations
 *
 * @typedef {import('../src/shared/pattern-matcher').Pattern} Pattern
 * @typedef {object} Template
 * @property {string} type
 * @property {string} body
 */

/**
 * recipes.md から型はめパターンを抽出する。
 * @param {string} md
 * @param {string | null} jobFilter 複数職種形式の場合、抽出対象の職種名（部分一致、例: "看護師"）。null なら全職種。
 * @returns {Pattern[]}
 */
export function parsePatternsFromRecipes(md, jobFilter = null) {
  const result = [];

  // 複数職種形式: ### 型はめパターン（{職種}）
  const jobScopedRe = /^###\s*型はめパターン[（(]([^）)]+)[）)]/gm;
  const jobScopedSections = [];
  let jm;
  while ((jm = jobScopedRe.exec(md)) !== null) {
    jobScopedSections.push({ job: jm[1], start: jm.index, headerEnd: jm.index + jm[0].length });
  }

  if (jobScopedSections.length > 0) {
    // 複数職種形式: 各「型はめパターン（職種）」の範囲を次の同レベル(##)/上位(###)見出しまでに区切る。
    // `####` は `###` にマッチさせないため `(?!#)` で1文字先読みを禁止する。
    // `### 型A:` のような型本体は範囲区切りにしないため `(?!型[A-Z0-9])` で除外。
    for (let i = 0; i < jobScopedSections.length; i++) {
      const startSearch = jobScopedSections[i].headerEnd;
      const nextSameLevelRe = /^##(?!#)\s|^###(?!#)\s*(?!型[A-Z0-9])/gm;
      nextSameLevelRe.lastIndex = startSearch;
      let nextIdx = md.length;
      let nm;
      while ((nm = nextSameLevelRe.exec(md)) !== null) {
        if (nm.index <= startSearch) continue;
        nextIdx = nm.index;
        break;
      }
      jobScopedSections[i].end = nextIdx;
    }
    for (const js of jobScopedSections) {
      if (jobFilter && !js.job.includes(jobFilter)) continue;
      const body = md.slice(js.headerEnd, js.end);
      result.push(...extractPatternsFromBody(body));
    }
    return result;
  }

  // 単一形式: ## 型はめパターン
  const patternSectionIdx = md.search(/^## 型はめパターン/m);
  if (patternSectionIdx === -1) return [];
  const body = md.slice(patternSectionIdx);
  result.push(...extractPatternsFromBody(body));
  return result;
}

/**
 * 「型はめパターン」セクションの本文から `### 型X` または `#### 型X` 単位でパターンを抽出する。
 * @param {string} body
 * @returns {Pattern[]}
 */
function extractPatternsFromBody(body) {
  const result = [];
  const sectionRe = /^#{3,4}\s*型([A-Z0-9]+)(?:[:：]\s*([^\n]+))?/gm;
  const sections = [];
  let m;
  while ((m = sectionRe.exec(body)) !== null) {
    sections.push({ type: m[1], start: m.index, headerEnd: m.index + m[0].length });
  }
  for (let i = 0; i < sections.length; i++) {
    sections[i].end = i + 1 < sections.length ? sections[i + 1].start : body.length;
  }

  for (const sec of sections) {
    const chunk = body.slice(sec.headerEnd, sec.end);
    const features = extractFeatureVariations(chunk);

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
 * @param {string | null} jobFilter 見出しに含めるべき職種名（例: "看護師"）。指定時は header に含まないテンプレートを除外。
 * @returns {Template[]}
 */
export function parseTemplatesFromTemplates(md, jobFilter = null) {
  const result = [];
  // H2 (##) or H3 (###) — 会社によって見出しレベルが違うので両対応
  const sectionRe = /^#{2,3}\s*([^\n]+?)(初回|再送|お気に入り)テンプレート[^\n]*$/gm;
  const sections = [];
  let m;
  while ((m = sectionRe.exec(md)) !== null) {
    sections.push({
      kind: m[2], // 初回|再送|お気に入り
      header: m[1].trim(), // 例: "看護師 正職員 " / "看護師_正社員_"
      start: m.index,
      headerEnd: m.index + m[0].length,
    });
  }
  for (let i = 0; i < sections.length; i++) {
    sections[i].end = i + 1 < sections.length ? sections[i + 1].start : md.length;
  }

  for (const sec of sections) {
    if (jobFilter && !sec.header.includes(jobFilter)) continue;
    const chunk = md.slice(sec.headerEnd, sec.end);
    // 本文: の下の fenced block を優先。なければセクション内最初の fenced block を採用
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
