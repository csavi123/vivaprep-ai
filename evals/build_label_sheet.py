"""Build a blind label sheet from one saved RAG report (Phase 2, step 2b).

One row per (question, key concept). The judge's verdict is NOT written,
so I label without being influenced. Run from the repo root:
    python -m evals.build_label_sheet
"""

import csv
import json
from pathlib import Path

REPORT = Path(__file__).parent / "reports" / "rag_session01_2026-11-21_191338.jsonl"
OUTPUT = Path(__file__).parent / "datasets" / "judge_labels_v1.csv"
COLUMNS = ["row_id", "id", "question", "answer", "concept", "human", "note"]


if __name__ == "__main__":
    # 1. Never overwrite a sheet I may already have labeled
    if OUTPUT.exists():
        raise SystemExit(f"{OUTPUT} already exists. Delete it by hand if you really want a new sheet.")

    # 2. Read the report: one JSON object per line
    records = []
    with REPORT.open(encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            records.append(record)

    # 3. Build one row per key concept
    rows = []
    for record in records:
        # enumerate gives the position (0, 1, 2...) AND the verdict
        for index, verdict in enumerate(record["verdicts"]):
            row = {
                "row_id": f"{record['id']}#{index}",
                "id": record["id"],
                "question": record["question"],
                "answer": record["answer"],
                "concept": verdict["concept"],
                # verdict["covered"] (the judge's mark) is left out on purpose: blind labeling
                "human": "",     # I fill this in: yes / no
                "note": "",      # optional: why, when unsure
            }
            rows.append(row)

    # 4. Write the CSV (newline="" stops the csv module adding blank lines between rows)
    with OUTPUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows -> {OUTPUT}")
