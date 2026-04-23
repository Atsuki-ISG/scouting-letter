/**
 * Scout Assistant 統合拡張のビルドスクリプト。
 *
 * 使い方:
 *   node scripts/build.js --companies=nomura-hospital
 *   node scripts/build.js --companies=nomura-hospital,chigasaki-tokushukai
 *
 * 各会社IDは `companies/[id]/{recipes,templates}.md` を持つこと。
 * プラットフォーム（welme/comedical）は COMPANY_META マップで決定。
 *
 * 出力: scout_extension/
 * ジョブメドレー版 (../extension/) とは完全独立。
 * 既存の extension-welme / extension-comedical は温存しつつ、本ビルドで統合。
 */

import { build } from 'vite';
import { build as esbuild } from 'esbuild';
import { cpSync, readFileSync, writeFileSync, existsSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import {
  renderBuildConfig,
  renderBundledScoutConfig,
  patchManifest,
  zipName,
} from './build-config-inject.js';
import { parseOccupations } from './parse-company-config.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, '..');
const outDir = resolve(root, 'scout_extension');

/** 会社ID → (displayName, platform) */
const COMPANY_META = {
  'nomura-hospital': { displayName: '野村病院', platform: 'comedical' },
  'chigasaki-tokushukai': { displayName: '茅ヶ崎徳洲会病院', platform: 'welme' },
  'an-visiting-nurse': { displayName: 'an訪問看護', platform: 'comedical' },
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
  const companyIds = (argv.companies || 'nomura-hospital')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  const builtAt = new Date().toISOString();

  console.log('=== Build options ===');
  console.log({ companies: companyIds, builtAt });

  const buildConfigPath = resolve(root, 'src/shared/build-config.ts');
  const originalBuildConfig = readFileSync(buildConfigPath, 'utf-8');
  writeFileSync(buildConfigPath, renderBuildConfig({ builtAt }));

  const bundledConfigPath = resolve(root, 'src/shared/bundled-company-config.ts');
  const originalBundledConfig = readFileSync(bundledConfigPath, 'utf-8');

  console.log('=== Parsing company configs ===');
  const companies = [];
  for (const id of companyIds) {
    const meta = COMPANY_META[id];
    if (!meta) {
      console.warn(`[warn] COMPANY_META に ${id} がない。スキップ`);
      continue;
    }
    const companiesDir = resolve(root, '..', 'companies', id);
    const recipesPath = resolve(companiesDir, 'recipes.md');
    const templatesPath = resolve(companiesDir, 'templates.md');
    if (!existsSync(recipesPath) || !existsSync(templatesPath)) {
      console.warn(`[warn] ${id}: recipes.md / templates.md が見つからない`);
      continue;
    }
    const recipesMd = readFileSync(recipesPath, 'utf-8');
    const templatesMd = readFileSync(templatesPath, 'utf-8');
    const occupations = parseOccupations(recipesMd, templatesMd);
    console.log(
      `  ${id} (${meta.platform}): ${occupations.length} occupation(s)`,
      occupations.map((o) => `${o.id}[p=${o.patterns.length},t=${o.templates.length}]`).join(', ')
    );
    companies.push({
      companyId: id,
      displayName: meta.displayName,
      platform: meta.platform,
      occupations,
    });
  }

  const scoutConfig = { companies };
  writeFileSync(bundledConfigPath, renderBundledScoutConfig(scoutConfig));

  console.log('=== Building sidepanel ===');
  await build({
    root,
    configFile: resolve(root, 'vite.config.ts'),
    build: { outDir, emptyOutDir: true },
  });

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

  console.log('=== Writing manifest ===');
  const manifest = JSON.parse(readFileSync(resolve(root, 'manifest.json'), 'utf-8'));
  const patched = patchManifest(manifest);
  writeFileSync(resolve(outDir, 'manifest.json'), JSON.stringify(patched, null, 2));

  cpSync(resolve(root, 'icons'), resolve(outDir, 'icons'), { recursive: true });

  // Restore dev defaults — working tree を汚さない
  writeFileSync(buildConfigPath, originalBuildConfig);
  writeFileSync(bundledConfigPath, originalBundledConfig);

  console.log('=== Build complete ===');
  console.log('Suggested zip name:', zipName({ builtAt }));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
