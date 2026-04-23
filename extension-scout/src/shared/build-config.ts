/**
 * ビルド時注入される静的設定。
 *
 * `scripts/build.js` がこのファイルを上書き生成する。開発ビルドでは
 * 下のデフォルト値が使われる。会社リストは BUNDLED_SCOUT_CONFIG 側。
 */
export interface BuildConfig {
  builtAt: string;
}

export const BUILD_CONFIG: BuildConfig = {
  builtAt: '',
};
