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
