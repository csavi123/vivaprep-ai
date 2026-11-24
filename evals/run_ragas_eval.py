"""Ragas cross-check (Phase 4, step 4a-3): faithfulness + context recall on the 25 frozen RAG answers,
with Claude Haiku as the judge. Each row is saved next to our own metrics for the comparison in 4a-4.

- Answers are FROZEN: read from the Phase 1 report, no new answers are generated.
- Contexts are REBUILT: search is deterministic, so the same question returns the same 5 chunks.
- Reference = expected_answer from session01.jsonl (needed by context recall).

Run from the repo root:
    python -m evals.run_ragas_eval
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from ragas.llms import llm_factory
from ragas.metrics.collections import ContextRecall, Faithfulness

from evals.run_evals import load_cases
from rag.embeddings import load_model
from rag.search import search

load_dotenv()                                         # ANTHROPIC_API_KEY, DATABASE_URL

REPORT = Path(__file__).parent / "reports" / "rag_session01_2026-11-21_191338.jsonl"
DATASET = Path(__file__).parent / "datasets" / "session01.jsonl"
REPORTS_DIR = Path(__file__).parent / "reports"
JUDGE_MODEL = "claude-haiku-5-5"


def mean(values: list[float]) -> float | None:
    """Average of a list, or None when the list is empty."""
    if len(values) == 0:
        return None
    return sum(values) / len(values)


def summarise(records: list[dict], label: str) -> None:
    """Print mean faithfulness, context recall and our own coverage for one group of rows."""
    faithfulness = []
    recall = []
    coverage = []
    for r in records:
        if "error" in r:
            continue
        faithfulness.append(r["faithfulness"])
        recall.append(r["context_recall"])
        coverage.append(r["coverage"])
    if len(faithfulness) == 0:
        print(f"{label:<22} no rows")
        return
    print(f"{label:<22} n={len(faithfulness):<3} faithfulness {mean(faithfulness):.2f}   "
          f"context recall {mean(recall):.2f}   our coverage {mean(coverage):.2f}")


async def main() -> None:
    # async def: this function can pause at each "await" while Claude answers.
    # Everything runs inside ONE event loop, so the async Claude client stays valid for all 25 cases.

    # Reference answers, looked up by id
    expected_by_id = {}
    for case in load_cases(DATASET):
        expected_by_id[case["id"]] = case["expected_answer"]

    # Frozen answers from the Phase 1 report
    rows = []
    with REPORT.open(encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    print(f"Loaded {len(rows)} frozen answers from {REPORT.name}")

    # One judge, two metrics. BGE-M3 loaded once (slow) and passed to every search
    client = AsyncAnthropic()
    llm = llm_factory(JUDGE_MODEL, provider="anthropic", client=client, max_tokens=4096)
    faithfulness_metric = Faithfulness(llm=llm)
    recall_metric = ContextRecall(llm=llm)
    model = load_model()

    records = []
    for row in rows:
        # 1. Rebuild the contexts and check they match what Claude saw on 21 Nov
        chunks = search(row["question"], k=5, model=model)
        contexts = []
        sessions = []
        for chunk in chunks:
            contexts.append(chunk["text"])
            sessions.append(chunk["session"])
        contexts_changed = sessions != row["retrieved_sessions"]

        try:
            # 2. await: wait for Claude's verdict here (each metric makes its own judge calls)
            faithfulness = await faithfulness_metric.ascore(
                user_input=row["question"],
                response=row["answer"],
                retrieved_contexts=contexts,
            )
            recall = await recall_metric.ascore(
                user_input=row["question"],
                retrieved_contexts=contexts,
                reference=expected_by_id[row["id"]],
            )
        except Exception as error:
            # One failed judge call shouldn't stop the run; record it and move on
            print(f"{row['id']}: ERROR {type(error).__name__}: {error}")
            records.append({"id": row["id"], "error": str(error)})
            continue

        warning = "   (contexts changed!)" if contexts_changed else ""
        print(f"{row['id']}: faithfulness {faithfulness.value:.2f}  recall {recall.value:.2f}  | "
              f"our coverage {row['score']:.2f}  retrieval_hit {row['retrieval_hit']}{warning}")

        # 3. Ragas scores next to our own metrics, for the comparison in 4a-4
        records.append({
            "id": row["id"],
            "faithfulness": faithfulness.value,
            "context_recall": recall.value,
            "coverage": row["score"],
            "retrieval_hit": row["retrieval_hit"],
            "quotes_found": row["quotes_found"],
            "citations": row["citations"],
            "uncited": row["uncited"],
            "retrieved_sessions": sessions,
            "contexts_changed": contexts_changed,
        })

    # Summary: overall, then split by retrieval hit / miss (the Phase 1 view)
    hits = []
    misses = []
    for r in records:
        if "error" in r:
            continue
        if r["retrieval_hit"]:
            hits.append(r)
        else:
            misses.append(r)
    errors = len(records) - len(hits) - len(misses)

    print("\n--- Summary ---")
    summarise(records, "all")
    summarise(hits, "retrieval hit")
    summarise(misses, "retrieval miss")
    print(f"errors: {errors}")
    print("Cost: not logged by Ragas, check the Anthropic console")

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_file = REPORTS_DIR / f"ragas_{stamp}.jsonl"
    with out_file.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Saved -> {out_file}")


if __name__ == "__main__":
    asyncio.run(main())     # start the event loop once, run main() to the end, then close it
