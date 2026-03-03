import { SELECTORS } from './selectors';

/**
 * input要素にReact native setterで値をセットし、イベントを発火する
 */
function setNativeInputValue(el: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  const prototype = el instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype
    : HTMLInputElement.prototype;
  const nativeSetter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;

  if (nativeSetter) {
    nativeSetter.call(el, value);
  } else {
    el.value = value;
  }

  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

/** 指定ms待機 */
function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * input要素にexecCommandでテキストを挿入する（React/Downshift対応）
 * ブラウザの入力として扱われるため、Reactの合成イベントが正しく発火する
 */
function insertTextViaExecCommand(el: HTMLInputElement | HTMLTextAreaElement, text: string): void {
  el.focus();
  // 全選択してから挿入（既存テキストを置換）
  el.select();
  document.execCommand('insertText', false, text);
}

/**
 * スカウト対象求人を自動選択する
 * Downshift autocompleteに対してexecCommandでテキスト入力し、
 * ドロップダウンから一致する項目をクリックして選択する
 */
export async function fillJobOffer(jobId: string, jobName: string): Promise<{ success: boolean; error?: string }> {
  const suggestInput = document.querySelector(SELECTORS.jobOfferSuggestInput) as HTMLInputElement | null;
  if (!suggestInput) {
    return { success: false, error: '求人検索の入力欄が見つかりません' };
  }

  // 1. 入力欄をフォーカスしてクリア
  suggestInput.focus();
  suggestInput.select();
  document.execCommand('delete', false);
  await wait(100);

  // 2. 短い検索キーワードで入力（完全な求人名だと一致しない場合があるため）
  // 求人名から施設名部分を抽出して検索に使う
  const searchTerm = extractSearchTerm(jobName);
  console.log('[Scout Assistant] Searching job offer with:', searchTerm);
  insertTextViaExecCommand(suggestInput, searchTerm);
  await wait(500);

  // 3. Downshiftのドロップダウンが開くのを待つ
  const combobox = suggestInput.closest('[role="combobox"]');
  console.log('[Scout Assistant] Combobox found:', !!combobox, 'aria-expanded:', combobox?.getAttribute('aria-expanded'));
  console.log('[Scout Assistant] suggestInput value:', suggestInput.value);
  if (!combobox) {
    console.log('[Scout Assistant] Combobox not found, using fallback');
    return fillJobOfferFallback(jobId, jobName);
  }

  // aria-expanded="true" になるまで待機（最大3秒）
  let expanded = false;
  for (let i = 0; i < 30; i++) {
    if (combobox.getAttribute('aria-expanded') === 'true') {
      expanded = true;
      break;
    }
    await wait(100);
  }
  console.log('[Scout Assistant] Dropdown expanded:', expanded);

  if (!expanded) {
    console.log('[Scout Assistant] Dropdown did not open, using fallback');
    return fillJobOfferFallback(jobId, jobName);
  }

  // 4. ドロップダウン内のoption要素を探してクリック
  // Downshiftは[role="listbox"]を使わず、.c-suggest__list内にli[role="option"]を描画する
  // option描画を待つ（最大5秒ポーリング）
  let options: NodeListOf<Element> = document.querySelectorAll('[role="option"]');
  for (let i = 0; i < 50 && options.length === 0; i++) {
    await wait(100);
    options = document.querySelectorAll('[role="option"]');
    // デバッグ: .c-suggest__listの存在も確認
    if (i === 10) {
      const suggestList = document.querySelector('.c-suggest__list');
      console.log('[Scout Assistant] .c-suggest__list found:', !!suggestList, suggestList?.innerHTML?.slice(0, 200));
    }
  }
  console.log('[Scout Assistant] Found', options.length, 'options');

  if (options.length === 0) {
    console.log('[Scout Assistant] No options found, using fallback');
    return fillJobOfferFallback(jobId, jobName);
  }

  let selected = false;

  for (const option of options) {
    const text = option.textContent || '';
    // 求人名に含まれるキーワードで一致判定
    if (text.includes(jobName) || jobName.includes(text.trim())) {
      // Downshiftはmousedownイベントで選択を処理する
      (option as HTMLElement).dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      selected = true;
      console.log('[Scout Assistant] Selected job offer option:', text.slice(0, 60));
      break;
    }
  }

  // 完全一致しなかった場合、職種名で部分一致
  if (!selected) {
    for (const option of options) {
      const text = option.textContent || '';
      const jobType = jobName.split(/\s+/).pop() || '';
      if (jobType && text.includes(jobType)) {
        (option as HTMLElement).dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        selected = true;
        console.log('[Scout Assistant] Selected option by job type match:', text.slice(0, 60));
        break;
      }
    }
  }

  // それでもダメなら最初の選択肢を選択
  if (!selected && options.length === 1) {
    (options[0] as HTMLElement).dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    selected = true;
    console.log('[Scout Assistant] Selected only option');
  }

  if (!selected) {
    console.log('[Scout Assistant] No matching option, listing all:');
    options.forEach((o, i) => console.log(`  [${i}]`, o.textContent?.slice(0, 60)));
    return fillJobOfferFallback(jobId, jobName);
  }

  await wait(200);

  // 5. 選択後にhidden inputが正しくセットされたか確認
  const hiddenInput = document.querySelector(SELECTORS.jobOfferInput) as HTMLInputElement | null;
  if (hiddenInput && hiddenInput.value !== jobId) {
    console.log('[Scout Assistant] Hidden input mismatch, correcting:', hiddenInput.value, '->', jobId);
    setNativeInputValue(hiddenInput, jobId);
  }

  return { success: true };
}

/**
 * 求人名から検索キーワードを抽出
 * 例: "北海道 医療法人社団優希 アーク訪問看護ステーション 看護師/准看護師 (訪問看護師) パート・バイト"
 *   → "アーク訪問看護ステーション"
 * 例: "東京都 LCC訪問看護ステーション 本社 看護師/准看護師  正職員"
 *   → "LCC訪問看護ステーション"
 */
function extractSearchTerm(jobName: string): string {
  // "ステーション" を含む部分を探す
  const parts = jobName.split(/\s+/);
  for (const part of parts) {
    if (part.includes('ステーション')) {
      return part;
    }
  }
  // 見つからなければ2番目〜3番目のパーツ（施設名が多い）
  if (parts.length >= 3) {
    return parts.slice(1, 3).join(' ');
  }
  return jobName;
}

/**
 * フォールバック: hidden inputとテキスト入力欄を直接セット
 */
function fillJobOfferFallback(jobId: string, jobName: string): { success: boolean; error?: string } {
  console.log('[Scout Assistant] Using fallback for job offer');
  const hiddenInput = document.querySelector(SELECTORS.jobOfferInput) as HTMLInputElement | null;
  if (hiddenInput) {
    setNativeInputValue(hiddenInput, jobId);
  }

  const suggestInput = document.querySelector(SELECTORS.jobOfferSuggestInput) as HTMLInputElement | null;
  if (suggestInput) {
    setNativeInputValue(suggestInput, jobName);
  }

  return { success: true };
}

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

  setNativeInputValue(textarea, text);

  // 追加のキーボードイベントを発火（フレームワーク検知用）
  textarea.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true }));
  textarea.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));

  // フォーカスして視覚的にも反映
  textarea.focus();

  return { success: true };
}
