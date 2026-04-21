/**
 * WelMe (ウェルミージョブ) 向け MediumAdapter
 *
 * 実ドメインは kaigojob.com（旧カイゴジョブ時代のURLを継続使用）。
 * ブランド名は「ウェルミージョブ」。2026-04 実機調査ベースのセレクタ。
 *
 * WelMe の重要な前提:
 *  - 職務経歴・自己PR フィールドは存在しない（ジョブメドレーと違い）
 *    → 拡張は全部型はめで処理する設計と整合
 *  - 経験年数フィールドも無い → pattern_matcher に experience=null が渡り、
 *    自動的に D/F 系パターン（経験不明）にマッチする
 *  - 年齢は範囲表示（例「30-34歳」）→ parseAge が先頭数字で動くので問題なし
 *  - 就業状況: 「現職」欄の有無 + 「転職状況」文言で判定
 */

import {
  emptyCandidateProfile,
  type CandidateHandle,
  type MediumAdapter,
} from '../../shared/medium-adapter';
import type { CandidateProfile } from '../../shared/types';

const WELME_HOST_RE = /^https?:\/\/([a-z0-9-]+\.)?(kaigojob\.com|welme\.jp)(\/|$)/i;

const DL_SELECTOR = 'dl.c-definition__list';
const CANDIDATE_TABLE_SELECTOR = 'table.scout__index-table';

export const welmeAdapter: MediumAdapter = {
  id: 'welme',
  displayName: 'ウェルミージョブ',

  matchUrl(url: string): boolean {
    return WELME_HOST_RE.test(url);
  },

  getCandidateList(): CandidateHandle[] {
    const table = document.querySelector(CANDIDATE_TABLE_SELECTOR);
    if (!table) return [];
    const rows = Array.from(table.querySelectorAll<HTMLTableRowElement>('tbody tr'));
    return rows
      .map((row): CandidateHandle | null => {
        const memberId = extractMemberIdFromRow(row);
        if (!memberId) return null;
        return { memberId, element: row };
      })
      .filter((h): h is CandidateHandle => h !== null);
  },

  async extractProfile(): Promise<CandidateProfile> {
    const dl = document.querySelector<HTMLDListElement>(DL_SELECTOR);
    if (!dl) return emptyCandidateProfile();

    const values = readDefinitionList(dl);
    const profile = emptyCandidateProfile();

    profile.member_id = (values['ID'] || '').trim();

    // 基本情報: "神奈川県藤沢市: 30-34歳 男性"
    const basic = values['基本情報'] || '';
    const parsed = parseBasicInfo(basic);
    profile.area = parsed.area;
    profile.age = parsed.age;
    profile.gender = parsed.gender;

    profile.qualifications = (values['保有資格'] || '').trim();
    profile.desired_job = (values['希望職種'] || '').trim();
    profile.desired_area = normalizeSpaces(values['希望勤務地'] || '');
    profile.desired_employment_type = (values['希望雇用形態'] || '').trim();

    profile.employment_status = determineEmploymentStatus(
      values['現職'] || '',
      values['転職状況'] || ''
    );

    return profile;
  },

  getComposeTextarea(): HTMLTextAreaElement | null {
    return document.querySelector<HTMLTextAreaElement>('#scout-talk-message-input');
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extractMemberIdFromRow(row: HTMLElement): string | null {
  const text = row.textContent || '';
  const m = text.match(/ID\s+(\d+)/);
  return m ? m[1] : null;
}

function readDefinitionList(dl: HTMLDListElement): Record<string, string> {
  const result: Record<string, string> = {};
  const dts = dl.querySelectorAll('dt.c-definition__term');
  dts.forEach((dt) => {
    const key = dt.textContent?.trim();
    const dd = dt.nextElementSibling;
    if (key && dd && dd.tagName === 'DD') {
      result[key] = dd.textContent || '';
    }
  });
  return result;
}

interface BasicInfo {
  area: string;
  age: string;
  gender: string;
}

/**
 * 「神奈川県藤沢市: 30-34歳 男性」を分解。
 * 区切りは「:」「：」のいずれか。年齢の次の空白以降が性別。
 */
function parseBasicInfo(basic: string): BasicInfo {
  const empty = { area: '', age: '', gender: '' };
  if (!basic) return empty;
  const parts = basic.split(/[:：]/);
  if (parts.length < 2) return { area: basic.trim(), age: '', gender: '' };
  const area = parts[0].trim();
  const rest = parts.slice(1).join(':').trim();
  const m = rest.match(/^(\S+歳)\s*(.*)$/);
  if (m) {
    return { area, age: m[1].trim(), gender: m[2].trim() };
  }
  return { area, age: rest, gender: '' };
}

/** 複数空白・タブを半角スペース1個に圧縮し trim */
function normalizeSpaces(s: string): string {
  return s.replace(/[\s\t]+/g, ' ').trim();
}

/**
 * 「現職」欄と「転職状況」文言から就業中/離職中/在学中を判定。
 *  - 現職に値がある → 就業中
 *  - 転職状況に「在学中」を含む → 在学中
 *  - 転職状況に「辞めたい」「転職したい」「検討」を含む → 就業中
 *  - 転職状況に「求職中」「離職」を含む → 離職中
 *  - それ以外（空含む） → 離職中（デフォルト）
 */
function determineEmploymentStatus(genshoku: string, tenshoku: string): string {
  if (genshoku && genshoku.trim()) return '就業中';
  if (/在学/.test(tenshoku)) return '在学中';
  if (/辞めたい|転職したい|検討/.test(tenshoku)) return '就業中';
  if (/求職中|離職/.test(tenshoku)) return '離職中';
  return '離職中';
}
