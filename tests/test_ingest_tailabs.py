"""Checks that the scraped TAI Labs files are complete and faithful to the source.

These tests read local data in data/raw/tailabs/, which is never committed,
so they skip themselves on any machine that doesn't have it (e.g. CI).
"""

import json
import re
from pathlib import Path

import frontmatter
import pytest
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).parent.parent / "data" / "raw" / "tailabs"
MANIFEST = DATA_DIR / "_manifest.json"
REQUIRED_FIELDS = ["source", "module", "module_title", "session", "title", "url", "fetched_at"]

WORD = re.compile(r"[A-Za-z0-9]+")  # a "word" for comparing texts; ignores Markdown symbols like ** and |
MIN_WORD_RATIO = 0.99  # Markdown may lose at most 1% of a subtopic's words...
MAX_WORD_RATIO = 1.02  # ...and gain at most 2% (list numbers, link URLs). Measured max on 2026-11-11: +0.54%

# Skip every test in this file when the local data isn't there.
pytestmark = pytest.mark.skipif(not MANIFEST.exists(), reason="no local TAI Labs data")

# parametrize needs the list when pytest first reads this file, so load it once here.
SESSIONS = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else []


def md_file(session: int) -> Path:
    """Return the saved Markdown file for a session number, e.g. 3 -> s03_python-tooling.md."""
    matches = list(DATA_DIR.glob(f"s{session:02d}_*.md"))
    assert len(matches) == 1, f"expected 1 file for session {session}, found {len(matches)}"
    return matches[0]


def markdown_body(session: int) -> str:
    """The lesson text of a session, without the front matter."""
    return frontmatter.load(md_file(session)).content


def snapshot(session: int) -> BeautifulSoup:
    """The saved HTML snapshot of a session: the source we compare against."""
    return BeautifulSoup((DATA_DIR / "html" / f"s{session:02d}.html").read_text(), "html.parser")


def mark_code_lines(text: str) -> tuple[list[tuple[str, bool]], int, bool]:
    """Walk the Markdown line by line, tracking whether we are inside a code block.

    Returns (lines, blocks, unclosed):
      lines    - [(line, in_code), ...]; the fence lines themselves count as in_code
      blocks   - how many code blocks were opened
      unclosed - True if the file ends while still inside a code block
    A block opened with ```` only closes on a fence at least as long, so the
    ``` lines inside session 3's example README stay inside the outer block.
    """
    lines, blocks, fence = [], 0, None
    for line in text.splitlines():
        stripped = line.strip()
        if fence is None and re.match(r"^`{3,}", line):
            fence = re.match(r"^`{3,}", line).group()  # opening fence, e.g. ``` or ````
            blocks += 1
            lines.append((line, True))
        elif fence is not None:
            if re.fullmatch(r"`+", stripped) and len(stripped) >= len(fence):
                fence = None  # closing fence
            lines.append((line, True))
        else:
            lines.append((line, False))
    return lines, blocks, fence is not None


def md_subtopics(text: str) -> list[tuple[str, str]]:
    """Split the Markdown into [(subtopic heading, body), ...] on '## ' lines outside code."""
    subtopics = []
    for line, in_code in mark_code_lines(text)[0]:
        if not in_code and line.startswith("## "):
            subtopics.append((line[3:], []))  # start a new subtopic
        elif subtopics:
            subtopics[-1][1].append(line)  # add the line to the current subtopic's body
    return [(heading, "\n".join(body)) for heading, body in subtopics if heading != "In short"]


def snapshot_subtopics(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """The same split from the HTML snapshot: [(subtopic heading, visible text), ...]."""
    subtopics = []
    for article in soup.select("article.session-reading"):
        heading = article.find_parent("li").find("button").get_text(" ", strip=True)
        for copy_button in article.select("figcaption button"):
            copy_button.decompose()  # page UI only; the language label stays, like ```python
        subtopics.append((heading, article.get_text(" ")))
    return subtopics


def test_every_session_is_saved():
    assert len(SESSIONS) == 17, f"Expected 17 sessions in the manifest, found {len(SESSIONS)}"

    missing = []
    for entry in SESSIONS:
        n = entry["session"]
        if not list(DATA_DIR.glob(f"s{n:02d}_*.md")):
            missing.append(n)
    assert missing == [], f"Missing sessions: {missing}"


@pytest.mark.parametrize("entry", SESSIONS, ids=lambda e: f"s{e['session']:02d}")
def test_front_matter_is_complete(entry):
    post = frontmatter.load(md_file(entry["session"]))

    missing = [field for field in REQUIRED_FIELDS if field not in post.metadata]
    assert missing == [], f"missing fields: {missing}"
    assert post["session"] == entry["session"], "session number doesn't match the manifest"
    assert post["url"] == entry["url"], "url doesn't match the manifest"


@pytest.mark.parametrize("entry", SESSIONS, ids=lambda e: f"s{e['session']:02d}")
def test_no_leftover_junk(entry):
    text = markdown_body(entry["session"])

    html_tags = re.findall(r"</?(?:div|span|button|p|li|ul|ol|table|figure|figcaption)\b", text)
    assert html_tags == [], f"leftover HTML tags: {html_tags[:5]}"

    copy_lines = re.findall(r"^\w*Copy$", text, flags=re.M)  # e.g. "pythonCopy" from the code header
    assert copy_lines == [], f"leftover Copy-button labels: {copy_lines[:5]}"

    ui_text = [s for s in ["Expand all", "Collapse all", "min read", "Go to assignments"] if s in text]
    assert ui_text == [], f"leftover page UI text: {ui_text}"


@pytest.mark.parametrize("entry", SESSIONS, ids=lambda e: f"s{e['session']:02d}")
def test_subtopics_match_snapshot(entry):
    text = markdown_body(entry["session"])
    md_headings = [heading for heading, _ in md_subtopics(text)]
    snap_headings = [heading for heading, _ in snapshot_subtopics(snapshot(entry["session"]))]

    # Same subtopics, same order. A stray "## " (e.g. leaked from a broken code block) also fails this.
    assert md_headings == snap_headings, f"\nMarkdown: {md_headings}\nSnapshot: {snap_headings}"

    titles = [line for line, in_code in mark_code_lines(text)[0] if not in_code and line.startswith("# ")]
    assert titles == [f"# {entry['title']}"], f"expected exactly one title heading, found {titles}"


@pytest.mark.parametrize("entry", SESSIONS, ids=lambda e: f"s{e['session']:02d}")
def test_subtopic_text_matches_snapshot(entry):
    md = dict(md_subtopics(markdown_body(entry["session"])))  # {heading: body}

    problems = []
    for heading, snap_text in snapshot_subtopics(snapshot(entry["session"])):
        snap_words = len(WORD.findall(snap_text))
        md_words = len(WORD.findall(md.get(heading, "")))  # "" if the subtopic is missing
        ratio = md_words / snap_words
        if not MIN_WORD_RATIO <= ratio <= MAX_WORD_RATIO:
            problems.append(f"{heading}: {md_words} words vs {snap_words} in snapshot ({ratio:.1%})")
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("entry", SESSIONS, ids=lambda e: f"s{e['session']:02d}")
def test_code_blocks_and_tables_match_snapshot(entry):
    text = markdown_body(entry["session"])
    soup = snapshot(entry["session"])
    _, md_blocks, unclosed = mark_code_lines(text)

    assert not unclosed, "file ends inside a code block (a fence was never closed)"

    snap_blocks = len(soup.find_all("pre"))
    assert md_blocks == snap_blocks, f"{md_blocks} code blocks in Markdown vs {snap_blocks} in snapshot"

    md_tables = len(re.findall(r"^\|(?:\s*:?-+:?\s*\|)+\s*$", text, flags=re.M))  # the "| --- | --- |" rows
    snap_tables = len(soup.find_all("table"))
    assert md_tables == snap_tables, f"{md_tables} tables in Markdown vs {snap_tables} in snapshot"
