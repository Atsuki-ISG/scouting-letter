import { storage } from '../../shared/storage';
import {
  apiClient,
  PersonalizedGenerateOptions,
  PersonalizedGenerateResponse,
} from '../../shared/api-client';
import { CandidateList } from './CandidateList';
import { CandidateItem } from '../../shared/types';
import { renderPersonalizationBar } from './PersonalizationBar';

/** Developer-mode generation panel.
 *
 * Parallel to GeneratePanel — the two don't share any state and you
 * can switch between them freely. Results from this panel can be
 * pushed into the send tab via the existing CandidateList (same
 * data type), just with the extra `personalization_stats` field.
 */
export class PersonalizedGeneratePanel {
  private candidateList: CandidateList;
  private btn: HTMLButtonElement;
  private levelSelect: HTMLSelectElement;
  private sendTypeSelect: HTMLSelectElement;
  private profileCount: HTMLElement;
  private progressSection: HTMLElement;
  private progressText: HTMLElement;
  private progressFill: HTMLElement;
  private summary: HTMLElement;
  private resultsEl: HTMLElement;
  private results: PersonalizedGenerateResponse[] = [];
  private isGenerating = false;

  constructor(candidateList: CandidateList) {
    this.candidateList = candidateList;
    this.btn = document.getElementById(
      'btn-personalized-generate',
    ) as HTMLButtonElement;
    this.levelSelect = document.getElementById(
      'personalized-level',
    ) as HTMLSelectElement;
    this.sendTypeSelect = document.getElementById(
      'personalized-send-type',
    ) as HTMLSelectElement;
    this.profileCount = document.getElementById(
      'personalized-profile-count',
    ) as HTMLElement;
    this.progressSection = document.getElementById(
      'personalized-progress',
    ) as HTMLElement;
    this.progressText = document.getElementById(
      'personalized-progress-text',
    ) as HTMLElement;
    this.progressFill = document.getElementById(
      'personalized-progress-fill',
    ) as HTMLElement;
    this.summary = document.getElementById(
      'personalized-result-summary',
    ) as HTMLElement;
    this.resultsEl = document.getElementById(
      'personalized-results',
    ) as HTMLElement;

    this.btn.addEventListener('click', () => this.generate());

    this.updateProfileCount();
    chrome.storage.onChanged.addListener((changes) => {
      if (changes['scout_extracted_profiles']) {
        this.updateProfileCount();
      }
    });
  }

  private async updateProfileCount(): Promise<void> {
    const profiles = await storage.getExtractedProfiles();
    this.profileCount.textContent = String(profiles.length);
    this.btn.disabled = profiles.length === 0 || this.isGenerating;
  }

  private async generate(): Promise<void> {
    if (this.isGenerating) return;
    this.isGenerating = true;
    this.btn.disabled = true;
    this.btn.textContent = '生成中...';
    this.results = [];
    this.resultsEl.innerHTML = '';
    this.summary.classList.add('hidden');

    const company = await storage.getCompany();
    const profiles = await storage.getExtractedProfiles();
    if (profiles.length === 0) {
      this.resultsEl.innerHTML = '<p>生成対象のプロフィールがありません</p>';
      this.resetBtn();
      return;
    }

    const level = (this.levelSelect.value || 'L3') as 'L2' | 'L3';
    const isResend = this.sendTypeSelect.value === 'resend';

    this.progressSection.classList.remove('hidden');
    this.progressFill.style.width = '0%';
    this.progressText.textContent = `生成中... 0/${profiles.length}`;

    let done = 0;
    let failed = 0;
    for (const profile of profiles) {
      const opts: PersonalizedGenerateOptions = {
        level,
        is_resend: isResend,
      };
      try {
        const resp = await apiClient.generatePersonalized(company, profile, opts);
        this.results.push(resp);
      } catch (e) {
        failed += 1;
        this.results.push({
          member_id: profile.member_id,
          template_type: '',
          generation_path: 'filtered_out',
          personalized_text: '',
          full_scout_text: '',
          block_contents: {},
          personalization_stats: {
            level,
            total_chars: 0,
            personalized_chars: 0,
            fixed_chars: 0,
            ratio: 0,
            per_block_chars: {},
          },
          is_favorite: false,
          validation_warnings: [],
          filter_reason: e instanceof Error ? e.message : String(e),
        });
      }
      done += 1;
      this.progressFill.style.width = `${(done / profiles.length) * 100}%`;
      this.progressText.textContent = `生成中... ${done}/${profiles.length}`;
    }

    this.progressText.textContent = `完了 ${done}/${profiles.length}`;
    const ok = this.results.filter((r) => r.generation_path === 'ai_structured').length;
    this.summary.classList.remove('hidden');
    this.summary.innerHTML = `
      <div class="summary-stats">
        ${level} 生成: ${ok} / 失敗: ${failed}
      </div>
    `;

    this.renderResults();
    this.resetBtn();
  }

  private resetBtn(): void {
    this.isGenerating = false;
    this.btn.textContent = '一括生成';
    this.btn.disabled = false;
    this.updateProfileCount();
  }

  private renderResults(): void {
    if (!this.results.length) {
      this.resultsEl.innerHTML = '';
      return;
    }

    let html = `<div style="display:flex;gap:6px;margin-bottom:8px;">
      <button id="btn-personalized-push-to-send" class="btn btn-primary btn-sm">送信タブに流す（成功分のみ）</button>
    </div>`;

    this.results.forEach((r, idx) => {
      const err = r.generation_path === 'filtered_out';
      const bg = err ? '#fef2f2' : '#f8fafc';
      const title = `${r.template_type || '(型未確定)'} — ${r.member_id}`;
      const stats = r.personalization_stats;
      const bar = err
        ? `<div style="color:#dc2626;font-size:12px;">${escapeHtml(r.filter_reason || 'エラー')}</div>`
        : renderPersonalizationBar(stats);

      const blocksHtml = err
        ? ''
        : Object.entries(r.block_contents)
            .map(
              ([name, text]) => `
              <details style="margin-top:6px;">
                <summary style="font-size:11px;cursor:pointer;color:#374151;">
                  ${escapeHtml(blockLabel(name))}
                  <span style="color:#9ca3af;">(${(text || '').length}字)</span>
                </summary>
                <div style="font-size:12px;line-height:1.6;padding:6px 0;white-space:pre-wrap;color:#111827;">${escapeHtml(text || '')}</div>
              </details>
            `,
            )
            .join('');

      const fullText = err
        ? ''
        : `
          <details style="margin-top:6px;">
            <summary style="font-size:11px;cursor:pointer;color:#374151;">完成文プレビュー</summary>
            <div style="font-size:12px;line-height:1.6;padding:6px 8px;white-space:pre-wrap;background:#fff;border:1px solid #e5e7eb;border-radius:4px;">${escapeHtml(r.full_scout_text)}</div>
          </details>
        `;

      html += `
        <div style="border:1px solid #e5e7eb;border-radius:6px;margin-bottom:8px;padding:8px 10px;background:${bg};">
          <div style="display:flex;align-items:center;gap:8px;">
            <strong style="font-size:12px;">${escapeHtml(title)}</strong>
          </div>
          ${bar}
          ${blocksHtml}
          ${fullText}
        </div>
      `;
    });

    this.resultsEl.innerHTML = html;
    document
      .getElementById('btn-personalized-push-to-send')
      ?.addEventListener('click', () => this.pushToSendTab());
  }

  private async pushToSendTab(): Promise<void> {
    const candidates: CandidateItem[] = [];
    for (const r of this.results) {
      if (r.generation_path !== 'ai_structured') continue;
      candidates.push({
        member_id: r.member_id,
        label: `${r.template_type} [${Math.round((r.personalization_stats.ratio || 0) * 100)}%]`,
        status: 'ready',
        personalized_text: r.personalized_text,
        full_scout_text: r.full_scout_text,
        template_type: r.template_type,
        job_category: r.job_category,
        is_favorite: r.is_favorite,
        block_contents: r.block_contents,
        personalization_stats: r.personalization_stats,
      });
    }
    if (candidates.length === 0) {
      alert('送信可能な候補がありません');
      return;
    }
    await this.candidateList.setCandidates(candidates);
    // Switch to the send tab
    const sendTabBtn = document.querySelector('.tab[data-tab="send"]') as HTMLButtonElement | null;
    if (sendTabBtn) sendTabBtn.click();
  }
}

function blockLabel(name: string): string {
  return (
    {
      opening: '冒頭',
      bridge: '橋渡し',
      facility_intro: '施設紹介',
      job_framing: 'フレーミング',
      closing_cta: 'CTA',
    }[name] || name
  );
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
