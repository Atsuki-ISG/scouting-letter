import { CandidateProfile } from '../shared/types';
import { SELECTORS, FIELD_LABELS, getValueByLabel } from './selectors';
import { TAB_LOAD_WAIT_MS, MUTATION_OBSERVER_TIMEOUT_MS } from '../shared/constants';

/** 指定ミリ秒待機 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

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
  const maxWait = 5000;
  const interval = 200;
  let elapsed = 0;
  while (elapsed < maxWait) {
    if (overlay.querySelectorAll('dt').length > 0) return;
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
    }, 200);

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

/** サイドカバーが閉じるのを待つ */
export function waitForOverlayClose(timeoutMs = 5000): Promise<void> {
  return new Promise((resolve) => {
    const startTime = Date.now();
    let sawOpen = false;
    const check = () => {
      const el = document.querySelector(SELECTORS.overlay);
      const hidden = !el || el.classList.contains('u-is-hidden') || (el as HTMLElement).offsetParent === null;

      if (!hidden) sawOpen = true;

      if (sawOpen && hidden) {
        resolve();
        return;
      }

      if (timeoutMs > 0 && Date.now() - startTime > timeoutMs) {
        resolve();
        return;
      }
      requestAnimationFrame(check);
    };
    check();
  });
}

/** タブをクリックしてコンテンツ読み込みを待つ */
async function clickTabByText(overlay: Element, tabText: string): Promise<void> {
  const tabs = overlay.querySelectorAll(SELECTORS.tab);
  for (const tab of tabs) {
    if (tab.textContent?.trim() === tabText) {
      (tab as HTMLElement).click();
      await sleep(TAB_LOAD_WAIT_MS);
      return;
    }
  }
}

/**
 * 経験職種フィールドから職種と年数を分離する
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
  await waitForContent(overlay);

  await clickTabByText(overlay, 'プロフィール');
  await sleep(TAB_LOAD_WAIT_MS);

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
  };

  await clickTabByText(overlay, '職務経歴');
  await sleep(TAB_LOAD_WAIT_MS);

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
