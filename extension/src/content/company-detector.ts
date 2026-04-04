/**
 * ページのDOMからジョブメドレーの施設名を検出し、対応する会社IDを推定する。
 *
 * 検出キーワードはAPIから取得しstorageに保存されたものを使用。
 * storageになければハードコードのフォールバックを使用。
 *
 * 検出ソース:
 * 1. document.title
 * 2. サイドバーのナビリンク (.c-sub-side-nav__link)
 * 3. ヘッダー/パンくずリスト内のテキスト
 * 4. 求人選択の入力値
 */
import { COMPANY_FACILITY_KEYWORDS, STORAGE_KEYS } from '../shared/constants';

/** 会社IDを推定して返す。見つからなければnull */
export async function detectCompanyFromPage(): Promise<string | null> {
  // storageから検出キーワードを取得（API経由で保存済み）、なければフォールバック
  let keywordMap: Record<string, string[]> = COMPANY_FACILITY_KEYWORDS;
  try {
    const result = await chrome.storage.local.get(STORAGE_KEYS.DETECTION_KEYWORDS);
    const stored = result[STORAGE_KEYS.DETECTION_KEYWORDS];
    if (stored && Object.keys(stored).length > 0) {
      keywordMap = stored;
    }
  } catch { /* ignore */ }

  // ページ全体から効率よくテキストを収集
  const textSources: string[] = [];

  // 1. ページタイトル
  textSources.push(document.title);

  // 2. サイドバーリンク（施設名が表示される）
  const navLinks = document.querySelectorAll('a.c-sub-side-nav__link');
  for (const link of navLinks) {
    textSources.push(link.textContent || '');
  }

  // 3. ヘッダー・パンくず
  const headers = document.querySelectorAll('h1, h2, .c-breadcrumb, .c-header, .c-header__title, [class*="header"] [class*="title"]');
  for (const el of headers) {
    textSources.push(el.textContent || '');
  }

  // 4. 求人選択のサジェスト入力の現在値（既に選択済みの場合）
  const suggestInput = document.querySelector('.c-search-box .c-text-field') as HTMLInputElement | null;
  if (suggestInput?.value) {
    textSources.push(suggestInput.value);
  }

  const combinedText = textSources.join(' ');

  // キーワードマッチで会社IDを推定
  for (const [companyId, keywords] of Object.entries(keywordMap)) {
    if (keywords.some(kw => combinedText.includes(kw))) {
      console.log(`[Scout Assistant] Detected company: ${companyId} (keyword match in page text)`);
      return companyId;
    }
  }

  return null;
}
