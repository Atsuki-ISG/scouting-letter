"""Google Chat webhook notifier."""
from __future__ import annotations

import logging

import httpx

from config import GOOGLE_CHAT_WEBHOOK_URL

logger = logging.getLogger(__name__)


async def notify_google_chat(message: str) -> bool:
    """Send a message to Google Chat via webhook.

    Returns True if sent successfully, False otherwise.
    """
    if not GOOGLE_CHAT_WEBHOOK_URL:
        logger.debug("GOOGLE_CHAT_WEBHOOK_URL not set, skipping notification")
        return False

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                GOOGLE_CHAT_WEBHOOK_URL,
                json={"text": message},
            )
            resp.raise_for_status()
            logger.info("Google Chat notification sent")
            return True
    except Exception as e:
        logger.warning(f"Failed to send Google Chat notification: {e}")
        return False
