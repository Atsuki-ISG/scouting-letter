import { storage } from '../../shared/storage';
import { apiClient, GenerateOptions, GenerateResponse } from '../../shared/api-client';
import { CandidateList } from './CandidateList';
import { CandidateProfile, CandidateItem } from '../../shared/types';

export class GeneratePanel {
  private candidateList: CandidateList;
  private container: HTMLElement;
  private btnGenerate: HTMLButtonElement;
  private optionResend: HTMLInputElement;
  private optionSeishain: HTMLInputElement;
  private progressSection: HTMLElement;
  private progressText: HTMLElement;
  private progressFill: HTMLElement;
  private resultSummary: HTMLElement;
  private isGenerating = false;

  constructor(candidateList: CandidateList) {
    this.candidateList = candidateList;
    this.container = document.getElementById('panel-generate') as HTMLElement;
    this.btnGenerate = document.getElementById('btn-api-generate') as HTMLButtonElement;
    this.optionResend = document.getElementById('option-resend') as HTMLInputElement;
    this.optionSeishain = document.getElementById('option-seishain') as HTMLInputElement;
    this.progressSection = document.getElementById('generate-progress') as HTMLElement;
    this.progressText = document.getElementById('generate-progress-text') as HTMLElement;
    this.progressFill = document.getElementById('generate-progress-fill') as HTMLElement;
    this.resultSummary = document.getElementById('generate-result-summary') as HTMLElement;

    this.btnGenerate.addEventListener('click', () => this.generate());
    this.updateProfileCount();

    // Listen for extraction completion to update count
    chrome.storage.onChanged.addListener((changes) => {
      if (changes[/* STORAGE_KEYS.EXTRACTED_PROFILES key */ 'scout_extracted_profiles']) {
        this.updateProfileCount();
      }
    });
  }

  private async updateProfileCount(): Promise<void> {
    const profiles = await storage.getExtractedProfiles();
    const countEl = document.getElementById('generate-profile-count');
    if (countEl) {
      countEl.textContent = String(profiles.length);
    }
    this.btnGenerate.disabled = profiles.length === 0;
  }

  private async generate(): Promise<void> {
    if (this.isGenerating) return;
    this.isGenerating = true;

    const profiles = await storage.getExtractedProfiles();
    if (profiles.length === 0) {
      alert('抽出済みプロフィールがありません。先に抽出タブでプロフィールを抽出してください。');
      this.isGenerating = false;
      return;
    }

    const company = await storage.getCompany();
    const options: GenerateOptions = {
      is_resend: this.optionResend.checked,
      force_seishain: this.optionSeishain.checked,
    };

    this.btnGenerate.disabled = true;
    this.btnGenerate.textContent = '生成中...';
    this.progressSection.classList.remove('hidden');
    this.resultSummary.classList.add('hidden');
    this.progressFill.style.width = '0%';
    this.progressText.textContent = `生成中... 0/${profiles.length}`;

    try {
      const response = await apiClient.generateBatch(company, profiles, options);

      // Update progress to 100%
      this.progressFill.style.width = '100%';
      this.progressText.textContent = `完了 ${profiles.length}/${profiles.length}`;

      // Count errors within results
      const errorResults = response.results.filter(
        (r: GenerateResponse) => r.generation_path === 'filtered_out' && r.filter_reason?.startsWith('生成エラー')
      );

      // Show summary
      const s = response.summary;
      this.resultSummary.classList.remove('hidden');
      this.resultSummary.innerHTML = `
        <div class="summary-stats">
          合計: ${s.total} / AI生成: ${s.ai_generated} / 型はめ: ${s.pattern_matched} / 除外: ${s.filtered_out}
          ${errorResults.length > 0 ? `<br><span style="color:#dc2626">⚠ ${errorResults.length}件でエラー発生</span>` : ''}
        </div>
      `;

      // Convert all results to CandidateItems (filtered_out as skipped)
      const candidates: CandidateItem[] = response.results.map((r: GenerateResponse) => {
        if (r.generation_path === 'filtered_out') {
          return {
            member_id: r.member_id,
            label: `[除外] ${r.filter_reason || '対象外'}`,
            status: 'skipped' as const,
            personalized_text: '',
            full_scout_text: '',
            template_type: r.template_type || '',
          };
        }
        return {
          member_id: r.member_id,
          label: `${r.template_type} ${(r.personalized_text || '').slice(0, 30)}...`,
          status: 'ready' as const,
          personalized_text: r.personalized_text,
          full_scout_text: r.full_scout_text,
          template_type: r.template_type,
        };
      });

      if (candidates.length > 0) {
        await this.candidateList.setCandidates(candidates);
      }

    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      const isTimeout = err instanceof DOMException && err.name === 'AbortError';
      const displayMessage = isTimeout ? 'タイムアウト。サーバーの応答に時間がかかりすぎています' : message;
      this.progressText.textContent = '';
      this.resultSummary.classList.remove('hidden');
      this.resultSummary.innerHTML = `<div style="color:#dc2626;font-weight:600">⚠ ${displayMessage}</div>`;
    } finally {
      this.isGenerating = false;
      this.btnGenerate.disabled = false;
      this.btnGenerate.textContent = '一括生成';
    }
  }
}
