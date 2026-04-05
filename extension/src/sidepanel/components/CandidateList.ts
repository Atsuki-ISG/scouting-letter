import { CandidateItem, CandidateStatus, CompanyValidationConfig, ConfirmationData, FixRecord, Message, ValidationResult } from '../../shared/types';
import { storage } from '../../shared/storage';
import { localTimestamp } from '../../shared/constants';
import { configProvider } from '../../shared/config-provider';
import { validateCandidate } from '../../shared/validation';
import { gasClient } from '../../shared/gas-client';
import { escapeHtml } from '../../shared/utils';

/** フォールバック用: サーバー設定がない場合のデフォルト */
const FALLBACK_SEARCH_TERMS: Record<string, string> = {
  nurse: '看護',
  pt: '理学療法',
  st: '言語聴覚',
  ot: '作業療法',
  medical_office: '医療事務',
  dietitian: '管理栄養士',
};

/** job_categoryからDropdown検索キーワードを導出（categoryConfigがあればそちらを優先） */
function deriveSearchTerm(jobCategory: string, config?: CompanyValidationConfig | null): string {
  return config?.categoryConfig?.[jobCategory]?.search_term || FALLBACK_SEARCH_TERMS[jobCategory] || '看護';
}

/** job_categoryからマッチング用キーワードを取得 */
function deriveCategoryKeywords(jobCategory: string, config?: CompanyValidationConfig | null): string[] | undefined {
  return config?.categoryConfig?.[jobCategory]?.keywords;
}

/** 確認ポップアップを表示するコールバック */
export type ConfirmCallback = (data: ConfirmationData, options?: { isContinuousSend?: boolean }) => Promise<'ok' | 'ng'>;

export class CandidateList {
  private candidates: CandidateItem[] = [];
  private highlightedMemberId: string | null = null;
  private continuousSendActive = false;
  private confirmCallback: ConfirmCallback | null = null;

  private listEl: HTMLElement;
  private sendCurrent: HTMLElement;
  private sendTotal: HTMLElement;
  private sendProgressFill: HTMLElement;
  private sendProgressSection: HTMLElement;

  constructor() {
    this.listEl = document.getElementById('candidate-list')!;
    this.sendCurrent = document.getElementById('send-current')!;
    this.sendTotal = document.getElementById('send-total')!;
    this.sendProgressFill = document.getElementById('send-progress-fill')!;
    this.sendProgressSection = document.getElementById('send-progress')!;

    // overlay会員番号の変更を監視 + 連続送信メッセージ
    chrome.runtime.onMessage.addListener((msg: Message, sender, sendResponse) => {
      if (sender.id !== chrome.runtime.id) return false;
      if (msg.type === 'OVERLAY_MEMBER_ID') {
        this.highlightCandidate(msg.memberId);
      } else if (msg.type === 'GET_NEXT_CANDIDATE') {
        this.getNextReadyCandidate().then((next) => {
          sendResponse({ type: 'NEXT_CANDIDATE', candidate: next });
        });
        return true; // async response
      } else if (msg.type === 'CANDIDATE_SENT') {
        // skipped状態にすでに更新済みならsentに上書きしない
        const c = this.candidates.find((c) => c.member_id === msg.memberId);
        if (c && c.status !== 'skipped') {
          this.updateStatus(msg.memberId, 'sent');
        }
      } else if (msg.type === 'CONTINUOUS_SEND_COMPLETE') {
        // 連続送信ループが終了した → UIをリセット（Content Script側は既に停止済み）
        this.stopContinuousSend(false);
      }
    });

    // 連続送信UI
    this.setupContinuousSend();

    // 保存済みデータを復元
    this.restore();
  }

  private async getNextReadyCandidate(): Promise<{ memberId: string; text: string; searchTerm?: string; jobCategory?: string; employmentType?: string; categoryKeywords?: string[] } | null> {
    const candidate = this.candidates.find((c) => c.status === 'ready');
    if (!candidate) return null;

    const company = await storage.getCompany();
    const validationConfig = await configProvider.getValidationConfig(company);
    const jobCategory = candidate.job_category || 'nurse';
    const employmentType = candidate.template_type.includes('正社員') ? '正社員' : 'パート';
    const searchTerm = deriveSearchTerm(jobCategory, validationConfig);
    const categoryKeywords = deriveCategoryKeywords(jobCategory, validationConfig);

    return {
      memberId: candidate.member_id,
      text: candidate.full_scout_text,
      searchTerm,
      jobCategory,
      employmentType,
      categoryKeywords,
    };
  }

  private setupContinuousSend(): void {
    const toggle = document.getElementById('toggle-continuous') as HTMLInputElement | null;
    const startBtn = document.getElementById('btn-start-continuous');
    const skipBtn = document.getElementById('btn-skip-continuous');
    const stopBtn = document.getElementById('btn-stop-continuous');

    if (!toggle || !startBtn || !stopBtn || !skipBtn) return;

    toggle.addEventListener('change', () => {
      if (toggle.checked) {
        startBtn.classList.remove('hidden');
      } else {
        startBtn.classList.add('hidden');
        if (this.continuousSendActive) {
          this.stopContinuousSend();
        }
      }
    });

    startBtn.addEventListener('click', () => {
      this.startContinuousSend();
    });

    skipBtn.addEventListener('click', () => {
      // 現在ハイライト中の候補者をスキップ
      if (this.highlightedMemberId) {
        this.skipCandidate(this.highlightedMemberId);
      }
    });

    stopBtn.addEventListener('click', () => {
      this.stopContinuousSend();
    });
  }

  private startContinuousSend(): void {
    const startBtn = document.getElementById('btn-start-continuous');
    const skipBtn = document.getElementById('btn-skip-continuous');
    const stopBtn = document.getElementById('btn-stop-continuous');

    this.continuousSendActive = true;
    this.sendProgressFill.classList.add('active');
    startBtn?.classList.add('hidden');
    skipBtn?.classList.remove('hidden');
    stopBtn?.classList.remove('hidden');

    chrome.runtime.sendMessage({ type: 'START_CONTINUOUS_SEND' } satisfies Message);
  }

  private stopContinuousSend(sendStopMessage = true): void {
    const startBtn = document.getElementById('btn-start-continuous');
    const skipBtn = document.getElementById('btn-skip-continuous');
    const stopBtn = document.getElementById('btn-stop-continuous');
    const toggle = document.getElementById('toggle-continuous') as HTMLInputElement | null;

    this.continuousSendActive = false;
    this.sendProgressFill.classList.remove('active');
    stopBtn?.classList.add('hidden');
    skipBtn?.classList.add('hidden');
    startBtn?.classList.add('hidden');
    if (toggle) toggle.checked = false;

    // 確認ポップアップが開いていたら閉じる
    const popup = document.getElementById('confirmation-popup');
    if (popup && !popup.classList.contains('hidden')) {
      popup.classList.add('hidden');
      popup.innerHTML = '';
    }

    if (sendStopMessage) {
      chrome.runtime.sendMessage({ type: 'STOP_CONTINUOUS_SEND' } satisfies Message);
    }
  }

  /** 確認ポップアップのコールバックを設定 */
  setConfirmCallback(cb: ConfirmCallback): void {
    this.confirmCallback = cb;
  }

  /** 外部（sidepanel/index.ts）からステータスを更新 */
  async updateStatusExternal(memberId: string, status: CandidateStatus): Promise<void> {
    await this.updateStatus(memberId, status);
  }

  private async restore(): Promise<void> {
    this.candidates = await storage.getCandidates();
    if (this.candidates.length > 0) {
      await this.runValidation();
      this.render();
    }
  }

  async setCandidates(candidates: CandidateItem[]): Promise<void> {
    this.candidates = candidates;
    await this.runValidation();
    await storage.setCandidates(candidates);
    this.render();
  }

  /** 全候補者にバリデーションを実行 */
  async runValidation(): Promise<void> {
    const company = await storage.getCompany();
    const config = await configProvider.getValidationConfig(company);
    if (!config) return;

    const profiles = await storage.getExtractedProfiles();

    for (const candidate of this.candidates) {
      const profile = profiles.find((p) => p.member_id === candidate.member_id) || null;
      candidate.validationResults = validateCandidate(candidate, profile, null, config);
    }
  }

  async clearCandidates(): Promise<void> {
    this.candidates = [];
    await storage.setCandidates([]);
    this.listEl.innerHTML = '';
    this.sendProgressSection.classList.add('hidden');
  }

  highlightCandidate(memberId: string | null): void {
    this.highlightedMemberId = memberId;

    // 全てのハイライトを解除
    this.listEl.querySelectorAll('.candidate-item').forEach((el) => {
      el.classList.remove('highlight');
    });

    if (memberId) {
      const el = this.listEl.querySelector(`[data-member-id="${memberId}"]`);
      if (el) {
        el.classList.add('highlight');
        el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }
  }

  private render(): void {
    this.listEl.innerHTML = '';

    const sentCount = this.candidates.filter((c) => c.status === 'sent').length;
    const total = this.candidates.length;

    if (total > 0) {
      this.sendProgressSection.classList.remove('hidden');
      this.sendCurrent.textContent = String(sentCount);
      this.sendTotal.textContent = String(total);
      this.sendProgressFill.style.width = `${(sentCount / total) * 100}%`;
    }

    for (const candidate of this.candidates) {
      const el = this.createCandidateElement(candidate);
      this.listEl.appendChild(el);
    }

    this.renderSummaryBar();
  }

  private createCandidateElement(candidate: CandidateItem): HTMLElement {
    const div = document.createElement('div');
    div.className = `candidate-item ${candidate.status === 'sent' ? 'sent' : ''}`;
    div.dataset.memberId = candidate.member_id;

    if (this.highlightedMemberId === candidate.member_id) {
      div.classList.add('highlight');
    }

    const statusLabel = this.getStatusLabel(candidate.status);

    // バリデーションバッジ生成
    const validationHtml = this.renderValidationBadges(candidate.validationResults);

    // template_type バッジ
    const templateBadge = this.renderTemplateBadge(candidate.template_type);

    div.innerHTML = `
      <div class="candidate-color-bar ${candidate.status}"></div>
      <div class="candidate-body">
        <div class="candidate-header">
          <span class="member-id">${escapeHtml(candidate.member_id)}</span>
          ${templateBadge}
          ${candidate.is_favorite ? '<span style="background:#fee2e2;color:#dc2626;font-size:10px;padding:1px 4px;border-radius:3px;margin-left:2px;">★気になる</span>' : ''}
          <span class="candidate-status ${candidate.status}">${statusLabel}</span>
        </div>
        ${validationHtml}
        <div class="candidate-preview" title="クリックして編集">${escapeHtml(candidate.personalized_text)}</div>
        <div class="candidate-edit hidden">
          <textarea class="edit-textarea" rows="4"></textarea>
          <input class="edit-reason" type="text" placeholder="修正理由（任意）">
          <div class="edit-actions">
            <button class="btn btn-sm btn-primary btn-save-edit">保存</button>
            <button class="btn btn-sm btn-secondary btn-cancel-edit">キャンセル</button>
          </div>
        </div>
        <div class="candidate-actions">
          <div class="candidate-actions-primary">
            <button class="btn btn-sm btn-primary btn-copy" data-id="${escapeHtml(candidate.member_id)}">コピー</button>
            <button class="btn btn-sm btn-primary btn-fill" data-id="${escapeHtml(candidate.member_id)}">本文セット</button>
            <button class="btn btn-sm btn-test-job btn-primary" data-id="${escapeHtml(candidate.member_id)}">求人+本文</button>
          </div>
          <div class="candidate-actions-secondary">
            <button class="btn btn-sm btn-secondary btn-sent" data-id="${escapeHtml(candidate.member_id)}" ${candidate.status === 'sent' ? 'disabled' : ''}>送信済</button>
            <button class="btn btn-sm btn-secondary btn-skip" data-id="${escapeHtml(candidate.member_id)}" ${candidate.status === 'skipped' ? 'disabled' : ''}>スキップ</button>
          </div>
        </div>
      </div>
    `;

    // プレビュークリックで編集モード
    const previewEl = div.querySelector('.candidate-preview') as HTMLElement;
    const editEl = div.querySelector('.candidate-edit') as HTMLElement;
    const textareaEl = div.querySelector('.edit-textarea') as HTMLTextAreaElement;
    const reasonEl = div.querySelector('.edit-reason') as HTMLInputElement;

    previewEl.addEventListener('click', () => {
      textareaEl.value = candidate.personalized_text;
      reasonEl.value = '';
      previewEl.classList.add('hidden');
      editEl.classList.remove('hidden');
      textareaEl.focus();
    });

    div.querySelector('.btn-save-edit')?.addEventListener('click', () => {
      this.saveEdit(candidate, textareaEl.value, reasonEl.value);
      previewEl.classList.remove('hidden');
      editEl.classList.add('hidden');
    });

    div.querySelector('.btn-cancel-edit')?.addEventListener('click', () => {
      previewEl.classList.remove('hidden');
      editEl.classList.add('hidden');
    });

    // イベントリスナー
    div.querySelector('.btn-copy')?.addEventListener('click', () => this.copyToClipboard(candidate));
    div.querySelector('.btn-fill')?.addEventListener('click', () => this.fillForm(candidate));
    div.querySelector('.btn-test-job')?.addEventListener('click', () => this.fillFormWithJobOffer(candidate));
    div.querySelector('.btn-sent')?.addEventListener('click', () => this.updateStatus(candidate.member_id, 'sent'));
    div.querySelector('.btn-skip')?.addEventListener('click', () => this.skipCandidate(candidate.member_id));

    return div;
  }

  private async copyToClipboard(candidate: CandidateItem): Promise<void> {
    try {
      await navigator.clipboard.writeText(candidate.full_scout_text);
    } catch {
      // fallback
      const textarea = document.createElement('textarea');
      textarea.value = candidate.full_scout_text;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }
  }

  private async fillFormWithJobOffer(candidate: CandidateItem): Promise<void> {
    // バリデーションエラーがある場合はブロック
    const errors = (candidate.validationResults || []).filter((v) => v.severity === 'error');
    if (errors.length > 0) {
      alert(`バリデーションエラー:\n${errors.map((e) => e.message).join('\n')}`);
      return;
    }

    const company = await storage.getCompany();
    const validationConfig = await configProvider.getValidationConfig(company);
    const jobCategory = candidate.job_category || 'nurse';
    const employmentType = candidate.template_type.includes('正社員') ? '正社員' : 'パート';
    const searchTerm = deriveSearchTerm(jobCategory, validationConfig);
    const categoryKeywords = deriveCategoryKeywords(jobCategory, validationConfig);

    const autoJobOffer = await storage.isAutoJobOfferEnabled();
    chrome.runtime.sendMessage(
      {
        type: 'FILL_FORM',
        text: candidate.full_scout_text,
        memberId: candidate.member_id,
        searchTerm,
        jobCategory,
        employmentType,
        skipJobOffer: !autoJobOffer,
        categoryKeywords,
      } satisfies Message,
      async (response) => {
        if (response && !response.success) {
          alert(`セット失敗: ${response.error || '不明なエラー'}`);
        } else {
          console.log('[Scout Assistant] Fill form with job offer succeeded');
          // 確認ポップアップを表示
          if (this.confirmCallback) {
            const profiles = await storage.getExtractedProfiles();
            const profile = profiles.find((p) => p.member_id === candidate.member_id);
            const profileSummary = profile
              ? {
                  qualifications: profile.qualifications,
                  experience: [profile.experience_type, profile.experience_years].filter(Boolean).join('（') + (profile.experience_years ? '）' : ''),
                  desiredEmploymentType: profile.desired_employment_type,
                  area: profile.area,
                  selfPr: profile.self_pr,
                  hasWorkHistory: !!(profile.work_history_summary && profile.work_history_summary.trim()),
                }
              : undefined;
            const validationWarnings = (candidate.validationResults || [])
              .filter((v) => v.severity === 'warning')
              .map((v) => v.message);
            const result = await this.confirmCallback({
              member_id: candidate.member_id,
              label: candidate.label,
              template_type: candidate.template_type,
              personalized_text: candidate.personalized_text,
              full_scout_text: candidate.full_scout_text,
              jobOfferName: `${jobCategory}/${employmentType}`,
              validationWarnings: validationWarnings.length > 0 ? validationWarnings : undefined,
              profileSummary,
            }, { isContinuousSend: this.continuousSendActive });
            if (result === 'ng') {
              await this.skipCandidate(candidate.member_id);
            }
          }
        }
      }
    );
  }

  private async getJobOffer(): Promise<{ id: string; name: string; label: string } | null> {
    let jobOffer = await storage.getSelectedJobOffer();
    if (!jobOffer) {
      const select = document.getElementById('job-offer') as HTMLSelectElement | null;
      if (select && select.value) {
        const company = await storage.getCompany();
        const offers = await configProvider.getJobOffers(company);
        const found = offers.find((o) => o.id === select.value);
        if (found) {
          jobOffer = found;
          await storage.setSelectedJobOffer(found);
        }
      }
    }
    return jobOffer;
  }

  private async fillForm(candidate: CandidateItem): Promise<void> {
    chrome.runtime.sendMessage(
      {
        type: 'FILL_FORM',
        text: candidate.full_scout_text,
        memberId: candidate.member_id,
      } satisfies Message,
      (response) => {
        if (response && !response.success) {
          alert(response.error || 'フォーム入力に失敗しました');
        }
      }
    );
  }

  private async saveEdit(candidate: CandidateItem, newText: string, reason: string): Promise<void> {
    const trimmed = newText.trim();
    if (trimmed === candidate.personalized_text) return; // 変更なし

    // 修正記録を保存
    const record: FixRecord = {
      member_id: candidate.member_id,
      template_type: candidate.template_type,
      timestamp: localTimestamp(),
      before: candidate.personalized_text,
      after: trimmed,
      reason: reason.trim(),
    };
    await storage.addFixRecord(record);

    // エクスポートボタンを表示
    const exportSection = document.getElementById('fix-export');
    if (exportSection) exportSection.classList.remove('hidden');

    // full_scout_text内のパーソナライズ文を置換
    const index = this.candidates.findIndex((c) => c.member_id === candidate.member_id);
    if (index !== -1) {
      this.candidates[index].full_scout_text = candidate.full_scout_text.replace(
        candidate.personalized_text,
        trimmed
      );
      this.candidates[index].personalized_text = trimmed;
      await storage.setCandidates(this.candidates);
      this.render();
    }
  }

  private async skipCandidate(memberId: string): Promise<void> {
    await this.updateStatus(memberId, 'skipped');
    // 連続送信中はContent Scriptにスキップを通知
    if (this.continuousSendActive) {
      chrome.runtime.sendMessage({ type: 'SKIP_CURRENT_CANDIDATE' } satisfies Message);
    }
  }

  private async updateStatus(memberId: string, status: CandidateStatus): Promise<void> {
    const index = this.candidates.findIndex((c) => c.member_id === memberId);
    if (index !== -1) {
      this.candidates[index].status = status;
      await storage.setCandidates(this.candidates);
      this.render();

      // GAS連携: 送信済みマーク時にログ送信（fire-and-forget）
      if (status === 'sent') {
        const candidate = this.candidates[index];
        const company = await storage.getCompany();
        const jobOffer = await this.getJobOffer();
        gasClient.logSentScout({
          timestamp: localTimestamp(),
          member_id: candidate.member_id,
          company,
          job_offer_id: jobOffer?.id || '',
          job_offer_label: jobOffer?.label || '',
          template_type: candidate.template_type,
          personalized_text: candidate.personalized_text,
        });
      }
    }
  }

  private renderTemplateBadge(templateType: string): string {
    if (!templateType) return '';
    const isSeishain = templateType.includes('正社員');
    const isResend = templateType.includes('再送');
    const typeCls = isSeishain ? 'seishain' : 'part';
    const label = isSeishain ? '正社員' : 'パート';
    let html = `<span class="template-badge ${typeCls}">${label}</span>`;
    if (isResend) {
      html += `<span class="template-badge resend">再送</span>`;
    }
    return html;
  }

  renderSummaryBar(): void {
    const existing = document.querySelector('.summary-bar');
    if (existing) existing.remove();

    if (this.candidates.length === 0) return;

    const ready = this.candidates.filter((c) => c.status === 'ready').length;
    const sent = this.candidates.filter((c) => c.status === 'sent').length;
    const skipped = this.candidates.filter((c) => c.status === 'skipped').length;
    const total = this.candidates.length;

    const bar = document.createElement('div');
    bar.className = 'summary-bar';
    bar.innerHTML = `
      <span class="summary-item"><span class="summary-count">${total}</span>件</span>
      <span class="summary-item summary-label-ready"><span class="summary-count">${ready}</span>未送信</span>
      <span class="summary-item summary-label-sent"><span class="summary-count">${sent}</span>送信済</span>
      <span class="summary-item summary-label-skipped"><span class="summary-count">${skipped}</span>スキップ</span>
    `;
    this.listEl.parentElement?.insertBefore(bar, this.listEl);
  }

  private renderValidationBadges(results?: ValidationResult[]): string {
    if (!results || results.length === 0) return '';
    return `<div class="validation-badges">${results
      .map((r) => {
        const cls = r.severity === 'error' ? 'validation-error' : 'validation-warning';
        return `<span class="${cls}" title="${escapeHtml(r.message)}">${r.severity === 'error' ? '\u26D4' : '\u26A0\uFE0F'} ${escapeHtml(r.message)}</span>`;
      })
      .join('')}</div>`;
  }

  private getStatusLabel(status: CandidateStatus): string {
    switch (status) {
      case 'sent': return '送信済';
      case 'skipped': return 'スキップ';
      default: return '未送信';
    }
  }

}
