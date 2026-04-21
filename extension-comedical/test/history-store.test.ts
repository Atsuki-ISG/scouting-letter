/**
 * history-store は chrome.storage.local 上にスカウト送信履歴を保持する。
 * サーバ非依存で、1オペレーター1ブラウザ内の履歴のみ扱う。
 */

import { describe, expect, it, beforeEach } from 'vitest';
import {
  createHistoryStore,
  type HistoryEntry,
  type StorageLike,
} from '../src/shared/history-store';

function makeMemoryStorage(): StorageLike {
  const mem = new Map<string, unknown>();
  return {
    async get(keys: string | string[]) {
      const arr = Array.isArray(keys) ? keys : [keys];
      const out: Record<string, unknown> = {};
      for (const k of arr) {
        if (mem.has(k)) out[k] = mem.get(k);
      }
      return out;
    },
    async set(items) {
      for (const [k, v] of Object.entries(items)) {
        mem.set(k, v);
      }
    },
    async remove(keys) {
      const arr = Array.isArray(keys) ? keys : [keys];
      for (const k of arr) mem.delete(k);
    },
  };
}

function sample(memberId: string, at = '2026-04-21T10:00:00+09:00'): HistoryEntry {
  return {
    memberId,
    age: '30歳',
    qualifications: '看護師',
    templateType: '正社員_初回',
    patternType: 'A',
    sentAt: at,
    body: '送信した本文',
  };
}

describe('history-store', () => {
  let storage: StorageLike;
  beforeEach(() => {
    storage = makeMemoryStorage();
  });

  it('空ストレージから list は空配列', async () => {
    const store = createHistoryStore(storage);
    expect(await store.list()).toEqual([]);
  });

  it('add したものが list に現れる', async () => {
    const store = createHistoryStore(storage);
    await store.add(sample('1001'));
    const list = await store.list();
    expect(list).toHaveLength(1);
    expect(list[0].memberId).toBe('1001');
  });

  it('複数add は新しい順（sentAt降順）で返る', async () => {
    const store = createHistoryStore(storage);
    await store.add(sample('1001', '2026-04-21T10:00:00+09:00'));
    await store.add(sample('1002', '2026-04-21T11:00:00+09:00'));
    await store.add(sample('1003', '2026-04-21T09:00:00+09:00'));
    const list = await store.list();
    expect(list.map((e) => e.memberId)).toEqual(['1002', '1001', '1003']);
  });

  it('同じ memberId は上書きされる（重複送信防止）', async () => {
    const store = createHistoryStore(storage);
    await store.add(sample('1001', '2026-04-21T10:00:00+09:00'));
    await store.add({ ...sample('1001', '2026-04-21T11:00:00+09:00'), templateType: '正社員_再送' });
    const list = await store.list();
    expect(list).toHaveLength(1);
    expect(list[0].templateType).toBe('正社員_再送');
  });

  it('clear で全削除', async () => {
    const store = createHistoryStore(storage);
    await store.add(sample('1001'));
    await store.add(sample('1002'));
    await store.clear();
    expect(await store.list()).toEqual([]);
  });

  it('toCsv で列ヘッダと各行を返す', async () => {
    const store = createHistoryStore(storage);
    await store.add(sample('1001'));
    const csv = await store.toCsv();
    const lines = csv.trim().split('\n');
    expect(lines[0]).toContain('会員番号');
    expect(lines[0]).toContain('日時');
    expect(lines[1]).toContain('1001');
  });

  it('toCsv は本文の改行・カンマ・ダブルクォートをエスケープ', async () => {
    const store = createHistoryStore(storage);
    await store.add({
      ...sample('1001'),
      body: 'ライン1\nライン2,"quoted"',
    });
    const csv = await store.toCsv();
    // データ行の本文セルは引用符で囲まれ、" は "" にエスケープ
    expect(csv).toContain('""quoted""');
    expect(csv.match(/"ライン1\nライン2/)).not.toBeNull();
  });

  it('lastSentAt は最新の sentAt を返す、空なら null', async () => {
    const store = createHistoryStore(storage);
    expect(await store.lastSentAt()).toBeNull();
    await store.add(sample('1001', '2026-04-20T10:00:00+09:00'));
    await store.add(sample('1002', '2026-04-21T10:00:00+09:00'));
    expect(await store.lastSentAt()).toBe('2026-04-21T10:00:00+09:00');
  });

  it('countToday は今日の送信数を返す', async () => {
    const store = createHistoryStore(storage);
    const today = new Date().toISOString();
    // 今日の送信
    await store.add(sample('1001', today));
    await store.add(sample('1002', today));
    // 昨日の送信
    const yesterday = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
    await store.add(sample('1003', yesterday));
    expect(await store.countToday()).toBe(2);
  });
});
