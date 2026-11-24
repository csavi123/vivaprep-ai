"""Ragas smoke test (Phase 4, step 4a-2): score ONE frozen RAG answer for faithfulness,
with Claude Haiku as the judge. Proves the setup works before scoring all 25.

Run from the repo root:
    python -m evals.ragas_smoke
"""

import json
from pathlib import Path

from anthropic import AsyncAnthropic                  # async client: Ragas calls the judge with await
from dotenv import load_dotenv
from ragas.llms import llm_factory                    # wraps our client so Ragas can use it as a judge
from ragas.metrics.collections import Faithfulness    # the 0.4 metric (old tutorials import from ragas.metrics)

from rag.search import search

load_dotenv()                                         # ANTHROPIC_API_KEY, DATABASE_URL

REPORT = Path(__file__).parent / "reports" / "rag_session01_2026-11-21_191338.jsonl"
CASE_ID = "s1-01"
JUDGE_MODEL = "claude-haiku-5-5"

# 1. Read the frozen answer from the Phase 1 report (we score old answers; no new answer is generated)
row = None
with REPORT.open(encoding="utf-8") as f:
    for line in f:
        record = json.loads(line)
        if record["id"] == CASE_ID:
            row = record
if row is None:
    raise SystemExit(f"{CASE_ID} not found in {REPORT}")

# 2. Rebuild the contexts: search is deterministic, so the same question returns the same 5 chunks
chunks = search(row["question"], k=5)
contexts = []
sessions = []
for chunk in chunks:
    contexts.append(chunk["text"])
    sessions.append(chunk["session"])

# Sanity check: same sessions as on 21 Nov? If not, the database changed and the score would be unfair
print(f"Sessions now: {sessions}   in report: {row['retrieved_sessions']}")

# 3. Claude as the judge. max_tokens: Claude requires it; claim lists can be long
client = AsyncAnthropic()
llm = llm_factory(JUDGE_MODEL, provider="anthropic", client=client, max_tokens=4096)
scorer = Faithfulness(llm=llm)

# 4. Score it
result = scorer.score(
    user_input=row["question"],
    response=row["answer"],
    retrieved_contexts=contexts,
)
print(f"\nQuestion: {row['question']}")
print(f"Answer:   {row['answer']}")
print(f"\nRagas faithfulness: {result.value}")
print(f"Your judge coverage (Phase 1): {row['score']}   quotes found: {row['quotes_found']}/{row['citations']}")
