import { Message } from '../shared/types';
import { localTimestamp } from '../shared/constants';

/** サイドパネルが閉じている場合のエラーを無視して送信 */
export function safeSendMessage(message: Message): void {
  chrome.runtime.sendMessage(message).catch(() => {});
}

/** デバッグログをサイドパネルに送信 */
export function debugLog(step: string, status: 'pending' | 'success' | 'error', detail?: string): void {
  safeSendMessage({
    type: 'DEBUG_LOG',
    entry: { timestamp: localTimestamp(), step, status, detail },
  });
}
