""" It reads the In short questions from the course files and writes then as eval set.
Run from the repo root:  python evals/build_retrieval_set.py
"""

import json
from pathlib import Path
import frontmatter
import argparse
import sys

DATA_DIR = Path(__file__).parent.parent / "data" / "raw" / "tailabs"
OUT_FILE = Path(__file__).parent.parent / "evals" / "datasets" / "retrieval_v1.jsonl"


#Exclude the in short questions from respective modules as those are very generic questions
EXCLUDE = {"s15-q1", "s15-q2", "s15-q3", "s16-q1","s16-q2","s16-q3", "s17-q1","s17-q2","s17-q3"}

def in_short_questions(text: str) -> list[str]:
    """Return the bullet lines under ## In short, without -"""
    questions = []
    inside = False
    for line in text.splitlines():
        if line == "## In short":
            inside = True
        elif line.startswith("## "):
            break
        elif inside and line.startswith("- "):
            questions.append(line[2:])
    return questions

def build_records() -> list[dict]:
    records = []
    for path in sorted(DATA_DIR.glob("s*.md")):
        post = frontmatter.load(path)
        session = post["session"]
        for i, question in enumerate(in_short_questions(post.content), start=1):
            qid = f"s{session:02d}-q{i}"
            if qid in EXCLUDE:
                continue
            records.append({
                "id": qid,
                "query": question,
                "session": session,
                "subtopics": [],      # filled in by hand later, as you study each module
                "source": "in_short",
            })
    return records


def main() -> None:
    parser = argparse.ArgumentParser() # This creates a reader for command line
    parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    args = parser.parse_args()  #Reads what si typed

    if OUT_FILE.exists() and not args.force:
        sys.exit(f"{OUT_FILE} already exists (it may have hand-added labels). Use --force to overwrite.")

    records = build_records()
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUT_FILE.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) +"\n")  #write the record as ONE line of JSON + "\n"

    sessions = {r["session"] for r in records}
    print(f"Wrote {len(records)} questions from {len(sessions)} sessions -> {OUT_FILE}")
    #  print "Wrote N questions from M sessions -> OUT_FILE" (N = len(records), M = len(sessions))

if __name__=="__main__":
    main()