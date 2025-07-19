import os
import requests
import logging

BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
CHAT_ID = os.getenv("TG_CHAT_ID")

log = logging.getLogger(__name__)

def send_telegram_message(text, parse_mode="Markdown"):
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("Telegram bot token or chat ID is not set.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    MAX_LEN = 4000
    text = text[:MAX_LEN]
    data = {
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": False
    }
    if parse_mode is not None:
        data["parse_mode"] = parse_mode
    try:
        response = requests.post(url, data=data)
        log.debug(f"Telegram status code: {response.status_code}")
    except Exception as e:
        log.error(f"Failed to send message: {e}")
