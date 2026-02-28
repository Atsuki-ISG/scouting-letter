import { CandidateItem, CandidateStatus, FixRecord, Message } from '../../shared/types';
import { storage } from '../../shared/storage';

export class CandidateList {
  private candidates: CandidateItem[] = [];
  private highlightedMemberId: string | null = null;

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

    // overlay会員番号の変更を監視
    chrome.runtime.onMessage.addListener((msg: Message) => {
      if (msg.type === 'OVERLAY_MEMBER_ID') {
        this.highlightCandidate(msg.memberId);
      }
    });

    // 保存済みデータを復元
    this.restore();
  }

  private async restore(): Promise<void> {
    this.candidates = await storage.getCandidates();
    if (this.candidates.length > 0) {
      this.render();
    }
  }

  async setCandidates(candidates: CandidateItem[]): Promise<void> {
    this.candidates = candidates;
    await storage.setCandidates(candidates);
    this.render();
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
  }

  private createCandidateElement(candidate: CandidateItem): HTMLElement {
    const div = document.createElement('div');
    div.className = `candidate-item ${candidate.status === 'sent' ? 'sent' : ''}`;
    div.dataset.memberId = candidate.member_id;

    if (this.highlightedMemberId === candidate.member_id) {
      div.classList.add('highlight');
    }

    const statusIcon = this.getStatusIcon(candidate.status);
    const statusLabel = this.getStatusLabel(candidate.status);

    div.innerHTML = `
      <div class="candidate-header">
        <span class="status-icon">${statusIcon}</span>
        <span class="member-id">${this.escapeHtml(candidate.member_id)}</span>
        <span class="candidate-label">${this.escapeHtml(candidate.label)}</span>
        <span class="candidate-status ${candidate.status}">${statusLabel}</span>
      </div>
      <div class="candidate-preview" title="クリックして編集">${this.escapeHtml(candidate.personalized_text)}</div>
      <div class="candidate-edit hidden">
        <textarea class="edit-textarea" rows="4"></textarea>
        <input class="edit-reason" type="text" placeholder="修正理由（任意）">
        <div class="edit-actions">
          <button class="btn btn-sm btn-primary btn-save-edit">保存</button>
          <button class="btn btn-sm btn-secondary btn-cancel-edit">キャンセル</button>
        </div>
      </div>
      <div class="candidate-actions">
        <button class="btn btn-sm btn-primary btn-copy" data-id="${this.escapeHtml(candidate.member_id)}">コピー</button>
        <button class="btn btn-sm btn-primary btn-fill" data-id="${this.escapeHtml(candidate.member_id)}">本文にセット</button>
        <button class="btn btn-sm btn-secondary btn-sent" data-id="${this.escapeHtml(candidate.member_id)}" ${candidate.status === 'sent' ? 'disabled' : ''}>送信済み</button>
        <button class="btn btn-sm btn-secondary btn-skip" data-id="${this.escapeHtml(candidate.member_id)}" ${candidate.status === 'skipped' ? 'disabled' : ''}>スキップ</button>
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
    div.querySelector('.btn-sent')?.addEventListener('click', () => this.updateStatus(candidate.member_id, 'sent'));
    div.querySelector('.btn-skip')?.addEventListener('click', () => this.updateStatus(candidate.member_id, 'skipped'));

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

  private fillForm(candidate: CandidateItem): void {
    chrome.runtime.sendMessage(
      { type: 'FILL_FORM', text: candidate.full_scout_text, memberId: candidate.member_id } satisfies Message,
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
      timestamp: new Date().toISOString(),
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

  private async updateStatus(memberId: string, status: CandidateStatus): Promise<void> {
    const index = this.candidates.findIndex((c) => c.member_id === memberId);
    if (index !== -1) {
      this.candidates[index].status = status;
      await storage.setCandidates(this.candidates);
      this.render();
    }
  }

  private getStatusIcon(status: CandidateStatus): string {
    switch (status) {
      case 'sent': return '<span style="color:#22c55e">&#10003;</span>';
      case 'skipped': return '<span style="color:#9ca3af">&#8212;</span>';
      default: return '<span style="color:#3b82f6">&#9679;</span>';
    }
  }

  private getStatusLabel(status: CandidateStatus): string {
    switch (status) {
      case 'sent': return '送信済';
      case 'skipped': return 'スキップ';
      default: return '未送信';
    }
  }

  private escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}
