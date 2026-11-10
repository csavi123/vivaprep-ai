from llm import ask

def test_ask_returns_result():
    r = ask("Say hi in one word")
    assert len(r.text)!=0
    assert r.input_tokens > 0 and r.output_tokens > 0
    assert r.cost_usd > 0
    assert r.latency_s > 0
    assert r.stop_reason == "end_turn"
