"""Score search() on the 46 eval questions: recall@1 and recall@5 (M4 step 6).

Run from the repo root:
    python -m evals.run_retrieval_eval
"""

import json

from evals.build_retrieval_set import OUT_FILE as EVAL_FILE   # evals/datasets/retrieval_v1.jsonl
from rag.embeddings import load_model
from rag.search import search

K = 5   # how many results to look at


def load_questions() -> list[dict]:
    """Read retrieval_v1.jsonl: one question record per line."""
    questions = []
    for line in EVAL_FILE.read_text(encoding="utf-8").splitlines():
        questions.append(json.loads(line))
    return questions


def main() -> None:
    questions = load_questions()
    model = load_model()            # load once, reuse for all 46 questions

    hits_at_1 = 0
    hits_at_5 = 0
    misses = []

    for q in questions:
        results = search(q["query"], k=K, model=model)

        # The session of each result, in rank order, e.g. [1, 4, 1, 1, 5]
        sessions = []
        for result in results:
            sessions.append(result["session"])

        # Is the #1 result from the right session?  -> recall@1
        if sessions[0] == q["session"]:
            hits_at_1 = hits_at_1 + 1

        # Is the right session ANYWHERE in the top 5?  -> recall@5 (rank-1 hits count too)
        if q["session"] in sessions:
            hits_at_5 = hits_at_5 + 1
        else:
            misses.append({"id": q["id"], "query": q["query"], "expected": q["session"], "got": sessions})

    total = len(questions)
    print(f"recall@1: {hits_at_1}/{total} = {hits_at_1 / total:.0%}")
    print(f"recall@{K}: {hits_at_5}/{total} = {hits_at_5 / total:.0%}")

    print(f"\n{len(misses)} misses (right session not in the top {K}):")
    for miss in misses:
        print(f"  {miss['id']}: expected s{miss['expected']}, got {miss['got']}")
        print(f"     {miss['query']}")


if __name__ == "__main__":
    main()
