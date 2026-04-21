import { build } from 'vite';
import { build as esbuild } from 'esbuild';
import { cpSync, readFileSync, writeFileSync, existsSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import {
  renderBuildConfig,
  patchManifest,
  renderBundledCompanyConfig,
  scoutExtensionZipName,
} from './build-config-inject.js';
import {
  parsePatternsFromRecipes,
  parseTemplatesFromTemplates,
} from './parse-company-config.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, '..');

/**
 * --company=X --medium=Y を読み取る。未指定なら開発用デフォルト
 * （dev モード）。本番配布時は必ず両方指定する想定。
 */
function parseArgs(argv) {
  const args = {};
  for (const a of argv.slice(2)) {
    const m = a.match(/^--([^=]+)=(.*)$/);
    if (m) args[m[1]] = m[2];
  }
  return args;
}

const DISPLAY_NAMES = {
  // 会社ID → 人間向け名。新会社追加時にここへ一行。
  'chigasaki-tokushukai': '茅ヶ崎徳洲会病院',
  'ark-visiting-nurse': 'ARK訪問看護',
  'lcc-visiting-nurse': 'LCC訪問看護',
  'ichigo-visiting-nurse': 'いちご訪問看護',
  'an-visiting-nurse': 'an訪問看護',
  'daiwa-house-ls': 'ネオ・サミット湯河原',
  'nomura-hospital': '野村病院',
};
const MEDIUM_NAMES = {
  jobmedley: 'ジョブメドレー',
  welme: 'WelMe',
};

async function main() {
  const argv = parseArgs(process.argv);
  const companyId = argv.company || 'ark-visiting-nurse';
  const medium = argv.medium || 'jobmedley';
  const builtAt = new Date().toISOString();
  const companyLabel = DISPLAY_NAMES[companyId] || companyId;
  const mediumLabel = MEDIUM_NAMES[medium] || medium;
  const displayName = `${companyLabel} Scout (${mediumLabel})`;

  const buildOpts = { companyId, medium, displayName, builtAt };
  console.log('=== Build options ===');
  console.log(buildOpts);

  // Step 0a: Inject build-config.ts with the target company/medium
  // Keep a copy of the committed dev default so we can restore it afterwards —
  // this keeps the working tree clean after each build.
  console.log('=== Writing build-config.ts ===');
  const buildConfigPath = resolve(root, 'src/shared/build-config.ts');
  const originalBuildConfig = readFileSync(buildConfigPath, 'utf-8');
  writeFileSync(buildConfigPath, renderBuildConfig(buildOpts));

  // Step 0b: Parse companies/[companyId]/ and inject bundled-company-config.ts
  // WelMe 等の他媒体向け拡張は全部型はめで完結するため、テンプレ・パターンを
  // ここで同梱する。companies/ は extension/ の1階層上にある。
  console.log('=== Parsing company config ===');
  const companiesDir = resolve(root, '..', 'companies', companyId);
  const bundledConfigPath = resolve(root, 'src/shared/bundled-company-config.ts');
  const originalBundledConfig = readFileSync(bundledConfigPath, 'utf-8');
  let bundledConfig = {
    companyId,
    displayName: companyLabel,
    patterns: [],
    templates: [],
  };
  const recipesPath = resolve(companiesDir, 'recipes.md');
  const templatesPath = resolve(companiesDir, 'templates.md');
  if (existsSync(recipesPath)) {
    bundledConfig.patterns = parsePatternsFromRecipes(
      readFileSync(recipesPath, 'utf-8')
    );
  } else {
    console.warn(`[warn] recipes.md not found at ${recipesPath}`);
  }
  if (existsSync(templatesPath)) {
    bundledConfig.templates = parseTemplatesFromTemplates(
      readFileSync(templatesPath, 'utf-8')
    );
  } else {
    console.warn(`[warn] templates.md not found at ${templatesPath}`);
  }
  console.log(
    `  patterns: ${bundledConfig.patterns.length}, templates: ${bundledConfig.templates.length}`
  );
  writeFileSync(bundledConfigPath, renderBundledCompanyConfig(bundledConfig));

  // Step 1: Build HTML pages (sidepanel + popup) with Vite
  console.log('=== Building HTML pages ===');
  await build({
    root,
    configFile: resolve(root, 'vite.config.ts'),
  });

  // Step 2: Bundle content script as IIFE (single file, no dynamic imports)
  // WelMe 等の「型はめ固定」媒体は jobmedley の重厚な content script を
  // 使わず、専用の軽量エントリ (welme-entry.ts) を使う。
  const contentEntry =
    medium === 'welme'
      ? 'src/content/welme-entry.ts'
      : 'src/content/index.ts';
  console.log(`=== Building content script (entry: ${contentEntry}) ===`);
  await esbuild({
    entryPoints: [resolve(root, contentEntry)],
    bundle: true,
    format: 'iife',
    outfile: resolve(root, 'scout_extension/content.js'),
    target: 'es2022',
    minify: false,
    sourcemap: true,
  });

  // Step 3: Bundle service worker as IIFE
  console.log('=== Building service worker ===');
  await esbuild({
    entryPoints: [resolve(root, 'src/background/service-worker.ts')],
    bundle: true,
    format: 'iife',
    outfile: resolve(root, 'scout_extension/service-worker.js'),
    target: 'es2022',
    minify: false,
    sourcemap: true,
  });

  // Step 4: Copy main-world script (plain JS, no bundling needed)
  console.log('=== Copying main-world script ===');
  cpSync(
    resolve(root, 'src/content/main-world.js'),
    resolve(root, 'scout_extension/main-world.js')
  );

  // Step 5: Patch and write manifest.json
  console.log('=== Patching manifest ===');
  const manifest = JSON.parse(
    readFileSync(resolve(root, 'manifest.json'), 'utf-8')
  );

  // Update paths for dist structure
  manifest.background.service_worker = 'service-worker.js';
  delete manifest.background.type; // IIFE doesn't need module type
  manifest.content_scripts[0].js = ['content.js'];
  manifest.content_scripts[1].js = ['main-world.js'];
  // medium ごとに異なる sidepanel を指す。welme は専用の軽量UI。
  manifest.side_panel.default_path =
    medium === 'welme'
      ? 'src/sidepanel/welme/index.html'
      : 'src/sidepanel/index.html';

  // Medium/company 注入（matches・host_permissions・name を差し替え）
  const patched = patchManifest(manifest, buildOpts);

  writeFileSync(
    resolve(root, 'scout_extension/manifest.json'),
    JSON.stringify(patched, null, 2)
  );

  // Copy icons
  cpSync(resolve(root, 'icons'), resolve(root, 'scout_extension/icons'), {
    recursive: true,
  });

  // Restore the committed dev defaults so `git status` stays clean.
  writeFileSync(buildConfigPath, originalBuildConfig);
  writeFileSync(bundledConfigPath, originalBundledConfig);

  console.log('=== Build complete ===');
  console.log('Suggested zip name:', scoutExtensionZipName(buildOpts));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
