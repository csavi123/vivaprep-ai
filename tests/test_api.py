"""Tests for the FastAPI backend (api/main.py).

Run from the repo root:
    pytest tests/test_api.py -v

These tests are free and fast: they never load BGE-M3 and never call Claude.
monkeypatch swaps in fakes for load_model() and answer(), and sets a test token,
so the tests don't depend on the real model, the database, or the secrets in .env.
"""

from fastapi.testclient import TestClient

import api.main
from schemas import GroundedAnswer, RagResult

TOKEN = "test-token"
FAKE_MODEL = "fake-model"       # stands in for BGE-M3; answer() only passes it along


def fake_answer(question, k=5, model=None):
    """Pretend to be rag.answer.answer(): return a fixed RagResult, no search, no Claude."""
    # The API must pass the model it loaded at startup (not None, not a new one)
    assert model == FAKE_MODEL
    grounded = GroundedAnswer(answer="A token is a piece of text.", citations=[], in_course=True)
    return RagResult(
        question=question,
        answer=grounded,
        chunks=[],
        invalid_citations=[],
        cost_usd=0.0,
        latency_s=0.0,
    )


def make_client(monkeypatch, answer_function=fake_answer):
    """Build a TestClient with a test token and fake model/answer.

    We patch api.main.answer, not rag.answer.answer: main.py did `from rag.answer import answer`,
    which copied the name into api.main, so api.main.answer is the name the endpoint actually uses.
    """
    monkeypatch.setenv("API_TOKEN", TOKEN)                          # overrides any API_TOKEN from .env
    monkeypatch.setattr(api.main, "load_model", lambda: FAKE_MODEL)
    monkeypatch.setattr(api.main, "answer", answer_function)
    # Use it as `with make_client(...) as client:` -- the `with` runs the lifespan (startup + shutdown)
    return TestClient(api.main.app)


def test_health_ok(monkeypatch):
    with make_client(monkeypatch) as client:
        response = client.get("/health")             # no token: /health is public
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ask_missing_token(monkeypatch):
    with make_client(monkeypatch) as client:
        response = client.post("/ask", json={"question": "What is a token?"})
    assert response.status_code == 401


def test_ask_wrong_token(monkeypatch):
    with make_client(monkeypatch) as client:
        response = client.post(
            "/ask",
            json={"question": "What is a token?"},
            headers={"X-API-Token": "wrong-token"},
        )
    assert response.status_code == 401


def test_ask_too_short(monkeypatch):
    with make_client(monkeypatch) as client:
        response = client.post("/ask", json={"question": "hi"}, headers={"X-API-Token": TOKEN})
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "string_too_short"


def test_ask_ok(monkeypatch):
    with make_client(monkeypatch) as client:
        response = client.post(
            "/ask",
            json={"question": "What is a token?"},
            headers={"X-API-Token": TOKEN},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["question"] == "What is a token?"
    assert body["answer"]["answer"] == "A token is a piece of text."
    assert body["answer"]["in_course"] is True


def test_ask_answer_fails(monkeypatch):
    """If answer() crashes, the client gets a 502 with a safe message, never the internal error text."""
    def broken_answer(question, k=5, model=None):
        raise RuntimeError("internal detail: DATABASE_URL=postgres://user:secret@host")

    with make_client(monkeypatch, answer_function=broken_answer) as client:
        response = client.post(
            "/ask",
            json={"question": "What is a token?"},
            headers={"X-API-Token": TOKEN},
        )
    assert response.status_code == 502
    assert "DATABASE_URL" not in response.text       # the error text stayed in the server log
    assert "secret" not in response.text
