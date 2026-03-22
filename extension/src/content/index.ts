import { Message } from '../shared/types';
import { getOverlayMemberId } from './scraper';
import { extractConversation, isMessagePage, extractAllConversations, abortBatchExtraction } from './message-scraper';
import { handleFillForm, handleFillJobOffer } from './fill-handler';
import { safeSendMessage } from './helpers';
import { setupOverlayObserver } from './overlay-observer';
import * as extraction from './extraction';
import * as continuousSender from './continuous-sender';
import { extractJobOffers } from './job-offer-extractor';
import { extractFacilityList, extractFacilityInfo, abortFacilityExtraction } from './facility-scraper';

/** メッセージリスナー */
chrome.runtime.onMessage.addListener(
  (message: Message, sender, sendResponse) => {
    // 自拡張機能からのメッセージのみ受け付ける
    if (sender.id !== chrome.runtime.id) return false;

    switch (message.type) {
      case 'START_EXTRACTION':
        console.log('[Scout Assistant] START_EXTRACTION received, count:', message.count, 'startMemberId:', message.startMemberId);
        extraction.startExtraction(message.count, message.startMemberId).catch((err) => {
          safeSendMessage({
            type: 'EXTRACTION_ERROR',
            error: err.message,
          });
        });
        sendResponse({ ok: true });
        return false;

      case 'GET_OVERLAY_MEMBER_ID': {
        const memberId = getOverlayMemberId();
        sendResponse({ memberId });
        return false;
      }

      case 'FILL_FORM': {
        handleFillForm(message.text, message.memberId, message.searchTerm, message.jobCategory, message.employmentType, message.skipJobOffer, message.categoryKeywords).then(sendResponse);
        return true;
      }

      case 'FILL_JOB_OFFER': {
        handleFillJobOffer(message.searchTerm, message.jobCategory, message.employmentType, message.memberId).then(sendResponse);
        return true;
      }

      case 'EXTRACT_CONVERSATION': {
        console.log('[Scout Assistant] EXTRACT_CONVERSATION received');
        if (!isMessagePage()) {
          sendResponse({ type: 'CONVERSATION_ERROR', error: 'メッセージページを開いてください' });
          return false;
        }
        const thread = extractConversation();
        if (thread) {
          sendResponse({ type: 'CONVERSATION_DATA', thread });
        } else {
          sendResponse({ type: 'CONVERSATION_ERROR', error: 'メッセージの抽出に失敗しました。会話を選択してから再度お試しください。' });
        }
        return false;
      }

      case 'EXTRACT_ALL_CONVERSATIONS': {
        console.log('[Scout Assistant] EXTRACT_ALL_CONVERSATIONS received');
        if (!isMessagePage()) {
          sendResponse({ type: 'CONVERSATION_ERROR', error: 'メッセージページを開いてください' });
          return false;
        }
        sendResponse({ ok: true });
        extractAllConversations((msg) => {
          safeSendMessage(msg);
        });
        return false;
      }

      case 'STOP_EXTRACTION':
        extraction.abort();
        abortBatchExtraction();
        sendResponse({ ok: true });
        return false;

      case 'START_CONTINUOUS_SEND':
        continuousSender.start().catch((err) => {
          console.error('[Scout Assistant] Continuous send error:', err);
        });
        sendResponse({ ok: true });
        return false;

      case 'STOP_CONTINUOUS_SEND':
        continuousSender.stop();
        sendResponse({ ok: true });
        return false;

      case 'SKIP_CURRENT_CANDIDATE':
        continuousSender.skipCurrent();
        sendResponse({ ok: true });
        return false;

      case 'RESUME_AFTER_JOB_OFFER':
        continuousSender.resumeAfterJobOfferFix();
        sendResponse({ ok: true });
        return false;

      case 'EXTRACT_JOB_OFFERS':
        extractJobOffers().then(sendResponse);
        return true;

      case 'EXTRACT_FACILITY_LIST': {
        try {
          const list = extractFacilityList();
          sendResponse({ success: true, facilities: list });
        } catch (err: unknown) {
          sendResponse({ success: false, facilities: [], error: (err as Error).message });
        }
        return false;
      }

      case 'EXTRACT_FACILITY_INFO':
        extractFacilityInfo(message.facilityIds)
          .then((facilities) => sendResponse({ success: true, facilities }))
          .catch((err) => sendResponse({ success: false, facilities: [], error: err.message }));
        return true;

      case 'STOP_FACILITY_EXTRACTION':
        abortFacilityExtraction();
        sendResponse({ ok: true });
        return false;

      default:
        return false;
    }
  }
);

// 初期化
setupOverlayObserver();
console.log('[Scout Assistant] Content script loaded');
