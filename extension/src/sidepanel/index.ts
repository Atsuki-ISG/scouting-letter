import { ExtractionPanel } from './components/ExtractionPanel';
import { CandidateList } from './components/CandidateList';
import { ImportPanel } from './components/ImportPanel';
import { ConversationPanel } from './components/ConversationPanel';
import { GeneratePanel } from './components/GeneratePanel';
import { DebugPanel } from './components/DebugPanel';
import { ConfirmationPopup } from './components/ConfirmationPopup';
import { storage } from '../shared/storage';
import { CandidateItem, CandidateProfile, FixRecord, Message } from '../shared/types';
import { configProvider } from '../shared/config-provider';
import { apiClient } from '../shared/api-client';
import { gasClient } from '../shared/gas-client';

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
async function setupCompanySelect(): Promise<void> {
  const select = document.getElementById('company') as HTMLSelectElement;

  // APIから会社リストを取得（フォールバック付き）
  const companies = await configProvider.getCompanyList();
  for (const company of companies) {
    if (!select.querySelector(`option[value="${company}"]`)) {
      const option = document.createElement('option');
      option.value = company;
      option.textContent = company;
      select.appendChild(option);
    }
  }

  const savedCompany = await storage.getCompany();
  select.value = savedCompany;
  await populateJobOffers(savedCompany);

  select.addEventListener('change', async () => {
    await storage.setCompany(select.value);
    await populateJobOffers(select.value);
    // 会社変更時は求人選択をリセット
    await storage.setSelectedJobOffer(null);
  });
}

/** 求人ドロップダウンを会社に応じて更新 */
async function populateJobOffers(company: string): Promise<void> {
  const select = document.getElementById('job-offer') as HTMLSelectElement;
  const offers = await configProvider.getJobOffers(company);

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
  const saved = await storage.getSelectedJobOffer();
  if (saved && offers.some((o) => o.id === saved.id)) {
    select.value = saved.id;
  } else if (offers.length > 0) {
    select.value = offers[0].id;
    await storage.setSelectedJobOffer(offers[0]);
  }
}

/** 求人選択 */
function setupJobOfferSelect(candidateList?: CandidateList): void {
  const select = document.getElementById('job-offer') as HTMLSelectElement;

  select.addEventListener('change', async () => {
    const company = await storage.getCompany();
    const offers = await configProvider.getJobOffers(company);
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

/** 求人自動選択トグル */
function setupAutoJobOfferToggle(): void {
  const toggle = document.getElementById('toggle-auto-job-offer') as HTMLInputElement;

  // 保存値を復元（デフォルトはON）
  storage.isAutoJobOfferEnabled().then((enabled) => {
    toggle.checked = enabled;
  });

  toggle.addEventListener('change', () => {
    storage.setAutoJobOffer(toggle.checked);
  });
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
    } else if (msg.type === 'JOB_OFFER_FAILED') {
      // 求人自動選択失敗の通知 → 再開ボタンを表示
      showJobOfferFailedNotification(msg.error);
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

/** 求人選択失敗時の通知・再開ボタン */
function showJobOfferFailedNotification(error: string): void {
  // 既存の通知があれば削除
  document.getElementById('job-offer-failed-notification')?.remove();

  const notification = document.createElement('div');
  notification.id = 'job-offer-failed-notification';
  notification.style.cssText = 'background:#fef2f2;border:1px solid #fca5a5;border-radius:6px;padding:10px;margin:8px 0;';
  notification.innerHTML = `
    <div style="color:#dc2626;font-weight:bold;font-size:13px;margin-bottom:6px;">⚠ 求人自動選択に失敗</div>
    <div style="color:#7f1d1d;font-size:12px;margin-bottom:8px;">${error}<br>ジョブメドレー画面で求人を手動で選択してください。</div>
    <button id="btn-resume-job-offer" style="background:#2563eb;color:white;border:none;border-radius:4px;padding:6px 16px;cursor:pointer;font-size:12px;">求人選択済み → 再開</button>
  `;

  // 送信パネル内の先頭に挿入
  const sendPanel = document.getElementById('panel-send');
  if (sendPanel) {
    sendPanel.insertBefore(notification, sendPanel.firstChild);
  }

  document.getElementById('btn-resume-job-offer')?.addEventListener('click', () => {
    notification.remove();
    chrome.runtime.sendMessage({ type: 'RESUME_AFTER_JOB_OFFER' } satisfies Message);
  });
}

/** 設定パネル */
function setupSettingsPanel(): void {
  const apiEndpoint = document.getElementById('settings-api-endpoint') as HTMLInputElement;
  const apiKeyInput = document.getElementById('settings-api-key') as HTMLInputElement;
  const btnTestApi = document.getElementById('btn-test-api') as HTMLButtonElement;
  const apiStatus = document.getElementById('settings-api-status') as HTMLElement;

  const gasEnabled = document.getElementById('settings-gas-enabled') as HTMLInputElement;
  const gasUrl = document.getElementById('settings-gas-url') as HTMLInputElement;
  const btnTestGas = document.getElementById('btn-test-gas-settings') as HTMLButtonElement;
  const gasStatus = document.getElementById('settings-gas-status') as HTMLElement;

  // 復元
  storage.getAPIEndpoint().then((v) => { apiEndpoint.value = v; });
  storage.getAPIKey().then((v) => { apiKeyInput.value = v; });
  storage.isGASEnabled().then((v) => { gasEnabled.checked = v; });
  storage.getGASEndpoint().then((v) => { gasUrl.value = v; });

  // 保存
  apiEndpoint.addEventListener('change', () => storage.setAPIEndpoint(apiEndpoint.value.trim()));
  apiKeyInput.addEventListener('change', () => storage.setAPIKey(apiKeyInput.value.trim()));
  gasEnabled.addEventListener('change', () => storage.setGASEnabled(gasEnabled.checked));
  gasUrl.addEventListener('change', () => storage.setGASEndpoint(gasUrl.value.trim()));

  // API接続テスト
  btnTestApi.addEventListener('click', async () => {
    apiStatus.textContent = 'テスト中...';
    apiStatus.style.color = '#6b7280';
    await storage.setAPIEndpoint(apiEndpoint.value.trim());
    await storage.setAPIKey(apiKeyInput.value.trim());
    const result = await apiClient.testConnection();
    apiStatus.textContent = result.success ? '接続成功' : `接続失敗: ${result.error}`;
    apiStatus.style.color = result.success ? '#22c55e' : '#ef4444';
  });

  // GAS接続テスト
  btnTestGas.addEventListener('click', async () => {
    gasStatus.textContent = 'テスト中...';
    gasStatus.style.color = '#6b7280';
    await storage.setGASEndpoint(gasUrl.value.trim());
    const result = await gasClient.testConnection();
    gasStatus.textContent = result.success ? '接続成功' : `接続失敗: ${result.error}`;
    gasStatus.style.color = result.success ? '#22c55e' : '#ef4444';
  });
}

/** 求人抽出・登録 */
function setupJobOfferExtraction(): void {
  const extractBtn = document.getElementById('btn-extract-job-offers');
  const registerBtn = document.getElementById('btn-register-job-offers');
  const listEl = document.getElementById('job-offers-extract-list')!;
  const statusEl = document.getElementById('job-offers-extract-status')!;
  const registerStatusEl = document.getElementById('job-offers-register-status')!;

  let extractedOffers: Array<{ id: string; name: string }> = [];

  extractBtn?.addEventListener('click', async () => {
    statusEl.textContent = '抽出中...';
    statusEl.style.color = '#6b7280';
    listEl.innerHTML = '';
    registerBtn?.classList.add('hidden');

    chrome.runtime.sendMessage(
      { type: 'EXTRACT_JOB_OFFERS' } satisfies Message,
      (response: { success: boolean; offers: Array<{ id: string; name: string }>; error?: string }) => {
        if (!response || !response.success) {
          statusEl.textContent = `抽出失敗: ${response?.error || '不明なエラー'}`;
          statusEl.style.color = '#ef4444';
          return;
        }

        extractedOffers = response.offers;
        statusEl.textContent = `${extractedOffers.length}件の求人を取得しました`;
        statusEl.style.color = '#22c55e';

        // チェックボックス付きリスト表示
        listEl.innerHTML = extractedOffers.map((o, i) => `
          <label style="display:block;padding:4px 0;font-size:12px;cursor:pointer;">
            <input type="checkbox" checked data-index="${i}" style="margin-right:6px;">
            <strong>${o.id || '(ID不明)'}</strong> ${o.name}
          </label>
        `).join('');

        if (extractedOffers.length > 0) {
          registerBtn?.classList.remove('hidden');
        }
      }
    );
  });

  registerBtn?.addEventListener('click', async () => {
    const company = await storage.getCompany();
    const checkboxes = listEl.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
    const selected = extractedOffers.filter((_, i) => checkboxes[i]?.checked);

    if (selected.length === 0) {
      registerStatusEl.textContent = '登録する求人を選択してください';
      registerStatusEl.style.color = '#ef4444';
      return;
    }

    registerStatusEl.textContent = `登録中... (0/${selected.length})`;
    registerStatusEl.style.color = '#6b7280';

    let registered = 0;
    for (const offer of selected) {
      try {
        const endpoint = await storage.getAPIEndpoint();
        const apiKey = await storage.getAPIKey();
        const res = await fetch(`${endpoint}/api/v1/admin/job_offers`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
          body: JSON.stringify({
            company,
            job_category: '',
            id: offer.id,
            name: offer.name,
            label: offer.name.split(/\s+/).slice(-2).join(' '),
            employment_type: offer.name.includes('パート') ? 'part' : 'full',
            active: 'TRUE',
          }),
        });
        if (res.ok) registered++;
      } catch {
        // continue with next
      }
      registerStatusEl.textContent = `登録中... (${registered}/${selected.length})`;
    }

    registerStatusEl.textContent = `${registered}件を登録しました`;
    registerStatusEl.style.color = '#22c55e';
    registerBtn?.classList.add('hidden');
  });
}

/** 初期化 */
async function init(): Promise<void> {
  setupTabs();
  await setupCompanySelect();
  setupFixExport();

  // 各パネルのインスタンス生成
  new ExtractionPanel();
  const candidateList = new CandidateList();
  new ImportPanel(candidateList);
  new GeneratePanel(candidateList);
  setupJobOfferSelect(candidateList);
  setupAutoJobOfferToggle();
  new ConversationPanel();
  const debugPanel = new DebugPanel();
  const confirmPopup = new ConfirmationPopup();

  setupDebugControls(debugPanel);
  setupSettingsPanel();
  setupJobOfferExtraction();
  setupMessageHandlers(debugPanel, confirmPopup, candidateList);

  // 確認ポップアップ内の停止ボタンから連続送信を停止
  confirmPopup.setStopCallback(() => {
    chrome.runtime.sendMessage({ type: 'STOP_CONTINUOUS_SEND' } satisfies Message);
  });

  // 確認ポップアップをCandidateListに接続
  candidateList.setConfirmCallback((data) => confirmPopup.show(data));
}

document.addEventListener('DOMContentLoaded', init);
