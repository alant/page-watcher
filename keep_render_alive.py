import os
import requests
from dotenv import load_dotenv
from monitor import send_telegram_message

load_dotenv()

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
LOGIN_URL = os.getenv("LOGIN_URL")
PING_NEXT = os.getenv("PING_NEXT")

def main():
    errors = []

    # Check Next.js ping
    try:
        r_next = requests.get(PING_NEXT, timeout=10)
        if r_next.status_code != 200 or r_next.json().get("status") != "ok":
            errors.append(f"Next.js ping failed: status={r_next.status_code}, body={r_next.text}")
    except Exception as e:
        errors.append(f"Next.js ping exception: {e}")

    # Login Flask
    with requests.Session() as s:
        try:
            res = s.post(LOGIN_URL, json={"email": EMAIL, "password": PASSWORD}, timeout=15)
            if res.status_code != 200:
                errors.append(f"Flask login failed: status={res.status_code}, body={res.text}")
        except Exception as e:
            errors.append(f"Flask login exception: {e}")

    # Send alert if errors found
    if errors:
        msg = "*Render App Monitor Alert*\n\n" + "\n".join(errors)
        print(msg)
        send_telegram_message(msg)
    else:
        print("All checks passed.")

if __name__ == "__main__":
    main()
