"""Score search() on the 46 eval questions: recall@1 and recall@5 (M4 step 6).

Run from the repo root:
    python -m evals.run_retrieval_eval
"""

import json

from datetime import date
from pathlib import Path
from evals.build_retrieval_set import OUT_FILE as EVAL_FILE   # evals/datasets/retrieval_v1.jsonl
from rag.embeddings import load_model
from rag.search import search

K = 5   # how many results to look at
REPORTS_DIR = Path(__file__).parent/ "reports"


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
    details = []

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

        # Where did the right session FIRST appear? 1 to 5, or None if not in the top 5
        rank = None
        for position, session in enumerate(sessions, start=1):
            if session == q["session"]:
                rank = position
                break           # found it; stop looking

        # What search returned, in readable form: "s05 | Prompting > 05 The context budget > ..."
        top5 = []
        for result in results:
            top5.append(f"s{result['session']:02d} | {result['heading_path']}")

        # Save everything about this question, for error analysis
        details.append({
            "id": q["id"],
            "query": q["query"],
            "expected": q["session"],
            "rank": rank,
            "top5": top5,
        })

    total = len(questions)
    print(f"recall@1: {hits_at_1}/{total} = {hits_at_1 / total:.0%}")
    print(f"recall@{K}: {hits_at_5}/{total} = {hits_at_5 / total:.0%}")

    print(f"\n{len(misses)} misses (right session not in the top {K}):")
    for miss in misses:
        print(f"  {miss['id']}: expected s{miss['expected']}, got {miss['got']}")
        print(f"     {miss['query']}")

    # Every question where the right session was NOT #1 (these are what we analyse)
    not_first = []
    for d in details:
        if d["rank"] != 1:
            not_first.append(d)

    print(f"\n{len(not_first)} questions where the right session was NOT ranked #1:")
    for d in not_first:
        found = f"rank {d['rank']}" if d["rank"] else "NOT in top 5"
        print(f"\n  {d['id']} | expected s{d['expected']:02d} | {found}")
        print(f"  Q: {d['query']}")
        for position, line in enumerate(d["top5"], start=1):
            print(f"     {position}. {line}")

    # Save all 46 to a file you can read in VS Code (evals/reports/ is git-ignored: course text)
    REPORTS_DIR.mkdir(exist_ok=True)
    report_file = REPORTS_DIR / f"retrieval_v1_{date.today()}.jsonl"
    with report_file.open("w", encoding="utf-8") as f:
        for d in details:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"\nSaved {len(details)} results -> {report_file}")


if __name__ == "__main__":
    main()
