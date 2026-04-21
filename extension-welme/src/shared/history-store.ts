/**
 * スカウト送信履歴ストア。chrome.storage.local 上で動く。
 *
 * サーバ非依存。1オペレーター1ブラウザ内の履歴のみ扱う。
 * 複数オペ間で履歴を共有したくなったら、別モジュールで同期層を
 * 足す（現状 v1 スコープでは不要）。
 *
 * テスト容易性のため、chrome.storage.local と同シグネチャの
 * StorageLike を受け取る factory 形式にしている。
 */

export interface HistoryEntry {
  memberId: string;
  age: string;
  qualifications: string;
  templateType: string;
  patternType: string;
  sentAt: string; // ISO8601
  body: string;
}

export interface StorageLike {
  get(keys: string | string[]): Promise<Record<string, unknown>>;
  set(items: Record<string, unknown>): Promise<void>;
  remove(keys: string | string[]): Promise<void>;
}

export interface HistoryStore {
  list(): Promise<HistoryEntry[]>;
  add(entry: HistoryEntry): Promise<void>;
  clear(): Promise<void>;
  toCsv(): Promise<string>;
  lastSentAt(): Promise<string | null>;
  countToday(): Promise<number>;
}

const STORAGE_KEY = 'scout_history_v1';

export function createHistoryStore(storage: StorageLike): HistoryStore {
  async function readAll(): Promise<HistoryEntry[]> {
    const raw = await storage.get(STORAGE_KEY);
    const v = raw[STORAGE_KEY];
    return Array.isArray(v) ? (v as HistoryEntry[]) : [];
  }

  async function writeAll(entries: HistoryEntry[]): Promise<void> {
    await storage.set({ [STORAGE_KEY]: entries });
  }

  return {
    async list() {
      const entries = await readAll();
      return [...entries].sort((a, b) => (a.sentAt < b.sentAt ? 1 : -1));
    },

    async add(entry) {
      const entries = await readAll();
      const filtered = entries.filter((e) => e.memberId !== entry.memberId);
      filtered.push(entry);
      await writeAll(filtered);
    },

    async clear() {
      await storage.remove(STORAGE_KEY);
    },

    async toCsv() {
      const entries = await readAll();
      const sorted = [...entries].sort((a, b) => (a.sentAt < b.sentAt ? 1 : -1));
      const headers = ['会員番号', '年齢', '資格', 'テンプレ', '型', '日時', '本文'];
      const rows = sorted.map((e) => [
        e.memberId,
        e.age,
        e.qualifications,
        e.templateType,
        e.patternType,
        e.sentAt,
        e.body,
      ]);
      return [headers, ...rows].map(csvRow).join('\n') + '\n';
    },

    async lastSentAt() {
      const entries = await readAll();
      if (entries.length === 0) return null;
      return entries
        .map((e) => e.sentAt)
        .sort()
        .pop() ?? null;
    },

    async countToday() {
      const entries = await readAll();
      const today = new Date();
      const y = today.getFullYear();
      const m = today.getMonth();
      const d = today.getDate();
      return entries.filter((e) => {
        const sent = new Date(e.sentAt);
        return (
          sent.getFullYear() === y &&
          sent.getMonth() === m &&
          sent.getDate() === d
        );
      }).length;
    },
  };
}

function csvRow(cells: string[]): string {
  return cells.map(csvCell).join(',');
}

function csvCell(value: string): string {
  // 常に quote して改行含むcellも安全に扱う。中の " は "" にエスケープ。
  const escaped = value.replace(/"/g, '""');
  return `"${escaped}"`;
}
