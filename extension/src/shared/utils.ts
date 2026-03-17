/** HTML特殊文字をエスケープ */
export function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/** 指定ミリ秒待機 */
export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** ランダム揺らぎ付き待機（min〜maxミリ秒） */
export function randomSleep(min: number, max: number): Promise<void> {
  const ms = min + Math.floor(Math.random() * (max - min));
  return sleep(ms);
}
