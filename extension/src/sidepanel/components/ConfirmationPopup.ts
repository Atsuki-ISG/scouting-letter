import { ConfirmationData } from '../../shared/types';
import { escapeHtml } from '../../shared/utils';

export class ConfirmationPopup {
  private containerEl: HTMLElement;
  private resolver: ((result: 'ok' | 'ng') => void) | null = null;
  private stopCallback: (() => void) | null = null;

  constructor() {
    this.containerEl = document.getElementById('confirmation-popup')!;
  }

  /** 連続送信停止時のコールバックを設定 */
  setStopCallback(cb: (() => void) | null): void {
    this.stopCallback = cb;
  }

  show(data: ConfirmationData, options?: { isContinuousSend?: boolean }): Promise<'ok' | 'ng'> {
    return new Promise((resolve) => {
      this.resolver = resolve;

      const isEmpty = !data.personalized_text?.trim() || !data.full_scout_text?.trim();
      const emptyWarningHtml = isEmpty
        ? `<div class="confirmation-warning">
            <div style="font-weight:bold;margin-bottom:4px;">⚠ スカウト対象外の候補者です</div>
            <div>パーソナライズ文が生成されていません。スキップしてください。</div>
          </div>`
        : '';
      const validationWarningHtml = data.validationWarnings?.length
        ? `<div class="confirmation-warning" style="background:#fef3c7;border-color:#f59e0b;color:#92400e;">
            ${data.validationWarnings.map((w) => `<div style="font-weight:bold;">⚠ ${escapeHtml(w)}</div>`).join('')}
          </div>`
        : '';
      const warningHtml = emptyWarningHtml + validationWarningHtml;

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
          ${warningHtml}
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
          <div class="confirmation-stop-row hidden">
            <button class="btn btn-danger btn-confirm-stop">連続送信を停止</button>
          </div>
        </div>
      `;

      this.containerEl.classList.remove('hidden');

      // チェックリスト制御
      const okBtn = this.containerEl.querySelector('.btn-confirm-ok') as HTMLButtonElement;
      const checks = this.containerEl.querySelectorAll<HTMLInputElement>('.confirm-check');
      const updateOkState = () => {
        if (isEmpty) {
          okBtn.disabled = true;
          return;
        }
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

      // 連続送信中なら停止ボタンを表示
      if (this.stopCallback && options?.isContinuousSend) {
        const stopRow = this.containerEl.querySelector('.confirmation-stop-row');
        stopRow?.classList.remove('hidden');
        this.containerEl.querySelector('.btn-confirm-stop')?.addEventListener('click', () => {
          // resolver('ng')は呼ばない — STOP_CONTINUOUS_SENDで
          // continuous-senderのstop()→confirmCancelResolverが発火し、
          // requestConfirmationが'cancelled'で解決してループがbreakする。
          // ポップアップはstopContinuousSend内のDOM操作で閉じられる。
          this.resolver = null;
          this.stopCallback?.();
        });
      }
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
