"""Read the TAI Labs course page and save the list of sessions to fetch.

Run from the repo root:  python ingest/build_manifest.py
Writes data/raw/tailabs/_manifest.json. Scope: sessions 1..LAST_SESSION only.
"""

import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE_URL = "https://tailabs.ai"
COURSE_URL = f"{BASE_URL}/app/courses/ai-career-accelerator"
AUTH_FILE = Path("auth.json")
MANIFEST = Path("data/raw/tailabs/_manifest.json")
LAST_SESSION = 17  # "Learning · Modules 1-17"; sessions 18+ are out of scope
SESSION_HREF = re.compile(r"/sessions/(\d+)$")


def fetch_course_html() -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=AUTH_FILE)
        page = context.new_page()
        page.goto(COURSE_URL, wait_until="networkidle")
        if "/auth" in page.url:  # redirected to login = session expired
            sys.exit("Session expired: run python ingest/login.py again")
        html = page.content()
        browser.close()
    return html


def parse_sessions(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    sessions = {}  # keyed by number, so duplicate links collapse to one entry
    for a in soup.select('a[href*="/sessions/"]'):
        match = SESSION_HREF.search(a["href"])
        title_p = a.find("p")  # module cards have the title in their first <p>
        if not match or not title_p:
            continue  # e.g. the "Continue Module 2" shortcut link
        n = int(match.group(1))
        if n > LAST_SESSION:
            continue
        title = title_p.get_text(" ", strip=True)
        sessions[n] = {
            "source": "tailabs",
            "module": n,
            "module_title": title,
            "session": n,  # one session page per module on this course
            "title": title,
            "url": f"{BASE_URL}{a['href']}",
        }
    return [sessions[n] for n in sorted(sessions)]


def main() -> None:
    sessions = parse_sessions(fetch_course_html())
    missing = sorted(set(range(1, LAST_SESSION + 1)) - {s["session"] for s in sessions})
    if missing:  # fail loudly rather than silently fetch an incomplete course
        sys.exit(f"Expected sessions 1-{LAST_SESSION}, missing: {missing}")

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(sessions, indent=2, ensure_ascii=False), encoding="utf-8")

    for s in sessions:
        print(f"{s['session']:>2}  {s['title']:<40}  {s['url']}")
    print(f"\nSaved {len(sessions)} sessions to {MANIFEST}")


if __name__ == "__main__":
    main()
