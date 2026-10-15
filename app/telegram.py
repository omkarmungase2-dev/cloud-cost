"""
Telegram notification and polling (optional).
Enabled only if both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set.
Never raises errors to callers; catches and logs all exceptions.
"""

import logging
from typing import Dict, Any, Optional
import httpx
from app.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger("firewall.telegram")


async def notify(client: Optional[httpx.AsyncClient], info: Dict[str, Any]) -> None:
    """
    Send an approval request to Telegram with inline buttons for Approve / Deny.
    No-op if Telegram is not configured.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not client:
        return

    run_id = info.get("run_id", "unknown")
    user = info.get("user", "unknown")
    feature = info.get("feature", "unknown")
    spent = info.get("spent", 0.0)
    est = info.get("est", 0.0)
    projected = info.get("projected", 0.0)
    cap = info.get("cap", 0.0)
    reason = info.get("reason", "")

    text = (
        f"🚨 <b>Cost Firewall Approval Needed</b>\n\n"
        f"<b>Run:</b> <code>{run_id}</code>\n"
        f"<b>User:</b> {user} | <b>Feature:</b> {feature}\n"
        f"<b>Current spend:</b> Rs{spent:.5f}\n"
        f"<b>This call est:</b> Rs{est:.5f}\n"
        f"<b>Projected:</b> Rs{projected:.5f} (Cap: Rs{cap:.5f})\n"
        f"<b>Reason:</b> {reason}\n"
    )

    # Inline keyboard: Approve / Deny (max 64 bytes callback_data)
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve (2x Cap)", "callback_data": f"a:{run_id}"[:64]},
                {"text": "❌ Deny", "callback_data": f"d:{run_id}"[:64]},
            ]
        ]
    }

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": keyboard,
    }

    try:
        resp = await client.post(url, json=payload, timeout=5.0)
        if resp.status_code != 200:
            logger.warning(f"[telegram] sendMessage failed: {resp.text}")
    except Exception as e:
        logger.warning(f"[telegram] Failed to notify: {e}")
