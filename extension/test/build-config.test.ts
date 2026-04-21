/**
 * ビルド設定注入のテスト
 *
 * `scripts/build.js` の差し替えロジックを関数として切り出し、
 * 単体テストする。実際のファイルは書き込まず、文字列変換として
 * 検証する。
 */

import { describe, expect, it } from 'vitest';
import {
  renderBuildConfig,
  patchManifest,
  renderBundledCompanyConfig,
  scoutExtensionZipName,
} from '../scripts/build-config-inject.js';

describe('renderBuildConfig', () => {
  it('companyId / medium / displayName を含む TS ソースを返す', () => {
    const src = renderBuildConfig({
      companyId: 'chigasaki-tokushukai',
      medium: 'welme',
      displayName: '茅ヶ崎徳洲会 Scout (WelMe)',
      builtAt: '2026-04-21T10:00:00+09:00',
    });
    expect(src).toContain("companyId: 'chigasaki-tokushukai'");
    expect(src).toContain("medium: 'welme'");
    expect(src).toContain('茅ヶ崎徳洲会 Scout (WelMe)');
    expect(src).toContain('2026-04-21T10:00:00+09:00');
  });

  it('既存のファイルフォーマット（BUILD_CONFIG export）を保つ', () => {
    const src = renderBuildConfig({
      companyId: 'a',
      medium: 'welme',
      displayName: 'x',
      builtAt: '',
    });
    expect(src).toMatch(/export const BUILD_CONFIG:\s*BuildConfig/);
    expect(src).toMatch(/import type \{ MediumId \}/);
  });
});

describe('patchManifest', () => {
  const baseManifest = {
    manifest_version: 3,
    name: 'Job Medley Scout Assistant',
    version: '1.0.0',
    host_permissions: ['https://job-medley.com/*'],
    content_scripts: [
      { matches: ['https://job-medley.com/*'], js: ['src/content/index.ts'] },
      { matches: ['https://job-medley.com/*'], js: ['src/content/main-world.js'] },
    ],
  };

  it('medium=welme なら welme.jp を追加', () => {
    const patched = patchManifest(baseManifest, {
      companyId: 'chigasaki-tokushukai',
      medium: 'welme',
      displayName: 'x',
      builtAt: '',
    });
    const hosts = patched.host_permissions as string[];
    expect(hosts.some((h) => h.includes('welme.jp'))).toBe(true);
    expect(patched.content_scripts[0].matches.some((m: string) => m.includes('welme.jp'))).toBe(true);
  });

  it('medium=jobmedley なら job-medley.com のまま（welme は混ぜない）', () => {
    const patched = patchManifest(baseManifest, {
      companyId: 'ark-visiting-nurse',
      medium: 'jobmedley',
      displayName: 'x',
      builtAt: '',
    });
    const hosts = patched.host_permissions as string[];
    expect(hosts.some((h) => h.includes('welme.jp'))).toBe(false);
    expect(hosts.some((h) => h.includes('job-medley.com'))).toBe(true);
  });

  it('name に displayName を入れる', () => {
    const patched = patchManifest(baseManifest, {
      companyId: 'chigasaki-tokushukai',
      medium: 'welme',
      displayName: '茅ヶ崎徳洲会 Scout (WelMe)',
      builtAt: '',
    });
    expect(patched.name).toContain('茅ヶ崎徳洲会');
  });
});

describe('renderBundledCompanyConfig', () => {
  it('JSON が BUNDLED_COMPANY_CONFIG export に入る', () => {
    const src = renderBundledCompanyConfig({
      companyId: 'chigasaki-tokushukai',
      displayName: '茅ヶ崎徳洲会病院',
      patterns: [
        { pattern_type: 'A', template_text: 'x', feature_variations: ['y'] },
      ],
      templates: [{ type: '正社員_初回', body: 'body...' }],
    });
    expect(src).toContain("BUNDLED_COMPANY_CONFIG: BundledCompanyConfig");
    expect(src).toContain('chigasaki-tokushukai');
    expect(src).toContain('"pattern_type": "A"');
    expect(src).toContain('正社員_初回');
  });

  it('patterns と templates が空でも有効なソース', () => {
    const src = renderBundledCompanyConfig({
      companyId: 'a',
      displayName: 'a',
      patterns: [],
      templates: [],
    });
    expect(src).toMatch(/"patterns": \[\]/);
    expect(src).toMatch(/"templates": \[\]/);
  });
});

describe('scoutExtensionZipName', () => {
  it('{company}-{medium}-extension-YYYYMMDD.zip 命名', () => {
    const name = scoutExtensionZipName(
      { companyId: 'chigasaki-tokushukai', medium: 'welme', displayName: '', builtAt: '2026-04-21T10:00:00+09:00' }
    );
    expect(name).toBe('chigasaki-tokushukai-welme-extension-20260421.zip');
  });
});
