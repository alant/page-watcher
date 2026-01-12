import os
import requests
import logging

BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
CHAT_ID = os.getenv("TG_CHAT_ID")

log = logging.getLogger(__name__)

def send_telegram_message(text, parse_mode="Markdown"):
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("Telegram bot token or chat ID is not set.")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    MAX_LEN = 4000
    text = text[:MAX_LEN]
    data = {
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": True
    }
    if parse_mode is not None:
        data["parse_mode"] = parse_mode
    try:
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            log.info(f"Telegram message sent successfully")
            return True
        else:
            # If markdown fails, retry without parse_mode
            log.warning(f"Telegram failed with markdown (status {response.status_code}), retrying as plain text")
            data.pop("parse_mode", None)
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                log.info(f"Telegram message sent as plain text")
                return True
            else:
                log.error(f"Telegram failed: {response.status_code} - {response.text[:200]}")
                return False
    except Exception as e:
        log.error(f"Failed to send Telegram message: {e}")
        return False
