"""Cost tracker with Google Sheets persistence.

Each record() call updates both in-memory stats and the Sheets row for
the current day (upsert).  Daily/monthly summaries read from Sheets so
that data survives Cloud Run container restarts.
"""
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
    "total_tokens", "estimated_cost_usd", "ai_requests",
]

_EMPTY_STATS = {
    "requests": 0,
    "ai_requests": 0,
    "prompt_tokens": 0,
    "output_tokens": 0,
    "estimated_cost": 0.0,
}


def _parse_int(v: str, default: int = 0) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def _parse_float(v: str, default: float = 0.0) -> float:
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


class CostTracker:
    def __init__(self):
        self._lock = Lock()
        # In-memory buffer for the current day only (accumulates between Sheets writes)
        self._daily_stats: dict[str, dict] = defaultdict(lambda: {**_EMPTY_STATS})
        self._last_alerted_level: float = 0.0

    # ------------------------------------------------------------------
    # Sheets helpers
    # ------------------------------------------------------------------

    def _sheets_writer(self):
        from db.sheets_writer import sheets_writer
        return sheets_writer

    def _ensure_sheet(self) -> None:
        self._sheets_writer().ensure_sheet_exists(COST_SHEET, COST_HEADERS)

    def _upsert_today_to_sheets(self, date_str: str, stats: dict) -> None:
        """Upsert a single day's row in the cost sheet."""
        try:
            sw = self._sheets_writer()
            self._ensure_sheet()
            rows = sw.get_all_rows(COST_SHEET)

            row_values = [
                date_str,
                str(stats["requests"]),
                str(stats["prompt_tokens"]),
                str(stats["output_tokens"]),
                str(stats["prompt_tokens"] + stats["output_tokens"]),
                f"{stats['estimated_cost']:.6f}",
                str(stats.get("ai_requests", 0)),
            ]

            # Find existing row for this date (skip header at index 0)
            for idx, row in enumerate(rows):
                if idx == 0:
                    continue
                if row and row[0] == date_str:
                    sw.update_row(COST_SHEET, idx + 1, row_values)  # 1-indexed
                    logger.debug(f"Updated cost row for {date_str}")
                    return

            # No existing row – append
            sw.append_row(COST_SHEET, row_values)
            logger.debug(f"Appended cost row for {date_str}")
        except Exception as e:
            logger.warning(f"Failed to upsert cost to Sheets: {e}")

    def _read_daily_from_sheets(self, date_str: str) -> dict | None:
        """Read a single day's stats from Sheets. Returns None if not found."""
        try:
            rows = self._sheets_writer().get_all_rows(COST_SHEET)
            for idx, row in enumerate(rows):
                if idx == 0:
                    continue
                if row and row[0] == date_str:
                    return {
                        "requests": _parse_int(row[1] if len(row) > 1 else "0"),
                        "prompt_tokens": _parse_int(row[2] if len(row) > 2 else "0"),
                        "output_tokens": _parse_int(row[3] if len(row) > 3 else "0"),
                        "estimated_cost": _parse_float(row[5] if len(row) > 5 else "0"),
                        # ai_requests列は後方互換: 無い場合は requests と同値扱い(旧データ想定)
                        "ai_requests": _parse_int(row[6] if len(row) > 6 else "0"),
                    }
        except Exception as e:
            logger.warning(f"Failed to read cost from Sheets for {date_str}: {e}")
        return None

    def _read_monthly_from_sheets(self, month_prefix: str) -> dict:
        """Aggregate all rows matching month_prefix from Sheets."""
        total = {**_EMPTY_STATS}
        try:
            rows = self._sheets_writer().get_all_rows(COST_SHEET)
            for idx, row in enumerate(rows):
                if idx == 0:
                    continue
                if row and row[0].startswith(month_prefix):
                    total["requests"] += _parse_int(row[1] if len(row) > 1 else "0")
                    total["prompt_tokens"] += _parse_int(row[2] if len(row) > 2 else "0")
                    total["output_tokens"] += _parse_int(row[3] if len(row) > 3 else "0")
                    total["estimated_cost"] += _parse_float(row[5] if len(row) > 5 else "0")
                    total["ai_requests"] += _parse_int(row[6] if len(row) > 6 else "0")
        except Exception as e:
            logger.warning(f"Failed to read monthly cost from Sheets: {e}")
        return total

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        prompt_tokens: int,
        output_tokens: int,
        model_name: str,
        generation_path: str = "ai",
    ) -> None:
        """Record a single generation to daily stats + Sheets.

        `generation_path` is one of "ai" / "pattern" / "mock" / "filtered_out".
        Patterns and mock calls don't consume tokens but still count as
        requests — they're tracked so we can see the ratio of AI vs
        pattern generation in daily reports.
        """
        if generation_path == "ai" and (prompt_tokens > 0 or output_tokens > 0):
            pricing = get_model_pricing(model_name)
            cost = (
                prompt_tokens * pricing["input"]
                + output_tokens * pricing["output"]
            ) / 1_000_000
        else:
            cost = 0.0
            prompt_tokens = 0
            output_tokens = 0

        today = datetime.now(JST).strftime("%Y-%m-%d")

        with self._lock:
            stats = self._daily_stats[today]
            # On first write of the day, seed from Sheets (container may have restarted)
            if stats["requests"] == 0:
                sheets_stats = self._read_daily_from_sheets(today)
                if sheets_stats:
                    stats.update(sheets_stats)

            stats["requests"] += 1
            if generation_path == "ai":
                stats["ai_requests"] += 1
            stats["prompt_tokens"] += prompt_tokens
            stats["output_tokens"] += output_tokens
            stats["estimated_cost"] += cost

            snapshot = {**stats}

        # Persist outside the lock
        self._upsert_today_to_sheets(today, snapshot)

        logger.info(
            f"Cost recorded [{generation_path}]: "
            f"{prompt_tokens}+{output_tokens} tokens, "
            f"${cost:.6f} ({model_name})"
        )

    def get_daily_summary(self, date_str: str | None = None) -> dict:
        """Get summary for a specific date. Reads from Sheets for persistence."""
        if date_str is None:
            date_str = datetime.now(JST).strftime("%Y-%m-%d")

        # For today, in-memory may be more up-to-date
        today = datetime.now(JST).strftime("%Y-%m-%d")
        if date_str == today:
            with self._lock:
                stats = self._daily_stats.get(date_str)
                if stats and stats["requests"] > 0:
                    return {
                        "date": date_str,
                        "requests": stats["requests"],
                        "ai_requests": stats.get("ai_requests", 0),
                        "pattern_requests": stats["requests"] - stats.get("ai_requests", 0),
                        "prompt_tokens": stats["prompt_tokens"],
                        "output_tokens": stats["output_tokens"],
                        "estimated_cost_usd": round(stats["estimated_cost"], 6),
                    }

        # Past dates or cold start → read from Sheets
        sheets_stats = self._read_daily_from_sheets(date_str)
        if sheets_stats and sheets_stats["requests"] > 0:
            return {
                "date": date_str,
                "requests": sheets_stats["requests"],
                "ai_requests": sheets_stats.get("ai_requests", 0),
                "pattern_requests": sheets_stats["requests"] - sheets_stats.get("ai_requests", 0),
                "prompt_tokens": sheets_stats["prompt_tokens"],
                "output_tokens": sheets_stats["output_tokens"],
                "estimated_cost_usd": round(sheets_stats["estimated_cost"], 6),
            }

        return {
            "date": date_str,
            "requests": 0,
            "ai_requests": 0,
            "pattern_requests": 0,
            "prompt_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_usd": 0.0,
        }

    def get_monthly_summary(self) -> dict:
        """Get summary for the current month from Sheets."""
        now = datetime.now(JST)
        month_prefix = now.strftime("%Y-%m")

        total = self._read_monthly_from_sheets(month_prefix)

        return {
            "month": month_prefix,
            "requests": total["requests"],
            "ai_requests": total.get("ai_requests", 0),
            "pattern_requests": total["requests"] - total.get("ai_requests", 0),
            "prompt_tokens": total["prompt_tokens"],
            "output_tokens": total["output_tokens"],
            "estimated_cost_usd": round(total["estimated_cost"], 6),
        }

    def should_alert(self, threshold_usd: float) -> bool:
        """Check if monthly cost crossed the next threshold multiple."""
        now = datetime.now(JST)

        # Reset on new month
        if now.day == 1 and self._last_alerted_level > 0:
            self._last_alerted_level = 0.0

        monthly = self.get_monthly_summary()
        cost = monthly["estimated_cost_usd"]

        if threshold_usd <= 0:
            return False

        current_level = int(cost / threshold_usd) * threshold_usd
        if current_level > 0 and current_level > self._last_alerted_level:
            self._last_alerted_level = current_level
            return True
        return False

    def persist_daily_to_sheets(self, date_str: str | None = None) -> None:
        """Write daily summary to Google Sheets (kept for backward compat)."""
        summary = self.get_daily_summary(date_str)
        if summary["requests"] == 0:
            return
        self._upsert_today_to_sheets(
            summary["date"],
            {
                "requests": summary["requests"],
                "ai_requests": summary.get("ai_requests", 0),
                "prompt_tokens": summary["prompt_tokens"],
                "output_tokens": summary["output_tokens"],
                "estimated_cost": summary["estimated_cost_usd"],
            },
        )


cost_tracker = CostTracker()
