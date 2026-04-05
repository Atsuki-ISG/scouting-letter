import { storage } from '../../shared/storage';
import { apiClient, GenerateOptions, GenerateResponse } from '../../shared/api-client';
import { configProvider } from '../../shared/config-provider';
import { CandidateList } from './CandidateList';
import { CandidateItem } from '../../shared/types';

export class GeneratePanel {
  private candidateList: CandidateList;
  private btnGenerate: HTMLButtonElement;
  private progressSection: HTMLElement;
  private progressText: HTMLElement;
  private progressFill: HTMLElement;
  private resultSummary: HTMLElement;
  private isGenerating = false;

  // Modal elements
  private modal: HTMLElement;
  private modalCompany: HTMLSelectElement;
  private modalEmployment: HTMLSelectElement;
  private modalJobCategory: HTMLSelectElement;
  private modalSendType: HTMLSelectElement;
  private modalProfileCount: HTMLElement;
  private modalPrevNotice: HTMLElement;

  constructor(candidateList: CandidateList) {
    this.candidateList = candidateList;
    this.btnGenerate = document.getElementById('btn-api-generate') as HTMLButtonElement;
    this.progressSection = document.getElementById('generate-progress') as HTMLElement;
    this.progressText = document.getElementById('generate-progress-text') as HTMLElement;
    this.progressFill = document.getElementById('generate-progress-fill') as HTMLElement;
    this.resultSummary = document.getElementById('generate-result-summary') as HTMLElement;

    // Modal
    this.modal = document.getElementById('generate-settings-modal') as HTMLElement;
    this.modalCompany = document.getElementById('gen-setting-company') as HTMLSelectElement;
    this.modalEmployment = document.getElementById('gen-setting-employment') as HTMLSelectElement;
    this.modalJobCategory = document.getElementById('gen-setting-job-category') as HTMLSelectElement;
    this.modalSendType = document.getElementById('gen-setting-send-type') as HTMLSelectElement;
    this.modalProfileCount = document.getElementById('gen-setting-profile-count') as HTMLElement;
    this.modalPrevNotice = document.getElementById('gen-settings-prev') as HTMLElement;

    this.btnGenerate.addEventListener('click', () => this.showModal());
    document.getElementById('gen-setting-cancel')!.addEventListener('click', () => this.hideModal());
    document.getElementById('gen-setting-start')!.addEventListener('click', () => this.confirmAndGenerate());
    // Close on backdrop click
    this.modal.querySelector('.confirmation-backdrop')!.addEventListener('click', () => this.hideModal());
    // Refresh dropdowns when company changes
    this.modalCompany.addEventListener('change', () => {
      this.populateJobCategories(this.modalCompany.value);
      this.populateEmploymentTypes(this.modalCompany.value);
    });

    this.updateProfileCount();

    chrome.storage.onChanged.addListener((changes) => {
      if (changes['scout_extracted_profiles']) {
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

  private async showModal(): Promise<void> {
    if (this.isGenerating) return;

    const profiles = await storage.getExtractedProfiles();
    if (profiles.length === 0) {
      alert('抽出済みプロフィールがありません。先に抽出タブでプロフィールを抽出してください。');
      return;
    }

    // Populate company dropdown from header select
    const headerCompany = document.getElementById('company') as HTMLSelectElement;
    this.modalCompany.innerHTML = headerCompany.innerHTML;
    this.modalCompany.value = headerCompany.value;

    // Profile count
    this.modalProfileCount.textContent = String(profiles.length);

    // Populate dropdowns from API
    await Promise.all([
      this.populateJobCategories(this.modalCompany.value),
      this.populateEmploymentTypes(this.modalCompany.value),
    ]);

    // Restore previous settings
    const prev = await storage.getGenerateSettings();
    if (prev) {
      this.modalEmployment.value = prev.employment_type;
      this.modalJobCategory.value = prev.job_category || '';
      this.modalSendType.value = prev.send_type;
      this.modalPrevNotice.classList.remove('hidden');
    } else {
      this.modalEmployment.value = 'auto';
      this.modalJobCategory.value = '';
      this.modalSendType.value = 'initial';
      this.modalPrevNotice.classList.add('hidden');
    }

    this.modal.classList.remove('hidden');
  }

  private hideModal(): void {
    this.modal.classList.add('hidden');
  }

  private async populateJobCategories(companyId: string): Promise<void> {
    const savedValue = this.modalJobCategory.value;
    // Keep only the first option (全職種)
    while (this.modalJobCategory.options.length > 1) {
      this.modalJobCategory.remove(1);
    }
    try {
      const config = await configProvider.getCompanyConfig(companyId);
      if (config?.job_categories && config.job_categories.length > 0) {
        for (const jc of config.job_categories) {
          const option = document.createElement('option');
          option.value = jc.id;
          option.textContent = jc.display_name;
          this.modalJobCategory.appendChild(option);
        }
      }
    } catch { /* API failure: show only 全職種 */ }
    // Restore previous selection if still available
    this.modalJobCategory.value = savedValue;
    if (this.modalJobCategory.selectedIndex === -1) {
      this.modalJobCategory.value = '';
    }
  }

  private async populateEmploymentTypes(companyId: string): Promise<void> {
    const savedValue = this.modalEmployment.value;
    // Keep only the first option (自動判定)
    while (this.modalEmployment.options.length > 1) {
      this.modalEmployment.remove(1);
    }
    try {
      const config = await configProvider.getCompanyConfig(companyId);
      if (config?.employment_types && config.employment_types.length > 0) {
        for (const et of config.employment_types) {
          const option = document.createElement('option');
          option.value = et.id;
          option.textContent = et.display_name;
          this.modalEmployment.appendChild(option);
        }
      }
    } catch { /* API failure: show only 自動判定 */ }
    // Restore previous selection if still available
    this.modalEmployment.value = savedValue;
    if (this.modalEmployment.selectedIndex === -1) {
      this.modalEmployment.value = 'auto';
    }
  }

  private async confirmAndGenerate(): Promise<void> {
    const employment = this.modalEmployment.value;
    const jobCategory = this.modalJobCategory.value;
    const sendType = this.modalSendType.value;
    const company = this.modalCompany.value;

    // Save settings for next time
    await storage.setGenerateSettings({
      employment_type: employment,
      send_type: sendType,
      job_category: jobCategory,
    });

    // Sync company selection back to header
    const headerCompany = document.getElementById('company') as HTMLSelectElement;
    if (headerCompany.value !== company) {
      headerCompany.value = company;
      await storage.setCompany(company);
    }

    this.hideModal();

    // Build options
    const options: GenerateOptions = {
      is_resend: sendType === 'resend',
      force_employment: employment === 'auto' ? undefined : employment,
      job_category_filter: jobCategory || undefined,
    };

    await this.generate(company, options);
  }

  private async generate(company: string, options: GenerateOptions): Promise<void> {
    if (this.isGenerating) return;
    this.isGenerating = true;

    const profiles = await storage.getExtractedProfiles();

    this.btnGenerate.disabled = true;
    this.btnGenerate.textContent = '生成中...';
    this.progressSection.classList.remove('hidden');
    this.resultSummary.classList.add('hidden');
    this.progressFill.style.width = '0%';
    this.progressFill.classList.add('active');
    this.progressText.textContent = `生成中... 0/${profiles.length}`;

    try {
      const response = await apiClient.generateBatch(company, profiles, options);

      this.progressFill.style.width = '100%';
      this.progressText.textContent = `完了 ${profiles.length}/${profiles.length}`;

      const errorResults = response.results.filter(
        (r: GenerateResponse) => r.generation_path === 'filtered_out' && r.filter_reason?.startsWith('生成エラー')
      );

      const s = response.summary;
      this.resultSummary.classList.remove('hidden');
      this.resultSummary.innerHTML = `
        <div class="summary-stats">
          合計: ${s.total} / AI生成: ${s.ai_generated} / 型はめ: ${s.pattern_matched} / 除外: ${s.filtered_out}
          ${errorResults.length > 0 ? `<br><span style="color:#b45309">⚠ うち${errorResults.length}件は生成できませんでした</span>` : ''}
        </div>
      `;

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
          job_category: r.job_category,
          is_favorite: r.is_favorite,
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
      this.progressFill.classList.remove('active');
      this.btnGenerate.disabled = false;
      this.btnGenerate.textContent = '一括生成';
    }
  }
}
