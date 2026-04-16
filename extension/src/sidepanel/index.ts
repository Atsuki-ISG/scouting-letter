import { ExtractionPanel } from './components/ExtractionPanel';
import { CandidateList } from './components/CandidateList';
import { ImportPanel } from './components/ImportPanel';
import { ConversationPanel } from './components/ConversationPanel';
import { GeneratePanel } from './components/GeneratePanel';
import { PersonalizedGeneratePanel } from './components/PersonalizedGeneratePanel';
import { DebugPanel } from './components/DebugPanel';
import { ConfirmationPopup } from './components/ConfirmationPopup';
import { storage } from '../shared/storage';
import { CandidateItem, CandidateProfile, FacilityInfo, FacilityListItem, FixRecord, Message } from '../shared/types';
import { configProvider } from '../shared/config-provider';
import { apiClient } from '../shared/api-client';
import { gasClient } from '../shared/gas-client';

/** タブ切替 */
function setupTabs(): void {
  const tabs = document.querySelectorAll<HTMLButtonElement>('.tab');
  const panels = document.querySelectorAll<HTMLElement>('.panel');
  const settingsBtn = document.getElementById('btn-open-settings') as HTMLButtonElement | null;

  const activate = (target: string | undefined, clickedEl: HTMLElement | null) => {
    if (!target) return;
    tabs.forEach((t) => t.classList.remove('active'));
    settingsBtn?.classList.remove('active');
    panels.forEach((p) => p.classList.add('hidden'));

    if (clickedEl) clickedEl.classList.add('active');
    const panel = document.getElementById(`panel-${target}`);
    if (panel) panel.classList.remove('hidden');
  };

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => activate(tab.dataset.tab, tab));
  });

  // ヘッダー歯車ボタン → 設定パネルを開く
  settingsBtn?.addEventListener('click', () => {
    activate('settings', settingsBtn);
  });
}

/** 会社ドロップダウンに会社リストを反映（既存選択は維持） */
async function renderCompanyOptions(forceRefresh = false): Promise<void> {
  const select = document.getElementById('company') as HTMLSelectElement | null;
  if (!select) return;
  const companies = await configProvider.getCompanyListWithDisplayNames(forceRefresh);
  const currentValue = select.value;
  for (const company of companies) {
    const existing = select.querySelector(`option[value="${company.id}"]`) as HTMLOptionElement | null;
    if (!existing) {
      const option = document.createElement('option');
      option.value = company.id;
      option.textContent = company.display_name;
      select.appendChild(option);
    } else if (existing.textContent !== company.display_name) {
      // display_name が遅れて届いた場合に表示を更新（英→日本語）
      existing.textContent = company.display_name;
    }
  }
  if (currentValue) select.value = currentValue;
}

/** 会社選択 */
async function setupCompanySelect(): Promise<void> {
  const select = document.getElementById('company') as HTMLSelectElement;

  await renderCompanyOptions();

  const savedCompany = await storage.getCompany();
  select.value = savedCompany;
  await populateJobOffers(savedCompany);

  select.addEventListener('change', async () => {
    await storage.setCompany(select.value);
    await populateJobOffers(select.value);
    // 会社変更時は求人選択をリセット
    await storage.setSelectedJobOffer(null);
  });

  // タブ切り替えでサイドパネルに戻ってきたとき、古ければ裏で再取得して
  // display_name 等を最新化（UIはキャッシュで先に描画済みなのでブロックしない）
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      void renderCompanyOptions();
    }
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

/** 修正履歴エクスポート + 未送信リトライ */
function setupFixExport(): void {
  const exportBtn = document.getElementById('btn-export-fixes');
  const retryBtn = document.getElementById('btn-retry-unsynced');
  const unsyncedCountEl = document.getElementById('unsynced-count');
  const exportSection = document.getElementById('fix-export');

  const refreshUnsyncedBadge = async () => {
    const records = await storage.getFixRecords();
    const unsynced = records.filter((r) => r._unsynced);
    if (unsyncedCountEl) unsyncedCountEl.textContent = String(unsynced.length);
    if (retryBtn) retryBtn.classList.toggle('hidden', unsynced.length === 0);
    if (records.length > 0 && exportSection) {
      exportSection.classList.remove('hidden');
    }
  };

  // 修正記録があればボタンを表示
  refreshUnsyncedBadge();

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

  retryBtn?.addEventListener('click', async () => {
    const records = await storage.getFixRecords();
    const unsynced = records.filter((r) => r._unsynced);
    if (unsynced.length === 0) {
      alert('未送信の修正はありません');
      return;
    }
    const company = await storage.getCompany();
    try {
      await apiClient.syncFixes(company, unsynced);
      // 成功: 全レコードから _unsynced を外して保存し直す
      const updated = records.map((r) => (r._unsynced ? { ...r, _unsynced: false } : r));
      await chrome.storage.local.set({ scout_fix_records: updated });
      await refreshUnsyncedBadge();
      alert(`${unsynced.length} 件の修正をサーバへ送信しました`);
    } catch (err) {
      alert(`送信失敗: ${err instanceof Error ? err.message : String(err)}`);
    }
  });

  // 修正が追加されたタイミングでバッジを更新するため、storageの変更を監視
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes.scout_fix_records) {
      refreshUnsyncedBadge();
    }
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
    } else if (msg.type === 'COMPANY_DETECTED') {
      // ページから会社を自動検出 → セレクトを更新
      handleCompanyDetected(msg.companyId);
    } else if (msg.type === 'COMPANY_MISMATCH') {
      // 会社不一致警告
      showCompanyMismatchWarning(msg.companyId);
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

/** ページから検出した会社IDで会社セレクトを自動更新 */
async function handleCompanyDetected(detectedCompanyId: string): Promise<void> {
  const select = document.getElementById('company') as HTMLSelectElement | null;
  if (!select) return;

  const currentCompany = select.value;
  if (currentCompany === detectedCompanyId) return; // 既に一致

  // セレクトのオプションに存在するか確認
  const optionExists = Array.from(select.options).some(o => o.value === detectedCompanyId);
  if (!optionExists) return;

  // 自動切替
  select.value = detectedCompanyId;
  select.dispatchEvent(new Event('change'));
  console.log(`[Scout Assistant] Auto-switched company: ${currentCompany} -> ${detectedCompanyId}`);
}

/** 会社不一致警告を表示 */
function showCompanyMismatchWarning(companyId: string): void {
  // 既存の警告があれば削除
  document.getElementById('company-mismatch-warning')?.remove();

  const warning = document.createElement('div');
  warning.id = 'company-mismatch-warning';
  warning.style.cssText = 'background:#fffbeb;border:2px solid #f59e0b;border-radius:6px;padding:12px;margin:8px 0;';
  warning.innerHTML = `
    <div style="color:#b45309;font-weight:bold;font-size:14px;margin-bottom:6px;">⚠ 会社が違う可能性があります</div>
    <div style="color:#92400e;font-size:12px;margin-bottom:8px;">
      選択中の会社「<b>${companyId}</b>」の求人が、ジョブメドレーのスカウト画面に見つかりません。<br>
      別の施設のスカウト画面を開いていないか確認してください。
    </div>
    <button onclick="this.parentElement.remove()" style="background:#f59e0b;color:white;border:none;border-radius:4px;padding:4px 12px;cursor:pointer;font-size:12px;">閉じる</button>
  `;

  // 送信パネルの先頭、またはメインコンテンツの先頭に挿入
  const sendPanel = document.getElementById('panel-send');
  const extractPanel = document.getElementById('panel-extract');
  const target = sendPanel || extractPanel;
  if (target) {
    target.insertBefore(warning, target.firstChild);
  }
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
            employment_type: offer.name.includes('パート') ? 'part' : offer.name.includes('契約') ? 'contract' : 'full',
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

/** 施設情報抽出・profile.md生成 */
function setupFacilityExtraction(): void {
  const scanBtn = document.getElementById('btn-scan-facilities')!;
  const listArea = document.getElementById('facility-list-area')!;
  const checklist = document.getElementById('facility-checklist')!;
  const extractBtn = document.getElementById('btn-extract-facility')!;
  const stopBtn = document.getElementById('btn-stop-facility')!;
  const statusEl = document.getElementById('facility-extract-status')!;
  const resultEl = document.getElementById('facility-extract-result')!;
  const summaryEl = document.getElementById('facility-info-summary')!;
  const downloadBtn = document.getElementById('btn-download-profile-md');
  const rawBtn = document.getElementById('btn-download-raw-text');

  let facilityItems: FacilityListItem[] = [];
  let lastFacilities: FacilityInfo[] = [];

  // Step 1: 施設一覧を取得
  scanBtn.addEventListener('click', () => {
    statusEl.textContent = '施設一覧を取得中...';
    statusEl.style.color = '#6b7280';

    chrome.runtime.sendMessage(
      { type: 'EXTRACT_FACILITY_LIST' } satisfies Message,
      (response: { success: boolean; facilities: FacilityListItem[]; error?: string }) => {
        if (!response || !response.success || response.facilities.length === 0) {
          statusEl.textContent = response?.error || '施設が見つかりません。施設・求人情報ページを開いてください。';
          statusEl.style.color = '#ef4444';
          return;
        }

        facilityItems = response.facilities;
        statusEl.textContent = `${facilityItems.length}件の施設が見つかりました`;
        statusEl.style.color = '#22c55e';

        // チェックボックス付きリスト
        checklist.innerHTML = facilityItems.map((f, i) => `
          <label style="display:block;padding:4px 0;font-size:12px;cursor:pointer;">
            <input type="checkbox" checked data-index="${i}" style="margin-right:6px;">
            ${f.name} <span style="color:#9ca3af;">(${f.facilityId})</span>
          </label>
        `).join('');

        listArea.classList.remove('hidden');
      }
    );
  });

  // Step 2: 選択した施設の求人を取得
  stopBtn.addEventListener('click', () => {
    chrome.runtime.sendMessage({ type: 'STOP_FACILITY_EXTRACTION' } satisfies Message);
    stopBtn.classList.add('hidden');
    extractBtn.classList.remove('hidden');
    statusEl.textContent = '停止しました';
    statusEl.style.color = '#f59e0b';
  });

  extractBtn.addEventListener('click', () => {
    const checkboxes = checklist.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
    const selectedIds = facilityItems
      .filter((_, i) => checkboxes[i]?.checked)
      .map((f) => f.facilityId);

    if (selectedIds.length === 0) {
      statusEl.textContent = '施設を選択してください';
      statusEl.style.color = '#ef4444';
      return;
    }

    statusEl.textContent = `取得中... ${selectedIds.length}施設の求人情報を取得しています`;
    statusEl.style.color = '#6b7280';
    resultEl.classList.add('hidden');
    extractBtn.classList.add('hidden');
    stopBtn.classList.remove('hidden');

    chrome.runtime.sendMessage(
      { type: 'EXTRACT_FACILITY_INFO', facilityIds: selectedIds } satisfies Message,
      (response: { success: boolean; facilities: FacilityInfo[]; error?: string }) => {
        stopBtn.classList.add('hidden');
        extractBtn.classList.remove('hidden');

        if (!response || !response.success) {
          statusEl.textContent = `取得失敗: ${response?.error || '不明なエラー'}`;
          statusEl.style.color = '#ef4444';
          return;
        }

        lastFacilities = response.facilities;
        const totalJobs = lastFacilities.reduce((sum, f) => sum + f.jobs.length, 0);
        statusEl.textContent = `取得完了: ${lastFacilities.length}施設 / 掲載中求人${totalJobs}件`;
        statusEl.style.color = '#22c55e';

        // サマリー表示
        let summary = '';
        for (const facility of lastFacilities) {
          summary += `=== ${facility.facilityName} (ID:${facility.facilityId}) ===\n`;
          summary += `求人数: ${facility.jobs.length}件\n\n`;
          for (const job of facility.jobs) {
            summary += `  --- ${job.title || '(タイトル不明)'} ---\n`;
            if (job.jobType) summary += `  職種: ${job.jobType}\n`;
            if (job.salary) summary += `  給与: ${job.salary}\n`;
            if (job.workingHours) summary += `  勤務: ${job.workingHours}\n`;
            summary += '\n';
          }
        }

        summaryEl.textContent = summary;
        resultEl.classList.remove('hidden');
      }
    );
  });

  downloadBtn?.addEventListener('click', () => {
    if (lastFacilities.length === 0) return;
    // 施設ごとにprofile.mdを生成（1つにまとめる）
    const md = lastFacilities.map((f) => generateProfileMd(f)).join('\n\n---\n\n');
    downloadText(md, `profile.md`);
  });

  rawBtn?.addEventListener('click', () => {
    if (lastFacilities.length === 0) return;
    let raw = '';
    for (const facility of lastFacilities) {
      raw += `========== ${facility.facilityName} ==========\n`;
      raw += `=== ページ生テキスト ===\n${facility.rawPageText}\n\n`;
      for (let i = 0; i < facility.jobs.length; i++) {
        raw += `=== 求人${i + 1} 生テキスト ===\n${facility.jobs[i].rawText}\n\n`;
      }
    }
    downloadText(raw, `facility-raw.txt`);
  });
}

/** FacilityInfoからprofile.mdを生成 */
function generateProfileMd(facility: FacilityInfo): string {
  const lines: string[] = [];

  lines.push(`# 会社プロファイル: ${facility.facilityName}`);
  lines.push('');
  lines.push('## 基本情報');
  lines.push('');
  lines.push(`- **施設名**: ${facility.facilityName}`);
  if (facility.facilityId) lines.push(`- **施設ID**: ${facility.facilityId}`);
  if (facility.facilityType) lines.push(`- **種別**: ${facility.facilityType}`);
  if (facility.address) lines.push(`- **所在地**: ${facility.address}`);
  lines.push('- **代表者**: ');
  lines.push('- **スカウト担当者名**: ');
  lines.push('');

  if (facility.description) {
    lines.push('## 施設の特徴');
    lines.push('');
    lines.push(facility.description);
    lines.push('');
  }

  if (facility.representativeMessage) {
    lines.push('## 代表メッセージ');
    lines.push('');
    lines.push(`> ${facility.representativeMessage.split('\n').join('\n> ')}`);
    lines.push('');
  }

  // 求人情報
  if (facility.jobs.length > 0) {
    lines.push('## 募集要項');
    lines.push('');

    for (const job of facility.jobs) {
      lines.push(`### ${job.title || job.jobType || '(職種不明)'}`);
      lines.push('');

      if (job.jobType) {
        lines.push(`**募集職種**: ${job.jobType}`);
        lines.push('');
      }

      if (job.jobDescription) {
        lines.push('**仕事内容**');
        lines.push('');
        lines.push(job.jobDescription);
        lines.push('');
      }

      if (job.salary) {
        lines.push(`**給与**: ${job.salary}`);
        lines.push('');
      }

      if (job.workingHours) {
        lines.push('**勤務時間**');
        lines.push('');
        lines.push(job.workingHours);
        lines.push('');
      }

      if (job.holidays) {
        lines.push('**休日**');
        lines.push('');
        lines.push(job.holidays);
        lines.push('');
      }

      if (job.benefits) {
        lines.push('**待遇・福利厚生**');
        lines.push('');
        lines.push(job.benefits);
        lines.push('');
      }

      lines.push('---');
      lines.push('');
    }
  }

  return lines.join('\n');
}

/** 開発者モードの初期化 — devMode トグルと dev-only タブの可視化。 */
async function setupDevMode(): Promise<void> {
  const toggle = document.getElementById('settings-dev-mode') as HTMLInputElement | null;
  const devElements = document.querySelectorAll<HTMLElement>('.dev-only');

  const applyVisibility = (enabled: boolean) => {
    devElements.forEach((el) => {
      el.classList.toggle('hidden', !enabled);
    });
    // If dev mode is turned off while sitting on the personalized tab,
    // bounce back to extract so the user isn't left on a hidden panel.
    if (!enabled) {
      const activePersonalized = document.querySelector('.tab.active[data-tab="personalized"]');
      if (activePersonalized) {
        const extractTab = document.querySelector('.tab[data-tab="extract"]') as HTMLButtonElement | null;
        extractTab?.click();
      }
    }
  };

  const initial = await storage.getDevMode();
  if (toggle) toggle.checked = initial;
  applyVisibility(initial);

  toggle?.addEventListener('change', async () => {
    const enabled = toggle.checked;
    await storage.setDevMode(enabled);
    applyVisibility(enabled);
  });
}

/** 残数取得の鮮度しきい値（ミリ秒）: 4時間 */
const QUOTA_FRESH_MS = 4 * 60 * 60 * 1000;

/**
 * 残数取得を裏で発火（UI ステータスは出さない）。
 * 失敗してもユーザー作業を妨げないよう握りつぶす。成功時のみ最終取得時刻を保存。
 */
async function fetchQuotaSilently(): Promise<void> {
  try {
    const companyId = await storage.getCompany();
    if (!companyId) return;
    const res: { success: boolean; remaining?: number; error?: string } =
      await chrome.runtime.sendMessage({ type: 'REQUEST_QUOTA_SNAPSHOT', companyId });
    if (res?.success) {
      await storage.setQuotaLastFetch(Date.now());
    }
  } catch {
    /* noop: 裏で走るので失敗しても無視 */
  }
}

/** 鮮度 4h を過ぎていれば残数を自動取得 */
async function fetchQuotaIfStale(): Promise<void> {
  const last = await storage.getQuotaLastFetch();
  if (Date.now() - last < QUOTA_FRESH_MS) return;
  await fetchQuotaSilently();
}

/** 「残数を取得」ボタン: Service Worker 経由で裏タブ開いて残数スクレイプ */
function setupFetchQuotaButton(): void {
  const btn = document.getElementById('btn-fetch-quota') as HTMLButtonElement | null;
  const status = document.getElementById('quota-status') as HTMLDivElement | null;
  if (!btn) return;

  const setStatus = (text: string, kind: 'info' | 'success' | 'error') => {
    if (!status) return;
    status.textContent = text;
    status.style.display = 'block';
    status.dataset.kind = kind;
  };

  btn.addEventListener('click', async () => {
    const companyId = await storage.getCompany();
    if (!companyId) {
      setStatus('会社が選択されていません', 'error');
      return;
    }
    btn.disabled = true;
    setStatus('ジョブメドレーから残数を取得中…', 'info');
    try {
      const res: { success: boolean; remaining?: number; error?: string } =
        await chrome.runtime.sendMessage({ type: 'REQUEST_QUOTA_SNAPSHOT', companyId });
      if (res?.success) {
        await storage.setQuotaLastFetch(Date.now());
        setStatus(`残数 ${res.remaining} 通を記録しました`, 'success');
        setTimeout(() => {
          if (status) status.style.display = 'none';
        }, 4000);
      } else {
        setStatus(res?.error || '取得に失敗しました', 'error');
      }
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err), 'error');
    } finally {
      btn.disabled = false;
    }
  });
}

/** 初期化 */
async function init(): Promise<void> {
  setupTabs();
  await setupCompanySelect();
  setupFixExport();
  setupFetchQuotaButton();

  // 各パネルのインスタンス生成
  new ExtractionPanel();
  const candidateList = new CandidateList();
  new ImportPanel(candidateList);
  new GeneratePanel(candidateList);
  new PersonalizedGeneratePanel(candidateList);
  setupJobOfferSelect(candidateList);
  setupAutoJobOfferToggle();
  new ConversationPanel();
  await setupDevMode();
  const debugPanel = new DebugPanel();
  const confirmPopup = new ConfirmationPopup();

  setupDebugControls(debugPanel);
  setupSettingsPanel();
  setupJobOfferExtraction();
  setupFacilityExtraction();
  setupMessageHandlers(debugPanel, confirmPopup, candidateList);

  // サイドパネル起動時に会社自動検出をリクエスト
  chrome.runtime.sendMessage({ type: 'DETECT_COMPANY' } satisfies Message);

  // 残数が 4h 以上古ければ裏で自動取得（UI ブロックなし）
  void fetchQuotaIfStale();

  // 連続送信完了後は残数が確実に変化しているので自動取得
  chrome.runtime.onMessage.addListener((msg: Message) => {
    if (msg.type === 'CONTINUOUS_SEND_COMPLETE') {
      void fetchQuotaSilently();
    }
  });

  // 確認ポップアップ内の停止ボタンから連続送信を停止
  confirmPopup.setStopCallback(() => {
    chrome.runtime.sendMessage({ type: 'STOP_CONTINUOUS_SEND' } satisfies Message);
  });

  // 確認ポップアップをCandidateListに接続
  candidateList.setConfirmCallback((data, options) => confirmPopup.show(data, options));
}

document.addEventListener('DOMContentLoaded', init);
