import { build } from 'vite';
import { build as esbuild } from 'esbuild';
import { cpSync, readFileSync, writeFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, '..');

async function main() {
  // Step 1: Build HTML (sidepanel) with Vite
  console.log('=== Building HTML pages ===');
  await build({
    root,
    configFile: resolve(root, 'vite.config.ts'),
  });

  // Step 2: Bundle content script as IIFE
  console.log('=== Building content script ===');
  await esbuild({
    entryPoints: [resolve(root, 'src/content/index.ts')],
    bundle: true,
    format: 'iife',
    outfile: resolve(root, 'dist/content.js'),
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
    outfile: resolve(root, 'dist/service-worker.js'),
    target: 'es2022',
    minify: false,
    sourcemap: true,
  });

  // Step 4: Copy manifest.json with correct paths
  console.log('=== Copying manifest and icons ===');
  const manifest = JSON.parse(readFileSync(resolve(root, 'manifest.json'), 'utf-8'));

  manifest.background.service_worker = 'service-worker.js';
  delete manifest.background.type;
  manifest.content_scripts[0].js = ['content.js'];
  manifest.side_panel.default_path = 'src/sidepanel/index.html';

  writeFileSync(resolve(root, 'dist/manifest.json'), JSON.stringify(manifest, null, 2));

  // Copy icons
  cpSync(resolve(root, 'icons'), resolve(root, 'dist/icons'), { recursive: true });

  console.log('=== Build complete ===');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
