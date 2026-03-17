/**
 * Scout Assistant - GAS Web App
 *
 * Setup:
 * 1. Create a new Google Apps Script project
 * 2. Paste this code
 * 3. Deploy as Web App (Execute as: Me, Access: Anyone)
 * 4. Copy the deployment URL to the Chrome extension popup settings
 *
 * Spreadsheet structure:
 * - Sheet 1 "送信ログ": timestamp, member_id, company, job_offer_id, job_offer_label, template_type, personalized_text
 */

const SPREADSHEET_ID = '1VA6unIqDsH0uFPCmTqH72gkSZ_33IGiQ7E28Vhc8yvw';

function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents);

    if (payload.action === 'logScout') {
      logScout(payload.data);
      return ContentService.createTextOutput(JSON.stringify({ success: true }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    return ContentService.createTextOutput(JSON.stringify({ success: false, error: 'Unknown action' }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({ success: false, error: err.message }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  var action = e.parameter.action;

  if (action === 'ping') {
    return ContentService.createTextOutput(JSON.stringify({ success: true, message: 'pong' }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  if (action === 'logScout') {
    try {
      var data = JSON.parse(e.parameter.data);
      logScout(data);
      return ContentService.createTextOutput(JSON.stringify({ success: true }))
        .setMimeType(ContentService.MimeType.JSON);
    } catch (err) {
      return ContentService.createTextOutput(JSON.stringify({ success: false, error: err.message }))
        .setMimeType(ContentService.MimeType.JSON);
    }
  }

  return ContentService.createTextOutput(JSON.stringify({ success: false, error: 'Unknown action' }))
    .setMimeType(ContentService.MimeType.JSON);
}

/** JST ローカルタイムスタンプ (YYYY-MM-DDTHH:mm:ss+09:00) */
function localTimestamp_() {
  var now = new Date();
  var jst = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  var pad = function(n) { return ('0' + n).slice(-2); };
  return jst.getUTCFullYear() + '-' + pad(jst.getUTCMonth() + 1) + '-' + pad(jst.getUTCDate()) +
    'T' + pad(jst.getUTCHours()) + ':' + pad(jst.getUTCMinutes()) + ':' + pad(jst.getUTCSeconds()) + '+09:00';
}

function logScout(data) {
  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sheet = ss.getSheetByName('送信ログ') || ss.insertSheet('送信ログ');

  // Add header if empty
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(['timestamp', 'member_id', 'company', 'job_offer_id', 'job_offer_label', 'template_type', 'personalized_text']);
  }

  sheet.appendRow([
    data.timestamp || localTimestamp_(),
    data.member_id,
    data.company,
    data.job_offer_id,
    data.job_offer_label,
    data.template_type,
    data.personalized_text,
  ]);
}
