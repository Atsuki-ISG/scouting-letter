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

  /**
   * カード内の「スカウトを送る」ボタン（旧: ツアーガイド用クラス）。
   * 2026-10 にこのクラスが消えたため、実際の探索は findScoutButton() を使うこと。
   * 表示が戻った場合に備えて第一候補として残している。
   */
  scoutButton: 'button.js-tour-guide-scout-button',

  /** カード下部のボタン領域（プロフィール確認 / スカウトを送る が並ぶ） */
  cardButtonArea: '.c-search-member-card__buttons',

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
 * カード内スカウトボタンの文言。未送信は「スカウトを送る」、送信済みは
 * 「再度スカウトを送る」になるため、空白除去後の部分一致で判定する。
 */
const SCOUT_BUTTON_TEXT = 'スカウトを送る';

/**
 * 候補者カードから「スカウトを送る」ボタンを探す。
 *
 * 2026-10 にジョブメドレーがボタンの `js-tour-guide-scout-button` クラスを外し、
 * `button.c-button.c-button--secondary` + 文言のみになった。クラス名は汎用で
 * 「プロフィール確認」ボタンと区別できないため、ボタン領域内の文言で特定する。
 * 旧クラスが残っている／戻った場合はそちらを優先する。
 */
export function findScoutButton(card: Element): HTMLElement | null {
  const legacy = card.querySelector(SELECTORS.scoutButton) as HTMLElement | null;
  if (legacy) return legacy;
  const scope = card.querySelector(SELECTORS.cardButtonArea) || card;
  for (const btn of scope.querySelectorAll('button')) {
    if ((btn.textContent || '').replace(/\s+/g, '').includes(SCOUT_BUTTON_TEXT)) {
      return btn as HTMLElement;
    }
  }
  return null;
}

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
  favorite: '気になる',
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
