"""Log in to TAI Labs once by hand and save the browser session to auth.json.

Run from the repo root:  python ingest/login.py
Later scripts load auth.json instead of logging in, so no password lives in code.
"""

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

LOGIN_URL = "https://tailabs.ai/auth"
AUTH_FILE = Path("auth.json")


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # visible window so you can type
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN_URL)

        input("Log in in the browser window, wait until you see the course, then press Enter here... ")

        context.storage_state(path=AUTH_FILE)  # cookies + localStorage -> JSON file
        os.chmod(AUTH_FILE, 0o600)  # readable/writable by you only
        browser.close()

    print(f"Saved session to {AUTH_FILE.resolve()}")


if __name__ == "__main__":
    main()
