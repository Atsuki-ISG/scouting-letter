import { ScoutEntry, CandidateItem, SCOUT_CSV_COLUMNS } from '../../shared/types';
import { parseCSV, readCSVFile } from '../../shared/csv';
import { buildFullScoutText } from '../../shared/templates';
import { CandidateList } from './CandidateList';

export class ImportPanel {
  private candidateList: CandidateList;
  private btnImport: HTMLButtonElement;
  private btnTogglePaste: HTMLButtonElement;
  private btnPasteImport: HTMLButtonElement;
  private btnClear: HTMLButtonElement;
  private pasteSection: HTMLElement;
  private pasteTextarea: HTMLTextAreaElement;

  constructor(candidateList: CandidateList) {
    this.candidateList = candidateList;
    this.btnImport = document.getElementById('btn-import-csv') as HTMLButtonElement;
    this.btnTogglePaste = document.getElementById('btn-toggle-paste') as HTMLButtonElement;
    this.btnPasteImport = document.getElementById('btn-paste-import') as HTMLButtonElement;
    this.btnClear = document.getElementById('btn-clear-candidates') as HTMLButtonElement;
    this.pasteSection = document.getElementById('paste-import') as HTMLElement;
    this.pasteTextarea = document.getElementById('paste-csv') as HTMLTextAreaElement;

    this.btnImport.addEventListener('click', () => this.importCSV());
    this.btnTogglePaste.addEventListener('click', () => this.togglePaste());
    this.btnPasteImport.addEventListener('click', () => this.importFromPaste());
    this.btnClear.addEventListener('click', () => this.clearCandidates());
  }

  private async importCSV(): Promise<void> {
    try {
      const csvText = await readCSVFile();
      const entries = parseCSV<ScoutEntry>(csvText);

      if (entries.length === 0) {
        alert('CSVにデータが含まれていません');
        return;
      }

      // ScoutEntryをCandidateItemに変換
      const candidates: CandidateItem[] = entries.map((entry) => ({
        member_id: entry.member_id,
        label: this.createLabel(entry),
        status: 'ready' as const,
        personalized_text: entry.personalized_text,
        full_scout_text: entry.full_scout_text,
        template_type: entry.template_type,
      }));

      await this.candidateList.setCandidates(candidates);
    } catch (err) {
      if (err instanceof Error && err.message !== 'ファイルが選択されませんでした') {
        alert(`インポートエラー: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
  }

  private togglePaste(): void {
    this.pasteSection.classList.toggle('hidden');
  }

  private async importFromPaste(): Promise<void> {
    try {
      let csvText = this.pasteTextarea.value.trim();
      if (!csvText) {
        alert('CSVを貼り付けてください');
        return;
      }

      // コードブロック記法（```csv ... ``` や ``` ... ```）を除去
      csvText = csvText.replace(/^```(?:csv)?\s*\n?/, '').replace(/\n?```\s*$/, '');

      const entries = parseCSV<ScoutEntry>(csvText);

      if (entries.length === 0) {
        alert('CSVにデータが含まれていません');
        return;
      }

      const candidates: CandidateItem[] = entries.map((entry) => ({
        member_id: entry.member_id,
        label: this.createLabel(entry),
        status: 'ready' as const,
        personalized_text: entry.personalized_text,
        full_scout_text: entry.full_scout_text,
        template_type: entry.template_type,
      }));

      await this.candidateList.setCandidates(candidates);
      this.pasteTextarea.value = '';
      this.pasteSection.classList.add('hidden');
    } catch (err) {
      alert(`インポートエラー: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  private createLabel(entry: ScoutEntry): string {
    // パーソナライズ文の先頭を使ってラベル生成
    const preview = entry.personalized_text?.slice(0, 30) || '';
    return `${entry.template_type || ''} ${preview}...`.trim();
  }

  private async clearCandidates(): Promise<void> {
    if (confirm('候補者リストをクリアしますか？')) {
      await this.candidateList.clearCandidates();
    }
  }
}
