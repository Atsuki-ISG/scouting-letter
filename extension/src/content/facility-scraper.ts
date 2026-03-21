/**
 * 施設・求人情報ページからのスクレイパー
 *
 * 対象ページ: customers.job-medley.com/customers/facilities
 *
 * フロー:
 * 1. サイドバーから施設一覧を取得（EXTRACT_FACILITY_LIST）
 * 2. ユーザーが施設を選択
 * 3. 選択施設ごとにサイドバーリンクをクリック → DOM更新待ち → 現在のDOMから求人情報を読み取り
 * 4. 掲載中の求人のプレビューページ（/job_offer/{id}/confirmation/）をfetchして詳細取得
 *
 * NOTE: 施設ページはSPAのためfetchでは取得不可。DOMから直接読み取る。
 *       プレビューページ（/job_offer/{id}/confirmation/）はSSRのためfetchで取得可能。
 */

import { FacilityInfo, FacilityJobInfo, FacilityListItem } from '../shared/types';

let aborted = false;

/** 抽出を中止 */
export function abortFacilityExtraction(): void {
  aborted = true;
}

/** 施設ページかどうか判定 */
export function isFacilityPage(): boolean {
  return location.href.includes('/customers/facilities');
}

/** サイドバーから施設一覧を取得 */
export function extractFacilityList(): FacilityListItem[] {
  const facilities: FacilityListItem[] = [];

  // サイドバーのナビリンク（.c-sub-side-nav__link）を探す
  const navLinks = document.querySelectorAll<HTMLAnchorElement>('a.c-sub-side-nav__link');
  console.log(`[FacilityScraper] Found ${navLinks.length} sidebar nav links`);

  const excludeTexts = ['すべての施設', '新規登録', '求人を新規', '施設を新規'];

  for (const link of navLinks) {
    const name = link.textContent?.trim() || '';
    if (!name) continue;
    if (excludeTexts.some(t => name.includes(t))) continue;
    if (name.startsWith('＋') || name.startsWith('+')) continue;

    // facility_id をhrefから取得
    const href = link.href || '';
    const match = href.match(/facility_id=(\d+)/);

    // hrefにfacility_idがない場合、data属性やonClickからIDを探す
    let facilityId = match?.[1] || '';
    if (!facilityId) {
      // href内の数値パターンを試す
      const numMatch = href.match(/facilities\/(\d+)/) || href.match(/\/(\d+)/);
      if (numMatch) facilityId = numMatch[1];
    }

    if (!facilityId) {
      // IDが取れなくても名前があればログに出す
      console.log(`[FacilityScraper] Nav link without ID: "${name}" href="${href}"`);
      // リンク要素のインデックスをIDの代わりに使用（後でクリック用）
      facilityId = `__index_${Array.from(navLinks).indexOf(link)}`;
    }

    facilities.push({ facilityId, name });
    console.log(`[FacilityScraper] Found facility: "${name}" (${facilityId})`);
  }

  // フォールバック: .c-sub-side-nav__link が見つからない場合、facility_idを含む全リンクを検索
  if (facilities.length === 0) {
    console.log('[FacilityScraper] Fallback: searching all links with facility_id');
    const allLinks = document.querySelectorAll('a');
    for (const link of allLinks) {
      const href = link.href || '';
      const match = href.match(/facility_id=(\d+)/);
      if (match) {
        const name = link.textContent?.trim() || '';
        if (!name) continue;
        if (excludeTexts.some(t => name.includes(t))) continue;
        if (name.startsWith('＋') || name.startsWith('+')) continue;
        facilities.push({ facilityId: match[1], name });
      }
    }
  }

  // 重複排除
  const seen = new Set<string>();
  return facilities.filter((f) => {
    if (seen.has(f.facilityId)) return false;
    seen.add(f.facilityId);
    return true;
  });
}

/**
 * プレビューページからdt/ddペアで求人情報を抽出
 *
 * プレビューページの構造:
 * - 上部: 施設紹介（h2/h3 + div。おすすめポイント、代表メッセージ等）
 * - 「募集内容」セクション内: dt/dd ペアで構造化された求人情報
 *   - 募集職種, 仕事内容, 給与, 給与の備考, 待遇, 勤務時間, 休日, etc.
 * - 下部: 法人・施設名, アクセス（これもdt/dd）
 *
 * → dt/dd ペアだけを抽出すれば、施設紹介文の混入を防げる
 */
function extractJobFieldsFromDtDd(root: Element): Record<string, string> {
  const fields: Record<string, string> = {};
  const dtElements = root.querySelectorAll('dt');

  for (const dt of dtElements) {
    const label = dt.textContent?.trim();
    if (!label) continue;
    // ラベルが長すぎるものは無視（dt/ddではない可能性）
    if (label.length > 30) continue;

    // 対応するdd要素を探す
    const dd = dt.nextElementSibling;
    if (dd?.tagName === 'DD') {
      const content = dd.textContent?.trim() || '';
      if (content) {
        fields[label] = content;
      }
    }
  }

  return fields;
}

/** 施設紹介セクション（h2/h3の内容）を抽出 */
function extractFacilityDescription(root: Element): { description: string; representativeMessage: string } {
  let description = '';
  let representativeMessage = '';

  const headings = root.querySelectorAll('h2, h3');
  for (const heading of headings) {
    const label = heading.textContent?.trim() || '';

    // 代表メッセージ
    if (label.includes('代表メッセージ') || label.includes('代表者メッセージ')) {
      let sibling = heading.nextElementSibling;
      while (sibling && !['H2', 'H3'].includes(sibling.tagName)) {
        representativeMessage += (sibling.textContent?.trim() || '') + '\n';
        sibling = sibling.nextElementSibling;
      }
      representativeMessage = representativeMessage.trim();
    }

    // 募集内容の前にある施設紹介テキスト
    if (label.includes('募集内容')) break; // 募集内容以降はdt/ddで処理

    // 施設紹介系のセクション
    if (label.includes('おすすめ') || label.includes('特徴') || label.includes('紹介')) {
      let sibling = heading.nextElementSibling;
      while (sibling && !['H2', 'H3'].includes(sibling.tagName)) {
        description += (sibling.textContent?.trim() || '') + '\n';
        sibling = sibling.nextElementSibling;
      }
    }
  }

  return { description: description.trim(), representativeMessage };
}

/**
 * rawTextからラベルパターンで求人フィールドを抽出
 *
 * プレビューページのテキスト構造:
 *   ...施設紹介文...
 *   募集内容
 *   募集職種
 *     訪問看護師（看護師/准看護師）
 *   仕事内容
 *     ...
 *   給与
 *     【正職員】月給 300,000円 〜 370,000円
 *   給与の備考
 *     ...
 *   待遇
 *     ...
 *   勤務時間
 *     ...
 *   休日
 *     ...
 *   法人・施設名
 *     ...
 */
function extractJobFieldsFromText(rawText: string): Record<string, string> {
  const fields: Record<string, string> = {};

  // 「募集内容」以降のテキストだけを使う（施設紹介文を除外）
  const recruitIdx = rawText.indexOf('募集内容');
  if (recruitIdx === -1) return fields;
  const text = rawText.substring(recruitIdx);

  // 抽出対象のラベル（出現順）
  const labels = [
    '募集職種', '仕事内容', '診療科目・サービス形態',
    '給与', '給与の備考',
    '待遇', '教育体制・研修', '勤務時間', '休日',
    '応募要件', '歓迎要件',
    '法人・施設名', '募集職種', 'アクセス',
  ];

  // 各ラベルの位置を特定
  const positions: Array<{ label: string; start: number; end: number }> = [];
  for (const label of labels) {
    let searchFrom = 0;
    while (true) {
      const idx = text.indexOf(label, searchFrom);
      if (idx === -1) break;
      positions.push({ label, start: idx, end: idx + label.length });
      searchFrom = idx + label.length;
      // 「法人・施設名」以降の2回目の「募集職種」も取得するため続行
      if (label !== '募集職種') break;
    }
  }

  // 位置順にソート
  positions.sort((a, b) => a.start - b.start);

  // 各ラベルの後ろから次のラベルまでをコンテンツとして抽出
  for (let i = 0; i < positions.length; i++) {
    const { label, end } = positions[i];
    const nextStart = i + 1 < positions.length ? positions[i + 1].start : text.length;
    const content = text.substring(end, nextStart).trim();

    if (content && !fields[label]) {
      // ラベル名自体が含まれていたら除去（例: 「募集職種\n訪問看護師」→「訪問看護師」）
      let cleaned = content;
      if (cleaned.startsWith(label)) {
        cleaned = cleaned.substring(label.length).trim();
      }
      if (cleaned) {
        fields[label] = cleaned;
      }
    }
  }

  return fields;
}

/** dt/dd辞書から求人情報にマッピング */
function applyJobSections(job: FacilityJobInfo, fields: Record<string, string>): void {
  const mapping: Array<[keyof FacilityJobInfo, string[]]> = [
    ['jobType', ['募集職種']],
    ['jobDescription', ['仕事内容']],
    ['salary', ['給与']],
    ['benefits', ['待遇']],
    ['workingHours', ['勤務時間']],
    ['holidays', ['休日']],
  ];

  for (const [field, labels] of mapping) {
    for (const label of labels) {
      // 完全一致を優先
      if (fields[label]) {
        job[field] = fields[label];
        break;
      }
    }
  }

  // 給与の備考があれば給与に追記
  if (fields['給与の備考']) {
    job.salary = (job.salary ? job.salary + '\n\n' : '') + fields['給与の備考'];
  }

  // 教育体制・研修があれば待遇に追記
  if (fields['教育体制・研修']) {
    job.benefits = (job.benefits ? job.benefits + '\n\n【研修】' : '') + fields['教育体制・研修'];
  }

  // 応募要件
  const reqKey = Object.keys(fields).find(k => k.includes('応募要件') || k.includes('応募資格'));
  if (reqKey) {
    job.jobDescription = (job.jobDescription ? job.jobDescription + '\n\n【応募要件】' : '') + fields[reqKey];
  }

  // 診療科目・サービス形態
  const serviceKey = Object.keys(fields).find(k => k.includes('診療科目') || k.includes('サービス形態'));
  if (serviceKey) {
    job.jobDescription = (job.jobDescription ? job.jobDescription + '\n\n【サービス形態】' : '') + fields[serviceKey];
  }
}

/** プレビューURLからHTMLを取得しパース（SSRページなのでfetch可能） */
async function fetchPreviewPage(url: string): Promise<FacilityJobInfo> {
  console.log('[FacilityScraper] Fetching preview:', url);

  const job: FacilityJobInfo = {
    title: '',
    jobType: '',
    jobDescription: '',
    salary: '',
    benefits: '',
    workingHours: '',
    holidays: '',
    rawText: '',
  };

  const res = await fetch(url, { credentials: 'include' });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${url}`);
  }

  const html = await res.text();
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, 'text/html');

  job.rawText = doc.body?.textContent?.trim() || '';

  // タイトル取得（h1 or ページ上部のタイトル要素）
  const titleEl = doc.querySelector('h1, h2, .title');
  if (titleEl) {
    job.title = titleEl.textContent?.trim() || '';
  }

  // rawTextからラベルパターンで求人フィールドを抽出
  // プレビューページはdt/ddではなくdiv構造なので、テキストベースで解析
  const fields = extractJobFieldsFromText(job.rawText);
  applyJobSections(job, fields);

  console.log('[FacilityScraper] Preview fetched:', job.title || '(no title)', 'fields:', Object.keys(fields).join(', '));

  return job;
}

/** 指定時間待機 */
function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** DOMの変化を待つ（指定テキストが現れるまで、またはタイムアウト） */
function waitForDomUpdate(check: () => boolean, timeoutMs = 5000): Promise<boolean> {
  return new Promise((resolve) => {
    if (check()) {
      resolve(true);
      return;
    }

    const observer = new MutationObserver(() => {
      if (check()) {
        observer.disconnect();
        resolve(true);
      }
    });

    observer.observe(document.body, { childList: true, subtree: true, characterData: true });

    setTimeout(() => {
      observer.disconnect();
      resolve(check());
    }, timeoutMs);
  });
}

/** サイドバーの施設リンクをクリックしてページを切り替え */
async function navigateToFacility(facilityId: string): Promise<boolean> {
  // __index_ プレフィックスの場合、ナビリンクのインデックスで検索
  if (facilityId.startsWith('__index_')) {
    const index = parseInt(facilityId.replace('__index_', ''), 10);
    const navLinks = document.querySelectorAll<HTMLAnchorElement>('a.c-sub-side-nav__link');
    const link = navLinks[index];
    if (link) {
      console.log(`[FacilityScraper] Clicking sidebar link by index ${index}: "${link.textContent?.trim()}"`);
      link.click();
      await wait(1000);
      await waitForDomUpdate(() => !!document.querySelector('.c-sub-side-nav__link--active'), 5000);
      await wait(500);
      return true;
    }
    return false;
  }

  // facility_idで検索
  const links = document.querySelectorAll('a');
  for (const link of links) {
    const href = link.href || '';
    const linkText = link.textContent?.trim() || '';
    if (href.includes(`facility_id=${facilityId}`) && !linkText.startsWith('＋') && !linkText.startsWith('+') && !linkText.includes('新規登録')) {
      console.log(`[FacilityScraper] Clicking sidebar link for facility ${facilityId}: "${linkText}"`);
      link.click();

      // DOM更新を待つ（施設IDがページ内に表示されるまで）
      await wait(500); // SPAのルーティングを待つ
      const updated = await waitForDomUpdate(() => {
        const text = document.body.textContent || '';
        return text.includes(`施設ID`) && text.includes(facilityId);
      }, 5000);

      if (!updated) {
        console.warn(`[FacilityScraper] DOM update timeout for facility ${facilityId}`);
      }

      // 追加の安定待ち
      await wait(500);
      return true;
    }
  }

  console.warn(`[FacilityScraper] Sidebar link not found for facility ${facilityId}`);
  return false;
}

/** 現在のDOMから掲載中の求人IDを収集 */
function collectActiveJobIdsFromDom(): string[] {
  const jobIds: string[] = [];
  const pageText = document.body.textContent || '';

  // 求人IDを全て探す
  const allIds: Array<{ id: string; position: number }> = [];
  const idRegex = /求人ID[:：]\s*(\d+)/g;
  let match;
  while ((match = idRegex.exec(pageText)) !== null) {
    allIds.push({ id: match[1], position: match.index });
  }

  console.log(`[FacilityScraper] Found ${allIds.length} job IDs in DOM`);

  // 各求人IDの近くに「掲載中」があるかチェック
  for (const { id, position } of allIds) {
    const contextStart = Math.max(0, position - 500);
    const contextEnd = Math.min(pageText.length, position + 500);
    const context = pageText.substring(contextStart, contextEnd);

    // 「掲載中」はあるが「応募受付終了」がその求人の近くにない
    if (context.includes('掲載中')) {
      jobIds.push(id);
      console.log(`[FacilityScraper] Job ${id}: 掲載中`);
    } else {
      console.log(`[FacilityScraper] Job ${id}: not active (skipped)`);
    }
  }

  return [...new Set(jobIds)];
}

/** 現在のDOMから施設の基本情報を抽出 */
function extractFacilityBasicInfo(facilityId: string): Partial<FacilityInfo> {
  const pageText = document.body.textContent || '';

  // 施設名: メインコンテンツ領域のh2やh3から取得
  // スクショでは施設名が大きく表示されている
  let facilityName = '';

  // 施設IDの近くに施設名があるはず
  const idMatch = pageText.match(new RegExp(`([^\\n]{1,50})\\s*[\\s\\S]*?施設ID[:：]\\s*${facilityId}`));
  if (idMatch) {
    // 施設IDの前のテキストから施設名を探す
    const beforeId = pageText.substring(
      Math.max(0, pageText.indexOf(`施設ID`) - 200),
      pageText.indexOf(`施設ID`)
    );
    // 行分割して、空でない最後の行が施設名の可能性が高い
    const lines = beforeId.split(/\n/).map(l => l.trim()).filter(l => l.length > 0 && l.length < 100);
    if (lines.length > 0) {
      // 「編集」「プレビュー」などのUI文字列を除外
      const candidates = lines.filter(l =>
        !['編集', 'プレビュー', '条件をクリア', '求人情報を絞り込む'].includes(l) &&
        !l.startsWith('+') &&
        !l.includes('施設の登録')
      );
      if (candidates.length > 0) {
        facilityName = candidates[candidates.length - 1];
      }
    }
  }

  // 所在地を探す（都道府県パターン）
  let address = '';
  const addrMatch = pageText.match(/((?:北海道|東京都|(?:京都|大阪)府|.{2,3}県)\S+)/);
  if (addrMatch) {
    address = addrMatch[1];
  }

  // 施設種別（「訪問看護ステーション」「病院」等）
  let facilityType = '';
  const typeMatch = pageText.match(/(?:施設ID[:：]\s*\d+[\s\S]*?)(訪問看護ステーション|病院|クリニック|診療所|介護施設|有料老人ホーム|デイサービス|居宅介護|グループホーム|特別養護老人ホーム)/);
  if (typeMatch) {
    facilityType = typeMatch[1];
  }

  console.log(`[FacilityScraper] Basic info: name="${facilityName}", addr="${address}", type="${facilityType}"`);

  return {
    facilityName,
    facilityId,
    address,
    facilityType,
    rawPageText: pageText.substring(0, 5000).trim(),
  };
}

/** 施設ページのDOMから情報を読み取り（SPA対応: クリックでナビゲーション） */
async function extractFacilityFromDom(facilityId: string, facilityName: string): Promise<FacilityInfo> {
  // サイドバーリンクをクリックして施設ページに切り替え
  const navigated = await navigateToFacility(facilityId);

  const facility: FacilityInfo = {
    facilityName: facilityName || '',
    facilityId,
    address: '',
    facilityType: '',
    representativeMessage: '',
    description: '',
    jobs: [],
    rawPageText: '',
  };

  if (!navigated) {
    facility.rawPageText = '(施設ページへのナビゲーション失敗)';
    return facility;
  }

  // 現在のDOMから基本情報を抽出
  const basicInfo = extractFacilityBasicInfo(facilityId);
  Object.assign(facility, basicInfo);
  // サイドバーから取得した名前を優先（DOM解析は不安定なため）
  if (facilityName) {
    facility.facilityName = facilityName;
  }

  // 掲載中の求人IDを現在のDOMから収集
  const activeJobIds = collectActiveJobIdsFromDom();
  console.log(`[FacilityScraper] Facility "${facility.facilityName}": ${activeJobIds.length} active jobs`);

  // 各求人のプレビューページをfetch（SSRなので取得可能）
  for (let i = 0; i < activeJobIds.length; i++) {
    if (aborted) break;
    const previewUrl = `https://customers.job-medley.com/job_offer/${activeJobIds[i]}/confirmation/`;
    try {
      const job = await fetchPreviewPage(previewUrl);
      facility.jobs.push(job);
    } catch (err) {
      console.error(`[FacilityScraper] Failed to fetch preview:`, err);
      facility.jobs.push({
        title: `(取得失敗: ${activeJobIds[i]})`,
        jobType: '', jobDescription: '', salary: '',
        benefits: '', workingHours: '', holidays: '',
        rawText: String(err),
      });
    }
  }

  return facility;
}

/** 複数施設の情報を一括抽出 */
export async function extractFacilityInfo(facilityIds: string[]): Promise<FacilityInfo[]> {
  console.log('[FacilityScraper] Starting extraction for', facilityIds.length, 'facilities');
  aborted = false;

  // サイドバーから施設名を取得（クリック前に名前を保存）
  const facilityList = extractFacilityList();
  const nameMap = new Map(facilityList.map(f => [f.facilityId, f.name]));

  const results: FacilityInfo[] = [];

  for (let i = 0; i < facilityIds.length; i++) {
    if (aborted) {
      console.log('[FacilityScraper] Aborted by user');
      break;
    }
    const fId = facilityIds[i];
    const fName = nameMap.get(fId) || '';
    console.log(`[FacilityScraper] Processing facility ${i + 1}/${facilityIds.length}: ${fName} (${fId})`);
    try {
      const facility = await extractFacilityFromDom(fId, fName);
      results.push(facility);
    } catch (err) {
      console.error(`[FacilityScraper] Failed:`, err);
      results.push({
        facilityName: fName || `(取得失敗: ${fId})`,
        facilityId: fId,
        address: '', facilityType: '', representativeMessage: '',
        description: '', jobs: [], rawPageText: String(err),
      });
    }
  }

  console.log('[FacilityScraper] Extraction complete:', results.length, 'facilities');
  return results;
}
