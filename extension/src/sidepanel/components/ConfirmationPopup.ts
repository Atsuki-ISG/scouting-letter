import { ConfirmationData } from '../../shared/types';
import { escapeHtml } from '../../shared/utils';

export class ConfirmationPopup {
  private containerEl: HTMLElement;
  private resolver: ((result: 'ok' | 'ng') => void) | null = null;

  constructor() {
    this.containerEl = document.getElementById('confirmation-popup')!;
  }

  show(data: ConfirmationData): Promise<'ok' | 'ng'> {
    return new Promise((resolve) => {
      this.resolver = resolve;

      const profileHtml = data.profileSummary
        ? `
          <div class="confirmation-section">
            <div class="confirmation-label">プロフィール情報:</div>
            <table class="confirmation-profile-table">
              <tr><th>資格</th><td>${escapeHtml(data.profileSummary.qualifications)}</td></tr>
              <tr><th>経験</th><td>${escapeHtml(data.profileSummary.experience)}</td></tr>
              <tr><th>希望雇用</th><td>${escapeHtml(data.profileSummary.desiredEmploymentType)}</td></tr>
              <tr><th>エリア</th><td>${escapeHtml(data.profileSummary.area)}</td></tr>
              ${data.profileSummary.selfPr ? `<tr><th>自己PR</th><td class="confirmation-selfpr">${escapeHtml(this.truncate(data.profileSummary.selfPr, 120))}</td></tr>` : ''}
              <tr><th>職歴</th><td>${data.profileSummary.hasWorkHistory ? '<span style="color:#059669">あり</span>' : '<span style="color:#9ca3af">なし</span>'}</td></tr>
            </table>
          </div>`
        : '';

      this.containerEl.innerHTML = `
        <div class="confirmation-backdrop"></div>
        <div class="confirmation-card">
          <h3 class="confirmation-title">送信前確認</h3>
          <div class="confirmation-body">
            <label class="confirmation-check-row">
              <input type="checkbox" class="confirm-check" data-check="member">
              <span class="confirmation-check-content">
                <span class="confirmation-label">会員番号</span>
                <span class="confirmation-value">${escapeHtml(data.member_id)}</span>
              </span>
            </label>
            <label class="confirmation-check-row">
              <input type="checkbox" class="confirm-check" data-check="job">
              <span class="confirmation-check-content">
                <span class="confirmation-label">対象求人</span>
                <span class="confirmation-value confirmation-job-name">${escapeHtml(data.jobOfferName)}</span>
              </span>
            </label>
            <label class="confirmation-check-row">
              <input type="checkbox" class="confirm-check" data-check="content">
              <span class="confirmation-check-content">
                <span class="confirmation-label">パーソナライズ文</span>
                <span class="confirmation-value">${escapeHtml(data.personalized_text)}</span>
              </span>
            </label>
            ${profileHtml}
            <details class="confirmation-details">
              <summary>全文プレビュー</summary>
              <div class="confirmation-fulltext">${escapeHtml(data.full_scout_text)}</div>
            </details>
          </div>
          <div class="confirmation-actions">
            <button class="btn btn-primary btn-confirm-ok" disabled>OK - 送信する</button>
            <button class="btn btn-secondary btn-confirm-ng">NG - スキップ</button>
          </div>
        </div>
      `;

      this.containerEl.classList.remove('hidden');

      // チェックリスト制御
      const okBtn = this.containerEl.querySelector('.btn-confirm-ok') as HTMLButtonElement;
      const checks = this.containerEl.querySelectorAll<HTMLInputElement>('.confirm-check');
      const updateOkState = () => {
        const allChecked = Array.from(checks).every((c) => c.checked);
        okBtn.disabled = !allChecked;
      };
      checks.forEach((c) => c.addEventListener('change', updateOkState));

      okBtn.addEventListener('click', () => {
        this.hide();
        this.resolver?.('ok');
        this.resolver = null;
      });

      this.containerEl.querySelector('.btn-confirm-ng')?.addEventListener('click', () => {
        this.hide();
        this.resolver?.('ng');
        this.resolver = null;
      });

      this.containerEl.querySelector('.confirmation-backdrop')?.addEventListener('click', () => {
        this.hide();
        this.resolver?.('ng');
        this.resolver = null;
      });
    });
  }

  hide(): void {
    this.containerEl.classList.add('hidden');
    this.containerEl.innerHTML = '';
  }

  private truncate(text: string, maxLen: number): string {
    if (text.length <= maxLen) return text;
    return text.slice(0, maxLen) + '...';
  }

}
