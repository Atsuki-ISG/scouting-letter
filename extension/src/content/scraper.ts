import { CandidateProfile } from '../shared/types';
import { SELECTORS, FIELD_LABELS, getValueByLabel } from './selectors';
import { MUTATION_OBSERVER_TIMEOUT_MS } from '../shared/constants';
import { sleep } from '../shared/utils';

/** overlayが表示されているか判定 */
function isOverlayVisible(el: Element): boolean {
  if (el.classList.contains('u-is-hidden')) return false;
  const html = el as HTMLElement;
  const style = window.getComputedStyle(html);
  if (style.display === 'none' || style.visibility === 'hidden') return false;
  if (html.offsetWidth === 0 && html.offsetHeight === 0) return false;
  return true;
}

/** overlay内のコンテンツ（DT要素）が読み込まれるまで待つ */
async function waitForContent(overlay: Element): Promise<void> {
  const maxWait = 3000;
  const interval = 20;
  let elapsed = 0;
  while (elapsed < maxWait) {
    if (overlay.querySelectorAll('dt').length > 0) return;
    await sleep(interval);
    elapsed += interval;
  }
}

/** 指定ラベルのDT要素が出現するまで待つ（タブ切替後のコンテンツ検知用） */
async function waitForLabel(overlay: Element, label: string, maxWait = 1500): Promise<void> {
  const interval = 20;
  let elapsed = 0;
  while (elapsed < maxWait) {
    const dts = overlay.querySelectorAll('dt');
    for (const dt of dts) {
      if (dt.textContent?.trim() === label) return;
    }
    await sleep(interval);
    elapsed += interval;
  }
}

/** サイドカバーの表示を待つ */
export function waitForOverlay(): Promise<Element> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(SELECTORS.overlay);
    if (existing && isOverlayVisible(existing)) {
      resolve(existing);
      return;
    }

    const timeout = setTimeout(() => {
      clearInterval(pollInterval);
      observer.disconnect();
      reject(new Error('サイドカバー表示がタイムアウトしました'));
    }, MUTATION_OBSERVER_TIMEOUT_MS);

    const pollInterval = setInterval(() => {
      const el = document.querySelector(SELECTORS.overlay);
      if (el && isOverlayVisible(el)) {
        clearTimeout(timeout);
        clearInterval(pollInterval);
        observer.disconnect();
        resolve(el);
      }
    }, 50);

    const observer = new MutationObserver(() => {
      const el = document.querySelector(SELECTORS.overlay);
      if (el && isOverlayVisible(el)) {
        clearTimeout(timeout);
        clearInterval(pollInterval);
        observer.disconnect();
        resolve(el);
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['style', 'class'],
    });
  });
}

/** サイドカバーが閉じるのを待つ（タイムアウト付き） */
export function waitForOverlayClose(timeoutMs = 5000): Promise<void> {
  return new Promise((resolve) => {
    const startTime = Date.now();
    let sawOpen = false;
    const check = () => {
      const el = document.querySelector(SELECTORS.overlay);
      const hidden = !el || el.classList.contains('u-is-hidden') || (el as HTMLElement).offsetParent === null;

      // まずoverlayが開いている状態を検知する
      if (!hidden) {
        sawOpen = true;
      }

      // overlayが開いた後に閉じた場合のみresolve
      if (sawOpen && hidden) {
        resolve();
        return;
      }

      // タイムアウト（0なら無限待機）
      if (timeoutMs > 0 && Date.now() - startTime > timeoutMs) {
        resolve();
        return;
      }
      requestAnimationFrame(check);
    };
    check();
  });
}

/** タブをクリック（待機はcaller側でコンテンツ検知） */
function clickTab(overlay: Element, tabText: string): void {
  const tabs = overlay.querySelectorAll(SELECTORS.tab);
  for (const tab of tabs) {
    if (tab.textContent?.trim() === tabText) {
      (tab as HTMLElement).click();
      return;
    }
  }
}

/**
 * 経験職種フィールドから職種と年数を分離する
 * 例: "看護師/准看護師（10年以上）" → { type: "看護師/准看護師", years: "10年以上" }
 */
function parseExperienceType(raw: string): { type: string; years: string } {
  const match = raw.match(/^(.+?)(?:[（(](.+?)[）)])?$/);
  if (match) {
    return {
      type: match[1].trim(),
      years: match[2]?.trim() || '',
    };
  }
  return { type: raw, years: '' };
}

/** サイドカバーからプロフィール情報を抽出 */
export async function extractProfile(overlay: Element): Promise<CandidateProfile> {
  // overlayのコンテンツ読み込みを待機
  await waitForContent(overlay);

  // プロフィールタブを表示し、会員番号ラベルの出現で読み込み完了を検知
  clickTab(overlay, 'プロフィール');
  await waitForLabel(overlay, FIELD_LABELS.memberId);

  // 経験職種から職種と年数を分離
  const expRaw = getValueByLabel(overlay, FIELD_LABELS.experienceType);
  const exp = parseExperienceType(expRaw);

  const profile: CandidateProfile = {
    member_id: getValueByLabel(overlay, FIELD_LABELS.memberId),
    gender: getValueByLabel(overlay, FIELD_LABELS.gender),
    age: getValueByLabel(overlay, FIELD_LABELS.age),
    area: getValueByLabel(overlay, FIELD_LABELS.area),
    qualifications: getValueByLabel(overlay, FIELD_LABELS.qualifications),
    experience_type: exp.type,
    experience_years: exp.years,
    employment_status: getValueByLabel(overlay, FIELD_LABELS.employmentStatus),
    desired_job: getValueByLabel(overlay, FIELD_LABELS.desiredJob),
    desired_area: getValueByLabel(overlay, FIELD_LABELS.desiredArea),
    desired_employment_type: getValueByLabel(overlay, FIELD_LABELS.desiredEmploymentType),
    desired_start: getValueByLabel(overlay, FIELD_LABELS.desiredStart),
    self_pr: getValueByLabel(overlay, FIELD_LABELS.selfPr),
    special_conditions: getValueByLabel(overlay, FIELD_LABELS.specialConditions),
    work_history_summary: '',
    scout_sent_date: '',
  };

  // 職務経歴タブに切替えて抽出（勤務先名ラベルの出現で読み込み完了を検知）
  clickTab(overlay, '職務経歴');
  await waitForLabel(overlay, '勤務先名', 1000).catch(() => {});

  // 職務経歴: プロフィールの既知ラベルとUI文言を除外してDT/DDペアを取得
  const profileLabels = new Set<string>(Object.values(FIELD_LABELS));
  const allDts = overlay.querySelectorAll('dt');
  const workPairs: string[] = [];
  for (const dt of allDts) {
    const label = dt.textContent?.trim() || '';
    if (profileLabels.has(label)) continue;
    if (label.includes('テンプレート')) continue;
    const dd = dt.nextElementSibling;
    if (dd && dd.tagName === 'DD') {
      const value = dd.textContent?.trim() || '';
      if (value) {
        workPairs.push(`${label}: ${value}`);
      }
    }
  }
  if (workPairs.length > 0) {
    profile.work_history_summary = workPairs.join('\n');
  }

  return profile;
}

/** サイドカバーを閉じる */
export function closeOverlay(): void {
  const btn = document.querySelector(SELECTORS.closeButton);
  if (btn) {
    (btn as HTMLElement).click();
  }
}

/** 現在表示中のサイドカバーから会員番号を取得 */
export function getOverlayMemberId(): string | null {
  const overlay = document.querySelector(SELECTORS.overlay);
  if (!overlay || (overlay as HTMLElement).offsetParent === null) {
    return null;
  }
  const memberId = getValueByLabel(overlay, FIELD_LABELS.memberId);
  return memberId || null;
}
