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
