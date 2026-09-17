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
  private isOpeningModal = false;
  /** 最新の populateDropdowns 呼び出しだけがDOMを書き換えるようにするための世代番号 */
  private dropdownToken = 0;

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
      void this.populateDropdowns(this.modalCompany.value);
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
    // 設定取得の待ち時間中にボタンを連打されると、選択肢が候補の数だけ重複する。
    // 開いている最中は再入させない（ボタンも押せなくする）。
    if (this.isGenerating || this.isOpeningModal) return;
    this.isOpeningModal = true;
    this.btnGenerate.disabled = true;

    try {
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
      await this.populateDropdowns(this.modalCompany.value);

      // Restore previous settings
      const prev = await storage.getGenerateSettings();
      if (prev) {
        this.modalEmployment.value = prev.employment_type;
        this.modalJobCategory.value = prev.job_category || '';
        this.modalSendType.value = prev.send_type;
        if (this.modalEmployment.selectedIndex === -1) {
          this.modalEmployment.value = 'auto';
        }
        if (this.modalSendType.selectedIndex === -1) {
          this.modalSendType.value = 'auto';
        }
        this.modalPrevNotice.classList.remove('hidden');
      } else {
        this.modalEmployment.value = 'auto';
        this.modalJobCategory.value = '';
        this.modalSendType.value = 'auto';
        this.modalPrevNotice.classList.add('hidden');
      }

      this.modal.classList.remove('hidden');
    } finally {
      this.isOpeningModal = false;
      // 抽出件数に応じた本来の disabled 状態に戻す
      void this.updateProfileCount();
    }
  }

  private hideModal(): void {
    this.modal.classList.add('hidden');
  }

  /**
   * 職種・雇用形態のプルダウンを会社設定から作り直す。
   *
   * 取得を待ってから一気に差し替える（クリアしてから待たない）。
   * 途中で別の呼び出しが始まったら、古い方は世代番号で弾いてDOMに触れない。
   * こうしないと複数呼び出しが重なったとき選択肢が重複して並ぶ。
   */
  private async populateDropdowns(companyId: string): Promise<void> {
    const token = ++this.dropdownToken;
    const savedJobCategory = this.modalJobCategory.value;
    const savedEmployment = this.modalEmployment.value;

    let config = null;
    try {
      config = await configProvider.getCompanyConfig(companyId);
    } catch { /* API failure: 先頭の選択肢だけ残す */ }

    if (token !== this.dropdownToken) return; // 新しい呼び出しに追い越された

    this.fillSelect(this.modalJobCategory, config?.job_categories, savedJobCategory, '');
    this.fillSelect(this.modalEmployment, config?.employment_types, savedEmployment, 'auto');
  }

  /** 先頭の選択肢（プレースホルダー／自動判定）を残して中身を入れ替える */
  private fillSelect(
    select: HTMLSelectElement,
    items: Array<{ id: string; display_name: string }> | undefined,
    savedValue: string,
    fallbackValue: string,
  ): void {
    while (select.options.length > 1) {
      select.remove(1);
    }
    for (const item of items || []) {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = item.display_name;
      select.appendChild(option);
    }
    // Restore previous selection if still available
    select.value = savedValue;
    if (select.selectedIndex === -1) {
      select.value = fallbackValue;
    }
  }

  private async confirmAndGenerate(): Promise<void> {
    const employment = this.modalEmployment.value;
    const jobCategory = this.modalJobCategory.value;
    const sendType = this.modalSendType.value;
    const company = this.modalCompany.value;

    if (!jobCategory) {
      alert('職種を選択してください');
      this.modalJobCategory.focus();
      return;
    }

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
    // send_type: "auto" は候補者ごとにスカウト送信日で初回/再送を判定。
    // is_resend は旧サーバへのフォールバック用に併送する。
    const options: GenerateOptions = {
      is_resend: sendType === 'resend',
      send_type: sendType,
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
      // チャンク分割で /generate/batch を順次呼ぶ。各チャンク内はサーバ側で並列処理。
      // 単発 /generate を高並列で叩くと Cloud Run のインスタンス数が追い付かず
      // 503/timeout が量産される (10並列で 25件中 22件失敗を観測)。バッチ経由なら
      // 1 HTTP リクエスト＝1 インスタンスで完結するため詰まらない。
      // CHUNK_SIZE = サーバ内並列度の MAX_BATCH_CONCURRENCY に揃えた。
      const CHUNK_SIZE = 10;
      const total = profiles.length;
      const results: GenerateResponse[] = [];
      let done = 0;

      for (let i = 0; i < total; i += CHUNK_SIZE) {
        const slice = profiles.slice(i, i + CHUNK_SIZE);
        try {
          const resp = await apiClient.generateBatch(company, slice, options);
          results.push(...resp.results);
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          // バッチごと失敗 → スライス内全員を「生成エラー」として記録
          for (const p of slice) {
            results.push({
              member_id: p.member_id,
              template_type: '',
              generation_path: 'filtered_out',
              personalized_text: '',
              full_scout_text: '',
              validation_warnings: [],
              filter_reason: `生成エラー: ${msg}`,
            });
          }
        }
        done += slice.length;
        this.progressFill.style.width = `${(done / total) * 100}%`;
        this.progressText.textContent = `生成中... ${done}/${total}`;
      }

      // クライアント側で summary を再構築 (サーババッチと同じ形)
      const summary = {
        total,
        ai_generated: results.filter(r => r.generation_path === 'ai').length,
        pattern_matched: results.filter(r => r.generation_path === 'pattern').length,
        filtered_out: results.filter(r => r.generation_path === 'filtered_out').length,
      };
      const response = { results, summary };

      this.progressFill.style.width = '100%';
      this.progressText.textContent = `完了 ${done}/${total}`;

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
        const apiWarnings = (r.validation_warnings || []).map((msg: string) => ({
          ruleId: 'api_warning',
          severity: 'warning' as const,
          message: msg,
        }));
        return {
          member_id: r.member_id,
          label: `${r.template_type} ${(r.personalized_text || '').slice(0, 30)}...`,
          status: 'ready' as const,
          personalized_text: r.personalized_text,
          full_scout_text: r.full_scout_text,
          template_type: r.template_type,
          job_category: r.job_category,
          job_offer_id: r.job_offer_id,
          is_favorite: r.is_favorite,
          validationResults: apiWarnings.length > 0 ? apiWarnings : undefined,
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
