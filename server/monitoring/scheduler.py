"""Background scheduler for cost notifications and alerts."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from config import COST_ALERT_THRESHOLD_USD, GOOGLE_CHAT_WEBHOOK_URL

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


def _format_cost_message(summary: dict, title: str) -> str:
    """Format a cost summary into a human-readable message."""
    cost = summary["estimated_cost_usd"]
    ai_reqs = summary.get("ai_requests", 0)
    pattern_reqs = summary.get("pattern_requests", max(0, summary["requests"] - ai_reqs))
    lines = [
        f"📊 *{title}*",
        f"期間: {summary.get('date') or summary.get('month')}",
        f"総生成数: {summary['requests']:,}",
        f"  ├ AI生成: {ai_reqs:,}",
        f"  └ パターン: {pattern_reqs:,}",
        f"入力トークン: {summary['prompt_tokens']:,}",
        f"出力トークン: {summary['output_tokens']:,}",
        f"推定コスト: ${cost:.4f}",
    ]
    return "\n".join(lines)


async def _check_alert() -> None:
    """Check if monthly cost alert threshold is exceeded."""
    from monitoring.cost_tracker import cost_tracker
    from monitoring.notifier import notify_google_chat

    if cost_tracker.should_alert(COST_ALERT_THRESHOLD_USD):
        monthly = cost_tracker.get_monthly_summary()
        message = (
            f"⚠️ *コストアラート*\n"
            f"月間推定コストが閾値 ${COST_ALERT_THRESHOLD_USD:.2f} を超えました。\n\n"
            + _format_cost_message(monthly, "今月の集計")
        )
        await notify_google_chat(message)
        logger.warning(
            f"Cost alert triggered: ${monthly['estimated_cost_usd']:.4f} "
            f">= ${COST_ALERT_THRESHOLD_USD:.2f}"
        )


async def _daily_report() -> None:
    """Send daily cost summary and persist to Sheets."""
    from monitoring.cost_tracker import cost_tracker
    from monitoring.notifier import notify_google_chat

    yesterday = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")
    summary = cost_tracker.get_daily_summary(yesterday)

    # Persist to Sheets
    cost_tracker.persist_daily_to_sheets(yesterday)

    # Send notification (always, even if 0 requests)
    monthly = cost_tracker.get_monthly_summary()
    if summary["requests"] > 0:
        message = _format_cost_message(summary, "日次コストレポート")
    else:
        message = (
            f"📊 *日次コストレポート*\n"
            f"期間: {yesterday}\n"
            f"総生成数: 0"
        )
    message += (
        f"\n\n📅 今月累計: ${monthly['estimated_cost_usd']:.4f} "
        f"(AI {monthly.get('ai_requests', 0):,} / "
        f"パターン {monthly.get('pattern_requests', 0):,})"
    )
    await notify_google_chat(message)


async def _scheduler_loop() -> None:
    """Main scheduler loop. Runs daily report at 9:00 JST and checks alerts every 5 min."""
    logger.info("Cost monitoring scheduler started")

    last_daily_report_date = ""

    while True:
        try:
            now = datetime.now(JST)

            # Daily report at 9:00 JST
            today = now.strftime("%Y-%m-%d")
            if now.hour >= 9 and today != last_daily_report_date:
                await _daily_report()
                last_daily_report_date = today

            # Alert check
            await _check_alert()

        except Exception as e:
            logger.error(f"Scheduler error: {e}")

        await asyncio.sleep(300)  # Check every 5 minutes


async def start_scheduler() -> None:
    """Start the background scheduler if webhook is configured."""
    if not GOOGLE_CHAT_WEBHOOK_URL:
        logger.info("GOOGLE_CHAT_WEBHOOK_URL not set, cost scheduler disabled")
        return

    asyncio.create_task(_scheduler_loop())
