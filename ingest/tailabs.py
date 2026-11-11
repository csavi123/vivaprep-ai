"""Fetch TAI Labs session pages (Content tab only) and save them as Markdown.

Run from the repo root:
    python ingest/tailabs.py --only 1     # one session
    python ingest/tailabs.py              # every session in the manifest
    python ingest/tailabs.py --force      # re-fetch files that already exist
    python ingest/tailabs.py --from-html  # rebuild Markdown from saved snapshots, no browser

Reads data/raw/tailabs/_manifest.json (from build_manifest.py) and writes:
    data/raw/tailabs/sNN_<slug>.md   Markdown with front matter:
                                     source, module, module_title, session, title, url, fetched_at
    data/raw/tailabs/html/sNN.html   snapshot of the content sections (proof of the source)

Markdown is always converted FROM the snapshot, so --from-html reproduces it exactly.
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import frontmatter
from bs4 import BeautifulSoup
from markdownify import MarkdownConverter
from playwright.sync_api import Page, expect, sync_playwright

AUTH_FILE = Path("auth.json")
OUT_DIR = Path("data/raw/tailabs")
HTML_DIR = OUT_DIR / "html"
MANIFEST = OUT_DIR / "_manifest.json"
DELAY_S = 2  # politeness gap between page loads


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def output_path(entry: dict) -> Path:
    return OUT_DIR / f"s{entry['session']:02d}_{slugify(entry['title'])}.md"


def snapshot_path(entry: dict) -> Path:
    return HTML_DIR / f"s{entry['session']:02d}.html"


def already_saved(entry: dict) -> bool:
    # match on the number only, so a renamed title doesn't cause a re-fetch
    return any(OUT_DIR.glob(f"s{entry['session']:02d}_*.md"))


# ---------- 1. Playwright: load the page with every subtopic expanded ----------

def load_expanded_html(page: Page, url: str) -> str:
    page.goto(url, wait_until="networkidle")
    if "/auth" in page.url:
        sys.exit("Session expired: run python ingest/login.py again")

    # The Reading section holds one <li> per subtopic; only open ones have their <article>.
    reading = page.locator("section:has(article.session-reading)").first
    subtopics = reading.locator("li:has(> button[aria-expanded])")
    expand_all = page.get_by_role("button", name="Expand all")
    if expand_all.count():
        expand_all.click()

    # Wait until EVERY subtopic has rendered its text, or fail after 15s.
    expect(reading.locator("article.session-reading")).to_have_count(subtopics.count(), timeout=15_000)
    return page.content()


# ---------- 2. Snapshot: keep only the content sections (no nav, no personal data) ----------

def find_intro_section(soup: BeautifulSoup):
    label = soup.find(string=lambda s: s and s.strip() == "In short")
    return label.find_parent("section") if label else None


def content_snapshot(page_html: str, entry: dict, fetched_at: str) -> str:
    soup = BeautifulSoup(page_html, "html.parser")
    article = soup.select_one("article.session-reading")
    if not article:
        raise ValueError("no subtopic articles found on page")
    sections = [s for s in (find_intro_section(soup), article.find_parent("section")) if s]
    return (
        "<!doctype html>\n<html><head><meta charset='utf-8'>\n"
        f"<meta name='url' content='{entry['url']}'>\n"
        f"<meta name='fetched_at' content='{fetched_at}'>\n"
        "</head><body>\n" + "\n".join(str(s) for s in sections) + "\n</body></html>\n"
    )


# ---------- 3. BeautifulSoup + markdownify: snapshot HTML -> Markdown ----------

def intro_questions(soup: BeautifulSoup) -> list[str]:
    section = find_intro_section(soup)
    if not section:
        return []
    questions = []
    for card in section.select("ol > li"):
        p = card.find("p")  # the question; the first card is an image with no text
        if p and p.get_text(strip=True):
            questions.append(p.get_text(" ", strip=True))
    return questions


class FenceSafeConverter(MarkdownConverter):
    """Use a longer fence when the code itself contains ``` (e.g. an example README).

    Otherwise the inner ``` closes the outer block early, and the example's
    "# headings" leak out as real headings.
    """

    def convert_pre(self, el, text, parent_tags):
        md = super().convert_pre(el, text, parent_tags)
        longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
        if longest < 3:
            return md  # normal case: ``` is safe
        fence = "`" * (longest + 1)
        head, rest = md.split("```", 1)     # replace the opening fence...
        body, tail = rest.rsplit("```", 1)  # ...and the closing fence
        return f"{head}{fence}{body}{fence}{tail}"


def tag_code_languages(article) -> None:
    """Move each code block's header label ("python") onto its <pre>, then drop the header.

    On the site a code block is <figure><figcaption><span>python</span><button>Copy</button>
    </figcaption><pre>...</pre></figure>. Left alone, the header becomes a "pythonCopy" line.
    """
    for caption in article.select("figure > figcaption"):
        pre = caption.find_next_sibling("pre")
        label = caption.find("span")
        if pre and label and label.get_text(strip=True):
            pre["data-lang"] = label.get_text(strip=True).lower()
            caption.decompose()


def article_to_markdown(article) -> str:
    # Lesson subheadings must sit below the "## subtopic" heading
    for h in article.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        h.name = "h3"
    tag_code_languages(article)
    md = FenceSafeConverter(
        heading_style="ATX",
        bullets="-",
        code_language_callback=lambda pre: pre.get("data-lang"),  # -> ```python
    ).convert(str(article))
    return re.sub(r"\n{3,}", "\n\n", md).strip()  # collapse runs of blank lines


def to_markdown(html: str, entry: dict) -> tuple[str, list[tuple[str, int]]]:
    """Return (markdown body, [(subtopic heading, chars), ...]) for reporting."""
    soup = BeautifulSoup(html, "html.parser")
    parts = [f"# {entry['title']}"]

    questions = intro_questions(soup)
    if questions:
        parts.append("## In short\n\n" + "\n".join(f"- {q}" for q in questions))
    else:
        print("   warning: no 'In short' questions found")

    articles = soup.select("article.session-reading")
    if not articles:
        raise ValueError("no subtopic articles found in snapshot")

    stats = []
    for article in articles:
        heading = article.find_parent("li").find("button").get_text(" ", strip=True)
        body = article_to_markdown(article)
        parts.append(f"## {heading}\n\n{body}")
        stats.append((heading, len(body)))
    return "\n\n".join(parts) + "\n", stats


# ---------- 4. python-frontmatter: add metadata and save ----------

def save(entry: dict, body: str, fetched_at: str) -> Path:
    meta = {**entry, "fetched_at": fetched_at}
    path = output_path(entry)
    path.write_text(frontmatter.dumps(frontmatter.Post(body, **meta), sort_keys=False) + "\n", encoding="utf-8")
    return path


def convert_and_save(entry: dict, snapshot: str, fetched_at: str) -> None:
    body, stats = to_markdown(snapshot, entry)
    for heading, chars in stats:
        print(f"     {chars:>7,} chars  {heading}")
    path = save(entry, body, fetched_at)
    print(f"   -> {path} ({len(body):,} chars, {len(stats)} subtopics)")


# ---------- main ----------

def fetch_live(entries: list[dict], failures: list) -> None:
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(storage_state=AUTH_FILE).new_page()
        for i, entry in enumerate(entries):
            if i:
                time.sleep(DELAY_S)
            print(f"[{entry['session']:>2}] {entry['title']}")
            try:
                page_html = load_expanded_html(page, entry["url"])
                fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                snapshot = content_snapshot(page_html, entry, fetched_at)
                snapshot_path(entry).write_text(snapshot, encoding="utf-8")  # saved even if conversion fails
                convert_and_save(entry, snapshot, fetched_at)
            except Exception as e:  # one bad page shouldn't stop the run
                print(f"   FAILED: {type(e).__name__}: {e}")
                failures.append((entry["session"], str(e)))
        browser.close()


def rebuild_from_html(entries: list[dict], failures: list) -> None:
    for entry in entries:
        print(f"[{entry['session']:>2}] {entry['title']} (from snapshot)")
        try:
            snapshot = snapshot_path(entry).read_text(encoding="utf-8")
            fetched_at = BeautifulSoup(snapshot, "html.parser").find("meta", attrs={"name": "fetched_at"})["content"]
            convert_and_save(entry, snapshot, fetched_at)  # keeps the ORIGINAL fetch time
        except Exception as e:
            print(f"   FAILED: {type(e).__name__}: {e}")
            failures.append((entry["session"], str(e)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", type=int, nargs="+", help="session numbers to process")
    parser.add_argument("--force", action="store_true", help="re-fetch files that already exist")
    parser.add_argument("--from-html", action="store_true", help="rebuild Markdown from saved snapshots")
    args = parser.parse_args()

    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if args.only:
        entries = [e for e in entries if e["session"] in args.only]

    failures = []
    if args.from_html:
        print(f"Rebuilding {len(entries)} sessions from snapshots\n")
        rebuild_from_html(entries, failures)
        done = len(entries)
    else:
        todo = [e for e in entries if args.force or not already_saved(e)]
        print(f"{len(entries)} selected, {len(entries) - len(todo)} already saved, {len(todo)} to fetch\n")
        fetch_live(todo, failures)
        done = len(todo)

    print(f"\nDone: {done - len(failures)} saved, {len(failures)} failed")
    if failures:
        for n, err in failures:
            print(f"  session {n}: {err[:150]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
