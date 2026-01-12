"""
Notification module with multiple backends.
Primary: Telegram
Backup: Discord webhook (free, reliable on iOS)

Setup for Discord webhook:
1. Create a Discord server (or use existing)
2. Go to Server Settings > Integrations > Webhooks
3. Create a webhook, copy the URL
4. Set DISCORD_WEBHOOK_URL in .env
5. Enable notifications for that channel on your phone
"""

import os
import requests
import logging
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# Telegram config
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

# Discord webhook config (backup)
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")


def send_telegram(text, parse_mode="Markdown"):
    """Send message via Telegram. Returns True on success."""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        log.warning("Telegram bot token or chat ID is not set.")
        return False

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    MAX_LEN = 4000
    text = text[:MAX_LEN]
    data = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True
    }
    if parse_mode:
        data["parse_mode"] = parse_mode

    try:
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            log.info("Telegram message sent successfully")
            return True
        else:
            # If markdown fails, retry without parse_mode
            log.warning(f"Telegram failed with markdown (status {response.status_code}), retrying as plain text")
            data.pop("parse_mode", None)
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                log.info("Telegram message sent as plain text")
                return True
            else:
                log.error(f"Telegram failed: {response.status_code} - {response.text[:200]}")
                return False
    except Exception as e:
        log.error(f"Failed to send Telegram message: {e}")
        return False


def send_discord(text, username="Page Watcher", is_error=False):
    """
    Send message via Discord webhook. Returns True on success.

    Discord supports basic markdown (bold, italic, code blocks).
    """
    if not DISCORD_WEBHOOK_URL:
        log.warning("DISCORD_WEBHOOK_URL is not set, skipping Discord notification")
        return False

    # Discord has 2000 char limit per message
    MAX_LEN = 1900
    text = text[:MAX_LEN]

    # Add emoji prefix for errors
    if is_error:
        text = f"⚠️ **ERROR**\n{text}"

    payload = {
        "username": username,
        "content": text,
    }

    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        # Discord returns 204 No Content on success
        if response.status_code in [200, 204]:
            log.info("Discord message sent successfully")
            return True
        else:
            log.error(f"Discord failed: {response.status_code} - {response.text[:200]}")
            return False
    except Exception as e:
        log.error(f"Failed to send Discord message: {e}")
        return False


def notify(text, is_error=False):
    """
    Send notification via Telegram, with Discord as backup.

    Args:
        text: Message content
        is_error: If True, marks as error notification

    Returns True if at least one notification succeeded.
    """
    # Try Telegram first
    tg_success = send_telegram(text)

    if tg_success:
        return True

    # Telegram failed, try Discord as backup
    log.warning("Telegram failed, trying Discord backup...")

    # Convert Telegram markdown to Discord markdown (mostly compatible)
    # Just need to handle code blocks slightly differently
    discord_text = text.replace("```diff\n", "```\n")
    discord_success = send_discord(discord_text, is_error=is_error)

    if discord_success:
        return True

    log.error("All notification methods failed!")
    return False


def notify_error(error_msg, context=""):
    """
    Convenience function for error notifications.
    Sends via both channels if possible for redundancy.
    """
    full_msg = f"🚨 *ERROR in Page Watcher*\n\n{context}\n\n{error_msg}" if context else f"🚨 *ERROR in Page Watcher*\n\n{error_msg}"

    # Try both channels for errors (redundancy)
    tg_ok = send_telegram(full_msg)

    # Discord version (** for bold instead of *)
    discord_msg = full_msg.replace("*", "**")
    discord_ok = send_discord(discord_msg, is_error=True)

    return tg_ok or discord_ok
