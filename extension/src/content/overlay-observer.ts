import { getOverlayMemberId } from './scraper';
import { safeSendMessage } from './helpers';

/** overlay表示を監視して、会員番号変更をサイドパネルに通知 */
export function setupOverlayObserver(): void {
  let lastMemberId: string | null = null;

  const observer = new MutationObserver(() => {
    const memberId = getOverlayMemberId();
    if (memberId && memberId !== lastMemberId) {
      lastMemberId = memberId;
      safeSendMessage({
        type: 'OVERLAY_MEMBER_ID',
        memberId,
      });
    } else if (!memberId && lastMemberId) {
      lastMemberId = null;
    }
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['style', 'class'],
  });
}
