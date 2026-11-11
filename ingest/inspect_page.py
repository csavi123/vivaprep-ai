"""Debug helper: open ONE TAI Labs page with the saved session and save what we see.

Run from the repo root:  python ingest/inspect_page.py <url>
Writes HTML + a screenshot to data/raw/tailabs/_debug/ (git-ignored) so we can
find the selectors for the scraper. Read-only: it does not click anything.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

AUTH_FILE = Path("auth.json")
DEBUG_DIR = Path("data/raw/tailabs/_debug")


def main(url: str) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    name = url.rstrip("/").split("/")[-1] or "page"  # e.g. "1" for /sessions/1

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=AUTH_FILE)  # reuse the login
        page = context.new_page()
        page.goto(url, wait_until="networkidle")  # wait until the JS app has loaded

        html_path = DEBUG_DIR / f"{name}.html"
        html_path.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=DEBUG_DIR / f"{name}.png", full_page=True)

        print(f"Requested: {url}")
        print(f"Landed on: {page.url}")  # if this is /auth, the session expired
        print(f"Title:     {page.title()}")
        print(f"Saved:     {html_path} ({html_path.stat().st_size:,} bytes)")

        links = page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
        print(f"\nLinks on page ({len(links)}):")
        for href in sorted(set(links)):
            print(f"  {href}")

        browser.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python ingest/inspect_page.py <url>")
    main(sys.argv[1])
