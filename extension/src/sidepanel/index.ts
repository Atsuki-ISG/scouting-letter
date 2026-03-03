import { ExtractionPanel } from './components/ExtractionPanel';
import { CandidateList } from './components/CandidateList';
import { ImportPanel } from './components/ImportPanel';
import { ConversationPanel } from './components/ConversationPanel';
import { storage } from '../shared/storage';
import { FixRecord } from '../shared/types';
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
function setupJobOfferSelect(): void {
  const select = document.getElementById('job-offer') as HTMLSelectElement;

  select.addEventListener('change', async () => {
    const company = await storage.getCompany();
    const offers = COMPANY_JOB_OFFERS[company] || [];
    const selected = offers.find((o) => o.id === select.value);
    storage.setSelectedJobOffer(selected || null);
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

/** 初期化 */
function init(): void {
  setupTabs();
  setupCompanySelect();
  setupJobOfferSelect();
  setupFixExport();

  // 各パネルのインスタンス生成
  new ExtractionPanel();
  const candidateList = new CandidateList();
  new ImportPanel(candidateList);
  new ConversationPanel();
}

document.addEventListener('DOMContentLoaded', init);
