"""Re-judge the SAME saved answers with a chosen judge prompt (Phase 2, step 2e).

No new tutor answers are generated: the answers come from one frozen RAG report,
so any change in the verdicts comes only from the judge (its prompt, or its own randomness).

Each run writes a small report that evals/judge_agreement.py can read.
Run from the repo root:
    python -m evals.rejudge --prompt v1 --runs 3
    python -m evals.rejudge --prompt v2 --runs 3
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from evals.run_evals import DATASET, JUDGE_PROMPTS, judge, load_cases

ANSWERS = Path(__file__).parent / "reports" / "rag_session01_2026-11-21_191338.jsonl"
REPORTS_DIR = Path(__file__).parent / "reports"
MAX_TRIES = 2       # retry once if the judge returns nothing or the wrong number of verdicts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", choices=list(JUDGE_PROMPTS), required=True)
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()
    prompt_template = JUDGE_PROMPTS[args.prompt]

    # 1. Key concepts come from the dataset (the source of truth), keyed by question id
    cases_by_id = {}
    for case in load_cases(DATASET):
        cases_by_id[case["id"]] = case

    # 2. The frozen answers
    answers = []
    with ANSWERS.open(encoding="utf-8") as f:
        for line in f:
            answers.append(json.loads(line))

    # Build all file names BEFORE any paid call (lesson from phase 1)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    REPORTS_DIR.mkdir(exist_ok=True)

    for run in range(1, args.runs + 1):
        out_file = REPORTS_DIR / f"rejudge_{args.prompt}_{stamp}_run{run}.jsonl"
        records = []
        failed = 0

        for record in answers:
            case = cases_by_id[record["id"]]

            # 3. Judge it, retrying once if the output is unusable
            verdict = None
            for attempt in range(MAX_TRIES):
                result = judge(case, record["answer"], prompt_template=prompt_template)
                if result is not None and len(result.verdicts) == len(case["key_concepts"]):
                    verdict = result
                    break

            if verdict is None:
                failed = failed + 1
                print(f"run {run} {record['id']}: FAILED (no usable verdict after {MAX_TRIES} tries)")
                continue

            print(f"run {run} {record['id']}: done")
            verdict_list = []
            for v in verdict.verdicts:
                verdict_list.append({"concept": v.concept, "covered": v.covered, "reason": v.reason})
            records.append({"id": record["id"], "verdicts": verdict_list})

        # 4. Save this run
        with out_file.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"run {run}: judged {len(records)}/{len(answers)} answers, failed {failed} -> {out_file}")
