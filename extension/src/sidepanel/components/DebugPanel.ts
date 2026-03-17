import { DebugLogEntry } from '../../shared/types';
import { escapeHtml } from '../../shared/utils';

export class DebugPanel {
  private panelEl: HTMLElement;
  private entriesEl: HTMLElement;

  constructor() {
    this.panelEl = document.getElementById('debug-log-panel')!;
    this.entriesEl = document.getElementById('debug-log-entries')!;

    document.getElementById('btn-clear-debug')?.addEventListener('click', () => this.clear());
  }

  addEntry(entry: DebugLogEntry): void {
    const div = document.createElement('div');
    div.className = `debug-entry ${entry.status}`;

    const icon = entry.status === 'pending' ? '\u{1F535}' :
                 entry.status === 'success' ? '\u2705' : '\u274C';

    const time = new Date(entry.timestamp).toLocaleTimeString('ja-JP');
    div.innerHTML = `
      <span class="debug-time">${time}</span>
      <span class="debug-icon">${icon}</span>
      <span class="debug-step">${escapeHtml(entry.step)}</span>
      ${entry.detail ? `<span class="debug-detail">${escapeHtml(entry.detail)}</span>` : ''}
    `;
    this.entriesEl.appendChild(div);
    this.entriesEl.scrollTop = this.entriesEl.scrollHeight;
  }

  clear(): void {
    this.entriesEl.innerHTML = '';
  }

  toggle(visible: boolean): void {
    if (visible) {
      this.panelEl.classList.remove('hidden');
    } else {
      this.panelEl.classList.add('hidden');
    }
  }

}
