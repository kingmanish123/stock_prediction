"""Check if Upstox access token is valid; WhatsApp reminder if not.

Runs at 6:50 AM IST daily. Token expires every day ~3:30 AM IST so a fresh
login is needed each morning. This script pings /user/profile and sends a
reminder via WhatsApp if it fails.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.common.logger import get_logger, setup_logging
from src.notifications import templates, whatsapp

setup_logging()
logger = get_logger(__name__)


def main() -> int:
    # Lazy import so script doesn't crash if broker module has deps issue
    try:
        from src.broker.upstox_client import UpstoxClient, UpstoxError
    except Exception as e:
        logger.error("upstox_import_failed", error=str(e))
        whatsapp.send(templates.upstox_token_warning())
        return 1

    try:
        client = UpstoxClient()
        profile = client.ping()
        logger.info("upstox_token_valid", user=profile.get("user_name"))
        return 0
    except UpstoxError as e:
        logger.warning("upstox_token_missing", error=str(e))
        whatsapp.send(templates.upstox_token_warning())
        return 1
    except Exception as e:
        # 401 Unauthorized is the normal "token expired" signal
        logger.warning("upstox_token_invalid", error=str(e)[:200])
        whatsapp.send(templates.upstox_token_warning())
        return 1


if __name__ == "__main__":
    sys.exit(main())
