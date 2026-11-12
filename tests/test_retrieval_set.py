"""Checks the retrieval eval set built from the 'In short' questions.

Calls build_records() directly, so it checks the data in memory and never touches
the .jsonl file.
"""

from collections import Counter

import pytest

from evals.build_retrieval_set import DATA_DIR, EXCLUDE, build_records

pytestmark = pytest.mark.skipif(not DATA_DIR.exists(), reason="no local TAI Labs data")

EXPECTED_QUESTIONS = 46  # 46 "In short" questions minus the ones in EXCLUDE 
EXPECTED_SESSIONS = 14


def test_expected_number_of_questions():
    records = build_records()
    assert len(records) == EXPECTED_QUESTIONS, f"expected {EXPECTED_QUESTIONS} questions, got {len(records)}"

    sessions = {r["session"] for r in records}
    assert sessions == set(range(1, EXPECTED_SESSIONS + 1)), f"sessions found: {sorted(sessions)}"


def test_ids_are_unique():
    ids = [r["id"] for r in build_records()]
    duplicates = [i for i, count in Counter(ids).items() if count > 1]
    assert duplicates == [], f"duplicate ids: {duplicates}"


def test_excluded_questions_are_dropped():
    ids = {r["id"] for r in build_records()}
    leaked = ids & EXCLUDE  # set intersection: ids that are in both
    assert leaked == set(), f"excluded questions still present: {leaked}"


def test_queries_are_clean():
    problems = []
    for r in build_records():
        query = r["query"]
        if not query.strip():
            problems.append(f"{r['id']}: empty query")
        elif query.startswith("- "):
            problems.append(f"{r['id']}: leftover bullet: {query[:40]}")
    assert problems == [], "\n".join(problems)
