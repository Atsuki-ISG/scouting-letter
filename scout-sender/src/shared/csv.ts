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
