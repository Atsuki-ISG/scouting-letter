/**
 * 媒体別アダプタ契約
 *
 * ジョブメドレー・ウェルミー・コメディカル等、媒体ごとにDOM構造・抽出
 * ロジック・送信フローが異なる。各媒体はこの MediumAdapter を実装する。
 *
 * 新媒体対応の流れ:
 *   1. src/content/adapters/{medium}.ts で MediumAdapter を実装
 *   2. manifest.json の host_permissions / matches にドメイン追加
 *   3. src/content/index.ts の selectAdapter() に分岐追加
 */

import type { CandidateProfile } from './types';

export type MediumId = 'jobmedley' | 'welme';

/** 候補者リスト内の1候補者への参照（クリック等の操作を抽象化） */
export interface CandidateHandle {
  memberId: string;
  element: HTMLElement;
  /** カード上に見える最低限のラベル（氏名イニシャル・会員番号など） */
  label?: string;
}

export interface MediumAdapter {
  /** 媒体識別子 */
  readonly id: MediumId;

  /** 人間向け表示名（UI・ログ用） */
  readonly displayName: string;

  /**
   * この URL がこの媒体で扱える対象か判定する。
   * content script は全媒体の adapter を持つが、実行中のタブURLに
   * マッチする1つだけを選ぶ。
   */
  matchUrl(url: string): boolean;

  /**
   * 候補者一覧ページから候補者ハンドルを列挙する。
   * スカウト送信対象の選定に使う。
   */
  getCandidateList(): CandidateHandle[];

  /**
   * 現在開かれている候補者プロフィールページ（overlay等）から
   * プロフィール情報を抽出する。
   *
   * 媒体によって取れるフィールドが異なるため、
   * 不明なフィールドは空文字 / false で埋める。
   */
  extractProfile(): Promise<CandidateProfile>;

  /**
   * スカウト本文を入力する textarea を返す。
   * 見つからない場合は null。
   */
  getComposeTextarea(): HTMLTextAreaElement | null;
}

/**
 * 空のプロフィール（全フィールド未入力）を返す。
 * 媒体アダプタが部分抽出しかできないとき、未取得フィールドを
 * この既定値で埋める。
 */
export function emptyCandidateProfile(): CandidateProfile {
  return {
    member_id: '',
    gender: '',
    age: '',
    area: '',
    qualifications: '',
    experience_type: '',
    experience_years: '',
    employment_status: '',
    desired_job: '',
    desired_area: '',
    desired_employment_type: '',
    desired_start: '',
    self_pr: '',
    special_conditions: '',
    work_history_summary: '',
    scout_sent_date: '',
    is_favorite: false,
  };
}
