/**
 * ジョブメドレーのスカウト送信パネルから求人リストを抽出する。
 * Downshift autocompleteの入力欄に空文字を入力し、
 * ドロップダウンに表示される全求人を取得する。
 */
import { SELECTORS } from './selectors';
import { sleep } from '../shared/utils';

export interface ExtractedJobOffer {
  id: string;
  name: string;
}

/**
 * スカウト画面の求人サジェストからページ内の全求人を抽出する。
 * overlayが開いている状態で呼び出す必要がある。
 */
export async function extractJobOffers(): Promise<{ success: boolean; offers: ExtractedJobOffer[]; error?: string }> {
  const suggestInput = document.querySelector(SELECTORS.jobOfferSuggestInput) as HTMLInputElement | null;
  if (!suggestInput) {
    return { success: false, offers: [], error: '求人検索の入力欄が見つかりません。スカウト送信パネルを開いてください。' };
  }

  // 1. 入力欄をフォーカスしてクリア → 空文字で全件表示を試みる
  suggestInput.focus();
  suggestInput.select();
  document.execCommand('delete', false);
  await sleep(200);

  // 空文字で入力イベントを発火（Downshiftが全件ドロップダウンを開くトリガー）
  suggestInput.dispatchEvent(new Event('input', { bubbles: true }));
  suggestInput.dispatchEvent(new Event('change', { bubbles: true }));
  await sleep(500);

  // 2. ドロップダウンが開くのを待つ（最大5秒）
  const combobox = suggestInput.closest('[role="combobox"]');
  if (!combobox) {
    return { success: false, offers: [], error: 'combobox要素が見つかりません' };
  }

  let expanded = false;
  for (let i = 0; i < 50; i++) {
    if (combobox.getAttribute('aria-expanded') === 'true') {
      expanded = true;
      break;
    }
    await sleep(100);
  }

  if (!expanded) {
    // フォーカスだけでは開かない場合、クリックで再試行
    suggestInput.click();
    await sleep(500);
    expanded = combobox.getAttribute('aria-expanded') === 'true';
  }

  if (!expanded) {
    return { success: false, offers: [], error: 'ドロップダウンが開きませんでした' };
  }

  // 3. option要素を全取得（最大5秒ポーリング）
  let options: NodeListOf<Element> = document.querySelectorAll('[role="option"]');
  for (let i = 0; i < 50 && options.length === 0; i++) {
    await sleep(100);
    options = document.querySelectorAll('[role="option"]');
  }

  if (options.length === 0) {
    return { success: false, offers: [], error: '求人が見つかりませんでした' };
  }

  // 4. 各optionからID・名称を抽出
  const offers: ExtractedJobOffer[] = [];
  for (const option of options) {
    const text = option.textContent?.trim() || '';
    if (!text) continue;

    // optionのテキストは "123456 北海道 医療法人... 看護師/准看護師 パート・バイト" のような形式
    // 先頭の数字が求人ID
    const match = text.match(/^(\d+)\s+(.+)$/);
    if (match) {
      offers.push({ id: match[1], name: match[2] });
    } else {
      // IDが先頭にない場合はテキスト全体をnameとする
      offers.push({ id: '', name: text });
    }
  }

  // 5. ドロップダウンを閉じる（Escキー）
  suggestInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));

  console.log(`[Scout Assistant] Extracted ${offers.length} job offers`);
  return { success: true, offers };
}
