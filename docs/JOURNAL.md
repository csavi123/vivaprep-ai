# Journal

## 2026-11-09 · M0 Setup

**Built**
- Git repo on `main`, `.gitignore` (`.env`, `.venv/`)
- venv with Python 3.12.10; `requirements.txt` from `pip freeze` (17 pinned packages)
- `.env` with `ANTHROPIC_API_KEY` (checked it is ignored with `git check-ignore -v`)
- `hello_claude.py`: one call to Claude Haiku that prints the reply text, input/output tokens and cost

**Learned**
- `python3 -m venv .venv` copies *that* Python; `activate` puts `.venv/bin` first on PATH (`which python` proves it)
- Install name ≠ import name: `pip install python-dotenv` → `import dotenv`
- `client.messages.create` wraps an HTTP POST to `/v1/messages`; required params are `model`, `max_tokens`, `messages`
- `messages` is a list of `{role, content}` dicts; the API has no memory, so you resend the whole conversation
- The response is an object: `message.content[-1].text` for the text, `message.usage.input_tokens` / `output_tokens` for usage
- Cost = tokens / 1,000,000 × price per MTok, for input and output separately
- Reading tracebacks: last line first, then the frame in *my* file, and skip anything under `.venv/`
- 3 kinds of error: `SyntaxError` (can't parse), `AttributeError` (no such field), `AuthenticationError 401` (server rejected the key)

**Confused me**
- `message` (the response) vs `messages=` (the conversation I send)
- `completion_tokens` is OpenAI's name; Anthropic uses `output_tokens`
- Batch API price vs standard price on the pricing page
- `100000` vs `1_000_000`: use underscores in big numbers

**Numbers**
- First call: 14 input + 13 output tokens = **$0.0000079**
- Haiku 5.5 (prompts ≤100K tokens): $0.10 input / $0.50 output per MTok

**Next**
- M1: `llm.py` wrapper with retries, token counting and cost logging; structured `TutorAnswer` with Pydantic
- Open question: which errors should be retried? (401 bad key vs 429 rate limit)
- Before M3: add `data/raw/`, `data/processed/`, `auth.json` to `.gitignore`

## 2026-11-10 · M1 LLM basics

**Built**
- `schemas.py`: `TutorAnswer` (answer, key_points) and `LLMResult` (text, tokens, cost, latency, stop_reason, parsed)
- `llm.py`: `ask()` wraps every model call with hand-written retries (backoff + jitter), latency timing, cost calculation and JSONL logging; `ask_tutor()` returns a validated `TutorAnswer` via `client.messages.parse(output_format=...)`
- `tests/test_llm.py`: 3 tests (normal call, retry after a fake 429, structured output); `pyproject.toml` so pytest can import from the project root

**Learned**
- Pydantic: coercion (`"30"` → `30`), `ValidationError` types (`missing`, `list_type`, `int_parsing`), `model_validate` for outside data
- Classes describe things (data shapes); functions do things; add a class with methods only when state must persist
- `stop_reason == "max_tokens"` means a cut-off answer, with no error raised
- HTTP codes: 4xx = my fault (fix the request), 5xx = server's fault (retry); 429 is the retryable exception; 401 = who are you, 403 = not allowed
- `try` / `except` / `raise`; catch named errors only, so a typo (`NameError`) is never retried
- Testing: monkeypatch + fakes to force a 429; break a test on purpose to prove it can fail; a nested `def test_` is silently skipped
- `.gitignore` doesn't affect files already tracked: use `git rm --cached`
- `parse` is about the *output*: the SDK sends a JSON schema, then parses Claude's JSON text into my Pydantic object

**Confused me**
- Which names come from Anthropic vs from my code (`max_tokens=max_tokens`, `output_format=output_format`)
- `LLMResult.text` vs `TutorAnswer.answer` (envelope vs form)
- Why pytest couldn't find `llm.py` (import search path)
- `4.1e-06` looked wrong but is just how Python prints small floats

**Numbers**
- "Say hi": 16 in / 5 out tokens, $0.0000041, 0.89s
- `ask_tutor("What is RAG?")`: 288 in / 407 out tokens, $0.00023, 3.8s (the schema adds input tokens)
- Same question twice → 5 vs 8 key points (non-deterministic)
- `pytest`: 3 passed in ~4s (all real API calls)

**Deferred from M1**
- Temperature experiment: do in M2 (evals need repeatable answers)
- Async: do when M2's 25 questions make sequential calls slow
- Move to `src/compass/` + `pip install -e .`: at the start of M2

**Next**
- M2: eval harness v0, 25 questions with expected answers from one TAI Labs session; `run_evals.py` prints a score
- Fix the top items in `docs/LIMITS.md` (silent `None` in `ask_tutor`)

## 2026-11-11 · M2 Eval harness v0

**How the LLM judge works**

```
1. question       ──► the student (ask_tutor) writes an answer
2. question + answer + key concepts ──► judge()
3. judge() doesn't mark it itself: it ASKS CLAUDE to mark it, and Claude returns ✅/❌ + a reason per concept
4. your code counts the ✅s ──► score (e.g. 2/3 = 0.67)
```

So judge() is the messenger. It packages up the question, the answer and the checklist, hands them to Claude (the real marker), and brings back the marked sheet. The counting happens afterwards, in your main loop.

## 2026-11-11 · M3 Ingestion

**Built**
- `ingest/login.py`: log in by hand once, save the browser session to `auth.json` (git-ignored, `chmod 600`)
- `ingest/inspect_page.py`: read-only helper that saves one page's HTML + screenshot, used to find selectors
- `ingest/build_manifest.py`: reads the course page → `_manifest.json` with sessions 1–17; fails if any are missing
- `ingest/tailabs.py`: per session: load the page, click "Expand all", wait until every subtopic has loaded, save a
  content-only HTML snapshot, convert it to Markdown with 7-field front matter. 2s between pages, skips files already
  saved; options `--only`, `--force`, `--from-html`
- `tests/test_ingest_tailabs.py`: 6 tests (86 checks) comparing each `.md` with its snapshot; skipped when there's no local data

**Learned**
- Inspect before scraping: collapsed subtopics had 0 characters in the HTML, because the site loads them on click
- Clicking isn't enough: wait for a condition (loaded subtopics = subtopic buttons), or partial pages get saved silently
- `storage_state` saves cookies, so the script never sees my password; the session expires eventually → re-run `login.py`
- Markdown keeps the structure (headings for the M4 chunker) and drops the markup (fewer tokens than HTML)
- Keep the raw source and make conversion a rebuildable step: 2 bugs fixed from snapshots with 0 page loads
- A code block that contains ``` needs a longer fence (````), or it closes early and its headings leak out
- pytest: `parametrize` = one test per session; `pytestmark = skipif` for local-only data; helpers don't start with `test_`
- A passing test proves nothing until I've made it fail
- Ingestion is a fidelity problem (pass/fail checks); "is it good for RAG?" is a retrieval-eval question (M4/M5)
- Code assertions first, LLM judge second: these tests are free, deterministic and take 1.5s

**Confused me**
- `__DATA_DIR__` vs `DATA_DIR`: double-underscore names belong to Python (`__file__`), not to me; filenames need quotes
- Absolute vs relative paths, and why `Path(__file__).parent.parent` works from anywhere
- `glob` returns a generator, so wrap it in `list()` to check whether anything was found
- Why the tests keep passing after the website changes (they compare against snapshots, not the live site)
- How a saved login can still "expire"

**Numbers**
- 17 sessions, 124 subtopics, 187 code blocks, 7 tables; 1.38M characters ≈ 344K tokens
- Fetch: 16 sessions, 0 failures; session 1 snapshot 91 KB vs 70 KB as Markdown
- Bugs caught by checks: 1 nested fence (s03), 187 `pythonCopy` header lines → both fixed from snapshots
- Markdown vs snapshot word count per subtopic: 0% to +0.54% → test tolerance 99–102%
- `pytest tests/test_ingest_tailabs.py`: 86 passed in 1.55s, 0 API calls

**Still open in M3**
- Spot-check s04 and s09 against the website
- Break-it experiments A–F
- Not checked: whether lessons contain images or diagrams (text inside images would be lost)

**Next**
- M4: chunking + Voyage embeddings + pgvector. The chunker must ignore `#` lines inside code blocks; keep "Check yourself"
  questions out of the index (leakage) and use them as a labelled retrieval eval set
- Still pending from M2: full 25-question baseline (run 2–3 times and record the range); temperature experiment

## 2026-11-12 · M4 eval set + chunker

**Built**
- Docker Postgres 17 + pgvector 0.8.7 on `127.0.0.1:5433` (D014)
- `evals/build_retrieval_set.py` → `retrieval_v1.jsonl`: 46 "In short" questions from s01–s14, labelled by session;
  refuses to overwrite without `--force`. `tests/test_retrieval_set.py` (4 tests)
- `rag/chunker.py`: split at `##`/`###` outside code, drop eval text, pack same-subtopic sections up to 800 tokens
  (measured on the rendered text via `render()`), heading path in every chunk; `--write` → `data/processed/chunks.jsonl`
- `tests/test_chunker.py`: 12 tests (rules on a made-up lesson + checks on the real chunks) (D017)

**Learned**
- Measure before choosing a chunk size: subtopics median ~2,400 tokens (too big), `###` sections median ~360 (97% under 800)
- Median vs average: the median isn't pulled up by a few huge values
- `break` vs `continue`; `[2:]` slicing; `json.dumps`/`json.loads`; `if __name__ == "__main__"`; `python -m` vs `python file.py`
- Eval data must stay out of the index (leakage); a leakage test can also catch false alarms (lesson text quoting a question)
- One function that builds the text (`render`) for both the size check and the output, so they can't disagree

**Confused me**
- `sys.argv`, list vs single item; empty `else:`; indentation of checks inside vs after a loop
- Why "Answering the question" quotes the eval question, and whether that counts as leakage (decided: it's content)

**Numbers**
- 17 files → 124 subtopics → 831 sections → 591 chunks, median 557 tokens, 30 over 800 (all single sections)
- Count checks caught 2 bugs: 714 vs 831 sections (intros never appended); 89 vs 30 chunks over 800 (headings not counted)

## 2026-11-13 · M4 table, embeddings, search, first recall

**Built**
- `rag/schema.sql`: `chunks` table, `vector(1024)`, HNSW cosine index
- Switched embeddings from Voyage to local **BGE-M3** (D018): `rag/embeddings.py` (pinned revision, one place for
  documents and queries), `rag/embed_store.py` (token-limit check, batches of 16, upsert by `chunk_id`)
- `rag/search.py`: `search(question, k)`: embed query, `ORDER BY embedding <=> %s LIMIT k`, score = 1 − distance
- `evals/run_retrieval_eval.py`: session-level recall@1 and recall@5 on the 46 questions, prints misses

**Learned**
- Schema vs data: `CREATE TABLE` builds the shelf once; `INSERT … ON CONFLICT DO UPDATE` (upsert) fills it, safely re-runnable
- Parameterised SQL (`%s`), never f-strings; `EXCLUDED` = the row I tried to insert
- Batching (fewer round trips, within limits, commit per batch)
- Rate limits are a real constraint: Voyage free tier = 3 RPM / 10K TPM
- Choosing a model from my data: context length vs chunk sizes (bge-small would truncate half), dimensions vs schema
- sentence-transformers truncates silently → check tokens with the model's own tokenizer
- Cosine ignores vector length; normalising makes every distance agree
- A model is an artifact, not a pip package: pin its revision; deployment needs ~2–3 GB RAM for it
- Offline indexing vs online serving; retrieval is the "R" in RAG and is evaluated on its own first

**Confused me**
- `ModuleNotFoundError: No module named 'rag'` → run with `python -m rag.embed_store`
- Why `embeddings.py` was needed now but not with Voyage (local model = my code does the server's work)
- The search output format (heading path repeated in the preview, `\n`)

**Numbers**
- Embedding: 591 rows, 1024 dims, unit length, 317,375 real tokens (chars/4 estimate 330K, +4%), longest chunk 1,233 tokens, 5.3 min, $0
- **Baseline retrieval (800-cap chunks, BGE-M3): recall@1 = 36/46 = 78%, recall@5 = 45/46 = 98%**
- Only miss: s01-q1 (tokens + cost + context window), got sessions [5, 4, 5, 5, 5]: a multi-part question taught across
  3 sessions, so more a single-label limit than a retrieval failure

**Next**
- Print and read the 10 rank-1 misses; decide how to handle multi-session questions like s01-q1
- Compare 800-cap vs one chunk per subtopic (`max_tokens=None`) on the same 46 questions, then D019
- M4 explain-back and close; then M5 (answers with citations)

## 2026-11-14 · M4 close: error analysis + baseline decision

**Built**
- `run_retrieval_eval.py` now records the rank of the first correct session and the top-5 heading paths, prints every
  question not ranked #1, and saves a per-question report to `evals/reports/` (git-ignored: course text)
- Local error-analysis note for the 10 non-#1 questions; D019 (accept the baseline, fix the eval before the search)

**Learned**
- recall@k is a metric I computed by hand (count hits, divide by 46), not a library function; with one label per
  question it's the same as hit rate@k
- The score decides the order inside search; the eval only reads the order and the sessions, against the answer key
- At serving time there's no answer key: the same search ranks chunks and Claude writes one answer from them
- Error analysis before fixing: most "misses" were relevant results from another session that revisits the topic,
  so the label was too strict, not the search
- The per-question report is a baseline to diff later runs against (catches regressions an average hides)
- Course content must not be published: the walkthrough page with real data stayed a local file

**Confused me**
- Where the similarity comparison happens (SQL `<=>` in `search.py`) vs where recall is computed (the eval)
- Why save a report of all 46 when only 10 need reading (answer: it's for comparing future runs)
- Session-level eval being lenient: any chunk from the right session counts

**Numbers**
- Ranks of the 46: rank 1 × 36, rank 2 × 6, rank 4 × 1, rank 5 × 2, not in top 5 × 1
- Of the 10 not ranked #1: 7 overlap (s15 took #1 three times), 3 ordering errors (s03-q1, s06-q1, s09-q1)

**Still open**
- Explain-back questions 2–4 (why this approach, how I know it works, limits): answer before interviews
- Subtopic labels with multiple correct answers (M5); reranker, 800 vs `None`, Voyage vs BGE-M3 (M7)

**Next**
- M5: RAG answers with citations (search → prompt with numbered chunks → Claude via `llm.py` → citation + answer evals)

## 2026-11-14 · M5 slice (answers with citations) + M6 app (VivaPrep AI)

**Built**
- `schemas.py`: `Citation` (block number + exact quote), `GroundedAnswer` (answer, citations, `in_course`),
  `RagResult` (Claude's answer + retrieved chunks + invalid citations + cost/latency; built by my code, not sent to Claude)
- `rag/answer.py`: `format_context()` (numbered `[n] Session X` blocks), `PROMPT_TEMPLATE` (rules → context → question),
  `answer()` (search → prompt → `llm.ask(output_format=GroundedAnswer)` → `None` check → citation validation)
- `app/app.py` + `app/styles.py` + `.streamlit/config.toml`: Streamlit app "VivaPrep AI": question form,
  pipeline strip (retrieve → generate → cite), answer card, retrieval panel (all 5 chunks with similarity bars,
  cited ones highlighted with quotes, others dimmed), dark theme with design tokens in one file
- `docs/LIMITS.md`: ingestion drops spaces next to some inline elements ("aretwo")

**Learned**
- Grounding = answer only from the given context; abstention = say "not in the course" instead of guessing
- Cite block numbers, not chunk IDs: short ints are easy for the model to copy and easy for my code to validate
- Keep the model's contract (`GroundedAnswer`) separate from my code's result (`RagResult`), or Claude would be
  asked to invent cost and chunk data
- Python `#` comments never reach Claude; `Field(description=...)` does (it goes into the JSON schema)
- At query time the question must be embedded with the same model as the chunks, so whoever runs search needs
  BGE-M3 in memory or an embedding API (this drives the deploy choice)
- Streamlit reruns the whole script on every interaction: `@st.cache_resource` for the model, `st.form` so
  Claude is only called on Ask
- Only `answer()` costs money (Claude); search is local and free

**Confused me**
- Whether FastAPI was needed already (answer: not until a second client needs the RAG over HTTP)
- Where the model loads (the Streamlit server process, not the browser)

**Numbers**
- Smoke test: "What is a token?" → `in_course=True`, 2 citations to s01-c006, quotes match the chunk;
  "How do I bake sourdough bread?" → `in_course=False`, no citations
- 3,155–4,211 input tokens per question (5 chunks); ~$0.0004–0.0005 per question; Claude latency 2.0–2.5 s
- Haiku prices in `llm.py` ($0.10 / $0.50 per MTok) not yet checked against Anthropic's pricing page

**Still open**
- M5 Steps 4–6: unit tests for `format_context` / citation validation, RAG eval (recall@k, citation accuracy,
  closed-book vs open-book, abstention), D-entry with the baseline
- New UI (pipeline + retrieval panel) not yet checked on screen; Inter font not loading
- Quotes aren't verified against the chunk text; `in_course=False` with citations isn't flagged

**Next**
- Check the new UI, record a 20–30 s demo, LinkedIn post (only measured numbers)
- FastAPI `POST /ask` → Supabase (re-run retrieval eval) → deploy (private HF Space, spend limit)
- Back to the M5 eval
