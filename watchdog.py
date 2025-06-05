import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path

from monitor import parse_interval, send_telegram_message  # import both from monitor.py

BASE_DIR = Path(__file__).parent.resolve()
LOG_FILE = BASE_DIR / "monitor.log"
WATCHDOG_LOG = BASE_DIR / "watchdog.log"

load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(WATCHDOG_LOG), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

CHECK_INTERVAL_STR = os.getenv("CHECK_INTERVAL", "3h")

def main():
    try:
        threshold_seconds = parse_interval(CHECK_INTERVAL_STR)
    except Exception as e:
        log.error(f"Invalid CHECK_INTERVAL format: {e}")
        threshold_seconds = 3 * 3600  # fallback 3 hours

    if not LOG_FILE.exists():
        log.error(f"{LOG_FILE} does not exist.")
        send_telegram_message(f"⚠️ Warning: `{LOG_FILE.name}` does not exist on server!")
        return

    last_modified = datetime.fromtimestamp(LOG_FILE.stat().st_mtime)
    now = datetime.now()
    diff = now - last_modified

    log.info(f"Last monitor.log modification: {last_modified} ({diff.total_seconds()/3600:.2f} hours ago)")

    if diff.total_seconds() > threshold_seconds:
        message = (
            f"🚨 *Alert*: The log file `{LOG_FILE.name}` was last updated "
            f"{diff.total_seconds() / 3600:.2f} hours ago, which exceeds the "
            f"threshold of `{CHECK_INTERVAL_STR}`.\n"
            "The page watcher may have stopped running."
        )
        send_telegram_message(message)
    else:
        log.info("Log file update time within threshold.")

if __name__ == "__main__":
    main()
