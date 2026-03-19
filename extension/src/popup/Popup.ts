import { storage } from '../shared/storage';
import { Message } from '../shared/types';
import { configProvider } from '../shared/config-provider';
import { gasClient } from '../shared/gas-client';
import { apiClient } from '../shared/api-client';

async function init(): Promise<void> {
  const companySelect = document.getElementById('company') as HTMLSelectElement;
  const btnOpenPanel = document.getElementById('btn-open-panel') as HTMLButtonElement;
  const statusEl = document.getElementById('status') as HTMLElement;

  // APIから会社リストを取得（フォールバック付き）
  const companies = await configProvider.getCompanyList();
  for (const company of companies) {
    const option = document.createElement('option');
    option.value = company;
    option.textContent = company;
    companySelect.appendChild(option);
  }

  // 保存値を復元
  const savedCompany = await storage.getCompany();
  companySelect.value = savedCompany;

  // 会社選択変更時に保存
  companySelect.addEventListener('change', async () => {
    await storage.setCompany(companySelect.value);
    statusEl.style.display = 'block';
    setTimeout(() => {
      statusEl.style.display = 'none';
    }, 2000);
  });

  // サイドパネルを開く
  btnOpenPanel.addEventListener('click', () => {
    chrome.runtime.sendMessage({ type: 'OPEN_SIDE_PANEL' } satisfies Message);
    window.close();
  });

  // GAS設定
  setupGASSettings();

  // API設定
  setupAPISettings();
}

function setupGASSettings(): void {
  const gasEnabled = document.getElementById('gas-enabled') as HTMLInputElement;
  const gasUrl = document.getElementById('gas-url') as HTMLInputElement;
  const btnTest = document.getElementById('btn-test-gas') as HTMLButtonElement;
  const gasStatus = document.getElementById('gas-status') as HTMLElement;

  // 復元
  storage.isGASEnabled().then((enabled) => {
    gasEnabled.checked = enabled;
  });
  storage.getGASEndpoint().then((url) => {
    gasUrl.value = url;
  });

  // 変更時に保存
  gasEnabled.addEventListener('change', () => {
    storage.setGASEnabled(gasEnabled.checked);
  });

  gasUrl.addEventListener('change', () => {
    storage.setGASEndpoint(gasUrl.value.trim());
  });

  // 接続テスト
  btnTest.addEventListener('click', async () => {
    gasStatus.style.display = 'block';
    gasStatus.textContent = 'テスト中...';
    gasStatus.style.color = '#6b7280';

    // URLを最新で保存してからテスト
    await storage.setGASEndpoint(gasUrl.value.trim());
    const result = await gasClient.testConnection();

    if (result.success) {
      gasStatus.textContent = '接続成功';
      gasStatus.style.color = '#22c55e';
    } else {
      gasStatus.textContent = `接続失敗: ${result.error}`;
      gasStatus.style.color = '#ef4444';
    }
  });
}

function setupAPISettings(): void {
  const apiEndpoint = document.getElementById('api-endpoint') as HTMLInputElement;
  const apiKey = document.getElementById('api-key') as HTMLInputElement;
  const btnTest = document.getElementById('btn-test-api') as HTMLButtonElement;
  const apiStatus = document.getElementById('api-status') as HTMLElement;

  // 復元
  storage.getAPIEndpoint().then((url) => {
    apiEndpoint.value = url;
  });
  storage.getAPIKey().then((key) => {
    apiKey.value = key;
  });

  // 変更時に保存
  apiEndpoint.addEventListener('change', () => {
    storage.setAPIEndpoint(apiEndpoint.value.trim());
  });

  apiKey.addEventListener('change', () => {
    storage.setAPIKey(apiKey.value.trim());
  });

  // 接続テスト
  btnTest.addEventListener('click', async () => {
    apiStatus.style.display = 'block';
    apiStatus.textContent = 'テスト中...';
    apiStatus.style.color = '#6b7280';

    // 最新値を保存してからテスト
    await storage.setAPIEndpoint(apiEndpoint.value.trim());
    await storage.setAPIKey(apiKey.value.trim());
    const result = await apiClient.testConnection();

    if (result.success) {
      apiStatus.textContent = '接続成功';
      apiStatus.style.color = '#22c55e';
    } else {
      apiStatus.textContent = `接続失敗: ${result.error}`;
      apiStatus.style.color = '#ef4444';
    }
  });
}

document.addEventListener('DOMContentLoaded', init);
