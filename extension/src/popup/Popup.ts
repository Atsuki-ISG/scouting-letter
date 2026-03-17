import { storage } from '../shared/storage';
import { Message } from '../shared/types';
import { COMPANY_JOB_OFFERS } from '../shared/constants';
import { gasClient } from '../shared/gas-client';

function init(): void {
  const companySelect = document.getElementById('company') as HTMLSelectElement;
  const btnOpenPanel = document.getElementById('btn-open-panel') as HTMLButtonElement;
  const statusEl = document.getElementById('status') as HTMLElement;

  // COMPANY_JOB_OFFERSから動的に会社リストを生成
  for (const company of Object.keys(COMPANY_JOB_OFFERS)) {
    const option = document.createElement('option');
    option.value = company;
    option.textContent = company;
    companySelect.appendChild(option);
  }

  // 保存値を復元
  storage.getCompany().then((company) => {
    companySelect.value = company;
  });

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

document.addEventListener('DOMContentLoaded', init);
