# Decisions

## D001 · Use Anthropic only, with Claude Haiku for development (2026-11-09)

**Decision:** Use only the Anthropic SDK for this project, with `claude-haiku-5-5` while developing. OpenAI is optional later.

**Alternatives:**
- Anthropic + OpenAI (the original plan for M0 and M12)
- A bigger Claude model (Sonnet) for development

**Evidence / reasons:**
- I have no OpenAI credits, and one provider is enough to learn the basics.
- Haiku is the cheapest model: $0.10 input / $0.50 output per MTok. The first call cost $0.0000079.

**Consequences:**
- Embeddings (M4) need a separate provider (Voyage), because Anthropic has no embeddings API.
- The M12 report becomes a model comparison (e.g. Haiku vs Sonnet); GPT is optional.

**Revisit at:** M4 (embeddings) and M12 (model comparison).

## D002 · Pin all dependencies with `pip freeze` (2026-11-09)

**Decision:** Generate `requirements.txt` with `pip freeze > requirements.txt` (every package, exact versions).

**Alternatives:**
- Hand-write only the top-level packages (`anthropic`, `python-dotenv`) with pinned versions. Easier to read, but dependencies can drift.
- A lock-file tool (`pip-tools`, `uv`) that keeps both a short list and a full pinned list.

**Tradeoff:** The venv can be rebuilt exactly, but the file mixes what I chose with what came along. I must re-run `pip freeze` after every `pip install`.

**Revisit at:** M13 (deploy), and consider `uv` / `pip-tools`.

## D003 · Write retries by hand instead of using the SDK's (2026-11-10)

**Decision:** Turn off the SDK's built-in retries (`anthropic.Anthropic(max_retries=0)`) and write my own retry loop in `ask()`.

**Alternatives:**
- Keep the SDK default (2 retries with backoff). It's well tested and reads the server's `retry-after` header.

**Evidence / reasons:**
- Learning: "build each concept by hand first." Now I know what the SDK does for me.
- Control: I choose exactly which errors are retried (`RETRYABLE_STATUS_CODES`) and can see each attempt.
- Testability: `test_ask_retries_after_429` fakes one 429 and asserts exactly 2 calls. I can only check that because I own the loop.
- `max_retries=0` is required: with both on, retries multiply (3 mine × 3 SDK = up to 9 requests per question).

**Limits:**
- My loop ignores the `retry-after` header, so on a 429 it may retry sooner than the server asked.

**Revisit at:** M13 (deploy). Consider honoring `retry-after`, or switching back to the SDK's retries.

## D004 · Retry only transient errors, with exponential backoff + jitter (2026-11-10)

**Decision:** Retry 429, 500/502/503/504, 529 and connection errors, up to `MAX_ATTEMPTS = 3`, waiting `BASE_DELAY_S * 2 ** (attempt - 1) + random.uniform(0, 1)` between attempts. Any other error is re-raised immediately.

**Alternatives:**
- Retry every error: pointless for 400/401, which won't fix themselves.
- Fixed delay: doesn't give an overloaded server more and more breathing room.
- Backoff without jitter: risks a thundering herd.

**Evidence / reasons:**
- 429 / 5xx / 529 / connection errors are *temporary*, so a retry can succeed. A 400 or 401 means my request or key is wrong.
- Exponential backoff (1s, 2s, …) gives a struggling server more and more time to recover.
- Jitter stops a "thundering herd": if 1,000 clients fail together and all wait exactly 1s, they all hit the server again together. Random jitter spreads them out.

**Tradeoff:** Retries add latency. 3 attempts caps the worst case at two sleeps (~1–2s, then ~2–3s) before raising.

## D005 · Log every model call to JSONL (2026-11-10)

**Decision:** Append one JSON record per successful call to `logs/llm_calls.jsonl` (timestamp, model, tokens, cost, latency, stop_reason). The `logs/` folder is not committed.

**Alternatives:**
- CSV: rigid columns, bad for nested fields.
- SQLite / Postgres: overkill for now.
- Langfuse tracing: planned for later (M12).

**Evidence / reasons:**
- Append-only (`"a"` mode): cheap, never rewrites the file, and a crash damages at most one line.
- Easy to analyse: `pd.read_json("logs/llm_calls.jsonl", lines=True)` gives a DataFrame of cost and latency.
- Same format as the eval datasets (`evals/datasets/*.jsonl`).

**Limits:**
- Only *successful* calls are logged, so failed attempts and retries leave no record.
- The file grows forever, and it isn't safe with several processes writing at once.

**Revisit at:** M12 (Langfuse), or sooner if I need to see failures.

## D006 · `ask_tutor()` reuses `ask()` instead of calling `parse` itself (2026-11-10)

**Decision:** `ask_tutor()` is a thin wrapper: `ask(question, output_format=TutorAnswer)` returns `result.parsed`. `ask()` is the only function that calls the model.

**Alternatives:**
- `ask_tutor()` calls `client.messages.parse` directly. Simpler at first, but it silently skips retries, cost and logging.

**Evidence / reasons:**
- One path for every call: reliability (retries) and observability (cost, latency, logs) apply to every call automatically.
- DRY: retry logic lives in one place, so a fix there helps every caller.
- Separation of concerns: `ask_tutor()` decides *what* to ask for (the schema); `ask()` handles *how* to call the model reliably.

**Tradeoffs / known bug:**
- `ask()` now always calls `parse`, even for plain text.
- `result.parsed` can be `None` (e.g. the model hits `max_tokens` mid-JSON). Then `ask_tutor()` returns `None` even though its type hint promises a `TutorAnswer`. **To fix:** check `stop_reason` / `parsed` and raise a clear error.

**Interview one-liner:** "I wrapped every model call in one function so reliability (retries with backoff and jitter on transient errors only) and observability (cost and latency logged to JSONL) are guaranteed everywhere. Feature functions like `ask_tutor()` only define the output schema."

## D007 · Ingest sessions 1–17, Content tab only (2026-11-11)

**Decision:** Scrape only the 17 "Learning" sessions, and only the Content tab ("In short" questions + all subtopics).

**Alternatives:**
- All 23 sessions (18–23 are outside the "Learning · Modules 1–17" section)
- Also the Assignments and Resources tabs

**Reasons:** The lessons are what the tutor needs to answer from. Assignments could feed quizzes later (M8); Resources are mostly external links. Adding a tab later is a small change to the scraper.

**Revisit at:** M8 (quiz generation), if assignments would help.

## D008 · Log in once by hand and reuse the saved session (2026-11-11)

**Decision:** `login.py` opens a visible browser, I log in by hand, and Playwright saves the session to `auth.json` (`storage_state`). Every other script loads that file.

**Alternatives:**
- Username and password in `.env`, with the script filling in the login form

**Reasons:** The password never appears in code or config. It works with any login flow (2FA, captchas). `auth.json` is git-ignored and `chmod 600`, because it's a live session token.

**Limits:** The session expires; the scraper detects the redirect to `/auth` and says to run `login.py` again.

## D009 · Store each session as Markdown with YAML front matter (2026-11-11)

**Decision:** One `.md` file per session: `# title`, `## In short`, one `## NN subtopic` per subtopic, lesson subheadings as `###`. Code blocks are fenced with their language (```` ```python ````); a block that contains ``` gets a longer fence (````).

**Alternatives:**
- HTML: keeps everything, but costs more tokens and buries the structure in tags
- PDF: loses headings, and text extraction is messy
- JSON: good for records, but hard to read, and the structure has to be designed

**Reasons:** The M4 chunker splits on headings, so they must survive as plain `#` lines. Markdown drops markup (session 1: 70 KB vs 91 KB for the content-only HTML), I can spot-check it by eye, and Claude reads it well. Language-tagged fences let the chunker find and handle code.

**Revisit at:** M4, if chunking needs a different structure.

## D010 · Click "Expand all" and wait until every subtopic has loaded (2026-11-11)

**Decision:** After the page loads, click "Expand all", then wait until the number of loaded subtopic articles equals the number of subtopic buttons (15s timeout), and only then copy the HTML.

**Alternatives:**
- Copy the page as loaded: saves 1 of 7 subtopics (the collapsed ones had 0 characters in the HTML)
- Click each subtopic one by one: 7+ clicks per page, more fragile
- Wait a fixed number of seconds: either slow or flaky

**Reasons:** The site loads subtopic text only when a section is opened. Waiting for a condition, not a delay, means a slow page fails loudly instead of silently saving partial content.

## D011 · Save a content-only HTML snapshot and convert from it (2026-11-11)

**Decision:** Save just the "In short" and Reading sections to `data/raw/tailabs/html/sNN.html` (with URL and fetch time), and always build the Markdown from that snapshot. `--from-html` rebuilds without visiting the site.

**Alternatives:**
- No snapshot; re-fetch from the site to validate or to fix conversion bugs
- Save the whole page (includes navigation and my email)

**Evidence:** Two conversion bugs (nested fence in s03; 187 `pythonCopy` header lines) were fixed by rebuilding all 17 files from snapshots, with 0 page loads. A rebuild of s01 was byte-identical to the live run.

**Tradeoff:** 2.4 MB of local files (17 snapshots); still git-ignored, same rules as the Markdown.

## D012 · Test ingestion against the snapshots, with a measured word-count tolerance (2026-11-11)

**Decision:** `tests/test_ingest_tailabs.py` compares every `.md` with its snapshot: files present, front matter, no junk, identical subtopic headings, code block and table counts, and words per subtopic within 99–102%. Tests skip when the local data isn't there.

**Alternatives:**
- Compare with the live site: slow, needs login, and breaks when the site changes
- Exact word match: fails on correct files (Markdown adds list numbers, link URLs)
- Ad-hoc checks only: not repeatable

**Evidence:** Measured the gap across 124 subtopics before choosing the tolerance: 0% to +0.54%, never fewer words. 86 checks pass in 1.55s with no API calls.

**Limits:** It proves fidelity to the snapshot, not that the snapshot is current, and not that the content is good for RAG (that's M4/M5).

## D013 · Keep "Check yourself" questions in the files; handle leakage in M4 (2026-11-11)

**Decision:** Keep each subtopic's "Check yourself" questions in the Markdown for now.

**Alternatives:**
- Strip them during ingestion

**Reasons:** They're a labelled eval set (each question's answer is in a known subtopic), and ingestion should keep the source complete.

**Risk:** If they're indexed, retrieval matches each question to the chunk that contains its own text, so recall@k looks nearly perfect but means nothing (test-set leakage).

**Revisit at:** M4: extract them into `evals/datasets/`, and leave them out of what gets indexed.
