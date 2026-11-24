"""Does the RAG tutor say "not in the course" at the right times? (Phase 3, step 3a)

Dataset: evals/datasets/abstention_v1.jsonl
  expected = "abstain"  (off_topic, near_miss)  -> in_course should be False
  expected = "answer"   (in_course)             -> in_course should be True

No judge: the tutor's own in_course flag is compared with "expected", so scoring is plain counting.
Extra free check: an abstention should have zero citations.

Run from the repo root:
    python -m evals.run_abstention_eval --runs 3
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from evals.run_evals import load_cases
from rag.answer import answer
from rag.embeddings import load_model

DATASET = Path(__file__).parent / "datasets" / "abstention_v1.jsonl"
REPORTS_DIR = Path(__file__).parent / "reports"


def outcome(expected: str, in_course: bool) -> str:
    """Name the result of one question: correct, false_answer or false_refusal."""
    if expected == "abstain" and not in_course:
        return "correct"
    if expected == "answer" and in_course:
        return "correct"
    if expected == "abstain" and in_course:
        return "false_answer"       # answered something it should have refused: the dangerous mistake
    return "false_refusal"          # refused something the course covers: the unhelpful mistake


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()

    cases = load_cases(DATASET)
    print(f"Loaded {len(cases)} cases. Loading BGE-M3 (slow, once)...")
    model = load_model()

    # Build file names BEFORE any paid call
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    REPORTS_DIR.mkdir(exist_ok=True)

    for run in range(1, args.runs + 1):
        out_file = REPORTS_DIR / f"abstention_{stamp}_run{run}.jsonl"
        records = []
        total_cost = 0.0

        for case in cases:
            # 1. Ask the RAG tutor (search -> Claude)
            try:
                rag_result = answer(case["question"], model=model)
            except ValueError as error:
                # answer() raises if Claude returns no structured answer; count it, don't crash the run
                print(f"run {run} {case['id']}: ERROR {error}")
                records.append({"id": case["id"], "type": case["type"], "expected": case["expected"],
                                "outcome": "error"})
                continue

            grounded = rag_result.answer
            total_cost = total_cost + rag_result.cost_usd

            # 2. Score it
            result = outcome(case["expected"], grounded.in_course)
            abstained_with_citations = (not grounded.in_course) and len(grounded.citations) > 0

            # Top search score: how close the best chunk was (maybe useful later as a "no good match" signal)
            top_score = None
            if len(rag_result.chunks) > 0:
                top_score = round(rag_result.chunks[0]["score"], 3)

            print(f"run {run} {case['id']} [{case['type']}]: in_course={grounded.in_course} -> {result}")

            records.append({
                "id": case["id"],
                "type": case["type"],
                "expected": case["expected"],
                "in_course": grounded.in_course,
                "outcome": result,
                "abstained_with_citations": abstained_with_citations,
                "citations": len(grounded.citations),
                "top_score": top_score,
                "answer": grounded.answer,
                "cost_usd": rag_result.cost_usd,
            })

        # 3. Summary per type, so near-miss and off-topic can be compared
        print(f"\n--- Run {run} summary ---")
        for case_type in ["off_topic", "near_miss", "in_course"]:
            typed = []
            for r in records:
                if r["type"] == case_type:
                    typed.append(r)
            correct = 0
            for r in typed:
                if r["outcome"] == "correct":
                    correct = correct + 1
            print(f"{case_type:<10} correct {correct}/{len(typed)}")

        false_answers = 0
        false_refusals = 0
        errors = 0
        bad_citations = 0
        for r in records:
            if r["outcome"] == "false_answer":
                false_answers = false_answers + 1
            if r["outcome"] == "false_refusal":
                false_refusals = false_refusals + 1
            if r["outcome"] == "error":
                errors = errors + 1
            if r.get("abstained_with_citations"):
                bad_citations = bad_citations + 1

        print(f"False answers (should have abstained): {false_answers}")
        print(f"False refusals (should have answered): {false_refusals}")
        print(f"Abstained but still cited:            {bad_citations}")
        print(f"Errors:                                {errors}")
        print(f"Cost: ${total_cost:.4f}")

        # 4. Save (evals/reports/ is git-ignored)
        with out_file.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"Saved -> {out_file}\n")
