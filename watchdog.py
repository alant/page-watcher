"""
Watchdog for Page Watcher service.
Checks if the monitor is running and sends alerts if something is wrong.

Run via cron every 30 minutes:
*/30 * * * * /home/ubuntu/page-watcher/venv/bin/python /home/ubuntu/page-watcher/watchdog.py >> /home/ubuntu/page-watcher/cron.log 2>&1
"""

import os
import subprocess
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pathlib import Path

# Load env before importing notify (which also loads env, but just to be safe)
BASE_DIR = Path(__file__).parent.resolve()
load_dotenv(BASE_DIR / ".env")

from notify import notify, send_telegram, send_discord

LOG_FILE = BASE_DIR / "monitor.log"
WATCHDOG_LOG = BASE_DIR / "watchdog.log"
HEARTBEAT_FILE = BASE_DIR / ".last_heartbeat"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(WATCHDOG_LOG), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# How often monitor should run (from env, default 3h)
CHECK_INTERVAL_STR = os.getenv("CHECK_INTERVAL", "3h")

# Heartbeat: send weekly "I'm alive" message with summary
HEARTBEAT_DAY = 5  # Saturday (0=Mon, 5=Sat, 6=Sun)
HEARTBEAT_HOUR = 10  # 10 AM PST


def parse_interval(interval_str):
    """Parse interval string like '3h' or '30m' to seconds."""
    import re
    match = re.match(r"(\d+)([smhd])", interval_str.strip().lower())
    if not match:
        raise ValueError(f"Invalid interval format: {interval_str}")
    value, unit = match.groups()
    value = int(value)
    return {"s": value, "m": value * 60, "h": value * 3600, "d": value * 86400}[unit]


def check_log_freshness():
    """Check if monitor.log was recently modified."""
    if not LOG_FILE.exists():
        return False, "monitor.log does not exist"

    last_modified = datetime.fromtimestamp(LOG_FILE.stat().st_mtime)
    now = datetime.now()
    age = now - last_modified

    # Threshold: 2x the check interval (gives buffer for slow runs)
    try:
        threshold_seconds = parse_interval(CHECK_INTERVAL_STR) * 2
    except:
        threshold_seconds = 6 * 3600  # fallback 6 hours

    if age.total_seconds() > threshold_seconds:
        hours_ago = age.total_seconds() / 3600
        return False, f"monitor.log last modified {hours_ago:.1f} hours ago"

    return True, f"monitor.log is fresh ({age.total_seconds() / 60:.0f} min ago)"


def check_service_status():
    """Check if page-watcher systemd service is running."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "page-watcher"],
            capture_output=True, text=True, timeout=10
        )
        status = result.stdout.strip()
        if status == "active":
            return True, "service is active"
        else:
            return False, f"service status: {status}"
    except FileNotFoundError:
        # systemctl not available (maybe not on Linux)
        return True, "systemctl not available (skipped)"
    except Exception as e:
        return False, f"failed to check service: {e}"


def check_recent_errors():
    """Check monitor.log for recent errors."""
    if not LOG_FILE.exists():
        return True, "no log file"

    try:
        # Read last 100 lines
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()[-100:]

        error_count = sum(1 for line in lines if "[ERROR]" in line)
        if error_count > 10:
            return False, f"{error_count} errors in recent logs"
        return True, f"{error_count} errors in recent logs"
    except Exception as e:
        return False, f"failed to read log: {e}"


def should_send_heartbeat():
    """Check if it's time to send weekly heartbeat (Monday 9 AM)."""
    now = datetime.now()

    # Only send on the right day and hour
    if now.weekday() != HEARTBEAT_DAY or now.hour != HEARTBEAT_HOUR:
        return False

    # Check if we already sent this week
    if HEARTBEAT_FILE.exists():
        last_heartbeat = datetime.fromtimestamp(HEARTBEAT_FILE.stat().st_mtime)
        days_since = (now - last_heartbeat).days
        if days_since < 6:  # Less than a week ago
            return False

    return True


def get_crawl_summary():
    """
    Fetch pages and count total properties to verify crawler is working.
    Uses unfiltered URLs to get true property counts per county.
    """
    import requests
    from bs4 import BeautifulSoup

    summary = []

    # URLs without waitlist filter - just to verify crawler can find properties
    # MidPen requires full params including empty city filter and asp_ls
    verification_urls = [
        ("MidPen Santa Clara", "https://www.midpen-housing.org/find-housing/?p_asid=1&p_asp_data=1&aspf[county__4]=Santa%20Clara&aspf[city__3]=&aspf[type__2]=Senior&filters_initial=0&filters_changed=1&qtranslate_lang=0&current_page_id=23&asp_ls="),
        ("MidPen Alameda", "https://www.midpen-housing.org/find-housing/?p_asid=1&p_asp_data=1&aspf[county__4]=Alameda&aspf[city__3]=&aspf[type__2]=Senior&filters_initial=0&filters_changed=1&qtranslate_lang=0&current_page_id=23&asp_ls="),
        ("MidPen San Mateo", "https://www.midpen-housing.org/find-housing/?p_asid=1&p_asp_data=1&aspf[county__4]=San%20Mateo&aspf[city__3]=&aspf[type__2]=Senior&filters_initial=0&filters_changed=1&qtranslate_lang=0&current_page_id=23&asp_ls="),
        ("MidPen San Francisco", "https://www.midpen-housing.org/find-housing/?p_asid=1&p_asp_data=1&aspf[county__4]=San%20Francisco&aspf[city__3]=&aspf[type__2]=Senior&filters_initial=0&filters_changed=1&qtranslate_lang=0&current_page_id=23&asp_ls="),
        ("Eden Santa Clara", "https://edenhousing.org/find-an-apartment/find-a-home/search-for-an-apartment/?_sft_county=santa-clara"),
        ("Eden Alameda", "https://edenhousing.org/find-an-apartment/find-a-home/search-for-an-apartment/?_sft_county=alameda"),
        ("Charities Housing", "https://charitieshousing.org/find-a-home/"),
        ("SAHA Homes", "https://www.sahahomes.org/properties/"),
    ]

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    for name, url in verification_urls:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")

            # Count properties based on site
            if "midpen-housing.org" in url:
                # MidPen: count property links in headings (dedupe by href)
                unique_hrefs = set()
                for h in soup.find_all(["h2", "h3", "h4"]):
                    link = h.find("a", href=lambda x: x and "/property/" in x)
                    if link:
                        unique_hrefs.add(link.get("href"))
                count = len(unique_hrefs)
            elif "edenhousing.org" in url:
                # Eden: count property listings
                props = soup.find_all("div", class_=lambda c: c and "property-listing" in c)
                count = len(props)
            elif "charitieshousing.org" in url:
                # Charities: count apartment cards
                props = soup.find_all("div", class_="apart_item_col")
                count = len(props)
            elif "sahahomes.org" in url:
                # SAHA: count map popup items
                props = soup.find_all("div", class_="map-popup-item")
                count = len(props)
            else:
                count = 0

            summary.append(f"  {name}: {count} properties")
        except Exception as e:
            summary.append(f"  {name}: Error ({str(e)[:30]})")

    return "\n".join(summary) if summary else "No data available"


def get_recent_changes():
    """Check if any changes were detected in the past week."""
    if not LOG_FILE.exists():
        return "Log file not found"

    try:
        week_ago = datetime.now() - timedelta(days=7)
        change_count = 0

        with open(LOG_FILE, "r") as f:
            for line in f:
                if "Change detected" in line:
                    # Parse timestamp from log line
                    try:
                        timestamp_str = line.split("[")[0].strip()
                        timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S,%f")
                        if timestamp > week_ago:
                            change_count += 1
                    except:
                        pass

        if change_count == 0:
            return "No changes detected in the past week"
        else:
            return f"{change_count} change(s) detected in the past week"
    except Exception as e:
        return f"Error checking changes: {e}"


def send_heartbeat():
    """Send weekly heartbeat message with crawl summary."""
    now = datetime.now()

    crawl_summary = get_crawl_summary()
    recent_changes = get_recent_changes()

    msg = f"""💓 *Page Watcher Weekly Report*

{now.strftime('%Y-%m-%d %H:%M')}

*Crawl Summary:*
{crawl_summary}

*Activity:* {recent_changes}

Monitor is running normally."""

    # Send to both channels
    tg_ok = send_telegram(msg)
    discord_ok = send_discord(msg.replace("*", "**"))

    if tg_ok or discord_ok:
        # Update heartbeat file
        HEARTBEAT_FILE.touch()
        log.info("Weekly heartbeat sent successfully")
        return True
    else:
        log.error("Failed to send heartbeat to any channel")
        return False


def main():
    log.info("Watchdog check starting...")

    issues = []

    # Check 1: Log freshness
    ok, msg = check_log_freshness()
    log.info(f"Log freshness: {msg}")
    if not ok:
        issues.append(f"📄 {msg}")

    # Check 2: Service status
    ok, msg = check_service_status()
    log.info(f"Service status: {msg}")
    if not ok:
        issues.append(f"⚙️ {msg}")

    # Check 3: Recent errors
    ok, msg = check_recent_errors()
    log.info(f"Error check: {msg}")
    if not ok:
        issues.append(f"❌ {msg}")

    # Send alert if any issues
    if issues:
        alert = "🚨 **Page Watcher Alert**\n\n" + "\n".join(issues) + "\n\nCheck the server!"
        log.warning(f"Issues detected, sending alert: {issues}")
        notify(alert, is_error=True)
    else:
        log.info("All checks passed")

    # Send daily heartbeat if it's time
    if should_send_heartbeat():
        log.info("Sending daily heartbeat...")
        send_heartbeat()

    log.info("Watchdog check complete")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error(f"Watchdog crashed: {e}")
        # Try to notify even if we crashed
        try:
            notify(f"🚨 **Watchdog Crashed**\n\n{e}", is_error=True)
        except:
            pass
        raise
