/**
 * メッセージページ用CSSセレクタ集約
 *
 * URL: https://customers.job-medley.com/customers/messages
 * DOM調査日: 2026-03-01
 */

export const MESSAGE_SELECTORS = {
  /** メッセージビュー全体（data属性にthread_id等を持つ） */
  messageView: '.c-message-view.js-message-view',

  /** メッセージ一覧コンテナ */
  messageListInner: '.c-message-view__body-inner.js-message-view__body-inner',

  /** 個々のメッセージ要素 */
  messageItem: '.c-message',

  /** メッセージ内部（企業: --companion付き、求職者: なし） */
  messageInner: '.c-message__inner',

  /** 企業メッセージの識別クラス */
  companionModifier: 'c-message__inner--companion',

  /** メッセージ本文 */
  messageBody: '.c-message__body',

  /** メッセージラベル（スカウト/応募/通常） */
  messageLabel: '.c-label',

  /** ヘッダー（sticky部分: 求人タイトル・候補者情報） */
  stickyHeader: '.c-message-view__sticky',

  /** 会員番号を含む要素（"03114222 | 53歳 女性"） */
  memberIdText: '.u-fs-lh-x-small-short.u-fw-bold.u-ml-15.u-color-grey-500',

  /** 候補者名 */
  candidateName: '.ds-o-flex .u-fs-lh-medium-short.u-fw-bold',

  /** 左サイドバー: 会話一覧 */
  conversationList: '.c-infinity-scroll__inner',

  /** 左サイドバー: 無限スクロールコンテナ */
  infinityScroll: '.c-infinity-scroll',

  /** 左サイドバー: ローダー（u-is-hidden時は読み込み完了） */
  infinityLoader: '.c-infinity-scroll .c-loader',

  /** 左サイドバー: 各会話リンク */
  conversationLink: 'a.c-sub-side-nav__link',

  /** 左サイドバー: アクティブ会話 */
  conversationLinkActive: 'a.c-sub-side-nav__link--active',

  /** 返信フォーム */
  replyForm: 'form#message-send-form',

  /** 返信テキストエリア */
  replyTextarea: 'form#message-send-form textarea',
} as const;
