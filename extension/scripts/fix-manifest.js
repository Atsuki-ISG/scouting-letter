import { readFileSync, writeFileSync } from 'fs';

const path = 'dist/manifest.json';
const manifest = JSON.parse(readFileSync(path, 'utf-8'));

// use_dynamic_url を除去（Content Scriptのモジュール読み込みと競合するため）
if (manifest.web_accessible_resources) {
  for (const entry of manifest.web_accessible_resources) {
    delete entry.use_dynamic_url;
  }
}

writeFileSync(path, JSON.stringify(manifest, null, 2));
console.log('Fixed manifest.json: removed use_dynamic_url');
