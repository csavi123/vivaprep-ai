"""Integration tests for rag/search.py: the session filter and list_sessions() (Viva plan step 1a).

Run from the repo root, with Postgres running:
    pytest tests/test_search.py -v

Unlike test_api.py, these use the REAL database and the REAL BGE-M3 model, because the
thing under test is the SQL itself. They cost nothing (no Claude calls) but take ~15 s
to load the model, so the model is loaded once and shared by every test in this file.
If the database can't be reached, every test here is skipped instead of failing.
"""

import os

import psycopg
import pytest
from dotenv import load_dotenv

from rag.embeddings import load_model
from rag.search import list_sessions, search

QUESTION = "What is a token?"   # its top 5 come from sessions 1, 4 and 5, so it spans sessions
K = 5
NUMBER_OF_SESSIONS = 17          # sessions 1 to 17 are in the chunks table (checked 2026-11-17)


def database_is_reachable() -> bool:
    """True if DATABASE_URL is set and Postgres answers."""
    load_dotenv(".env")
    url = os.environ.get("DATABASE_URL")
    if url is None:
        return False
    try:
        with psycopg.connect(url, connect_timeout=3):
            return True
    except psycopg.OperationalError:
        return False


# Applies to every test in this file
pytestmark = pytest.mark.skipif(not database_is_reachable(), reason="Postgres is not reachable")


@pytest.fixture(scope="module")
def model():
    """Load BGE-M3 once for the whole file (scope="module"), not once per test."""
    return load_model()


def test_session_filter_returns_only_that_session(model):
    results = search(QUESTION, k=K, model=model, session=1)

    # Exactly k rows: the filter must not leave gaps (the HNSW-plus-WHERE risk)
    assert len(results) == K
    for result in results:
        assert result["session"] == 1
        assert result["chunk_id"].startswith("s01-")


def test_no_session_searches_all_sessions(model):
    results = search(QUESTION, k=K, model=model)

    assert len(results) == K
    sessions_seen = set()
    for result in results:
        sessions_seen.add(result["session"])
    # Without a filter this question pulls from more than one session
    assert len(sessions_seen) > 1


def test_results_are_best_first(model):
    results = search(QUESTION, k=K, model=model, session=1)

    scores = []
    for result in results:
        scores.append(result["score"])
    assert scores == sorted(scores, reverse=True)


def test_list_sessions_has_each_session_once_in_order():
    sessions = list_sessions()

    numbers = []
    for entry in sessions:
        numbers.append(entry["session"])
        assert entry["title"] != ""     # every session has a title to show in the dropdown

    assert numbers == list(range(1, NUMBER_OF_SESSIONS + 1))   # 1..17, in order, no repeats
