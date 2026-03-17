import { ExtractionPanel } from './components/ExtractionPanel';
import { CandidateList } from './components/CandidateList';
import { ImportPanel } from './components/ImportPanel';
import { ConversationPanel } from './components/ConversationPanel';
import { DebugPanel } from './components/DebugPanel';
import { ConfirmationPopup } from './components/ConfirmationPopup';
import { storage } from '../shared/storage';
import { CandidateItem, CandidateProfile, FixRecord, Message } from '../shared/types';
import { COMPANY_JOB_OFFERS } from '../shared/constants';

/** タブ切替 */
function setupTabs(): void {
  const tabs = document.querySelectorAll<HTMLButtonElement>('.tab');
  const panels = document.querySelectorAll<HTMLElement>('.panel');

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      const target = tab.dataset.tab;

      tabs.forEach((t) => t.classList.remove('active'));
      panels.forEach((p) => p.classList.add('hidden'));

      tab.classList.add('active');
      const panel = document.getElementById(`panel-${target}`);
      if (panel) {
        panel.classList.remove('hidden');
      }
    });
  });
}

/** 会社選択 */
function setupCompanySelect(): void {
  const select = document.getElementById('company') as HTMLSelectElement;

  // COMPANY_JOB_OFFERSから動的に会社リストを生成
  const companies = Object.keys(COMPANY_JOB_OFFERS);
  for (const company of companies) {
    if (!select.querySelector(`option[value="${company}"]`)) {
      const option = document.createElement('option');
      option.value = company;
      option.textContent = company;
      select.appendChild(option);
    }
  }

  storage.getCompany().then((company) => {
    select.value = company;
    populateJobOffers(company);
  });

  select.addEventListener('change', () => {
    storage.setCompany(select.value);
    populateJobOffers(select.value);
    // 会社変更時は求人選択をリセット
    storage.setSelectedJobOffer(null);
  });
}

/** 求人ドロップダウンを会社に応じて更新 */
function populateJobOffers(company: string): void {
  const select = document.getElementById('job-offer') as HTMLSelectElement;
  const offers = COMPANY_JOB_OFFERS[company] || [];

  // 既存の選択肢をクリア（プレースホルダー以外）
  while (select.options.length > 1) {
    select.remove(1);
  }

  for (const offer of offers) {
    const option = document.createElement('option');
    option.value = offer.id;
    option.textContent = offer.label;
    select.appendChild(option);
  }

  // 保存済みの選択を復元、なければ最初の求人を自動選択
  storage.getSelectedJobOffer().then((saved) => {
    if (saved && offers.some((o) => o.id === saved.id)) {
      select.value = saved.id;
    } else if (offers.length > 0) {
      select.value = offers[0].id;
      storage.setSelectedJobOffer(offers[0]);
    }
  });
}

/** 求人選択 */
function setupJobOfferSelect(candidateList?: CandidateList): void {
  const select = document.getElementById('job-offer') as HTMLSelectElement;

  select.addEventListener('change', async () => {
    const company = await storage.getCompany();
    const offers = COMPANY_JOB_OFFERS[company] || [];
    const selected = offers.find((o) => o.id === select.value);
    await storage.setSelectedJobOffer(selected || null);
    // 求人変更時にバリデーション再実行
    if (candidateList) {
      await candidateList.runValidation();
      const candidates = await storage.getCandidates();
      if (candidates.length > 0) {
        await candidateList.setCandidates(candidates);
      }
    }
  });
}

/** 修正履歴エクスポート */
function setupFixExport(): void {
  const exportBtn = document.getElementById('btn-export-fixes');
  const exportSection = document.getElementById('fix-export');

  // 修正記録があればボタンを表示
  storage.getFixRecords().then((records) => {
    if (records.length > 0 && exportSection) {
      exportSection.classList.remove('hidden');
    }
  });

  exportBtn?.addEventListener('click', async () => {
    const records = await storage.getFixRecords();
    if (records.length === 0) {
      alert('修正履歴がありません');
      return;
    }

    const company = await storage.getCompany();
    const markdown = formatFixRecordsAsMarkdown(records, company);
    downloadText(markdown, `fixes-${getYearMonth()}.md`);
  });
}

function formatFixRecordsAsMarkdown(records: FixRecord[], company: string): string {
  const ym = getYearMonth();
  let md = `# 修正履歴 ${ym} - ${company}\n\n`;

  for (const r of records) {
    const date = new Date(r.timestamp).toLocaleDateString('ja-JP');
    md += `## 会員番号: ${r.member_id}（${r.template_type}）\n`;
    md += `- 日付: ${date}\n`;
    if (r.reason) {
      md += `- 理由: ${r.reason}\n`;
    }
    md += `\n### 修正前\n${r.before}\n`;
    md += `\n### 修正後\n${r.after}\n\n---\n\n`;
  }

  return md;
}

function getYearMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

function downloadText(content: string, filename: string): void {
  const blob = new Blob([content], { type: 'text/markdown; charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** デバッグ・ドライラン設定 */
function setupDebugControls(debugPanel: DebugPanel): void {
  const dryRunToggle = document.getElementById('toggle-dry-run') as HTMLInputElement;
  const debugLogToggle = document.getElementById('toggle-debug-log') as HTMLInputElement;

  // 保存値を復元
  storage.isDryRunMode().then((enabled) => {
    dryRunToggle.checked = enabled;
  });
  storage.isDebugLogEnabled().then((enabled) => {
    debugLogToggle.checked = enabled;
    debugPanel.toggle(enabled);
  });

  dryRunToggle.addEventListener('change', () => {
    storage.setDryRunMode(dryRunToggle.checked);
  });

  debugLogToggle.addEventListener('change', () => {
    storage.setDebugLogEnabled(debugLogToggle.checked);
    debugPanel.toggle(debugLogToggle.checked);
  });
}

/** デバッグログ + 確認ポップアップのメッセージハンドラ */
function setupMessageHandlers(debugPanel: DebugPanel, confirmPopup: ConfirmationPopup, candidateList: CandidateList): void {
  chrome.runtime.onMessage.addListener((msg: Message, sender, sendResponse) => {
    if (sender.id !== chrome.runtime.id) return false;
    if (msg.type === 'DEBUG_LOG') {
      debugPanel.addEntry(msg.entry);
    } else if (msg.type === 'DRY_RUN_COMPLETE') {
      // ドライラン完了 → ステータスをskippedに更新
      candidateList.updateStatusExternal(msg.memberId, 'skipped');
    } else if (msg.type === 'CONFIRM_BEFORE_SEND') {
      // 確認ポップアップ表示 → 候補者データで補完してから表示
      (async () => {
        const data = { ...msg.data };
        // member_idから候補者データとプロフィールを補完
        if (data.member_id) {
          const candidates = await storage.getCandidates();
          const candidate = candidates.find((c: CandidateItem) => c.member_id === data.member_id);
          if (candidate) {
            if (!data.template_type) data.template_type = candidate.template_type;
            if (!data.personalized_text) data.personalized_text = candidate.personalized_text;
            if (!data.full_scout_text) data.full_scout_text = candidate.full_scout_text;
            if (!data.label) data.label = candidate.label;
          }
          if (!data.profileSummary) {
            const profiles = await storage.getExtractedProfiles();
            const profile = profiles.find((p: CandidateProfile) => p.member_id === data.member_id);
            if (profile) {
              data.profileSummary = {
                qualifications: profile.qualifications,
                experience: [profile.experience_type, profile.experience_years].filter(Boolean).join('（') + (profile.experience_years ? '）' : ''),
                desiredEmploymentType: profile.desired_employment_type,
                area: profile.area,
                selfPr: profile.self_pr,
                hasWorkHistory: !!(profile.work_history_summary && profile.work_history_summary.trim()),
              };
            }
          }
        }
        const result = await confirmPopup.show(data);
        chrome.runtime.sendMessage({ type: 'CONFIRM_RESPONSE', result } satisfies Message);
      })();
    }
  });
}

/** 初期化 */
function init(): void {
  setupTabs();
  setupCompanySelect();
  setupFixExport();

  // 各パネルのインスタンス生成
  new ExtractionPanel();
  const candidateList = new CandidateList();
  new ImportPanel(candidateList);
  setupJobOfferSelect(candidateList);
  new ConversationPanel();
  const debugPanel = new DebugPanel();
  const confirmPopup = new ConfirmationPopup();

  setupDebugControls(debugPanel);
  setupMessageHandlers(debugPanel, confirmPopup, candidateList);

  // 確認ポップアップをCandidateListに接続
  candidateList.setConfirmCallback((data) => confirmPopup.show(data));
}

document.addEventListener('DOMContentLoaded', init);
