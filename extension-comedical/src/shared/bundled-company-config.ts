// 開発ビルド用のデフォルト。本番ビルドは scripts/build.js が上書き生成する。
import type { Pattern } from './pattern-matcher';

export interface BundledTemplate {
  type: string;
  body: string;
}

export interface BundledCompanyConfig {
  companyId: string;
  displayName: string;
  patterns: Pattern[];
  templates: BundledTemplate[];
}

export const BUNDLED_COMPANY_CONFIG: BundledCompanyConfig = {
  companyId: 'dev',
  displayName: 'Comedical Scout (dev)',
  patterns: [],
  templates: [],
};
