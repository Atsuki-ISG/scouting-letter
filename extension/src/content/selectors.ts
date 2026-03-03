/**
 * CSSセレクタ集約
 * DOM変更時はここだけ修正する
 *
 * ジョブメドレー管理画面の実際のDOM構造に基づく（2026-02調査）
 * プロフィールデータはDT/DD定義リスト形式
 * overlayはサイドカバーパネル（.c-side-cover）
 * 候補者カードは .c-search-member-card
 */

export const SELECTORS = {
  /** 候補者カード */
  candidateCard: '.c-search-member-card',

  /** カード内の会員番号チェックボックス */
  memberCheckbox: 'input[name="member-select"]',

  /** カード内の「スカウトを送る」ボタン */
  scoutButton: 'button.js-tour-guide-scout-button',

  /** サイドカバー（スカウト送信パネル） */
  overlay: '.c-side-cover',

  /** 閉じるボタン */
  closeButton: 'a.c-side-cover__close-btn',

  /** タブ（プロフィール/職務経歴） */
  tab: 'a.c-switcher__item',

  /** 本文テキストエリア */
  scoutTextarea: 'textarea[name="body"]',

  /** スカウト対象求人の隠しinput */
  jobOfferInput: 'input[name="jobOffer"]',

  /** スカウト対象求人のサジェスト入力欄 */
  jobOfferSuggestInput: '.c-search-box .c-text-field',

  /** プロフィールのDTラベル */
  definitionHead: 'dt',
} as const;

/**
 * ラベルテキストからDT/DDペアの値を取得する
 */
export function getValueByLabel(
  root: Element | Document,
  label: string
): string {
  const dts = root.querySelectorAll(SELECTORS.definitionHead);
  for (const dt of dts) {
    if (dt.textContent?.trim() === label) {
      const dd = dt.nextElementSibling;
      if (dd && dd.tagName === 'DD') {
        return dd.textContent?.trim() || '';
      }
    }
  }
  return '';
}

/** プロフィールフィールドのラベル名マッピング */
export const FIELD_LABELS = {
  memberId: '会員番号',
  gender: '性別',
  age: '年齢',
  area: '居住地',
  qualifications: '資格',
  experienceType: '経験職種',
  employmentStatus: '就業状況',
  desiredJob: '希望職種',
  desiredArea: '希望勤務地',
  desiredEmploymentType: '希望勤務形態',
  desiredStart: '希望入職時期',
  selfPr: '自己PR',
  specialConditions: 'こだわり条件',
} as const;

/**
 * セレクタで要素を検索し、テキストを返す
 */
export function queryText(
  root: Element | Document,
  selector: string
): string {
  const el = root.querySelector(selector);
  return el?.textContent?.trim() || '';
}

/**
 * セレクタで要素を検索し、要素を返す
 */
export function queryElement(
  root: Element | Document,
  selector: string
): Element | null {
  return root.querySelector(selector);
}

/**
 * セレクタで全要素を検索
 */
export function queryAllElements(
  root: Element | Document,
  selector: string
): Element[] {
  return Array.from(root.querySelectorAll(selector));
}
