import { SELECTORS } from './selectors';

/**
 * テキストエリアに値をセットする
 * React/Vueなどのフレームワークが入力を検知できるよう、
 * ネイティブのinput/changeイベントを発火する
 */
export function fillScoutText(text: string): { success: boolean; error?: string } {
  const textarea = document.querySelector(SELECTORS.scoutTextarea) as HTMLTextAreaElement | null;

  if (!textarea) {
    return { success: false, error: 'スカウト本文のテキストエリアが見つかりません' };
  }

  // React の value setter を使ってネイティブに値をセット
  const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    'value'
  )?.set;

  if (nativeInputValueSetter) {
    nativeInputValueSetter.call(textarea, text);
  } else {
    textarea.value = text;
  }

  // React/Vue が検知できるイベントを発火
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
  textarea.dispatchEvent(new Event('change', { bubbles: true }));
  textarea.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true }));
  textarea.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));

  // フォーカスして視覚的にも反映
  textarea.focus();

  return { success: true };
}
