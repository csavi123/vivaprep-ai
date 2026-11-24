"""Trajectory checks on hand-made agent results. No API calls, no ADK, no database."""

from evals.run_agent_eval import check_turn


def make_result(searches: list[tuple[str, list[tuple[str, int]]]], answer: str, model_calls: int = 2) -> dict:
    """Build a fake run_chat() result. searches = [(query, [(chunk_id, session), ...]), ...]"""
    trace = []
    for query, passages in searches:
        passage_dicts = []
        for chunk_id, session in passages:
            passage_dicts.append({"chunk_id": chunk_id, "session": session, "text": "..."})
        trace.append({"tool": "search_course", "args": {"query": query}, "status": "ok", "passages": passage_dicts})
    return {"answer": answer, "trace": trace, "model_calls": model_calls}


def test_good_course_answer_passes():
    result = make_result([("what is a context window", [("s01-c010", 1), ("s05-c002", 5)])],
                         "The context window is everything the model sees [s01-c010].")
    expect = {"search": "required", "query_keywords": ["context"], "citations": "required", "max_model_calls": 4}
    checks = check_turn(result, expect, {"s01-c010", "s05-c002"})
    assert checks["search_rule"] and checks["query_keywords"] and checks["citations_rule"]
    assert checks["citations_real"] and checks["bounded"]
    assert checks["in_scope"] is None           # no session was picked


def test_answer_without_search_fails_search_rule():
    result = make_result([], "A context window is the model's working memory.")
    checks = check_turn(result, {"search": "required", "query_keywords": ["context"]}, set())
    assert checks["search_rule"] is False
    assert checks["query_keywords"] is None     # no query to check; search_rule already failed


def test_made_up_citation_fails():
    result = make_result([("tokens", [("s01-c006", 1)])], "See [s01-c006, s01-c099].")
    checks = check_turn(result, {}, {"s01-c006"})
    assert checks["citations_real"] is False    # s01-c099 was never returned


def test_passage_from_other_session_fails_scope():
    result = make_result([("measure retrieval", [("s07-c020", 7), ("s09-c001", 9)])], "Use recall@k [s07-c020].")
    checks = check_turn(result, {"scope_session": 7}, {"s07-c020", "s09-c001"})
    assert checks["in_scope"] is False


def test_small_talk_with_search_fails():
    result = make_result([("who are you", [("s17-c001", 17)])], "I'm VivaPrep.")
    checks = check_turn(result, {"search": "forbidden", "citations": "forbidden"}, {"s17-c001"})
    assert checks["search_rule"] is False
    assert checks["citations_rule"] is True     # it didn't cite anything


def test_keyword_groups_need_one_match_each():
    result = make_result([("what is rag", []), ("when to fine-tune", [])], "...")
    expect = {"query_keywords": ["rag|retriev", "fine"], "min_searches": 2}
    checks = check_turn(result, expect, set())
    assert checks["query_keywords"] is True
    assert checks["enough_searches"] is True


def test_mentions_handles_curly_apostrophe():
    result = make_result([], "Sorry, the course doesn’t cover baking.")
    checks = check_turn(result, {"must_mention_any": ["doesn't cover"]}, set())
    assert checks["mentions"] is True


def test_too_many_model_calls_fails_bounded():
    result = make_result([], "Hi!", model_calls=5)
    checks = check_turn(result, {"max_model_calls": 2}, set())
    assert checks["bounded"] is False
