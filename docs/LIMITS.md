# Known limits

What the code doesn't handle yet. Tick an item off (and note the commit) when it's fixed.

## `llm.py`: `ask()` / `ask_tutor()` (as of 2026-11-10, M1)

- [ ] **`ask_tutor()` can silently return `None`.** If the model hits `max_tokens` mid-JSON, `result.parsed` is `None`, and `ask_tutor()` passes it through even though its type hint promises a `TutorAnswer`. The caller then crashes later, somewhere unrelated.
  *Fix:* check `stop_reason` / `parsed` and raise a clear error. Also decide whether a schema validation error should be retried (right now it is raised immediately).
- [ ] **Cost is only correct for Haiku.** `ask()` accepts `model=`, but the prices are hard-coded Haiku constants. Calling Sonnet logs the wrong cost with no error, which would break the M12 model comparison.
  *Fix:* a price table keyed by model that raises an error for unknown models.
- [ ] **The log has blind spots.**
  - Failed attempts aren't logged: a 429 followed by a successful retry looks like one clean call, so I can't measure how often I'm rate limited.
  - `Path("logs/llm_calls.jsonl")` is relative to the folder Python is started from, not the project, so running from another folder writes the log somewhere else.
  - The file grows forever and isn't safe with several processes writing at once.
- [ ] **Retry limits.** It ignores the server's `retry-after` header, and it uses `print()` instead of the `logging` module, so retry messages can't be filtered or saved.
- [ ] **Only single-turn, synchronous calls.** No system prompt, conversation history, `temperature` or async. Fine for M1; the tutor agent (M8) needs history, and the eval harness (M2) will want parallel calls.
- [ ] **Test gaps.** Nothing tests the 400 → raise immediately path, the give-up-after-3 path, or the log write. Every test calls the real API, so it costs money and fails without a network connection.

**Interview framing:** "It's a reliable, observable wrapper for single-turn Haiku calls. Its known limits are silent `None` on truncated structured output, cost that's only correct for Haiku, and no logging of failed attempts. I've written those down as the next fixes."

## Ingestion: `ingest/tailabs.py` (found 2026-11-14, M5)

- [ ] **Missing spaces in chunk text.** Words run together in some places: "aretwo", "fewthousand", "thewords", "toa human", "twoseparate", "bereverse-engineering". Likely cause (not confirmed yet): markdownify drops the space next to some inline elements (links, bold, italic).
  *Impact:* Claude still reads it fine (M5). It may slightly hurt embeddings, and it will hurt keyword search, because "aretwo" won't match "two".
  *Fix before M7 full-text search:* compare one case with the original HTML to confirm the cause, fix the conversion, re-ingest, re-embed, and re-run the retrieval eval.

## Retrieval: `rag/search.py` (found 2026-11-14, M6)

- [ ] **No minimum similarity score.** `search()` always returns the k closest chunks, even for off-topic questions
  ("weather in Bangalore" got 5 chunks scoring 0.35–0.38). Claude abstains correctly (prompt rule 3), but each
  off-topic question still costs a Claude call. The UI hides the chunks when the tutor abstains.
  *Idea for M7:* skip the Claude call when the top score is below a threshold, with the threshold chosen from eval
  data (scores of in-course vs off-topic questions), not guessed.
- [ ] **Warm embedding is slower inside the API than in a script** (found 2026-11-24 with Langfuse, D026).
  The same question embeds in ~0.03 s in a standalone script (main thread or new threads), but 0.2–0.4 s inside
  the running API. Not threads, not the database (0.03 s), not a model reload. Unexplained; under 10% of a
  tutor message, so not chased yet.
  *Next test:* time `embed()` inside the API with a dummy endpoint; then try `EMBED_DEVICE=cpu`, one change at a time.

## Tracing: Langfuse (found 2026-11-24, D026)

- [ ] **Tests and eval scripts send traces to the same project as the app.** pytest's `search()` calls and
  every eval run show up next to real questions, so latency and cost views mix test and real traffic.
  *Fix:* an environment tag (Langfuse `environment`, e.g. `dev` / `eval`), or tracing switched off in tests.
- [ ] **Traces contain full prompts with course chunks.** Allowed under the current data rule, but a privacy
  question for any real user data later (M10 memory).
