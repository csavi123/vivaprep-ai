# VivaPrep AI: a grounded tutor for my AI engineering study material

A RAG tutor over my AI engineering self-study material (17 sessions).
Ask a question and get an answer that quotes and cites the material; take a generated quiz;
or chat with a tutor agent that decides when to search.

Built by hand to learn AI engineering end to end: my own LLM wrapper, chunker, retrieval,
citations, agent tools and eval harness, with frameworks (Ragas, Langfuse) added only as cross-checks.

## What it does
- **Ask**: question → vector search (BGE-M3 + pgvector) → Claude Haiku answers with
  numbered citations and exact quotes, which are checked against the chunks.
- **Quiz**: MCQ, short-answer and viva questions generated from one session's chunks.
- **Tutor agent**: Google ADK agent with a `search_course` tool; it searches, scopes to a session,
  asks for clarification, or declines off-topic questions.
- **App**: Streamlit UI + FastAPI backend (token-protected), voice input via faster-whisper.

## Architecture
```
Streamlit UI ──HTTP──► FastAPI (/ask /quiz /chat /sessions /transcribe)
                          │
          ┌───────────────┼──────────────────┐
          ▼               ▼                  ▼
     rag/answer.py    rag/quiz.py    agents/vivaprep_tutor (ADK)
          │                                  │ search_course tool
          ▼                                  ▼
     rag/search.py ── BGE-M3 (local) ── Postgres + pgvector (Docker)
          │
          ▼
     llm.py ── Claude Haiku (retries, token + cost logging)
```

## Evaluation
| Layer | What is measured | Result |
|---|---|---|
| Retrieval | recall@1 / @5 on 46 questions | 78% / 98% (D019) |
| Answers, closed-book vs RAG | key-concept coverage, LLM judge, 3 runs | 0.79 vs 0.74, ranges overlap; RAG 0.90 on retrieval hits vs 0.24 on misses (D023) |
| Judge validation | judge vs 73 blind human labels | agreement ~0.93, Cohen's kappa ~0.79, 3% self-flips (D024) |
| Abstention | 20 off-topic / near-miss / in-course questions | 20/20 over 3 runs |
| Quiz | free structural checks on 20 generated questions | 20/20 |
| Agent trajectory | search rule, scope, real citations, bounded calls | 36/36 over 3 runs |
| Ragas cross-check | faithfulness / context recall, Claude as judge | recall 0.98 on hits vs 0.38 on misses; faithfulness 0.95 vs 0.80 |

**Main finding:** retrieval quality is the ceiling. When retrieval misses, coverage collapses
and the model starts filling gaps from its own knowledge.

## Run it locally
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # fill in ANTHROPIC_API_KEY, POSTGRES_PASSWORD, DATABASE_URL, API_TOKEN
docker compose up -d              # Postgres + pgvector on localhost:5433

# Terminal 1: API
uvicorn api.main:app --host 127.0.0.1 --port 8000
# Terminal 2: UI
python -m streamlit run app/app.py
```
The study material is not included in the repo; `ingest/` rebuilds it locally.

## Run the evals
```bash
python -m pytest -q                         # unit tests, free
python -m evals.run_retrieval_eval          # free (local embeddings)
python -m evals.run_rag_evals               # ~$0.02 per run
python -m evals.run_agent_eval --runs 3     # ~$0.04
python -m evals.run_ragas_eval              # ~$0.05–0.10
```

## Repo layout
```
llm.py, schemas.py   model wrapper, Pydantic schemas
ingest/              course pages → Markdown with front matter
rag/                 chunker, embeddings, pgvector search, answers, quizzes
agents/              ADK tutor agent and tools
api/, app/           FastAPI backend, Streamlit UI
evals/               eval scripts (datasets and reports stay local)
tests/               pytest, no API calls
docs/                DECISIONS.md (every design decision + evidence), JOURNAL.md, LIMITS.md
```

## Known limits
See [docs/LIMITS.md](docs/LIMITS.md). Main ones: answer eval sets cover session 1 only,
no minimum similarity threshold for retrieval, cost tracking is correct for Haiku only.
