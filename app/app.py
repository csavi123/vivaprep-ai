"""Streamlit study app for the course tutor (M6).

The UI is a thin client: it sends the question to the FastAPI backend (api/main.py)
and draws the RagResult it gets back. BGE-M3, Postgres and Claude all live behind the API.

Run from the repo root, in two terminals (the -m puts the repo root on Python's path, so `from schemas...` works):
    uvicorn api.main:app --host 127.0.0.1 --port 8000
    python -m streamlit run app/app.py

Design rules (so add-ons don't break things):
1. No RAG logic here: only call the API and display the RagResult.
2. One render_...() function per screen section.
3. Expensive things in @st.cache_resource; per-user things in st.session_state.
4. Call the API only when the form is submitted (each answer costs a Claude call).
5. Every API failure becomes a clear st.error message, never a crashed page or a raw traceback.
"""

import html
import os
import time

import dotenv
import httpx
import streamlit as st

from schemas import RagResult
# Streamlit puts this script's folder (app/) on Python's path, so styles.py is imported by its plain name.
# ("from app.styles" would fail: "app" would resolve to this file, app/app.py, not the folder.)
from styles import apply_styles

# Decision #1: app.py no longer imports rag/ or llm.py, so nothing loads .env for us by accident anymore.
# Load it here ourselves. (In the container there is no .env: the HF Secrets are already in the environment, and they win.)
dotenv.load_dotenv()

APP_TITLE = "VivaPrep AI"
CLAUDE_MODEL_LABEL = "Claude Haiku"    # display only; the real model ID is the default in llm.ask()
DEFAULT_API_URL = "http://127.0.0.1:8000"   # the API runs next to the UI: locally and inside the container

# Decision #4: how long to wait for the API.
# connect=5: the API is on the same machine, so if it doesn't accept the connection in 5 s it isn't running.
# read=120: a normal answer takes ~2-5 s, but llm.py may retry up to 3 times with backoff, and
# max_tokens=16000 allows a long answer. Too short -> we give up on answers that were about to arrive
# (and still pay for them). Too long -> the user stares at a spinner for minutes when something is stuck.
API_TIMEOUT = httpx.Timeout(120.0, connect=5.0)


class ApiError(Exception):
    """A failed API call, with a message that is safe and useful to show the user."""


def get_api_token() -> str:
    """The shared secret the API expects in X-API-Token ("" if it isn't set)."""
    # Read when needed, not at import time (the Step 2 lesson)
    return os.environ.get("API_TOKEN", "").strip()


def call_api(question: str, session: int | None = None) -> RagResult:
    """Send the question to POST /ask and turn the JSON answer back into a RagResult.

    session=None searches all sessions; session=1 searches only session 1.
    Raises ApiError with a user-friendly message for every kind of failure.
    """
    api_url = os.environ.get("API_URL", DEFAULT_API_URL)
    try:
        response = httpx.post(
            api_url + "/ask",
            # becomes the AskRequest body; None is sent as JSON null, which AskRequest reads as "all sessions"
            json={"question": question, "session": session},
            headers={"X-API-Token": get_api_token()},
            timeout=API_TIMEOUT,
        )
    except httpx.ConnectError:
        raise ApiError("The tutor's backend isn't running. Start it with: uvicorn api.main:app --port 8000")
    except httpx.TimeoutException:
        raise ApiError("The tutor took too long to answer. Please try again.")

    if response.status_code == 401:
        # Not the user's fault: the UI and the API have different API_TOKEN values (a config problem)
        raise ApiError("The app isn't configured correctly (API token rejected).")
    if response.status_code == 422:
        # The API's validation message, e.g. "String should have at least 3 characters"
        message = response.json()["detail"][0]["msg"]
        raise ApiError(f"That question can't be sent: {message}")
    if response.status_code != 200:
        # 502 and anything else: the API already made the message safe, so show its detail
        detail = response.json().get("detail", "Unknown error")
        raise ApiError(f"Something went wrong: {detail}")

    # The JSON has exactly RagResult's fields, so this rebuilds the same object answer() used to return.
    # The render_...() functions below don't need to change at all.
    return RagResult.model_validate(response.json())


# Streamlit reruns this whole script on every click. Without the cache, every click would call
# GET /sessions (and Postgres) again for a list that almost never changes.
# ttl=600: keep the result for 10 minutes, so a newly added session shows up without restarting the app.
# If the function raises, nothing is cached, so a failed call is simply tried again on the next rerun.
@st.cache_data(ttl=600)
def fetch_sessions() -> list[dict]:
    """Get the session list from GET /sessions: [{"session": 1, "title": "..."}, ...].

    Raises ApiError if the list can't be loaded.
    """
    api_url = os.environ.get("API_URL", DEFAULT_API_URL)
    try:
        response = httpx.get(
            api_url + "/sessions",
            headers={"X-API-Token": get_api_token()},
            timeout=API_TIMEOUT,
        )
    except httpx.HTTPError:
        # ConnectError, TimeoutException, ...: all mean "couldn't reach the API"
        raise ApiError("Couldn't load the session list (the backend isn't reachable).")

    if response.status_code != 200:
        raise ApiError(f"Couldn't load the session list (status {response.status_code}).")
    return response.json()


def build_session_labels(sessions: list[dict]) -> dict:
    """Map each dropdown value to the text shown for it: {None: "All sessions", 1: "Session 1: ...", ...}."""
    labels = {None: "All sessions"}          # first entry = the default choice
    for entry in sessions:
        number = entry["session"]
        labels[number] = f"Session {number}: {entry['title']}"
    return labels


def render_answer(rag: RagResult) -> None:
    """Show the answer, or a warning if the course material doesn't cover the question."""
    st.subheader("Answer")
    if not rag.answer.in_course:
        st.warning(rag.answer.answer)     # yellow box: the tutor abstained
        return
    with st.container(border=True):       # a card (styled in styles.py)
        st.markdown(rag.answer.answer)    # markdown, so lists or **bold** in the answer render properly


def render_pipeline(rag: RagResult, total_s: float) -> None:
    """The RAG steps as a strip: Retrieve -> Generate -> Cite, with time and cost.

    The UI only knows the total time and Claude's time (rag.latency_s), so retrieval time is estimated
    as total - Claude. That's why it shows "~". (An exact number would need a change in rag/answer.py.)
    """
    retrieve_s = max(total_s - rag.latency_s, 0.0)
    if rag.answer.in_course:
        cite_meta = f"{len(rag.answer.citations)} citation(s) · ${rag.cost_usd:.4f}"
    else:
        cite_meta = f"not in course: abstained · ${rag.cost_usd:.4f}"

    st.markdown(
        f"""
        <div class="pipeline">
          <div class="step">
            <div class="step-title">① Retrieve</div>
            <div class="step-meta">{len(rag.chunks)} chunks · ~{retrieve_s:.1f}s</div>
          </div>
          <div class="step-arrow">→</div>
          <div class="step">
            <div class="step-title">② Generate</div>
            <div class="step-meta">{CLAUDE_MODEL_LABEL} · {rag.latency_s:.1f}s</div>
          </div>
          <div class="step-arrow">→</div>
          <div class="step">
            <div class="step-title">③ Cite</div>
            <div class="step-meta">{cite_meta}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_retrieval(rag: RagResult) -> None:
    """All retrieved chunks, best first: score bar, CITED badge, and the quotes Claude used.

    Cited chunks are highlighted; the rest are dimmed. This is the part that makes RAG visible:
    what search found, how close each chunk was, and which ones the answer actually used.
    """
    if not rag.answer.in_course:
        # Search always returns the k closest chunks, even for off-topic questions (no minimum score).
        # When the tutor abstained, those chunks are just noise, so the answer alone says "not in the course".
        return
    # Claude can cite the same block several times (e.g. two quotes from block 1),
    # so group the quotes by block first: {block number: [quote, quote, ...]}
    quotes_by_block = {}
    for citation in rag.answer.citations:
        if citation.block not in quotes_by_block:
            quotes_by_block[citation.block] = []
        quotes_by_block[citation.block].append(citation.quote)

    st.subheader("Retrieved from the course")
    st.caption("Top chunks by cosine similarity to your question. Highlighted = used in the answer.")

    for number, chunk in enumerate(rag.chunks, start=1):    # same numbering as the context blocks
        is_cited = number in quotes_by_block
        card_class = "chunk-card cited" if is_cited else "chunk-card"

        # Score bar: cosine similarity (0 to 1) as a width percentage
        score = float(chunk["score"])
        bar_width = max(0, min(100, round(score * 100)))

        # html.escape: chunk text comes from the course, so make sure it can't break our HTML
        subtopic = html.escape(str(chunk["subtopic"]))

        badge = '<span class="badge">CITED</span>' if is_cited else ""
        quotes_html = ""
        if is_cited:
            for quote in quotes_by_block[number]:
                quotes_html += f'<div class="chunk-quote">"{html.escape(quote)}"</div>'

        # Built as one line on purpose: when badge or quotes_html is empty, a multi-line string would
        # leave a blank line, and markdown would then show the indented HTML after it as a code block.
        card_html = (
            f'<div class="{card_class}">'
            f'<div class="chunk-head">'
            f'<span class="chunk-title">[{number}] Session {chunk["session"]} · {subtopic}</span>'
            f'{badge}'
            f'</div>'
            f'<div class="score-row">'
            f'<div class="score-track"><div class="score-fill" style="width: {bar_width}%"></div></div>'
            f'<span class="score-value">{score:.2f}</span>'
            f'</div>'
            f'{quotes_html}'
            f'</div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)
        with st.expander(f"Read chunk {number} ({chunk['chunk_id']})"):   # full text, collapsed by default
            st.markdown(chunk["text"])

    if rag.invalid_citations:
        # Claude cited a block number that wasn't in the context: worth noticing (it's an eval signal)
        st.caption(f"⚠️ {len(rag.invalid_citations)} citation(s) pointed at a block that doesn't exist and were dropped.")


def main() -> None:
    # set_page_config must be the first Streamlit call: browser tab title, icon, centered layout
    st.set_page_config(page_title=APP_TITLE, page_icon="🧭", layout="centered")
    apply_styles()

    # Hero: plain HTML so styles.py can put the accent gradient on one word only (the accent is used sparingly)
    st.markdown(
        """
        <div class="hero">
          <h1>VivaPrep <span class="accent">AI</span></h1>
          <p>A RAG-powered AI tutor for self-learners.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Decision #2: without a token every request would get a 401, so stop here with a clear message
    # (the UI's version of the API refusing to start without API_TOKEN)
    if get_api_token() == "":
        st.error("API_TOKEN is not set. Add it to .env (locally) or to the Space secrets (on Hugging Face).")
        st.stop()                           # nothing below this line runs

    # The session list for the dropdown. If it can't be loaded, don't block the app:
    # "All sessions" still works (it doesn't need the list), so show a warning and carry on.
    try:
        sessions = fetch_sessions()
    except ApiError as e:
        st.warning(f"{e} You can still ask about all sessions.")
        sessions = []
    labels = build_session_labels(sessions)

    # A form: the code below only gets submitted=True when Ask is clicked (each answer costs a Claude call)
    with st.form("ask_form"):
        # The options are the VALUES we want back (None, 1, 2, ...); format_func turns each into its label.
        # So `session` is already None or an int, exactly what the API expects, with no converting back from text.
        session = st.selectbox(
            "Session",
            list(labels.keys()),
            format_func=lambda value: labels[value],
        )
        question = st.text_input("Your question")
        submitted = st.form_submit_button("Ask")

    if not submitted:
        return                              # page just opened or rerun without a new question: nothing to do
    if question.strip() == "":
        st.info("Type a question first.")   # don't spend a Claude call on an empty question
        return

    try:
        with st.spinner("Searching the course and asking Claude..."):
            start_time = time.perf_counter()
            rag = call_api(question, session=session)
            total_s = time.perf_counter() - start_time    # HTTP + search + Claude, measured here in the UI
    except ApiError as e:
        st.error(str(e))                    # already a friendly, safe message
        return
    except Exception as e:
        # Anything we didn't plan for (e.g. the API sent back something that isn't valid JSON):
        # details to the terminal for me, a short message for the user
        print(f"Unexpected error calling the API: {e!r}")
        st.error("Something unexpected went wrong. Please try again.")
        return

    render_pipeline(rag, total_s)
    render_answer(rag)
    render_retrieval(rag)


main()
