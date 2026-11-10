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
