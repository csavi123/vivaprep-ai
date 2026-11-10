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
