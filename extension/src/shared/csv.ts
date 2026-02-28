/** CSV読み書きユーティリティ（UTF-8 BOM対応） */

const BOM = '\uFEFF';

/** 値をCSVセルとしてエスケープ */
function escapeCell(value: string): string {
  if (value.includes(',') || value.includes('"') || value.includes('\n') || value.includes('\r')) {
    return '"' + value.replace(/"/g, '""') + '"';
  }
  return value;
}

/** オブジェクト配列をCSV文字列に変換（UTF-8 BOM付き） */
export function toCSV<T>(
  rows: T[],
  columns: (keyof T & string)[]
): string {
  const header = columns.map((c) => String(c)).join(',');
  const body = rows
    .map((row) => columns.map((col) => escapeCell(String((row as Record<string, unknown>)[col] ?? ''))).join(','))
    .join('\n');
  return BOM + header + '\n' + body;
}

/** CSV文字列をオブジェクト配列にパース */
export function parseCSV<T>(csv: string): T[] {
  // BOM除去
  const text = csv.replace(/^\uFEFF/, '');
  const lines = parseCSVLines(text);
  if (lines.length < 2) return [];

  const headers = lines[0];
  return lines.slice(1).map((cells) => {
    const obj: Record<string, string> = {};
    headers.forEach((h, i) => {
      obj[h] = cells[i] || '';
    });
    return obj as T;
  });
}

/** CSV行をパース（クォート対応） */
function parseCSVLines(text: string): string[][] {
  const results: string[][] = [];
  let current: string[] = [];
  let cell = '';
  let inQuotes = false;
  let i = 0;

  while (i < text.length) {
    const ch = text[i];

    if (inQuotes) {
      if (ch === '"') {
        if (i + 1 < text.length && text[i + 1] === '"') {
          cell += '"';
          i += 2;
        } else {
          inQuotes = false;
          i++;
        }
      } else {
        cell += ch;
        i++;
      }
    } else {
      if (ch === '"') {
        inQuotes = true;
        i++;
      } else if (ch === ',') {
        current.push(cell);
        cell = '';
        i++;
      } else if (ch === '\r' || ch === '\n') {
        current.push(cell);
        cell = '';
        if (ch === '\r' && i + 1 < text.length && text[i + 1] === '\n') {
          i++;
        }
        if (current.some((c) => c !== '')) {
          results.push(current);
        }
        current = [];
        i++;
      } else {
        cell += ch;
        i++;
      }
    }
  }

  // 最終行
  current.push(cell);
  if (current.some((c) => c !== '')) {
    results.push(current);
  }

  return results;
}

/** CSVをBlobとしてダウンロード */
export function downloadCSV(csvContent: string, filename: string): void {
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** ファイル選択ダイアログからCSVを読み込み */
export function readCSVFile(): Promise<string> {
  return new Promise((resolve, reject) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.csv';
    input.onchange = () => {
      const file = input.files?.[0];
      if (!file) {
        reject(new Error('ファイルが選択されませんでした'));
        return;
      }
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = () => reject(reader.error);
      reader.readAsText(file, 'utf-8');
    };
    input.click();
  });
}
