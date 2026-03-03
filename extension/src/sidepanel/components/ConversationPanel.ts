import { ConversationMessage, ConversationThread, ReplyRecord, Message } from '../../shared/types';
import { storage } from '../../shared/storage';
import { toYAML, downloadYAML } from '../../shared/yaml';

/**
 * 返信・やりとりタブのUIコンポーネント
 *
 * - メッセージページからのやりとり取得（単体 / 一括）
 * - 手動入力モード
 * - 保存済みやりとり一覧
 * - YAML個別/一括エクスポート
 * - 返信スカウト記録エクスポート
 */
export class ConversationPanel {
  private listEl: HTMLElement;
  private manualFormEl: HTMLElement;
  private isBatchRunning = false;

  constructor() {
    this.listEl = document.getElementById('conversation-list')!;
    this.manualFormEl = document.getElementById('manual-input-form')!;

    this.setupExtractButton();
    this.setupBatchExtractButton();
    this.setupManualInput();
    this.setupExportButtons();
    this.setupMessageListener();
    this.loadConversations();
  }

  /** Content Scriptからの進捗メッセージを受信 */
  private setupMessageListener(): void {
    chrome.runtime.onMessage.addListener((message: Message) => {
      switch (message.type) {
        case 'CONVERSATION_PROGRESS': {
          const { current, total, thread } = message;
          this.handleBatchProgress(current, total, thread);
          break;
        }
        case 'CONVERSATION_BATCH_COMPLETE': {
          this.handleBatchComplete(message.count);
          break;
        }
      }
    });
  }

  /** やりとりを取得ボタン（単体） */
  private setupExtractButton(): void {
    const btn = document.getElementById('btn-extract-conversation');
    btn?.addEventListener('click', async () => {
      btn.setAttribute('disabled', 'true');
      btn.textContent = '取得中...';

      try {
        const response = await chrome.runtime.sendMessage({ type: 'EXTRACT_CONVERSATION' });
        if (response?.type === 'CONVERSATION_DATA' && response.thread) {
          if (!response.thread.company) {
            response.thread.company = this.getCompanyFromUI();
          }
          await storage.addConversation(response.thread);
          await this.loadConversations();
          this.showStatus('やりとりを保存しました');
        } else {
          const errorMsg = response?.error || '抽出に失敗しました';
          this.showStatus(errorMsg, true);
          this.manualFormEl.classList.remove('hidden');
        }
      } catch {
        this.showStatus('Content Scriptと通信できません。ジョブメドレーのページを開いてください。', true);
        this.manualFormEl.classList.remove('hidden');
      } finally {
        btn.removeAttribute('disabled');
        btn.textContent = 'やりとりを取得';
      }
    });
  }

  /** 一括取得ボタン */
  private setupBatchExtractButton(): void {
    const btn = document.getElementById('btn-batch-extract');
    if (!btn) return;

    btn.addEventListener('click', async () => {
      if (this.isBatchRunning) {
        // 中断
        await chrome.runtime.sendMessage({ type: 'STOP_EXTRACTION' });
        this.isBatchRunning = false;
        btn.textContent = '一括取得';
        btn.classList.remove('btn-danger');
        this.showStatus('一括取得を中断しました');
        return;
      }

      btn.textContent = '中断';
      btn.classList.add('btn-danger');
      this.isBatchRunning = true;
      this.showStatus('一括取得を開始しています...', false);

      try {
        const response = await chrome.runtime.sendMessage({ type: 'EXTRACT_ALL_CONVERSATIONS' });
        if (response?.type === 'CONVERSATION_ERROR') {
          this.showStatus(response.error, true);
          this.resetBatchButton(btn);
        }
        // 成功時は非同期で進捗が来る（setupMessageListenerで処理）
      } catch {
        this.showStatus('Content Scriptと通信できません。', true);
        this.resetBatchButton(btn);
      }
    });
  }

  /** 一括取得の進捗処理 */
  private async handleBatchProgress(current: number, total: number, thread: ConversationThread): Promise<void> {
    if (!thread.company) {
      thread.company = this.getCompanyFromUI();
    }
    await storage.addConversation(thread);
    await this.loadConversations();
    this.showStatus(`取得中... ${current}/${total}件 (${thread.member_id})`, false);
  }

  /** 一括取得完了 */
  private handleBatchComplete(count: number): void {
    const btn = document.getElementById('btn-batch-extract');
    if (btn) this.resetBatchButton(btn);
    this.showStatus(`一括取得完了: ${count}件のやりとりを保存しました`);
    this.loadConversations();
  }

  private resetBatchButton(btn: HTMLElement): void {
    this.isBatchRunning = false;
    btn.textContent = '一括取得';
    btn.classList.remove('btn-danger');
  }

  /** 手動入力フォーム */
  private setupManualInput(): void {
    const toggleBtn = document.getElementById('btn-toggle-manual');
    toggleBtn?.addEventListener('click', () => {
      this.manualFormEl.classList.toggle('hidden');
    });

    const saveBtn = document.getElementById('btn-save-manual');
    saveBtn?.addEventListener('click', async () => {
      const memberId = (document.getElementById('manual-member-id') as HTMLInputElement).value.trim();
      const messagesText = (document.getElementById('manual-messages') as HTMLTextAreaElement).value.trim();

      if (!memberId) {
        alert('会員番号を入力してください');
        return;
      }
      if (!messagesText) {
        alert('やりとり内容を入力してください');
        return;
      }

      const messages = this.parseManualMessages(messagesText);
      if (messages.length === 0) {
        alert('メッセージをパースできませんでした。\n\n形式:\n企業: メッセージ本文\n求職者: メッセージ本文');
        return;
      }

      const company = await storage.getCompany();
      const thread: ConversationThread = {
        member_id: memberId,
        company,
        started: messages[0].date || new Date().toISOString().slice(0, 10),
        messages,
      };

      await storage.addConversation(thread);

      // 返信記録の自動生成: candidatesから該当member_idのデータを取得
      await this.tryCreateReplyRecord(memberId, company, thread);

      await this.loadConversations();
      this.showStatus('やりとりを保存しました');

      // フォームリセット
      (document.getElementById('manual-member-id') as HTMLInputElement).value = '';
      (document.getElementById('manual-messages') as HTMLTextAreaElement).value = '';
    });
  }

  /** テキストからメッセージをパース */
  private parseManualMessages(text: string): ConversationMessage[] {
    const messages: ConversationMessage[] = [];
    const lines = text.split('\n');
    let currentRole: 'company' | 'candidate' | null = null;
    let currentText = '';
    let currentDate = '';

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;

      // 「企業:」「求職者:」「候補者:」で始まる行を検出
      const companyMatch = trimmed.match(/^(?:企業|会社|こちら)[：:](.*)$/);
      const candidateMatch = trimmed.match(/^(?:求職者|候補者|相手)[：:](.*)$/);
      // 日付行: 「2026-03-01」等
      const dateMatch = trimmed.match(/^(\d{4}-\d{2}-\d{2})$/);

      if (dateMatch) {
        currentDate = dateMatch[1];
        continue;
      }

      if (companyMatch || candidateMatch) {
        // 前のメッセージを保存
        if (currentRole && currentText) {
          messages.push({
            role: currentRole,
            date: currentDate || new Date().toISOString().slice(0, 10),
            text: currentText.trim(),
          });
        }
        currentRole = companyMatch ? 'company' : 'candidate';
        currentText = (companyMatch?.[1] || candidateMatch?.[1] || '').trim();
      } else if (currentRole) {
        // 継続行
        currentText += '\n' + trimmed;
      }
    }

    // 最後のメッセージ
    if (currentRole && currentText) {
      messages.push({
        role: currentRole,
        date: currentDate || new Date().toISOString().slice(0, 10),
        text: currentText.trim(),
      });
    }

    return messages;
  }

  /** candidatesデータから返信スカウト記録を自動生成 */
  private async tryCreateReplyRecord(
    memberId: string,
    company: string,
    thread: ConversationThread
  ): Promise<void> {
    const candidates = await storage.getCandidates();
    const candidate = candidates.find((c) => c.member_id === memberId);
    if (!candidate) return;

    // 求職者からの返信があるか確認
    const candidateMessages = thread.messages.filter((m) => m.role === 'candidate');
    if (candidateMessages.length === 0) return;

    // プロフィール取得
    const profiles = await storage.getExtractedProfiles();
    const profile = profiles.find((p) => p.member_id === memberId);

    const companyFirstMessage = thread.messages.find((m) => m.role === 'company');
    const firstReply = candidateMessages[0];

    const record: ReplyRecord = {
      member_id: memberId,
      company,
      template_type: candidate.template_type || '',
      date_sent: companyFirstMessage?.date || thread.started,
      date_replied: firstReply.date,
      profile: profile ? {
        qualifications: profile.qualifications,
        experience_type: profile.experience_type,
        experience_years: profile.experience_years,
        area: profile.area,
        desired_employment_type: profile.desired_employment_type,
      } : {},
      personalized_text: candidate.personalized_text || '',
      replied: true,
    };

    await storage.addReplyRecord(record);
  }

  /** 保存済みやりとりの一覧を表示 */
  async loadConversations(): Promise<void> {
    const conversations = await storage.getConversations();
    this.listEl.innerHTML = '';

    if (conversations.length === 0) {
      this.listEl.innerHTML = '<div class="empty-message">保存済みやりとりはありません</div>';
      return;
    }

    const header = document.createElement('div');
    header.className = 'conversation-count';
    header.textContent = `保存済みやりとり (${conversations.length}件)`;
    this.listEl.appendChild(header);

    for (const thread of conversations) {
      this.listEl.appendChild(this.createThreadElement(thread));
    }
  }

  /** スレッド要素を生成 */
  private createThreadElement(thread: ConversationThread): HTMLElement {
    const el = document.createElement('div');
    el.className = 'conversation-item';

    const candidateCount = thread.messages.filter((m) => m.role === 'candidate').length;
    const hasReply = candidateCount > 0;

    el.innerHTML = `
      <div class="conversation-header">
        <span class="member-id">${thread.member_id}</span>
        <span class="conversation-date">${thread.started}</span>
      </div>
      <div class="conversation-summary">
        スカウト → ${hasReply ? '返信あり' : '返信なし'} (${thread.messages.length}通)
      </div>
      <div class="conversation-actions">
        <button class="btn btn-sm btn-secondary btn-yaml-dl">YAML DL</button>
        <button class="btn btn-sm btn-danger btn-delete">削除</button>
      </div>
    `;

    // YAMLダウンロード
    el.querySelector('.btn-yaml-dl')!.addEventListener('click', () => {
      const yaml = toYAML(thread as unknown as Record<string, unknown>);
      downloadYAML(yaml, `${thread.member_id}.yml`);
    });

    // 削除
    el.querySelector('.btn-delete')!.addEventListener('click', async () => {
      if (!confirm(`${thread.member_id} のやりとりを削除しますか？`)) return;
      await storage.removeConversation(thread.member_id);
      await this.loadConversations();
    });

    return el;
  }

  /** エクスポートボタン */
  private setupExportButtons(): void {
    // 全件やりとりYAMLエクスポート（1ファイルにまとめる）
    document.getElementById('btn-export-all-conversations')?.addEventListener('click', async () => {
      const conversations = await storage.getConversations();
      if (conversations.length === 0) {
        alert('やりとりデータがありません');
        return;
      }
      const yamlParts = conversations.map(
        (thread) => toYAML(thread as unknown as Record<string, unknown>)
      );
      const combined = yamlParts.join('\n---\n');
      const date = new Date().toISOString().slice(0, 10);
      downloadYAML(combined, `conversations_${date}.yml`);
    });

    // 返信スカウト記録エクスポート（1ファイルにまとめる）
    document.getElementById('btn-export-reply-records')?.addEventListener('click', async () => {
      const records = await storage.getReplyRecords();
      if (records.length === 0) {
        alert('返信スカウト記録がありません');
        return;
      }
      const yamlParts = records.map(
        (record) => toYAML(record as unknown as Record<string, unknown>)
      );
      const combined = yamlParts.join('\n---\n');
      const date = new Date().toISOString().slice(0, 10);
      downloadYAML(combined, `reply-records_${date}.yml`);
    });
  }

  /** UIのセレクトから会社名を取得（storageが空の場合のフォールバック） */
  private getCompanyFromUI(): string {
    const select = document.getElementById('company') as HTMLSelectElement | null;
    return select?.value || 'ark-visiting-nurse';
  }

  /** ステータスメッセージ表示 */
  private showStatus(message: string, isError = false): void {
    const statusEl = document.getElementById('conversation-status');
    if (!statusEl) return;

    statusEl.textContent = message;
    statusEl.className = `status-message ${isError ? 'status-error' : 'status-success'}`;
    statusEl.classList.remove('hidden');

    // 一括取得中はタイマーで消さない
    if (!this.isBatchRunning) {
      setTimeout(() => {
        statusEl.classList.add('hidden');
      }, 3000);
    }
  }
}
