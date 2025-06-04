import os
import re
import requests
import hashlib
import difflib
from bs4 import BeautifulSoup
from pathlib import Path
import time
from datetime import datetime
from urllib.parse import urlparse, quote
import logging
from urllib.parse import urlparse, quote, parse_qs


BASE_DIR = Path.cwd()

log_file = BASE_DIR / "monitor.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

log = logging.getLogger(__name__)


def parse_interval(interval_str):
    match = re.match(r"(\d+)([smhd])", interval_str.strip().lower())
    if not match:
        raise ValueError(f"Invalid CHECK_INTERVAL format: {interval_str}")
    value, unit = match.groups()
    value = int(value)
    return {
        "s": value,
        "m": value * 60,
        "h": value * 3600,
        "d": value * 86400,
    }[unit]


URLS = os.getenv("URLS", "").split(",")
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
CHAT_ID = os.getenv("TG_CHAT_ID")
CHECK_INTERVAL = parse_interval(os.getenv("CHECK_INTERVAL", "3h"))

HISTORY_DIR = BASE_DIR / "page-history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def fetch_page(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/114.0.0.0 Safari/537.36"
        )
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        log.error(f"Failed to fetch {url}: {e}")
        return None


def clean_html(html):
    soup = BeautifulSoup(html, "html.parser")

    # Remove unwanted tags like script/style
    for tag in soup(["script", "style"]):
        tag.decompose()

    # Normalize spacing
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def hash_content(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    try:
        response = requests.post(url, data=data)
        log.debug(f"Telegram status code: {response.status_code}")
        log.debug(f"Telegram response: {response.text}")
    except Exception as e:
        log.error(f"Failed to send message: {e}")


def slugify_url(url):
    parsed = urlparse(url)
    netloc = parsed.netloc.replace(":", "_")
    path = parsed.path.strip("/").replace("/", "_") or "root"
    qs = parse_qs(parsed.query)

    # Handle midpen-housing.org
    if "midpen-housing.org" in netloc:
        county = qs.get("aspf[county__4]", ["unknown"])[0].replace(" ", "_").lower()
        return f"{netloc}_{path}_county_{county}"

    # Handle edenhousing.org
    if "edenhousing.org" in netloc:
        county = qs.get("_sft_county", ["unknown"])[0].replace(" ", "_").lower()
        return f"{netloc}_{path}_county_{county}"

    # Fallback
    return quote(f"{netloc}_{path}")


def get_storage_paths(slug):
    base_dir = HISTORY_DIR / slug
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "latest.hash", base_dir / "latest.txt", base_dir


def monitor_page(url):
    log.info(f"Checking {url}")
    html = fetch_page(url)
    if not html:
        return

    text = clean_html(html)
    current_hash = hash_content(text)
    slug = slugify_url(url)
    hash_file, text_file, page_dir = get_storage_paths(slug)

    if not hash_file.exists():
        log.info(f"Storing first version of {url}")
        hash_file.write_text(current_hash)
        text_file.write_text(text)

        # Save the text snapshot
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (page_dir / f"{slug}-{timestamp}.txt").write_text(text)
        return

    old_hash = hash_file.read_text()
    if current_hash != old_hash:
        log.info(f"Detected change in {url}")
        old_text = text_file.read_text()

        diff = difflib.unified_diff(
            old_text.splitlines(), text.splitlines(),
            fromfile="before", tofile="after", lineterm=""
        )
        diff_lines = list(diff)

        if not diff_lines:
            log.warning("Diff empty despite hash change.")
            return

        trimmed_diff = "\n".join(diff_lines[:100])
        message = f"🚨 *Change detected*\n{url}\n\n```diff\n{trimmed_diff}\n```"
        send_telegram_message(message)

        # Save the new version
        hash_file.write_text(current_hash)
        text_file.write_text(text)

        # Save text snapshot
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (page_dir / f"{slug}-{timestamp}.txt").write_text(text)
    else:
        log.info(f"No change in {url}")


def format_sleep_time(seconds):
    if seconds < 60:
        return f"{seconds} seconds"
    elif seconds < 3600:
        return f"{seconds // 60} minutes"
    else:
        return f"{seconds // 3600} hours"


def main():
    while True:
        for url in URLS:
            url = url.strip()
            if url:
                monitor_page(url)
        log.info(f"Sleeping for {format_sleep_time(CHECK_INTERVAL)}...")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
