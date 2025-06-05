#!/usr/bin/env python3

import os
import time
import requests
import logging
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load .env from current directory
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Log and config paths
MONITOR_LOG = BASE_DIR / "monitor.log"
WATCHDOG_LOG = BASE_DIR / "watchdog.log"

# Telegram config from .env
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
CHAT_ID = os.getenv("TG_CHAT_ID")

# Time threshold
THRESHOLD_HOURS = 3

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(WATCHDOG_LOG),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

def send_telegram_message(text):
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("TG_BOT_TOKEN or TG_CHAT_ID not set in .env")
        return
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "Markdown"
            },
            timeout=10
        )
        log.info(f"Sent Telegram message: {response.status_code}")
    except Exception as e:
        log.error(f"Failed to send Telegram message: {e}")

def check_log_activity():
    if not MONITOR_LOG.exists():
        log.error("monitor.log does not exist.")
        send_telegram_message("🚨 *monitor.log is missing!*")
        return

    last_modified = datetime.fromtimestamp(MONITOR_LOG.stat().st_mtime)
    now = datetime.now()
    delta = now - last_modified

    log.info(f"monitor.log last updated: {last_modified.strftime('%Y-%m-%d %H:%M:%S')} ({delta.total_seconds() / 60:.1f} minutes ago)")

    if delta > timedelta(hours=THRESHOLD_HOURS):
        send_telegram_message(
            f"⚠️ *No activity in monitor.log for over {THRESHOLD_HOURS} hours!*\nLast update: `{last_modified.strftime('%Y-%m-%d %H:%M:%S')}`"
        )
    else:
        log.info("monitor.log is recent enough. No alert sent.")

if __name__ == "__main__":
    check_log_activity()
