/**
 * コメディカル拡張のビルドスクリプト。
 *
 * 使い方:
 *   node scripts/build.js --company=chigasaki-tokushukai
 *
 * 出力: scout_extension/ （Chrome に「パッケージ化されていない拡張機能
 * として」読み込むディレクトリ）。
 * ジョブメドレー版 (../extension/) / WelMe版 (../extension-welme/) とは完全独立。
 */

import { build } from 'vite';
import { build as esbuild } from 'esbuild';
import { cpSync, readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import {
  renderBuildConfig,
  renderBundledCompanyConfig,
  patchManifest,
  zipName,
} from './build-config-inject.js';
import {
  parsePatternsFromRecipes,
  parseTemplatesFromTemplates,
} from './parse-company-config.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, '..');
const outDir = resolve(root, 'scout_extension');

const DISPLAY_NAMES = {
  'an-visiting-nurse': 'an訪問看護',
  'chigasaki-tokushukai': '茅ヶ崎徳洲会病院',
  // 必要に応じて追加:
  // 'ark-visiting-nurse': 'ARK訪問看護',
};

function parseArgs(argv) {
  const args = {};
  for (const a of argv.slice(2)) {
    const m = a.match(/^--([^=]+)=(.*)$/);
    if (m) args[m[1]] = m[2];
  }
  return args;
}

async function main() {
  const argv = parseArgs(process.argv);
  const companyId = argv.company || 'chigasaki-tokushukai';
  const builtAt = new Date().toISOString();
  const companyLabel = DISPLAY_NAMES[companyId] || companyId;
  const displayName = `${companyLabel} Scout (コメディカル)`;
  const buildOpts = { companyId, displayName, builtAt };

  console.log('=== Build options ===');
  console.log(buildOpts);

  // Step 0a: build-config.ts 書き換え（後で復元）
  const buildConfigPath = resolve(root, 'src/shared/build-config.ts');
  const originalBuildConfig = readFileSync(buildConfigPath, 'utf-8');
  writeFileSync(buildConfigPath, renderBuildConfig(buildOpts));

  // Step 0b: companies/[会社]/ を parse して bundled-company-config.ts 注入
  console.log('=== Parsing company config ===');
  const companiesDir = resolve(root, '..', 'companies', companyId);
  const bundledConfigPath = resolve(root, 'src/shared/bundled-company-config.ts');
  const originalBundledConfig = readFileSync(bundledConfigPath, 'utf-8');
  const bundledConfig = {
    companyId,
    displayName: companyLabel,
    patterns: [],
    templates: [],
  };
  const recipesPath = resolve(companiesDir, 'recipes.md');
  const templatesPath = resolve(companiesDir, 'templates.md');
  if (existsSync(recipesPath)) {
    bundledConfig.patterns = parsePatternsFromRecipes(readFileSync(recipesPath, 'utf-8'));
  } else {
    console.warn(`[warn] recipes.md not found at ${recipesPath}`);
  }
  if (existsSync(templatesPath)) {
    bundledConfig.templates = parseTemplatesFromTemplates(readFileSync(templatesPath, 'utf-8'));
  } else {
    console.warn(`[warn] templates.md not found at ${templatesPath}`);
  }
  console.log(
    `  patterns: ${bundledConfig.patterns.length}, templates: ${bundledConfig.templates.length}`
  );
  writeFileSync(bundledConfigPath, renderBundledCompanyConfig(bundledConfig));

  // Step 1: HTML (sidepanel) を Vite で
  console.log('=== Building sidepanel ===');
  await build({
    root,
    configFile: resolve(root, 'vite.config.ts'),
    build: { outDir, emptyOutDir: true },
  });

  // Step 2: content script
  console.log('=== Building content script ===');
  await esbuild({
    entryPoints: [resolve(root, 'src/content/index.ts')],
    bundle: true,
    format: 'iife',
    outfile: resolve(outDir, 'content.js'),
    target: 'es2022',
    minify: false,
    sourcemap: true,
  });

  // Step 3: service worker
  console.log('=== Building service worker ===');
  await esbuild({
    entryPoints: [resolve(root, 'src/background/service-worker.ts')],
    bundle: true,
    format: 'iife',
    outfile: resolve(outDir, 'service-worker.js'),
    target: 'es2022',
    minify: false,
    sourcemap: true,
  });

  // Step 4: manifest（name を displayName で上書き）
  console.log('=== Writing manifest ===');
  const manifest = JSON.parse(readFileSync(resolve(root, 'manifest.json'), 'utf-8'));
  const patched = patchManifest(manifest, buildOpts);
  writeFileSync(resolve(outDir, 'manifest.json'), JSON.stringify(patched, null, 2));

  // Step 5: icons
  cpSync(resolve(root, 'icons'), resolve(outDir, 'icons'), { recursive: true });

  // Restore dev defaults — working tree を汚さない
  writeFileSync(buildConfigPath, originalBuildConfig);
  writeFileSync(bundledConfigPath, originalBundledConfig);

  console.log('=== Build complete ===');
  console.log('Suggested zip name:', zipName(buildOpts));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
