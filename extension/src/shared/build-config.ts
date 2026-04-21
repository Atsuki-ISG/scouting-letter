/**
 * ビルド時注入される静的設定
 *
 * `scripts/build.js` が `--company` / `--medium` 引数を受け、
 * ビルド時にこのファイルを上書き生成する。開発用ビルドでは
 * 下のデフォルト値が使われる。
 *
 * 配布zipは「1社・1媒体」単位で固定されるため、拡張インストール後に
 * オペレーターが会社を切り替えるUIは持たない（取り違え防止）。
 */

import type { MediumId } from './medium-adapter';

export interface BuildConfig {
  /** スカウト送信対象の会社ID（companies/ 配下のディレクトリ名） */
  companyId: string;
  /** 対応媒体 */
  medium: MediumId;
  /** 拡張表示名（manifest の name に入る） */
  displayName: string;
  /** ビルド時刻（ISO8601）。空文字は開発ビルド */
  builtAt: string;
}

/** 開発ビルド用のデフォルト。本番ビルドは scripts/build.js が上書き生成する */
export const BUILD_CONFIG: BuildConfig = {
  companyId: 'ark-visiting-nurse',
  medium: 'jobmedley',
  displayName: 'Scout Assistant (dev)',
  builtAt: '',
};
