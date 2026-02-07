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
from dotenv import load_dotenv
import logging
import yaml
import traceback
from notify import notify, notify_error

load_dotenv()

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

def load_urls_config():
    """Load URLs from urls_config.yaml file."""
    config_path = BASE_DIR / "urls_config.yaml"
    urls = []
    special_link_monitors = {}

    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)

            # Collect URLs from all categories
            for category in ["school", "midpen", "eden", "other_housing", "portals", "united_effort"]:
                if category in config and config[category]:
                    for item in config[category]:
                        if isinstance(item, dict) and "url" in item:
                            urls.append(item["url"])
                            log.info(f"Loaded URL [{category}]: {item.get('name', item['url'][:50])}")
                        elif isinstance(item, str):
                            urls.append(item)

            # Load special link monitors
            if "special_link_monitors" in config and config["special_link_monitors"]:
                for item in config["special_link_monitors"]:
                    if isinstance(item, dict) and "url" in item and "link_text" in item:
                        special_link_monitors[item["url"]] = item["link_text"]
                        log.info(f"Loaded SPECIAL_LINK_MONITOR: {item['url']} -> '{item['link_text']}'")

            log.info(f"Loaded {len(urls)} URLs from urls_config.yaml")
        except Exception as e:
            log.error(f"Failed to load urls_config.yaml: {e}")

    return urls, special_link_monitors

def collect_urls_from_env():
    """Fallback: Collect URLs from environment variables."""
    urls = []
    for key, value in os.environ.items():
        if key.startswith("URLS_") and value.strip():
            urls.extend([u.strip() for u in value.split(",") if u.strip()])
    if not urls:
        urls = [u.strip() for u in os.getenv("URLS", "").split(",") if u.strip()]
    return urls

def parse_special_link_monitors_env(value):
    """Parse special link monitors from environment variable."""
    result = {}
    if not value:
        return result
    for entry in value.split(","):
        if "|" in entry:
            page_url, link_text = entry.split("|", 1)
            page_url = page_url.strip().strip('"')
            link_text = link_text.strip().strip('"')
            result[page_url] = link_text
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

# Load configuration - prefer YAML config, fallback to env vars
URLS_FROM_CONFIG, SPECIAL_LINK_MONITORS_FROM_CONFIG = load_urls_config()
URLS_FROM_ENV = collect_urls_from_env()
SPECIAL_LINK_MONITORS_FROM_ENV = parse_special_link_monitors_env(os.getenv("SPECIAL_LINK_MONITORS", ""))

# Merge: YAML takes precedence, env vars as fallback
URLS = URLS_FROM_CONFIG if URLS_FROM_CONFIG else URLS_FROM_ENV
SPECIAL_LINK_MONITORS = {**SPECIAL_LINK_MONITORS_FROM_ENV, **SPECIAL_LINK_MONITORS_FROM_CONFIG}

BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
CHAT_ID = os.getenv("TG_CHAT_ID")
CHECK_INTERVAL = parse_interval(os.getenv("CHECK_INTERVAL", "3h"))

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

def extract_midpen_properties(soup):
    """Extract property listings from MidPen Housing pages."""
    properties = []
    seen_urls = set()
    status_pattern = re.compile(r"(Wait List Open|Wait List Closed|Interest List|Referral Only)", re.I)

    # Find property links inside headings (h2, h3, h4)
    for heading in soup.find_all(["h2", "h3", "h4"]):
        link = heading.find("a", href=lambda h: h and "/property/" in h)
        if not link:
            continue

        href = link.get("href", "")
        if href in seen_urls:
            continue
        seen_urls.add(href)

        name = heading.get_text(strip=True)
        if not name:
            continue

        # Make URL absolute
        full_url = f"https://www.midpen-housing.org{href}" if href.startswith('/') else href
        prop = {"name": name, "url": full_url}

        # Find parent section for description and location
        section = heading.find_parent("section")
        if section:
            # Get description from paragraphs
            paragraphs = section.find_all("p")
            for p in paragraphs:
                desc = p.get_text(strip=True)
                if len(desc) > 50:  # Real description, not just a label
                    prop["description"] = desc[:200] + "..."
                    break

            # Get location (City, CA) - handle multi-word cities like "Half Moon Bay", "East Palo Alto"
            # Look for pattern: City, CA (with optional zip) - spaces only, no newlines
            section_text = section.get_text()
            loc_match = re.search(r"((?:[A-Z][a-z]+ ){0,3}[A-Z][a-z]+), ?CA(?: \d{5})?", section_text)
            if loc_match:
                prop["location"] = loc_match.group(0)

        # Look backwards in sibling sections for status
        if section:
            prev = section.find_previous_sibling("section")
            for _ in range(5):  # Check up to 5 preceding sections
                if not prev:
                    break
                text = prev.get_text(strip=True)
                match = status_pattern.search(text)
                if match:
                    prop["status"] = match.group(1)
                    break
                prev = prev.find_previous_sibling("section")

        properties.append(prop)

    return properties

def extract_eden_properties(soup):
    """Extract property listings from Eden Housing pages."""
    properties = []

    for listing in soup.find_all("div", class_=re.compile(r"property-listing")):
        prop = {}

        # Get name and URL
        name_elem = listing.find("h3")
        if name_elem:
            prop["name"] = name_elem.get_text(strip=True)
            link = name_elem.find("a")
            if link:
                href = link.get("href", "")
                prop["url"] = f"https://edenhousing.org{href}" if href.startswith('/') else href

        # Get status
        status_elem = listing.find("a", class_=re.compile(r"status|applications"))
        if not status_elem:
            status_elem = listing.find(string=re.compile(r"Accepting Applications|Waitlist|Coming Soon", re.I))
        if status_elem:
            prop["status"] = status_elem.get_text(strip=True) if hasattr(status_elem, 'get_text') else str(status_elem).strip()

        # Get location
        loc_elem = listing.find("p", class_=re.compile(r"property-location"))
        if loc_elem:
            prop["location"] = loc_elem.get_text(strip=True)

        # Get unit count
        units_elem = listing.find("p", class_=re.compile(r"property-units"))
        if units_elem:
            prop["units"] = units_elem.get_text(strip=True)

        if prop.get("name"):
            properties.append(prop)

    return properties

def extract_saha_properties(soup):
    """Extract property listings from SAHA Homes pages - Bay Area only."""
    properties = []

    # Core Bay Area cities (Alameda, Contra Costa, SF, Santa Clara counties)
    bay_area_cities = {
        'oakland', 'berkeley', 'fremont', 'newark', 'alameda', 'albany',
        'livermore', 'pleasanton', 'hayward', 'union city', 'san leandro',
        'antioch', 'pittsburg', 'pleasant hill', 'walnut creek', 'pinole',
        'san ramon', 'concord', 'richmond', 'el cerrito', 'martinez',
        'san francisco', 'daly city', 'south san francisco',
        'san jose', 'sunnyvale', 'santa clara', 'mountain view', 'palo alto',
        'milpitas', 'cupertino', 'campbell', 'los gatos', 'saratoga',
    }

    # SAHA stores property data in map-popup-item divs with data attributes
    for item in soup.find_all("div", class_="map-popup-item"):
        prop = {}

        # Get city from data attribute first (for filtering)
        city_attr = item.get("data-limerock-city", "")
        if city_attr:
            city = city_attr.strip('[]"').replace("-", " ").title()
            prop["city"] = city

            # Skip non-Bay Area cities
            if city.lower() not in bay_area_cities:
                continue

        # Get waitlist status from data attribute
        status_attr = item.get("data-limerock-waitlist-status", "")
        if "accepting-applications" in status_attr:
            prop["status"] = "Accepting Applications"
        elif "waitlist-closed" in status_attr:
            prop["status"] = "Waitlist Closed"
        else:
            prop["status"] = status_attr.strip('[]"').replace("-", " ").title() if status_attr else "Unknown"

        # Get resident type
        resident_attr = item.get("data-limerock-resident-population", "")
        if "seniors" in resident_attr.lower():
            prop["type"] = "Senior"

        # Get name and address from content
        name_elem = item.find("h3")
        if name_elem:
            prop["name"] = name_elem.get_text(strip=True)

        addr_elem = item.find("p")
        if addr_elem:
            prop["address"] = addr_elem.get_text(strip=True)

        # Get URL
        link = item.find("a", href=True)
        if link:
            prop["url"] = "https://www.sahahomes.org" + link.get("href", "") if link.get("href", "").startswith("/") else link.get("href", "")

        if prop.get("name"):
            properties.append(prop)

    return properties

def extract_humangood_properties(soup):
    """Extract property info from HumanGood pages."""
    properties = []

    # Look for the main content area
    main = soup.find("main") or soup.find("article") or soup

    # Get page title
    title = main.find("h1")
    if title:
        prop = {"name": title.get_text(strip=True)}

        # Look for status/availability info
        for text in main.stripped_strings:
            if re.search(r"waitlist|wait list|accepting|available|open|closed|not accepting", text, re.I):
                prop["status"] = text[:100]
                break

        # Get address if present
        addr = main.find(string=re.compile(r"\d+.*(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Way|Boulevard|Blvd)", re.I))
        if addr:
            prop["address"] = addr.strip()

        properties.append(prop)

    return properties


def extract_charities_housing(soup):
    """Extract property listings from Charities Housing pages."""
    properties = []

    # Property cards are in div.apart_item_col
    for card in soup.find_all("div", class_="apart_item_col"):
        prop = {}
        texts = list(card.stripped_strings)

        if len(texts) < 3:
            continue

        # Structure: [status, name, address, city/state, email, phone, "Unit Type:", types..., "MORE INFORMATION"]
        idx = 0

        # Status (usually first)
        if texts[idx].lower() in ["accepting applications", "waitlist closed", "coming soon"]:
            prop["status"] = texts[idx].title()
            idx += 1

        # Name
        if idx < len(texts):
            prop["name"] = texts[idx]
            idx += 1

        # Address (contains street number or city name)
        if idx < len(texts):
            addr = texts[idx]
            idx += 1
            # Next might be city/state/zip
            if idx < len(texts) and "USA" in texts[idx]:
                addr += ", " + texts[idx]
                idx += 1
            prop["address"] = addr

        # Skip email and phone, look for unit types
        unit_types = []
        for text in texts[idx:]:
            if text.lower() == "unit type:":
                continue
            if text in ["MORE INFORMATION", "Income & Occupancy | Restrictions Apply"]:
                break
            if any(kw in text.lower() for kw in ["bedroom", "studio", "senior", "special needs"]):
                unit_types.append(text)

        if unit_types:
            prop["types"] = ", ".join(unit_types)

        # Get URL from first meaningful link
        link = card.find("a", href=re.compile(r"/property/"))
        if link:
            href = link.get("href", "")
            prop["url"] = f"https://charitieshousing.org{href}" if href.startswith('/') else href

        if prop.get("name"):
            properties.append(prop)

    return properties

def extract_united_effort_properties(soup):
    """Extract SENIOR-ONLY property listings from The United Effort Organization pages."""
    properties = []

    # Keywords that indicate senior-only housing
    senior_keywords = ['senior', '62+', '55+', 'elderly', 'older adult']

    # Each property is in a <li id="property-XXX"> element
    for li in soup.find_all('li', id=lambda x: x and x.startswith('property-')):
        # Get property name from h2 > a
        h2 = li.find('h2')
        if not h2:
            continue
        link = h2.find('a')
        if not link:
            continue

        name = link.get_text(strip=True)
        if not name:
            continue

        # Get property URL
        href = link.get('href', '')
        if href:
            prop_url = f"https://www.theunitedeffort.org{href}" if href.startswith('/') else href
        else:
            prop_url = ""

        # Check if this is senior-only housing
        full_text = li.get_text(separator=' ', strip=True).lower()
        is_senior_only = any(kw in name.lower() or kw in full_text for kw in senior_keywords)

        if not is_senior_only:
            continue  # Skip non-senior properties

        # Get status from badge classes
        status = ""
        status_badge = li.find('span', class_=lambda x: x and 'badge__ok' in x)
        if status_badge:
            status = status_badge.get_text(strip=True)  # "Waitlist Open"
        else:
            status_badge = li.find('span', class_=lambda x: x and 'badge__bad' in x)
            if status_badge:
                status = status_badge.get_text(strip=True)  # "Waitlist Closed"

        # Get unit types from other badges
        units = []
        for badge in li.find_all('span', class_='badge'):
            badge_text = badge.get_text(strip=True)
            if badge_text and badge_text not in ['Waitlist Open', 'Waitlist Closed', 'Call for Availability']:
                units.append(badge_text)

        # Get address from first contact span
        address = ""
        contact_span = li.find('span', attrs={'translate': 'no'})
        if contact_span:
            addr_text = contact_span.get_text(strip=True)
            if ',' in addr_text:  # Looks like an address
                address = addr_text

        prop = {"name": name}
        if status:
            prop["status"] = status
        if units:
            prop["types"] = ", ".join(units)
        if address:
            prop["address"] = address
        if prop_url:
            prop["url"] = prop_url

        properties.append(prop)

    return properties if properties else None


def extract_foster_city_properties(soup):
    """Extract senior housing from Foster City waitlist page."""
    properties = []

    # Find the main table with property listings
    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        if len(rows) < 2:
            continue

        # Check if this table has property data
        for row in rows[1:]:  # Skip header row
            cells = row.find_all(['td', 'th'])
            if len(cells) < 5:
                continue

            # Get cell text
            cell_text = [c.get_text(strip=True) for c in cells]

            # Check if this is a senior property
            name = cell_text[0] if cell_text else ""
            if 'senior' not in name.lower():
                continue

            prop = {"name": name}

            # Units count (column 1)
            if len(cell_text) > 1:
                prop["units"] = cell_text[1]

            # Affordability (column 2)
            if len(cell_text) > 2:
                prop["income_levels"] = cell_text[2]

            # Unit sizes (column 3)
            if len(cell_text) > 3:
                prop["types"] = cell_text[3]

            # Waitlist status (column 4) - "Yes", "No", "Closed"
            if len(cell_text) > 4:
                status_text = cell_text[4].lower()
                if 'yes' in status_text:
                    prop["status"] = "Waitlist Open"
                elif 'no' in status_text or 'closed' in status_text:
                    prop["status"] = "Waitlist Closed"
                else:
                    prop["status"] = cell_text[4]

            # Add Foster City page URL (no individual property pages)
            prop["url"] = "https://www.fostercity.org/commdev/page/affordable-housing-open-waitlists"

            if prop.get("name"):
                properties.append(prop)

    return properties if properties else None


def extract_generic_housing(soup, url):
    """Generic extractor for housing sites - captures key housing-related content."""
    lines = []
    text = soup.get_text(separator="\n")

    # Extract domain for labeling
    domain = urlparse(url).netloc.replace("www.", "")

    # Look for property/housing cards or listings
    property_patterns = [
        r"property-listing", r"property-card", r"apartment-card",
        r"housing-item", r"listing-item", r"unit-card"
    ]

    found_listings = []
    for pattern in property_patterns:
        listings = soup.find_all(class_=re.compile(pattern, re.I))
        found_listings.extend(listings)

    if found_listings:
        lines.append(f"[{domain}] {len(found_listings)} listing(s) found:")
        lines.append("")
        for listing in found_listings[:20]:  # Limit to 20
            listing_text = listing.get_text(separator=" | ", strip=True)[:300]
            lines.append(f"  - {listing_text}")
            lines.append("")
    else:
        # Fallback: extract lines containing housing keywords
        lines.append(f"[{domain}] Page content summary:")
        lines.append("")

        housing_keywords = [
            r"wait\s*list", r"waitlist", r"accepting\s*applications",
            r"open\s*now", r"available", r"senior\s*housing",
            r"affordable", r"income", r"apply", r"application",
            r"bedroom", r"unit", r"apartment", r"55\+", r"62\+"
        ]

        seen = set()
        for line in text.split("\n"):
            line = line.strip()
            if not line or len(line) < 10 or len(line) > 300:
                continue
            line_lower = line.lower()
            for kw in housing_keywords:
                if re.search(kw, line_lower) and line not in seen:
                    seen.add(line)
                    lines.append(f"  {line}")
                    break
            if len(seen) >= 50:  # Limit output
                break

    return "\n".join(lines) if lines else None

def format_properties(properties, site_name):
    """Format extracted properties into readable text."""
    if not properties:
        return f"[{site_name}] No properties found matching criteria.\n"

    lines = [f"[{site_name}] {len(properties)} property(ies) found:", ""]
    for prop in properties:
        lines.append(f"  - {prop.get('name', 'Unknown')}")
        if prop.get("status"):
            lines.append(f"    Status: {prop['status']}")
        if prop.get("type"):
            lines.append(f"    Type: {prop['type']}")
        if prop.get("types"):
            lines.append(f"    Unit Types: {prop['types']}")
        if prop.get("location"):
            lines.append(f"    Location: {prop['location']}")
        if prop.get("city"):
            lines.append(f"    City: {prop['city']}")
        if prop.get("address"):
            lines.append(f"    Address: {prop['address']}")
        if prop.get("units"):
            lines.append(f"    Units: {prop['units']}")
        if prop.get("description"):
            lines.append(f"    {prop['description']}")
        if prop.get("url"):
            lines.append(f"    URL: {prop['url']}")
        lines.append("")

    return "\n".join(lines)

def clean_html(html, url=""):
    """Clean HTML and extract relevant content based on site type."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove scripts, styles, and other non-content elements
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
        tag.decompose()

    # Site-specific extraction for housing sites
    try:
        if "midpen-housing.org" in url:
            properties = extract_midpen_properties(soup)
            if properties:
                return format_properties(properties, "MidPen Housing")
            else:
                # No properties found for this filter - that's valid, not a fallback
                return "[MidPen Housing] No senior properties found in this county.\n"

        if "edenhousing.org" in url:
            properties = extract_eden_properties(soup)
            if properties:
                return format_properties(properties, "Eden Housing")
            else:
                return "[Eden Housing] No senior properties found in this county.\n"

        if "humangood.org" in url:
            properties = extract_humangood_properties(soup)
            if properties:
                return format_properties(properties, "HumanGood")
            else:
                return "[HumanGood] No properties found.\n"

        if "sahahomes.org" in url:
            properties = extract_saha_properties(soup)
            if properties:
                # Filter to only seniors for cleaner output
                senior_props = [p for p in properties if p.get("type") == "Senior"]
                if senior_props:
                    return format_properties(senior_props, "SAHA Homes (Senior)")
                return format_properties(properties, "SAHA Homes")
            else:
                return "[SAHA Homes] No properties found.\n"

        if "charitieshousing.org" in url:
            properties = extract_charities_housing(soup)
            if properties:
                # Filter to senior housing if available
                senior_props = [p for p in properties if p.get("types") and "senior" in p.get("types", "").lower()]
                if senior_props:
                    return format_properties(senior_props, "Charities Housing (Senior)")
                return format_properties(properties, "Charities Housing")
            else:
                return "[Charities Housing] No properties found.\n"

        if "theunitedeffort.org" in url:
            properties = extract_united_effort_properties(soup)
            if properties:
                return format_properties(properties, "The United Effort (Senior)")
            else:
                return "[The United Effort] No senior properties found.\n"

        if "fostercity.org" in url:
            properties = extract_foster_city_properties(soup)
            if properties:
                return format_properties(properties, "Foster City Senior Housing")
            else:
                return "[Foster City] No senior properties found.\n"

        # Generic housing extractor for other housing sites
        housing_domains = [
            "charitieshousing.org", "hiphousing.org",
            "bridgehousing.com", "mercyhousing.org",
            "fostercity.org", "achousingchoices.org", "ebho.org",
            "liveatagrihood.com", "housingbayarea.mtc.ca.gov"
        ]
        if any(domain in url for domain in housing_domains):
            result = extract_generic_housing(soup, url)
            if result:
                return result

    except Exception as e:
        log.error(f"Extraction error for {url}: {e}")

    # Ultimate fallback: cleaned text with housing keyword focus
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # Filter to lines containing relevant keywords for housing sites
    if any(kw in url.lower() for kw in ["housing", "apartment", "senior", "affordable"]):
        housing_keywords = ["wait", "apply", "accept", "open", "close", "senior", "affordable", "income", "unit", "bedroom"]
        filtered = []
        for line in lines:
            if any(kw in line.lower() for kw in housing_keywords):
                filtered.append(line)
        if filtered:
            return "\n".join(filtered[:100])  # Limit to 100 relevant lines

    return "\n".join(lines)

def hash_content(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

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
            notify(f"❗️ *Missing link text* '{link_text}' on {url}")
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
                    notify(message)
                    href_file.write_text(current_href)
                else:
                    log.info(f"Link unchanged for '{link_text}' on {url}")

    text = clean_html(html, url)
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
            fromfile="before", tofile="after", lineterm="", n=0
        )
        diff_lines = list(diff)
        if diff_lines:
            trimmed_diff = "\n".join(diff_lines[:100])
            message = f"🚨 *Change detected*\n{url}\n\n```diff\n{trimmed_diff}\n```"
            notify(message)
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
    all_urls = set(URLS) | set(SPECIAL_LINK_MONITORS.keys())
    log.info(f"Page Watcher started. Monitoring {len(all_urls)} URLs.")

    consecutive_failures = 0
    MAX_CONSECUTIVE_FAILURES = 3

    while True:
        try:
            cycle_errors = []

            for url in all_urls:
                try:
                    monitor_page(url)
                except Exception as e:
                    error_msg = f"Error monitoring {url}: {e}"
                    log.error(error_msg)
                    log.error(traceback.format_exc())
                    cycle_errors.append(error_msg)

            # Report errors from this cycle
            if cycle_errors:
                consecutive_failures += 1
                error_summary = f"Errors in monitoring cycle ({len(cycle_errors)}/{len(all_urls)} URLs failed):\n\n" + "\n".join(cycle_errors[:10])
                if len(cycle_errors) > 10:
                    error_summary += f"\n... and {len(cycle_errors) - 10} more errors"

                # Send error notification
                notify_error(error_summary, context=f"Consecutive failures: {consecutive_failures}")

                # If too many consecutive failures, something is seriously wrong
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    notify_error(
                        f"CRITICAL: {MAX_CONSECUTIVE_FAILURES} consecutive cycles with errors. Check the server!",
                        context="Multiple failures detected"
                    )
            else:
                consecutive_failures = 0  # Reset on successful cycle

            log.info(f"Sleeping for {format_sleep_time(CHECK_INTERVAL)}...")
            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            log.info("Shutting down gracefully...")
            break
        except Exception as e:
            # Unexpected error in main loop
            error_msg = f"CRITICAL ERROR in main loop: {e}\n\n{traceback.format_exc()}"
            log.error(error_msg)
            notify_error(error_msg, context="Main loop crashed")

            # Wait a bit before retrying to avoid rapid failure loops
            log.info("Waiting 60 seconds before retry...")
            time.sleep(60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        error_msg = f"FATAL: Page Watcher crashed on startup: {e}\n\n{traceback.format_exc()}"
        log.error(error_msg)
        notify_error(error_msg, context="Startup failure")
        raise
