import { storage } from '../shared/storage';
import { Message } from '../shared/types';

function init(): void {
  const companySelect = document.getElementById('company') as HTMLSelectElement;
  const btnOpenPanel = document.getElementById('btn-open-panel') as HTMLButtonElement;
  const statusEl = document.getElementById('status') as HTMLElement;

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
}

document.addEventListener('DOMContentLoaded', init);
