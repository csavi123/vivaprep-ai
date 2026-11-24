"""Does the tutor agent take sensible steps? Trajectory eval (Phase 3, step 3c).

Dataset: evals/datasets/agent_v1.jsonl. Each case is one chat (1 or more student turns).
Every case runs through run_chat() (agents/vivaprep_tutor/chat.py), the same function POST /chat uses,
and the LAST turn is checked against the case's "expect" block. All checks are plain code, no judge.

Run from the repo root:
    python -m evals.run_agent_eval --runs 1
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from evals.run_evals import load_cases

DATASET = Path(__file__).parent / "datasets" / "agent_v1.jsonl"
REPORTS_DIR = Path(__file__).parent / "reports"

# A chunk id in an answer, e.g. s07-c012 (also inside "[s07-c012, s07-c013]")
CHUNK_ID_PATTERN = re.compile(r"s\d{2}-c\d{3}")

CHECK_NAMES = [
    "search_rule",          # searched when required / didn't when forbidden
    "enough_searches",      # at least min_searches calls (multi-concept, summaries)
    "query_keywords",       # each keyword group appears in at least one query
    "in_scope",             # every passage came from the picked session
    "citations_rule",       # cited when required / didn't when forbidden
    "citations_real",       # every cited chunk id was returned by a search in this chat
    "mentions",             # the answer contains one of the expected phrases
    "bounded",              # model_calls <= max_model_calls
]


def search_calls(trace: list[dict]) -> list[dict]:
    """Only the search_course calls from a trace."""
    calls = []
    for entry in trace:
        if entry["tool"] == "search_course":
            calls.append(entry)
    return calls


def check_turn(result: dict, expect: dict, returned_ids: set) -> dict:
    """Check one agent turn. Each check is True, False, or None (doesn't apply to this case).

    result:       what run_chat() returned for the last turn (answer, trace, model_calls)
    expect:       the case's expectations from the dataset
    returned_ids: every chunk id returned by any search in this chat (all turns), for citations_real
    """
    checks = {}
    searches = search_calls(result["trace"])
    answer = result["answer"].lower().replace("’", "'")     # curly apostrophe -> straight one
    cited = set(CHUNK_ID_PATTERN.findall(result["answer"]))

    # 1. Searched (or not) as the rule says
    rule = expect.get("search", "any")
    if rule == "required":
        checks["search_rule"] = len(searches) >= 1
    elif rule == "forbidden":
        checks["search_rule"] = len(searches) == 0
    else:
        checks["search_rule"] = None

    # 2. Enough searches
    if "min_searches" in expect:
        checks["enough_searches"] = len(searches) >= expect["min_searches"]
    else:
        checks["enough_searches"] = None

    # 3. Query keywords: "a|b" means a OR b; every group must match at least one query.
    #    Not applicable when there was no search (search_rule already reports that).
    if "query_keywords" in expect and len(searches) > 0:
        queries = []
        for s in searches:
            queries.append(str(s["args"].get("query", "")).lower())
        all_groups_found = True
        for group in expect["query_keywords"]:
            group_found = False
            for word in group.split("|"):
                for query in queries:
                    if word in query:
                        group_found = True
            if not group_found:
                all_groups_found = False
        checks["query_keywords"] = all_groups_found
    else:
        checks["query_keywords"] = None

    # 4. Scope: every passage from the picked session
    if "scope_session" in expect and len(searches) > 0:
        in_scope = True
        for s in searches:
            for passage in s["passages"]:
                if passage["session"] != expect["scope_session"]:
                    in_scope = False
        checks["in_scope"] = in_scope
    else:
        checks["in_scope"] = None

    # 5. Citations present (or absent) as the rule says
    citation_rule = expect.get("citations", "any")
    if citation_rule == "required":
        checks["citations_rule"] = len(cited) > 0
    elif citation_rule == "forbidden":
        checks["citations_rule"] = len(cited) == 0
    else:
        checks["citations_rule"] = None

    # 6. Citations real: nothing cited that no search returned (a made-up chunk id)
    if len(cited) > 0:
        checks["citations_real"] = cited.issubset(returned_ids)
    else:
        checks["citations_real"] = None

    # 7. Must mention one of these phrases
    if "must_mention_any" in expect:
        mentioned = False
        for phrase in expect["must_mention_any"]:
            if phrase.lower() in answer:
                mentioned = True
        checks["mentions"] = mentioned
    else:
        checks["mentions"] = None

    # 8. Bounded: not too many Claude calls for one message
    if "max_model_calls" in expect:
        checks["bounded"] = result["model_calls"] <= expect["max_model_calls"]
    else:
        checks["bounded"] = None

    return checks


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()

    # Imported here, not at the top: it loads ADK, which tests of check_turn() don't need
    from agents.vivaprep_tutor.chat import run_chat

    cases = load_cases(DATASET)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    REPORTS_DIR.mkdir(exist_ok=True)
    print(f"Loaded {len(cases)} cases (BGE-M3 loads on the first search, slow once)")

    for run in range(1, args.runs + 1):
        out_file = REPORTS_DIR / f"agent_{stamp}_run{run}.jsonl"
        records = []
        total_cost = 0.0

        for case in cases:
            # A fresh chat per case (and per run), so no case sees another case's history
            chat_id = f"eval-{case['id']}-{stamp}-run{run}"
            returned_ids = set()
            result = None
            try:
                for message in case["turns"]:
                    result = run_chat(chat_id, message, case["course_session"])
                    total_cost = total_cost + result["cost_usd"]
                    for s in search_calls(result["trace"]):
                        for passage in s["passages"]:
                            returned_ids.add(passage["chunk_id"])
            except Exception as error:
                # One failed network/model call shouldn't stop the whole run; record it and move on
                print(f"run {run} {case['id']}: ERROR {type(error).__name__}: {error}")
                records.append({"id": case["id"], "type": case["type"], "error": str(error)})
                continue

            checks = check_turn(result, case["expect"], returned_ids)
            failed = []
            for name in CHECK_NAMES:
                if checks[name] is False:
                    failed.append(name)
            searches = search_calls(result["trace"])
            status = "ok" if len(failed) == 0 else "FAILED " + ", ".join(failed)
            print(f"run {run} {case['id']} [{case['type']}]: {len(searches)} searches, "
                  f"{result['model_calls']} model calls -> {status}")

            # Save the trajectory without passage text (ids and sessions are enough to read it back)
            trajectory = []
            for s in searches:
                passage_ids = []
                for passage in s["passages"]:
                    passage_ids.append(f"{passage['chunk_id']} (s{passage['session']})")
                trajectory.append({"query": s["args"].get("query"), "passages": passage_ids})

            records.append({
                "id": case["id"],
                "type": case["type"],
                "checks": checks,
                "failed": failed,
                "trajectory": trajectory,
                "model_calls": result["model_calls"],
                "answer": result["answer"],
                "cost_usd": result["cost_usd"],
            })

        # Summary: pass rate per check, over the cases it applies to
        print(f"\n--- Run {run} summary ---")
        for name in CHECK_NAMES:
            applies = 0
            passed = 0
            for r in records:
                if "checks" not in r or r["checks"][name] is None:
                    continue
                applies = applies + 1
                if r["checks"][name]:
                    passed = passed + 1
            print(f"{name:<16} {passed}/{applies}")

        fully_passed = 0
        errors = 0
        for r in records:
            if "error" in r:
                errors = errors + 1
            elif len(r["failed"]) == 0:
                fully_passed = fully_passed + 1
        print(f"Cases fully passed: {fully_passed}/{len(cases)}   errors: {errors}")
        print(f"Cost: ${total_cost:.4f}")

        with out_file.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"Saved -> {out_file}\n")
