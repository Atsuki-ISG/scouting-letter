import { SELECTORS } from './selectors';
import { sleep, randomSleep } from '../shared/utils';

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
 * メインワールドのスクリプトにCustomEventでReact要素のクリックを依頼し、
 * 結果をPromiseで返す
 */
function clickOptionInMainWorld(index: number, jobId: string, jobName: string): Promise<{ success: boolean; selectedValue?: string; error?: string }> {
  return new Promise((resolve) => {
    const timeout = setTimeout(() => {
      window.removeEventListener('__scout_job_offer_result__', handler);
      console.log('[Scout Assistant] Main world result timeout');
      resolve({ success: false, error: 'main_world_timeout' });
    }, 3000);

    const handler = (e: Event) => {
      clearTimeout(timeout);
      window.removeEventListener('__scout_job_offer_result__', handler);
      const detail = (e as CustomEvent).detail;
      resolve({ success: detail.success, selectedValue: detail.selectedValue, error: detail.error });
    };

    window.addEventListener('__scout_job_offer_result__', handler);

    document.dispatchEvent(new CustomEvent('__scout_click_option', {
      detail: { selector: '[role="option"]', index, jobId, jobName },
    }));
  });
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
  await randomSleep(80, 200);

  // 2. 短い検索キーワードで入力
  const searchTerm = extractSearchTerm(jobName);
  console.log('[Scout Assistant] Searching job offer with:', searchTerm);
  insertTextViaExecCommand(suggestInput, searchTerm);
  await randomSleep(400, 700);

  // 3. Downshiftのドロップダウンが開くのを待つ（最大8秒）
  const combobox = suggestInput.closest('[role="combobox"]');
  console.log('[Scout Assistant] Combobox found:', !!combobox, 'aria-expanded:', combobox?.getAttribute('aria-expanded'));
  console.log('[Scout Assistant] suggestInput value:', suggestInput.value);
  if (!combobox) {
    console.log('[Scout Assistant] Combobox not found');
    return { success: false, error: 'combobox_not_found' };
  }

  // aria-expanded="true" になるまで待機（最大8秒）
  let expanded = false;
  for (let i = 0; i < 80; i++) {
    if (combobox.getAttribute('aria-expanded') === 'true') {
      expanded = true;
      break;
    }
    await sleep(100);
  }
  console.log('[Scout Assistant] Dropdown expanded:', expanded);

  if (!expanded) {
    console.log('[Scout Assistant] Dropdown did not open');
    return { success: false, error: 'dropdown_not_opened' };
  }

  // 4. ドロップダウン内のoption要素を探す（最大8秒ポーリング）
  let options: NodeListOf<Element> = document.querySelectorAll('[role="option"]');
  for (let i = 0; i < 80 && options.length === 0; i++) {
    await sleep(100);
    options = document.querySelectorAll('[role="option"]');
    if (i === 10) {
      const suggestList = document.querySelector('.c-suggest__list');
      console.log('[Scout Assistant] .c-suggest__list found:', !!suggestList, suggestList?.innerHTML?.slice(0, 200));
    }
  }
  console.log('[Scout Assistant] Found', options.length, 'options');

  if (options.length === 0) {
    console.log('[Scout Assistant] No options found');
    return { success: false, error: 'no_options' };
  }

  // デバッグ: 全optionのテキストを出力
  options.forEach((o, i) => console.log(`[Scout Assistant] option[${i}]:`, o.textContent?.trim().slice(0, 80)));

  // マッチング: 目的のoptionが何番目かを特定
  let targetIndex = -1;
  for (let i = 0; i < options.length; i++) {
    const text = options[i].textContent?.trim() || '';
    if (text.includes(jobName) || jobName.includes(text.replace(/^\d+/, '').trim())) {
      targetIndex = i;
      break;
    }
  }
  // searchTermでの部分一致フォールバック
  if (targetIndex === -1) {
    for (let i = 0; i < options.length; i++) {
      const text = options[i].textContent?.trim() || '';
      if (text.includes(searchTerm)) {
        targetIndex = i;
        break;
      }
    }
  }

  // マッチしない場合はindex 0にフォールバックしない → 失敗を返す
  if (targetIndex === -1) {
    console.log('[Scout Assistant] No matching option found for:', jobName);
    return { success: false, error: 'no_match' };
  }

  const targetEl = options[targetIndex] as HTMLElement;
  console.log('[Scout Assistant] Target option index:', targetIndex, targetEl?.textContent?.trim().slice(0, 60));

  // メインワールドでReact Fiberを辿ってDownshiftから直接選択し、結果を待つ
  const mwResult = await clickOptionInMainWorld(targetIndex, jobId, jobName);
  console.log('[Scout Assistant] Main world result:', mwResult);

  if (!mwResult.success) {
    console.log('[Scout Assistant] Main world selection failed:', mwResult.error);
    return { success: false, error: `main_world_failed: ${mwResult.error}` };
  }

  // Reactレンダリング完了を少し待ってからhidden inputを検証
  await sleep(300);

  // 5. 選択後にhidden inputが正しくセットされたか確認
  const hiddenInput = document.querySelector(SELECTORS.jobOfferInput) as HTMLInputElement | null;
  if (!hiddenInput) {
    console.log('[Scout Assistant] Hidden input not found');
    return { success: false, error: 'hidden_input_not_found' };
  }

  if (hiddenInput.value === jobId) {
    console.log('[Scout Assistant] Job offer selected correctly:', jobId);
    return { success: true };
  }

  // hidden inputの値が違う場合、Reactがまだ更新中の可能性があるので追加待機
  await sleep(500);
  const hiddenInputRetry = document.querySelector(SELECTORS.jobOfferInput) as HTMLInputElement | null;
  if (hiddenInputRetry && hiddenInputRetry.value === jobId) {
    console.log('[Scout Assistant] Job offer selected correctly (after retry):', jobId);
    return { success: true };
  }

  // それでも不一致の場合 → 値を直接セット（ベストエフォート）
  console.log('[Scout Assistant] Hidden input mismatch:', hiddenInputRetry?.value, 'expected:', jobId, '- correcting');
  if (hiddenInputRetry) {
    setNativeInputValue(hiddenInputRetry, jobId);
    // 修正した場合はsuccessとするが、warningをログに残す
    console.log('[Scout Assistant] Hidden input corrected to:', jobId);
    return { success: true };
  }

  return { success: false, error: 'hidden_input_verification_failed' };
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
 * テキストエリアに値をセットする（リトライ付き）
 * React/Vueなどのフレームワークが入力を検知できるよう、
 * ネイティブのinput/changeイベントを発火する
 * 求人選択後のReact再レンダリングで値が消えるケースに対応
 */
export async function fillScoutText(text: string): Promise<{ success: boolean; error?: string }> {
  const maxAttempts = 3;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const textarea = document.querySelector(SELECTORS.scoutTextarea) as HTMLTextAreaElement | null;

    if (!textarea) {
      if (attempt < maxAttempts - 1) {
        await sleep(300);
        continue;
      }
      return { success: false, error: 'スカウト本文のテキストエリアが見つかりません' };
    }

    setNativeInputValue(textarea, text);

    // 追加のキーボードイベントを発火（フレームワーク検知用）
    textarea.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true }));
    textarea.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));

    // フォーカスして視覚的にも反映
    textarea.focus();

    // 値が正しくセットされたか確認（React再レンダリングで消えることがある）
    await sleep(200);
    const verify = document.querySelector(SELECTORS.scoutTextarea) as HTMLTextAreaElement | null;
    if (verify && verify.value === text) {
      return { success: true };
    }

    console.log(`[Scout Assistant] fillScoutText: value not set on attempt ${attempt + 1}, retrying...`);
    await sleep(300);
  }

  // 最終試行: execCommandで入力（ブラウザネイティブの入力として扱われる）
  const textarea = document.querySelector(SELECTORS.scoutTextarea) as HTMLTextAreaElement | null;
  if (textarea) {
    console.log('[Scout Assistant] fillScoutText: using execCommand fallback');
    insertTextViaExecCommand(textarea, text);
    return { success: true };
  }

  return { success: false, error: 'テキストエリアへの値セットに失敗しました' };
}
