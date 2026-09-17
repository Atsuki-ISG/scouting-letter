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

/** ページから施設名が出そうな箇所のテキストを集める（document.title / h1,h2 / breadcrumb / サイドナビ等） */
function collectPageFacilityText(): string {
  const sources: string[] = [document.title];
  const navLinks = document.querySelectorAll('a.c-sub-side-nav__link');
  for (const el of navLinks) sources.push(el.textContent || '');
  const headers = document.querySelectorAll('h1, h2, .c-breadcrumb, .c-header, .c-header__title, [class*="header"] [class*="title"]');
  for (const el of headers) sources.push(el.textContent || '');
  return sources.join(' ');
}

/** job_category → 求人テキストのマッチングキーワード（サーバー設定がない場合のフォールバック） */
const FALLBACK_CATEGORY_KEYWORDS: Record<string, string[]> = {
  nurse: ['看護師', '准看護師'],
  rehab_pt: ['理学療法士'],
  pt: ['理学療法士'],
  rehab_st: ['言語聴覚士'],
  st: ['言語聴覚士'],
  rehab_ot: ['作業療法士'],
  ot: ['作業療法士'],
  medical_office: ['医療事務', '受付'],
  dietitian: ['管理栄養士', '栄養士'],
  counselor: ['相談支援専門員', '相談支援'],
  sales: ['入居相談員', '相談員', '営業'],
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
  jobOfferId?: string,
  jobOfferName?: string,
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

  // 4.5. 会社検証: ドロップダウン or ページテキストに施設名キーワードが含まれるか確認
  // 単一施設の「原稿作成委託」型スカウト画面ではドロップダウンに施設名が出ないことがあるため、
  // ページヘッダー/タイトル/パンくずもフォールバックとして見る
  if (!companyMismatchChecked) {
    companyMismatchChecked = true;
    try {
      const result = await chrome.storage.local.get([STORAGE_KEYS.COMPANY, STORAGE_KEYS.DETECTION_KEYWORDS]);
      const companyId = result[STORAGE_KEYS.COMPANY] || '';
      const storedKw: Record<string, string[]> = result[STORAGE_KEYS.DETECTION_KEYWORDS] || {};
      const keywords: string[] | undefined = storedKw[companyId] || COMPANY_FACILITY_KEYWORDS[companyId];
      if (keywords && keywords.length > 0) {
        const dropdownText = Array.from(options).map(o => o.textContent || '').join(' ');
        const pageText = collectPageFacilityText();
        const combined = `${dropdownText} ${pageText}`;
        const found = keywords.some(kw => combined.includes(kw));
        if (!found) {
          console.warn(`[Scout Assistant] COMPANY MISMATCH: selected=${companyId}, keywords=${keywords.join(',')}, not found in dropdown or page`);
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

  // 5.0 求人ID優先: プルダウンの先頭に求人IDが出ていた頃の表示形式
  //     （"1234567 東京都 施設名 看護師/准看護師 正職員"）向けの分岐。
  //     現在のジョブメドレーは求人IDを表示しないため通常はヒットしないが、
  //     表示が戻った場合に最も確実なので残してある。
  if (jobOfferId && jobOfferId.trim()) {
    const wantId = jobOfferId.trim();
    for (let i = 0; i < options.length; i++) {
      const idMatch = (options[i].textContent?.trim() || '').match(/^(\d+)/);
      if (idMatch && idMatch[1] === wantId) {
        targetIndex = i;
        console.log('[Scout Assistant] Job offer matched by ID %s at option[%d]', wantId, i);
        break;
      }
    }
  }

  // 5.1 職種 → 雇用形態 → 求人名 の順に絞り込む。
  //
  //     プルダウンに求人IDが出ないため、施設の区別は求人名に頼るしかない。
  //     ただし求人名とプルダウンの表記は揃っていない（シートは「訪問看護師」、
  //     画面は「看護師/准看護師」）ので、名前だけでは職種を判定できない。
  //     そこで職種・雇用形態はキーワードで絞り、残った候補の中から
  //     求人名に一番多く一致するものを選ぶ。
  if (targetIndex === -1) {
    let candidates: number[] = [];
    for (let i = 0; i < options.length; i++) {
      const text = options[i].textContent?.trim() || '';
      const categoryMatch = effectiveCategoryKeywords.some((kw) => text.includes(kw));
      const empMatch = empKeywords.length === 0 || empKeywords.some((kw) => text.includes(kw));
      if (categoryMatch && empMatch) candidates.push(i);
    }

    // 雇用形態まで一致するものが無ければ職種だけで拾い直す
    if (candidates.length === 0) {
      for (let i = 0; i < options.length; i++) {
        const text = options[i].textContent?.trim() || '';
        if (effectiveCategoryKeywords.some((kw) => text.includes(kw))) candidates.push(i);
      }
    }

    if (candidates.length === 1) {
      targetIndex = candidates[0];
    } else if (candidates.length > 1) {
      const nameTokens = (jobOfferName || '').trim().split(/\s+/).filter(Boolean);
      if (nameTokens.length === 0) {
        // 求人名が無いと施設を見分けられない。従来どおり先頭の候補を使う
        targetIndex = candidates[0];
        console.warn('[Scout Assistant] 求人名が無いため候補を絞り込めません。先頭の候補を使います:',
          options[targetIndex].textContent?.trim().slice(0, 60));
      } else {
        // 求人名の語が何個含まれるかで採点する。施設名がそのまま得点になるので、
        // 「富士見台サテライト」を持つ求人は富士見台の行だけが高得点になる。
        // 同点なら余分な語が少ない＝より正確な一致とみなして短い方を採る
        // （石神井の求人名は富士見台の行にも全語が出てしまうため）。
        const scored = candidates.map((index) => {
          const text = options[index].textContent?.trim() || '';
          return {
            index,
            score: nameTokens.filter((t) => text.includes(t)).length,
            length: text.length,
          };
        });
        scored.sort((a, b) => (b.score - a.score) || (a.length - b.length));
        targetIndex = scored[0].index;

        if (scored.length > 1 && scored[0].score === scored[1].score) {
          console.warn('[Scout Assistant] 求人名の得点が同点の候補があります。短い方を採用しました:',
            scored.slice(0, 3).map((c) => options[c.index].textContent?.trim().slice(0, 60)));
        } else {
          console.log('[Scout Assistant] Job offer matched by name "%s" at option[%d] (score %d/%d, %d candidates)',
            jobOfferName, targetIndex, scored[0].score, nameTokens.length, candidates.length);
        }
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
