"""Streamlit study app for the course tutor (M6).

Run from the repo root (the -m puts the repo root on Python's path, so `from rag...` works):
    python -m streamlit run app/app.py

Design rules (so add-ons don't break things):
1. No RAG logic here: only call answer() and display the RagResult.
2. One render_...() function per screen section.
3. Expensive things in @st.cache_resource; per-user things in st.session_state.
4. Call Claude only when the form is submitted (each call costs money).
5. Wrap answer() in try/except and show st.error, so a failure doesn't crash the page.
"""

import html
import time

import streamlit as st

from rag.answer import answer
from rag.embeddings import load_model
from schemas import RagResult
# Streamlit puts this script's folder (app/) on Python's path, so styles.py is imported by its plain name.
# ("from app.styles" would fail: "app" would resolve to this file, app/app.py, not the folder.)
from styles import apply_styles

TOP_K = 5                              # how many chunks to retrieve per question
APP_TITLE = "VivaPrep AI"
CLAUDE_MODEL_LABEL = "Claude Haiku"    # display only; the real model ID is the default in llm.ask()


@st.cache_resource          # run once, then reuse the same object on every rerun (and for every browser tab)
def get_embedding_model():
    """Load BGE-M3 once. Without the cache, every click would reload it (several seconds, ~2 GB of RAM)."""
    print("loading BGE-M3")    # goes to the terminal; it should appear only once per server start
    return load_model()


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
          <p>Ask anything about the course. Every answer cites the lesson it came from.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Load the model when the page opens, so the first question isn't slow too (cached: only the first visit waits)
    with st.spinner("Loading the embedding model..."):
        model = get_embedding_model()

    # A form: the code below only gets submitted=True when Ask is clicked (each answer costs a Claude call)
    with st.form("ask_form"):
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
            rag = answer(question, k=TOP_K, model=model)
            total_s = time.perf_counter() - start_time    # search + Claude, measured here in the UI
    except Exception as e:
        # Docker down, API error, no structured answer...: show it instead of crashing the page
        st.error(f"Something went wrong: {e}")
        return

    render_pipeline(rag, total_s)
    render_answer(rag)
    render_retrieval(rag)


main()
