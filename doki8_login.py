"""
Daily login script for http://www.doki8.net/login
Solves the math captcha, submits credentials, and notifies via Telegram on failure.
"""

import html
import logging
import os
import re
import sys
import time

import requests
from dotenv import load_dotenv

from notify import notify

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

LOGIN_URL = "http://www.doki8.net/login"
USERNAME = os.getenv("USER_NAME")
PASSWORD = os.getenv("PASSWORD")


_OP_RE = r"[+\-\×÷*/xX−×÷]"


def _solve_captcha(page_html: str) -> int | None:
    """Parse the math captcha from the login page HTML and return the answer.

    Handles both equation formats:
      A op ? = B  →  <span>A op <input/> = B</span>
      ? op A = B  →  <span><input/> op A = B</span>
    """
    span_m = re.search(r"<span>(.*?)</span>", page_html, re.DOTALL)
    if not span_m:
        return None
    span = html.unescape(span_m.group(1))

    # Replace the input element with the placeholder token "?"
    span_clean = re.sub(r"<input[^>]*/?>", "?", span).strip()
    log.info("Captcha span: %s", span_clean)

    # Parse:  A op ? = B   or   ? op A = B
    m = re.match(
        rf"(\d+)\s*({_OP_RE})\s*\?\s*=\s*(\d+)", span_clean
    )
    if m:
        a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
        log.info("Captcha equation: %d %s ? = %d", a, op, b)
        return _apply_op_right(a, op, b)

    m = re.match(
        rf"\?\s*({_OP_RE})\s*(\d+)\s*=\s*(\d+)", span_clean
    )
    if m:
        op, a, b = m.group(1), int(m.group(2)), int(m.group(3))
        log.info("Captcha equation: ? %s %d = %d", op, a, b)
        return _apply_op_left(op, a, b)

    log.error("Unrecognised captcha format: %s", span_clean)
    return None


def _apply_op_right(a: int, op: str, b: int) -> int | None:
    """Solve  a op ? = b  →  return ?"""
    if op in ("+",):
        return b - a
    if op in ("-", "−"):
        return a - b
    if op in ("×", "*", "x", "X", "×"):
        return b // a if a else None
    if op in ("÷", "/", "÷"):
        return a * b
    return None


def _apply_op_left(op: str, a: int, b: int) -> int | None:
    """Solve  ? op a = b  →  return ?"""
    if op in ("+",):
        return b - a
    if op in ("-", "−"):
        return b + a
    if op in ("×", "*", "x", "X", "×"):
        return b // a if a else None
    if op in ("÷", "/", "÷"):
        return b * a
    return None


def login() -> bool:
    """Attempt login. Returns True on success, False on failure."""
    session = requests.Session()
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    # Step 1: GET a fresh (non-cached) login page to receive captcha session cookies.
    # A cache-busting query string forces Hyper Cache to serve a live PHP response,
    # which sets mc_session_ids and wordpress_test_cookie properly.
    try:
        resp = session.get(f"{LOGIN_URL}?_={int(time.time())}", timeout=20)
        resp.raise_for_status()
    except Exception as e:
        log.error("Failed to fetch login page: %s", e)
        notify(f"❌ *doki8 login failed* — could not reach login page\n`{e}`", is_error=True)
        return False

    answer = _solve_captcha(resp.text)
    if answer is None:
        log.error("Could not parse math captcha")
        notify("❌ *doki8 login failed* — could not parse math captcha", is_error=True)
        return False

    log.info("Captcha answer: %d", answer)

    # Step 2: POST the login form
    payload = {
        "log": USERNAME,
        "pwd": PASSWORD,
        "mc-value": str(answer),
        "wp-submit": "登录",
        "redirect_to": "http://www.doki8.net",
        "testcookie": "1",
    }

    try:
        post_resp = session.post(LOGIN_URL, data=payload, timeout=20, allow_redirects=True)
    except Exception as e:
        log.error("POST request failed: %s", e)
        notify(f"❌ *doki8 login failed* — POST error\n`{e}`", is_error=True)
        return False

    # Step 3: Detect success — a successful WP login redirects away from /login
    # and sets a wordpress_logged_in_* cookie
    logged_in_cookie = any(
        c.name.startswith("wordpress_logged_in") for c in session.cookies
    )
    still_on_login = "loginform" in post_resp.text

    if logged_in_cookie or not still_on_login:
        log.info("Login succeeded (final URL: %s)", post_resp.url)
        return True

    # Extract WP error message if present
    err_match = re.search(r'<div id="login_error">(.*?)</div>', post_resp.text, re.DOTALL)
    err_text = html.unescape(re.sub(r"<[^>]+>", "", err_match.group(1))).strip() if err_match else "unknown error"

    log.error("Login failed: %s", err_text)
    notify(f"❌ *doki8 login failed*\n`{err_text}`", is_error=True)
    return False


if __name__ == "__main__":
    success = login()
    sys.exit(0 if success else 1)
