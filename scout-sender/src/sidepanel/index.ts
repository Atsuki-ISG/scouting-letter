import { CandidateProfile, PROFILE_CSV_COLUMNS, Message } from '../shared/types';
import { toCSV, downloadCSV } from '../shared/csv';
import { storage } from '../shared/storage';

/** 抽出パネル管理 */
class ExtractionPanel {
  private profiles: CandidateProfile[] = [];
  private extracting = false;

  private btnStart: HTMLButtonElement;
  private btnStop: HTMLButtonElement;
  private btnDownload: HTMLButtonElement;
  private extractStart: HTMLInputElement;
  private extractCount: HTMLInputElement;
  private progressSection: HTMLElement;
  private progressCurrent: HTMLElement;
  private progressTotal: HTMLElement;
  private progressFill: HTMLElement;
  private extractedList: HTMLElement;

  constructor() {
    this.btnStart = document.getElementById('btn-start-extract') as HTMLButtonElement;
    this.btnStop = document.getElementById('btn-stop-extract') as HTMLButtonElement;
    this.btnDownload = document.getElementById('btn-download-csv') as HTMLButtonElement;
    this.extractStart = document.getElementById('extract-start') as HTMLInputElement;
    this.extractCount = document.getElementById('extract-count') as HTMLInputElement;
    this.progressSection = document.getElementById('extraction-progress')!;
    this.progressCurrent = document.getElementById('progress-current')!;
    this.progressTotal = document.getElementById('progress-total')!;
    this.progressFill = document.getElementById('progress-fill')!;
    this.extractedList = document.getElementById('extracted-list')!;

    this.btnStart.addEventListener('click', () => this.startExtraction());
    this.btnStop.addEventListener('click', () => this.stopExtraction());
    this.btnDownload.addEventListener('click', () => this.downloadCSV());

    chrome.runtime.onMessage.addListener((msg: Message) => {
      switch (msg.type) {
        case 'EXTRACTION_PROGRESS':
          this.onProgress(msg.current, msg.total, msg.profile);
          break;
        case 'EXTRACTION_COMPLETE':
          this.onComplete(msg.profiles);
          break;
        case 'EXTRACTION_ERROR':
          this.onError(msg.error);
          break;
      }
    });

    this.restoreProfiles();
  }

  private async restoreProfiles(): Promise<void> {
    this.profiles = await storage.getExtractedProfiles();
    if (this.profiles.length > 0) {
      this.renderExtractedList();
      this.btnDownload.classList.remove('hidden');
    }
  }

  private async startExtraction(): Promise<void> {
    if (this.extracting) return;

    const count = parseInt(this.extractCount.value, 10);
    if (isNaN(count) || count < 1) return;

    this.extracting = true;
    this.profiles = [];
    this.btnStart.classList.add('hidden');
    this.btnStop.classList.remove('hidden');
    this.progressSection.classList.remove('hidden');
    this.progressCurrent.textContent = '0';
    this.progressTotal.textContent = String(count);
    this.progressFill.style.width = '0%';
    this.extractedList.innerHTML = '';
    this.btnDownload.classList.add('hidden');

    const startMemberId = this.extractStart.value.trim() || undefined;

    chrome.runtime.sendMessage({
      type: 'START_EXTRACTION',
      count,
      startMemberId,
    } satisfies Message).catch(() => {});
  }

  private stopExtraction(): void {
    chrome.runtime.sendMessage({
      type: 'STOP_EXTRACTION',
    } satisfies Message).catch(() => {});
    this.onStopped();
  }

  private onStopped(): void {
    this.extracting = false;
    this.btnStop.classList.add('hidden');
    this.btnStart.classList.remove('hidden');
    if (this.profiles.length > 0) {
      this.btnDownload.classList.remove('hidden');
    }
  }

  private onProgress(current: number, total: number, profile: CandidateProfile): void {
    this.profiles.push(profile);
    this.progressCurrent.textContent = String(current);
    this.progressTotal.textContent = String(total);
    this.progressFill.style.width = `${(current / total) * 100}%`;
    this.appendExtractedItem(profile);
  }

  private async onComplete(profiles: CandidateProfile[]): Promise<void> {
    this.profiles = profiles;
    this.onStopped();
    await storage.setExtractedProfiles(profiles);
  }

  private onError(error: string): void {
    this.onStopped();
    alert(`抽出エラー: ${error}`);
  }

  private appendExtractedItem(profile: CandidateProfile): void {
    const div = document.createElement('div');
    div.className = 'extracted-item';
    div.innerHTML = `
      <div class="member-id">${this.escapeHtml(profile.member_id)}</div>
      <div class="extracted-info">
        ${this.escapeHtml(profile.qualifications || '資格情報なし')} /
        ${this.escapeHtml(profile.experience_years || '経験年数不明')}
      </div>
    `;
    this.extractedList.appendChild(div);
  }

  private renderExtractedList(): void {
    this.extractedList.innerHTML = '';
    for (const profile of this.profiles) {
      this.appendExtractedItem(profile);
    }
  }

  private downloadCSV(): void {
    if (this.profiles.length === 0) return;
    const csv = toCSV(this.profiles, PROFILE_CSV_COLUMNS);
    const now = new Date();
    const dateStr = now.toISOString().slice(0, 10);
    const timeStr = now.toTimeString().slice(0, 5).replace(':', '');
    downloadCSV(csv, `profiles_${dateStr}_${timeStr}.csv`);
  }

  private escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  new ExtractionPanel();
});
