/**
 * メッセージページのDOM抽出
 *
 * Phase A: プレースホルダー実装（セレクタ未確定）
 * Phase B（3月）: 実際のDOM構造調査後に実装
 */

import { ConversationThread } from '../shared/types';

/**
 * メッセージページからやりとりスレッドを抽出
 *
 * Phase Aではまだ実DOMに対応していないため、
 * エラーを返してサイドパネルの手動入力にフォールバックさせる
 */
export function extractConversation(): ConversationThread | null {
  // Phase B で実装予定:
  // 1. MESSAGE_SELECTORS を使ってDOM要素を取得
  // 2. メッセージ一覧をパース
  // 3. ConversationThread を組み立てて返す

  console.log('[Scout Assistant] メッセージ抽出はPhase B（3月）で実装予定');
  return null;
}

/**
 * 現在のページがメッセージページかどうかを判定
 */
export function isMessagePage(): boolean {
  return location.pathname.includes('/messages');
}
