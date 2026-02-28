/** シンプルなYAMLシリアライザ（外部ライブラリ不使用） */

/**
 * JavaScriptオブジェクトをYAML文字列に変換
 */
export function toYAML(obj: Record<string, unknown>): string {
  return serializeValue(obj, 0).trimStart();
}

function serializeValue(value: unknown, indent: number): string {
  if (value === null || value === undefined) {
    return 'null';
  }
  if (typeof value === 'boolean') {
    return String(value);
  }
  if (typeof value === 'number') {
    return String(value);
  }
  if (typeof value === 'string') {
    return serializeString(value, indent);
  }
  if (Array.isArray(value)) {
    return serializeArray(value, indent);
  }
  if (typeof value === 'object') {
    return serializeObject(value as Record<string, unknown>, indent);
  }
  return String(value);
}

function serializeString(value: string, indent: number): string {
  if (value.includes('\n')) {
    const pad = '  '.repeat(indent + 1);
    const lines = value.split('\n').map((line) => pad + line).join('\n');
    return '|\n' + lines;
  }
  if (needsQuoting(value)) {
    return '"' + value.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
  }
  return '"' + value + '"';
}

function needsQuoting(value: string): boolean {
  if (value === '') return true;
  if (value === 'true' || value === 'false' || value === 'null') return true;
  if (/^[\d.]+$/.test(value)) return true;
  if (/[:#{}[\],&*?|>!'%@`]/.test(value)) return true;
  return false;
}

function serializeArray(arr: unknown[], indent: number): string {
  if (arr.length === 0) return '[]';
  const pad = '  '.repeat(indent);
  const lines = arr.map((item) => {
    if (typeof item === 'object' && item !== null && !Array.isArray(item)) {
      const obj = item as Record<string, unknown>;
      const keys = Object.keys(obj);
      if (keys.length === 0) return `${pad}- {}`;
      const firstKey = keys[0];
      const firstVal = serializeValue(obj[firstKey], indent + 1);
      let result = `${pad}- ${firstKey}: ${firstVal}`;
      for (let i = 1; i < keys.length; i++) {
        const val = serializeValue(obj[keys[i]], indent + 1);
        result += `\n${pad}  ${keys[i]}: ${val}`;
      }
      return result;
    }
    return `${pad}- ${serializeValue(item, indent + 1)}`;
  });
  return '\n' + lines.join('\n');
}

function serializeObject(obj: Record<string, unknown>, indent: number): string {
  const keys = Object.keys(obj);
  if (keys.length === 0) return '{}';
  const pad = '  '.repeat(indent);
  const lines = keys.map((key) => {
    const val = obj[key];
    if (typeof val === 'object' && val !== null && !Array.isArray(val)) {
      const nested = serializeObject(val as Record<string, unknown>, indent + 1);
      return `${pad}${key}:\n${nested}`;
    }
    return `${pad}${key}: ${serializeValue(val, indent)}`;
  });
  return (indent === 0 ? '' : '\n') + lines.join('\n');
}

/**
 * YAMLをBlobとしてダウンロード
 */
export function downloadYAML(yamlContent: string, filename: string): void {
  const blob = new Blob([yamlContent], { type: 'text/yaml;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
