"""In-memory cost tracker with Sheets persistence."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from threading import Lock

from config import get_model_pricing

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

COST_SHEET = "コスト集計"
COST_HEADERS = [
    "date", "requests", "prompt_tokens", "output_tokens",
    "total_tokens", "estimated_cost_usd",
]


class CostTracker:
    def __init__(self):
        self._lock = Lock()
        # {date_str: {"requests": int, "prompt_tokens": int, "output_tokens": int, "estimated_cost": float}}
        self._daily_stats: dict[str, dict] = defaultdict(
            lambda: {"requests": 0, "prompt_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0}
        )
        # Track the last threshold level that triggered an alert (e.g. 100, 200, 300...)
        self._last_alerted_level: float = 0.0

    def record(self, prompt_tokens: int, output_tokens: int, model_name: str) -> None:
        """Record a single AI generation's token usage."""
        pricing = get_model_pricing(model_name)
        cost = (
            prompt_tokens * pricing["input"]
            + output_tokens * pricing["output"]
        ) / 1_000_000

        today = datetime.now(JST).strftime("%Y-%m-%d")

        with self._lock:
            stats = self._daily_stats[today]
            stats["requests"] += 1
            stats["prompt_tokens"] += prompt_tokens
            stats["output_tokens"] += output_tokens
            stats["estimated_cost"] += cost

        logger.info(
            f"Cost recorded: {prompt_tokens}+{output_tokens} tokens, "
            f"${cost:.6f} ({model_name})"
        )

    def get_daily_summary(self, date_str: str | None = None) -> dict:
        """Get summary for a specific date (default: today)."""
        if date_str is None:
            date_str = datetime.now(JST).strftime("%Y-%m-%d")

        with self._lock:
            stats = self._daily_stats.get(date_str)
            if stats is None:
                return {
                    "date": date_str,
                    "requests": 0,
                    "prompt_tokens": 0,
                    "output_tokens": 0,
                    "estimated_cost_usd": 0.0,
                }
            return {
                "date": date_str,
                "requests": stats["requests"],
                "prompt_tokens": stats["prompt_tokens"],
                "output_tokens": stats["output_tokens"],
                "estimated_cost_usd": round(stats["estimated_cost"], 6),
            }

    def get_monthly_summary(self) -> dict:
        """Get summary for the current month."""
        now = datetime.now(JST)
        month_prefix = now.strftime("%Y-%m")

        total = {"requests": 0, "prompt_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0}

        with self._lock:
            for date_str, stats in self._daily_stats.items():
                if date_str.startswith(month_prefix):
                    total["requests"] += stats["requests"]
                    total["prompt_tokens"] += stats["prompt_tokens"]
                    total["output_tokens"] += stats["output_tokens"]
                    total["estimated_cost"] += stats["estimated_cost"]

        return {
            "month": month_prefix,
            "requests": total["requests"],
            "prompt_tokens": total["prompt_tokens"],
            "output_tokens": total["output_tokens"],
            "estimated_cost_usd": round(total["estimated_cost"], 6),
        }

    def should_alert(self, threshold_usd: float) -> bool:
        """Check if monthly cost crossed the next threshold multiple ($100, $200, $300...).

        Alerts at every multiple of threshold_usd, not just once.
        Resets at the start of each month.
        """
        now = datetime.now(JST)
        month_prefix = now.strftime("%Y-%m")

        # Reset on new month
        if now.day == 1 and self._last_alerted_level > 0:
            # Check if we're in a new month vs last alert
            self._last_alerted_level = 0.0

        monthly = self.get_monthly_summary()
        cost = monthly["estimated_cost_usd"]

        if threshold_usd <= 0:
            return False

        # Which threshold level are we at? e.g. cost=250, threshold=100 → level=200
        current_level = int(cost / threshold_usd) * threshold_usd
        if current_level > 0 and current_level > self._last_alerted_level:
            self._last_alerted_level = current_level
            return True
        return False

    def persist_daily_to_sheets(self, date_str: str | None = None) -> None:
        """Write daily summary to Google Sheets."""
        summary = self.get_daily_summary(date_str)
        if summary["requests"] == 0:
            return

        try:
            from db.sheets_writer import sheets_writer
            sheets_writer.ensure_sheet_exists(COST_SHEET, COST_HEADERS)
            sheets_writer.append_row(COST_SHEET, [
                summary["date"],
                str(summary["requests"]),
                str(summary["prompt_tokens"]),
                str(summary["output_tokens"]),
                str(summary["prompt_tokens"] + summary["output_tokens"]),
                f"{summary['estimated_cost_usd']:.6f}",
            ])
            logger.info(f"Persisted daily cost to Sheets: {summary['date']}")
        except Exception as e:
            logger.warning(f"Failed to persist daily cost: {e}")


cost_tracker = CostTracker()
