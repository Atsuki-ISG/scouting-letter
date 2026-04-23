/**
 * WelMe (kaigojob.com) DOM 操作レイヤー。
 *
 * MediumAdapter 抽象は削除し、直接の関数群として提供する。
 * この拡張は WelMe 専用なので媒体分岐の必要がない。
 *
 * 2026-04-21 実機調査ベース。ブランド名は「ウェルミージョブ」、
 * 実ドメインは旧カイゴジョブの kaigojob.com を継続使用。
 */

import { emptyCandidateProfile, type CandidateProfile } from '../../shared/types';

const HOST_RE = /^https?:\/\/([a-z0-9-]+\.)?(kaigojob\.com|welme\.jp)(\/|$)/i;

const DL_SELECTOR = 'dl.c-definition__list';
const CANDIDATE_TABLE_SELECTOR = 'table.scout__index-table';
const TEXTAREA_SELECTOR = '#scout-talk-message-input';

export interface CandidateHandle {
  memberId: string;
  element: HTMLElement;
}

export function matchUrl(url: string): boolean {
  return HOST_RE.test(url);
}

export function getCandidateList(): CandidateHandle[] {
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
}

export async function extractProfile(): Promise<CandidateProfile> {
  const dl = document.querySelector<HTMLDListElement>(DL_SELECTOR);
  if (!dl) return emptyCandidateProfile();

  const values = readDefinitionList(dl);
  const profile = emptyCandidateProfile();

  profile.member_id = (values['ID'] || '').trim();

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
}

export function getComposeTextarea(): HTMLTextAreaElement | null {
  return document.querySelector<HTMLTextAreaElement>(TEXTAREA_SELECTOR);
}

export function getSendButton(): HTMLButtonElement | null {
  return (
    Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent?.trim() === '送信'
    ) ?? null
  );
}

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

/** 「神奈川県藤沢市: 30-34歳 男性」を分解 */
function parseBasicInfo(basic: string): BasicInfo {
  if (!basic) return { area: '', age: '', gender: '' };
  const parts = basic.split(/[:：]/);
  if (parts.length < 2) return { area: basic.trim(), age: '', gender: '' };
  const area = parts[0].trim();
  const rest = parts.slice(1).join(':').trim();
  const m = rest.match(/^(\S+歳)\s*(.*)$/);
  if (m) return { area, age: m[1].trim(), gender: m[2].trim() };
  return { area, age: rest, gender: '' };
}

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
