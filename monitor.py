import os
import re
import requests
import hashlib
import difflib
from bs4 import BeautifulSoup
from pathlib import Path
import time
from datetime import datetime
from urllib.parse import urlparse, quote, parse_qs

# Logging setup
import logging
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

def parse_special_link_monitors(value):
    result = {}
    for entry in value.split(","):
        if "|" in entry:
            page_url, link_text = entry.split("|", 1)
            page_url = page_url.strip()
            link_text = link_text.strip()
            result[page_url] = link_text
            log.info(f"Loaded SPECIAL_LINK_MONITOR: {page_url} -> '{link_text}'")
    return result

def extract_link_href_by_text(html, link_text):
    soup = BeautifulSoup(html, "html.parser")
    normalized_target = " ".join(link_text.lower().split())
    for a in soup.find_all("a"):
        link_text_actual = a.get_text(separator=" ", strip=True)
        normalized_actual = " ".join(link_text_actual.lower().split())
        if normalized_target == normalized_actual:
            return a.get("href", "").strip()
    return None

URLS = [u.strip() for u in os.getenv("URLS", "").split(",") if u.strip()]
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
CHAT_ID = os.getenv("TG_CHAT_ID")
CHECK_INTERVAL = parse_interval(os.getenv("CHECK_INTERVAL", "3h"))
SPECIAL_LINK_MONITORS = parse_special_link_monitors(os.getenv("SPECIAL_LINK_MONITORS", ""))

HISTORY_DIR = BASE_DIR / "page-history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

def fetch_page(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"
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
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)

def hash_content(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def send_telegram_message(text):
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("Telegram bot token or chat ID is not set.")
        return
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
    except Exception as e:
        log.error(f"Failed to send message: {e}")

def slugify_url(url):
    parsed = urlparse(url)
    netloc = parsed.netloc.replace(":", "_")
    path = parsed.path.strip("/").replace("/", "_") or "root"
    qs = parse_qs(parsed.query)

    if "midpen-housing.org" in netloc:
        county = qs.get("aspf[county__4]", ["unknown"])[0].replace(" ", "_").lower()
        return f"{netloc}_{path}_county_{county}"

    if "edenhousing.org" in netloc:
        county = qs.get("_sft_county", ["unknown"])[0].replace(" ", "_").lower()
        return f"{netloc}_{path}_county_{county}"

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

    if url in SPECIAL_LINK_MONITORS:
        link_text = SPECIAL_LINK_MONITORS[url]
        log.info(f"Looking for link text: '{link_text}'")
        current_href = extract_link_href_by_text(html, link_text)
        if not current_href:
            log.error(f"Missing link with text '{link_text}' on {url}")
            send_telegram_message(f"❗️ *Missing link text* '{link_text}' on {url}")
        else:
            slug = slugify_url(url + "|" + link_text)
            href_file, _, _ = get_storage_paths(slug)
            if not href_file.exists():
                log.info(f"Storing first href for '{link_text}' on {url}")
                href_file.write_text(current_href)
            else:
                old_href = href_file.read_text()
                if old_href != current_href:
                    log.info(f"Link changed for '{link_text}' on {url}")
                    message = f"🔗 *Link changed*\n[{link_text}]({current_href}) on {url}\n\nPrevious: {old_href}"
                    send_telegram_message(message)
                    href_file.write_text(current_href)
                else:
                    log.info(f"Link unchanged for '{link_text}' on {url}")

    text = clean_html(html)
    current_hash = hash_content(text)
    slug = slugify_url(url)
    hash_file, text_file, page_dir = get_storage_paths(slug)

    if not hash_file.exists():
        log.info(f"Storing initial content of {url}")
        hash_file.write_text(current_hash)
        text_file.write_text(text)
        (page_dir / f"{slug}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt").write_text(text)
        return

    old_hash = hash_file.read_text()
    if current_hash != old_hash:
        log.info(f"Change detected in {url}")
        old_text = text_file.read_text()
        diff = difflib.unified_diff(
            old_text.splitlines(), text.splitlines(),
            fromfile="before", tofile="after", lineterm=""
        )
        diff_lines = list(diff)
        if diff_lines:
            trimmed_diff = "\n".join(diff_lines[:100])
            message = f"🚨 *Change detected*\n{url}\n\n```diff\n{trimmed_diff}\n```"
            send_telegram_message(message)
        hash_file.write_text(current_hash)
        text_file.write_text(text)
        (page_dir / f"{slug}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt").write_text(text)
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
            monitor_page(url)
        log.info(f"Sleeping for {format_sleep_time(CHECK_INTERVAL)}...")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
