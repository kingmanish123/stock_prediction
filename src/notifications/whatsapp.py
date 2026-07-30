"""WhatsApp client — thin wrapper over the local Baileys HTTP daemon.

The Node bot at `whatsapp-bot/server.js` exposes POST /send {to, message}.
We POST to it. Failure modes (bot offline, phone unlinked) never raise —
they log + return False so automation jobs never crash mid-pipeline.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

from ..common.logger import get_logger

logger = get_logger(__name__)

BOT_URL = os.getenv("WHATSAPP_BOT_URL", "http://127.0.0.1:3001")
DEFAULT_RECIPIENT = os.getenv("WHATSAPP_NUMBER", "")
REQUEST_TIMEOUT = 10.0


def send(message: str, to: Optional[str] = None) -> bool:
    """Send one WhatsApp message. Returns True on success, False otherwise."""
    recipient = to or DEFAULT_RECIPIENT
    if not recipient:
        logger.warning("whatsapp_no_recipient")
        return False

    try:
        resp = httpx.post(
            f"{BOT_URL}/send",
            json={"to": recipient, "message": message},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200 and resp.json().get("ok"):
            return True
        logger.warning(
            "whatsapp_send_failed",
            status=resp.status_code,
            body=resp.text[:200],
        )
        return False
    except Exception as e:
        logger.warning("whatsapp_bot_unreachable", error=str(e))
        return False


def is_healthy() -> bool:
    """Quick ping — useful before scheduling heavy jobs."""
    try:
        resp = httpx.get(f"{BOT_URL}/health", timeout=3.0)
        return resp.status_code == 200 and resp.json().get("ok") is True
    except Exception:
        return False
