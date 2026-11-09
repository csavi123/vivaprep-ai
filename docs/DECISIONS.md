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
