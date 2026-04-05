import { SELECTORS } from './selectors';
import { sleep, randomSleep } from '../shared/utils';
import { COMPANY_FACILITY_KEYWORDS, STORAGE_KEYS } from '../shared/constants';
import { Message } from '../shared/types';

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

/** 会社検証の重複チェック防止フラグ（ページリロードでリセット） */
let companyMismatchChecked = false;

/** 会社検証フラグをリセット（会社変更時に呼ぶ） */
export function resetCompanyMismatchCheck(): void {
  companyMismatchChecked = false;
}

/** job_category → 求人テキストのマッチングキーワード（サーバー設定がない場合のフォールバック） */
const FALLBACK_CATEGORY_KEYWORDS: Record<string, string[]> = {
  nurse: ['看護師', '准看護師'],
  rehab_pt: ['理学療法士'],
  rehab_st: ['言語聴覚士'],
  rehab_ot: ['作業療法士'],
  medical_office: ['医療事務', '受付'],
  dietitian: ['管理栄養士', '栄養士'],
};

/** employment_type → 求人テキストのマッチングキーワード */
const EMPLOYMENT_KEYWORDS: Record<string, string[]> = {
  'パート': ['パート', 'バイト'],
  '正社員': ['正職員', '正社員'],
  '契約': ['契約社員', '契約職員', '契約'],
};

/**
 * ドロップダウンを開いて中身を読み、job_category + employment_type でマッチする求人を選択する
 */
export async function selectJobOffer(
  searchTerm: string,
  jobCategory: string,
  employmentType: string,
  categoryKeywords?: string[],
): Promise<{ success: boolean; error?: string; selectedJobId?: string }> {
  const suggestInput = document.querySelector(SELECTORS.jobOfferSuggestInput) as HTMLInputElement | null;
  if (!suggestInput) {
    return { success: false, error: '求人検索の入力欄が見つかりません' };
  }

  // 1. 入力欄をフォーカスしてクリア
  suggestInput.focus();
  suggestInput.select();
  document.execCommand('delete', false);
  await randomSleep(80, 200);

  // 2. 検索キーワードで入力してドロップダウンを開く
  console.log('[Scout Assistant] Searching job offers with:', searchTerm);
  insertTextViaExecCommand(suggestInput, searchTerm);
  await randomSleep(400, 700);

  // 3. Downshiftのドロップダウンが開くのを待つ
  const combobox = suggestInput.closest('[role="combobox"]');
  if (!combobox) {
    return { success: false, error: 'combobox_not_found' };
  }

  let expanded = false;
  for (let i = 0; i < 80; i++) {
    if (combobox.getAttribute('aria-expanded') === 'true') {
      expanded = true;
      break;
    }
    await sleep(100);
  }

  if (!expanded) {
    return { success: false, error: 'dropdown_not_opened' };
  }

  // 4. ドロップダウン内のoption要素を読む
  let options: NodeListOf<Element> = document.querySelectorAll('[role="option"]');
  for (let i = 0; i < 80 && options.length === 0; i++) {
    await sleep(100);
    options = document.querySelectorAll('[role="option"]');
  }

  if (options.length === 0) {
    return { success: false, error: 'no_options' };
  }

  // デバッグ: 全optionのテキストを出力
  options.forEach((o, i) => console.log(`[Scout Assistant] option[${i}]:`, o.textContent?.trim().slice(0, 100)));

  // 4.5. 会社検証: ドロップダウンのテキストに選択中の会社の施設名が含まれるか確認
  if (!companyMismatchChecked) {
    companyMismatchChecked = true;
    try {
      const result = await chrome.storage.local.get([STORAGE_KEYS.COMPANY, STORAGE_KEYS.DETECTION_KEYWORDS]);
      const companyId = result[STORAGE_KEYS.COMPANY] || '';
      const storedKw: Record<string, string[]> = result[STORAGE_KEYS.DETECTION_KEYWORDS] || {};
      const keywords: string[] | undefined = storedKw[companyId] || COMPANY_FACILITY_KEYWORDS[companyId];
      if (keywords && keywords.length > 0) {
        const allText = Array.from(options).map(o => o.textContent || '').join(' ');
        const found = keywords.some(kw => allText.includes(kw));
        if (!found) {
          console.warn(`[Scout Assistant] COMPANY MISMATCH: selected=${companyId}, keywords=${keywords.join(',')}, not found in dropdown`);
          try {
            chrome.runtime.sendMessage({
              type: 'COMPANY_MISMATCH',
              companyId,
              keywords,
            } satisfies Message);
          } catch { /* ignore */ }
        }
      }
    } catch { /* ignore */ }
  }

  // 5. job_category + employment_type でマッチング（サーバー設定優先、なければフォールバック）
  const effectiveCategoryKeywords = categoryKeywords || FALLBACK_CATEGORY_KEYWORDS[jobCategory] || [];
  const empKeywords = EMPLOYMENT_KEYWORDS[employmentType] || [];

  let targetIndex = -1;

  // 両方マッチする求人を探す
  for (let i = 0; i < options.length; i++) {
    const text = options[i].textContent?.trim() || '';
    const categoryMatch = effectiveCategoryKeywords.some((kw) => text.includes(kw));
    const empMatch = empKeywords.length === 0 || empKeywords.some((kw) => text.includes(kw));
    if (categoryMatch && empMatch) {
      targetIndex = i;
      break;
    }
  }

  // 雇用形態なしでカテゴリだけマッチするフォールバック
  if (targetIndex === -1) {
    for (let i = 0; i < options.length; i++) {
      const text = options[i].textContent?.trim() || '';
      if (effectiveCategoryKeywords.some((kw) => text.includes(kw))) {
        targetIndex = i;
        break;
      }
    }
  }

  // それでもなければ最初のoptionにフォールバック（1件しかない場合等）
  if (targetIndex === -1 && options.length === 1) {
    targetIndex = 0;
  }

  if (targetIndex === -1) {
    console.log('[Scout Assistant] No matching option for:', jobCategory, employmentType);
    return { success: false, error: `no_match: ${jobCategory}/${employmentType}` };
  }

  const targetEl = options[targetIndex] as HTMLElement;
  console.log('[Scout Assistant] Matched option[%d]: %s', targetIndex, targetEl?.textContent?.trim().slice(0, 80));

  // 6. メインワールドでReact Fiberを辿って選択
  const mwResult = await clickOptionInMainWorld(targetIndex, '', '');
  if (!mwResult.success) {
    return { success: false, error: `main_world_failed: ${mwResult.error}` };
  }

  // 7. hidden inputに値がセットされたか確認
  await sleep(300);
  const hiddenInput = document.querySelector(SELECTORS.jobOfferInput) as HTMLInputElement | null;
  if (!hiddenInput) {
    return { success: false, error: 'hidden_input_not_found' };
  }

  // 追加待機
  if (!hiddenInput.value) {
    await sleep(500);
  }

  const selectedJobId = hiddenInput.value;
  if (selectedJobId) {
    console.log('[Scout Assistant] Job offer selected:', selectedJobId);
    return { success: true, selectedJobId };
  }

  return { success: false, error: 'hidden_input_empty' };
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
