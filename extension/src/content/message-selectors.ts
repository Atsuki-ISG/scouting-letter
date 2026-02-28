/**
 * メッセージページ用CSSセレクタ集約
 *
 * Phase B（3月）で実際のDOM構造を調査し、セレクタを更新する
 * URL: https://customers.job-medley.com/customers/messages
 */

export const MESSAGE_SELECTORS = {
  /** メッセージスレッド全体のコンテナ */
  threadContainer: '[data-message-thread]', // placeholder

  /** 個々のメッセージ要素 */
  messageItem: '[data-message-item]', // placeholder

  /** メッセージの送信者（企業 or 求職者） */
  messageSender: '[data-message-sender]', // placeholder

  /** メッセージの日時 */
  messageDate: '[data-message-date]', // placeholder

  /** メッセージ本文 */
  messageText: '[data-message-text]', // placeholder

  /** 会員番号（スレッドヘッダー等から取得） */
  memberId: '[data-member-id]', // placeholder
} as const;
