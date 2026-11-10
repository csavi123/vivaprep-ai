import anthropic
import httpx2

import llm
from llm import ask


def make_429():
    """Build a fake 'Too Many Requests' error, like the one Anthropic would send."""
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.RateLimitError(
        "rate limited", response=httpx2.Response(429, request=req), body=None
    )


def test_ask_returns_result():
    r = ask("Say hi in one word")
    assert len(r.text) != 0
    assert r.input_tokens > 0 and r.output_tokens > 0
    assert r.cost_usd > 0
    assert r.latency_s > 0
    assert r.stop_reason == "end_turn"


def test_ask_retries_after_429(monkeypatch):
    real_create = llm.client.messages.create  # keep the real one so call 2 can use it
    calls = {"count": 0}

    def fake_create(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise make_429()  # call 1: pretend Anthropic said "slow down"
        return real_create(**kwargs)  # call 2: the real API

    # Swap in the fakes for this test only (pytest puts the originals back afterwards)
    monkeypatch.setattr(llm.client.messages, "create", fake_create)
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)  # don't actually wait

    r = ask("Say hi in one word")

    assert calls["count"] == 2  # failed once, retried once
    assert r.stop_reason == "end_turn"  # the retry gave a real, complete answer
