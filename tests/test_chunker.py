"""Tests for rag/chunker.py.

Part 1 uses a tiny made-up lesson, so it runs on any computer.
Part 2 checks the real chunks. It skips itself if the course files aren't on this computer.
"""

import json

import pytest

from evals.build_retrieval_set import OUT_FILE as EVAL_FILE   # evals/datasets/retrieval_v1.jsonl
from rag.chunker import DATA_DIR, MAX_TOKENS, chunk_all, mark_code_lines, pack, split_sections


# =====================================================================
# Part 1: test the rules on a tiny made-up lesson
# =====================================================================

SAMPLE_LESSON = """# Caching basics

## In short

- What is a cache?

## 01 Why caches exist

By the end of this lesson you can:

- Explain a cache hit

### Hits and misses

A hit means the copy was there.

```python
# not a heading: a Python comment
cache = {}
```

**Check yourself**

- What is a cache miss?

## 02 Eviction

When the cache is full, something has to go.
"""


def test_eval_text_is_removed():
    sections = split_sections(SAMPLE_LESSON)

    # Put all the kept text together in one string
    all_text = ""
    for section in sections:
        all_text = all_text + section["text"]

    assert "What is a cache?" not in all_text        # the "In short" question
    assert "Explain a cache hit" not in all_text     # the learning objective
    assert "What is a cache miss?" not in all_text   # the "Check yourself" question


def test_comment_inside_code_is_not_a_heading():
    sections = split_sections(SAMPLE_LESSON)

    # We expect exactly 2 sections. If "# not a heading" had been treated
    # as a heading, there would be more.
    assert len(sections) == 2
    assert sections[0]["section"] == "Hits and misses"
    assert sections[1]["section"] == "(intro)"

    # The comment should still be there, as part of the code
    assert "# not a heading" in sections[0]["text"]


def make_section(subtopic, name, tokens):
    """A fake section of a chosen size (4 characters = about 1 token)."""
    return {"subtopic": subtopic, "section": name, "text": "x" * (tokens * 4)}


def test_small_sections_are_joined():
    a = make_section("01", "A", 300)
    b = make_section("01", "B", 300)
    c = make_section("01", "C", 300)

    groups = pack([a, b, c], max_tokens=800, title="Test")

    # A + B fit under 800 together. Adding C would go over, so C gets its own group.
    assert len(groups) == 2
    assert groups[0] == [a, b]
    assert groups[1] == [c]


def test_different_subtopics_are_never_joined():
    a = make_section("01", "A", 50)
    b = make_section("02", "B", 50)   # a different subtopic

    groups = pack([a, b], max_tokens=800, title="Test")

    # Both are tiny, but they must stay apart
    assert len(groups) == 2


def test_a_big_section_is_kept_whole():
    big = make_section("01", "Big", 1000)   # already over 800 on its own

    groups = pack([big], max_tokens=800, title="Test")

    # It is not cut in half: it stays as one group
    assert len(groups) == 1
    assert groups[0] == [big]


# =====================================================================
# Part 2: check the real chunks made from the course files
# =====================================================================

has_course_files = DATA_DIR.exists()
skip_if_no_files = pytest.mark.skipif(not has_course_files, reason="course files are not on this computer")

if has_course_files:
    CHUNKS = chunk_all()
else:
    CHUNKS = []


@skip_if_no_files
def test_number_of_chunks():
    # 591 measured on 2026-11-12. If the chunker or the files change, this number changes too.
    assert len(CHUNKS) == 591


@skip_if_no_files
def test_chunk_ids_are_unique():
    seen = set()
    for chunk in CHUNKS:
        assert chunk["chunk_id"] not in seen, f"duplicate id: {chunk['chunk_id']}"
        seen.add(chunk["chunk_id"])


@skip_if_no_files
def test_every_subtopic_has_at_least_one_chunk():
    subtopics = set()
    for chunk in CHUNKS:
        subtopics.add((chunk["session"], chunk["subtopic"]))

    # 124 subtopics were counted in the course files in M3
    assert len(subtopics) == 124


# s13's lesson quotes its own "In short" question in "Answering the question" and then
# answers it. That is lesson content, not leakage, so it stays (D017).
# Note: this is s13-q2 in the eval set, so it is an easy question for retrieval.
# This is the only allowed match: any other one fails the test.
ALLOWED_QUOTES = {
    "s13-c014": "When does a model need a GPU to serve",
}


@skip_if_no_files
def test_no_eval_text_in_any_chunk():
    # Read the 46 eval questions from evals/datasets/retrieval_v1.jsonl (one JSON record per line)
    assert EVAL_FILE.exists(), f"{EVAL_FILE} is missing: run python evals/build_retrieval_set.py"
    questions = []
    for line in EVAL_FILE.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        questions.append(record["query"])
    assert len(questions) == 46

    for chunk in CHUNKS:
        text = chunk["text"]
        assert "By the end of this lesson you can" not in text, f"objectives in {chunk['chunk_id']}"
        # Look for the bold marker that starts a quiz list. The plain words "Check yourself"
        # can appear in normal lesson text (s12 has one), and that text should stay.
        assert "**Check yourself**" not in text, f"'Check yourself' quiz in {chunk['chunk_id']}"
        for question in questions:
            if question in text:
                chunk_id = chunk["chunk_id"]
                # Allowed only if this chunk is in ALLOWED_QUOTES AND it is the expected question
                allowed = chunk_id in ALLOWED_QUOTES and question.startswith(ALLOWED_QUOTES[chunk_id])
                assert allowed, f"an 'In short' question is in {chunk_id}: {question[:50]}"


@skip_if_no_files
def test_every_chunk_starts_with_its_heading_path():
    for chunk in CHUNKS:
        # The heading path starts with the session title, then the subtopic
        expected_start = chunk["title"] + " > " + chunk["subtopic"]
        assert chunk["heading_path"].startswith(expected_start), chunk["chunk_id"]

        # The chunk's text starts with the heading path
        assert chunk["text"].startswith(chunk["heading_path"]), chunk["chunk_id"]


@skip_if_no_files
def test_no_code_block_is_cut_in_half():
    for chunk in CHUNKS:
        # mark_code_lines returns 3 things; the 3rd is True if a code block never closes
        lines, blocks, unclosed = mark_code_lines(chunk["text"])
        assert unclosed is False, f"a code block is cut in half in {chunk['chunk_id']}"


@skip_if_no_files
def test_only_single_sections_go_over_the_limit():
    for chunk in CHUNKS:
        if chunk["tokens_est"] > MAX_TOKENS:
            # Over the limit is only allowed for ONE section that was too big on its own
            assert len(chunk["sections"]) == 1, f"{chunk['chunk_id']} joined sections past {MAX_TOKENS}"
