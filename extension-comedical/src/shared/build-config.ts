/**
 * ビルド時注入される静的設定。
 *
 * `scripts/build.js` が `--company` 引数を受けてこのファイルを上書き
 * 生成する。開発ビルドでは下のデフォルト値が使われる。
 */
export interface BuildConfig {
  companyId: string;
  displayName: string;
  builtAt: string;
}

export const BUILD_CONFIG: BuildConfig = {
  companyId: 'dev',
  displayName: 'Comedical Scout (dev)',
  builtAt: '',
};
