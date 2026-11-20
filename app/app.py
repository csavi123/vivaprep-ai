"""Streamlit study app for the course tutor (M6).

The UI is a thin client: it sends the question to the FastAPI backend (api/main.py)
and draws the RagResult it gets back. BGE-M3, Postgres and Claude all live behind the API.
Three tabs: Ask (POST /ask), Tutor (POST /chat, the agent) and Quiz (POST /quiz).

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
import uuid

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

# Quiz dropdowns: the values POST /quiz accepts (QuizRequest in schemas.py), with the text shown for each
QUESTION_TYPE_LABELS = {"mixed": "Mixed", "mcq": "Multiple choice", "short": "Short answer", "viva": "Viva (oral)"}
DIFFICULTIES = ["easy", "medium", "hard"]


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


def call_quiz_api(session: int, num_questions: int, question_type: str, difficulty: str) -> dict:
    """Ask POST /quiz for a practice quiz: {"status", "session", "questions", "cost_usd"}.

    Each question is a dict with QuizQuestion's fields (schemas.py), including the answer key.
    Raises ApiError with a user-friendly message for every kind of failure (same rules as call_api).
    """
    api_url = os.environ.get("API_URL", DEFAULT_API_URL)
    try:
        response = httpx.post(
            api_url + "/quiz",
            # becomes the QuizRequest body
            json={
                "session": session,
                "num_questions": num_questions,
                "question_type": question_type,
                "difficulty": difficulty,
            },
            headers={"X-API-Token": get_api_token()},
            timeout=API_TIMEOUT,
        )
    except httpx.ConnectError:
        raise ApiError("The tutor's backend isn't running. Start it with: uvicorn api.main:app --port 8000")
    except httpx.TimeoutException:
        raise ApiError("Writing the quiz took too long. Please try again.")

    if response.status_code == 401:
        raise ApiError("The app isn't configured correctly (API token rejected).")
    if response.status_code == 404:
        # The session has no chunks: the API's detail says which one, e.g. "Session 99 not found"
        raise ApiError(response.json()["detail"])
    if response.status_code == 422:
        # Can't normally happen (the dropdowns only offer valid values), but the API is the real check
        message = response.json()["detail"][0]["msg"]
        raise ApiError(f"That quiz can't be requested: {message}")
    if response.status_code != 200:
        detail = response.json().get("detail", "Unknown error")
        raise ApiError(f"Something went wrong: {detail}")

    return response.json()


def call_transcribe_api(audio_bytes: bytes) -> dict:
    """Send a recording to POST /transcribe: {"text", "duration_s", "latency_s"}.

    Raises ApiError with a user-friendly message for every kind of failure (same rules as call_api).
    """
    api_url = os.environ.get("API_URL", DEFAULT_API_URL)
    try:
        response = httpx.post(
            api_url + "/transcribe",
            # files=: a multipart upload, not JSON. "audio" must match the endpoint's parameter name;
            # the tuple is (file name, the bytes, the content type). st.audio_input records WAV.
            files={"audio": ("answer.wav", audio_bytes, "audio/wav")},
            headers={"X-API-Token": get_api_token()},
            timeout=API_TIMEOUT,
        )
    except httpx.ConnectError:
        raise ApiError("The tutor's backend isn't running. Start it with: uvicorn api.main:app --port 8000")
    except httpx.TimeoutException:
        raise ApiError("Transcribing took too long. Please try a shorter answer.")

    if response.status_code == 401:
        raise ApiError("The app isn't configured correctly (API token rejected).")
    if response.status_code != 200:
        # Our own errors (413 too long, 422 empty, 502) send a plain text detail
        detail = response.json().get("detail", "Unknown error")
        if not isinstance(detail, str):
            detail = "The recording couldn't be sent."     # FastAPI's validation errors are a list
        raise ApiError(detail)

    return response.json()


def call_chat_api(chat_id: str, message: str, course_session: int | None) -> dict:
    """Send one chat message to POST /chat (the tutor agent).

    Returns {"answer", "trace", "model_calls", "input_tokens", "output_tokens", "cost_usd"}.
    Raises ApiError with a user-friendly message for every kind of failure (same rules as call_api).
    """
    api_url = os.environ.get("API_URL", DEFAULT_API_URL)
    try:
        response = httpx.post(
            api_url + "/chat",
            # becomes the ChatRequest body; course_session None = all sessions
            json={"chat_id": chat_id, "message": message, "course_session": course_session},
            headers={"X-API-Token": get_api_token()},
            timeout=API_TIMEOUT,
        )
    except httpx.ConnectError:
        raise ApiError("The tutor's backend isn't running. Start it with: uvicorn api.main:app --port 8000")
    except httpx.TimeoutException:
        raise ApiError("The tutor took too long to answer. Please try again.")

    if response.status_code == 401:
        raise ApiError("The app isn't configured correctly (API token rejected).")
    if response.status_code == 422:
        message_text = response.json()["detail"][0]["msg"]
        raise ApiError(f"That message can't be sent: {message_text}")
    if response.status_code != 200:
        detail = response.json().get("detail", "Unknown error")
        raise ApiError(f"Something went wrong: {detail}")

    return response.json()


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


def render_mode_hint(text: str) -> None:
    """One muted line at the top of a tab, so a first-time visitor knows what the mode is for."""
    # html.escape: the text is ours today, but escaping keeps this safe if it ever comes from elsewhere
    st.markdown(f'<p class="mode-hint">{html.escape(text)}</p>', unsafe_allow_html=True)


def render_ask_tab(labels: dict) -> None:
    """The Ask tab: one question -> a cited answer (the M6 flow, unchanged)."""
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


def start_new_chat() -> None:
    """Forget the current chat: a new chat_id (the agent starts with no history) and no messages on screen.

    Used as the New chat button's on_click: Streamlit runs it BEFORE the rerun,
    so the page is redrawn with the empty chat straight away.
    """
    # uuid4().hex: a random 32-character id, so two chats never get the same one
    st.session_state["chat_id"] = uuid.uuid4().hex
    st.session_state["chat_messages"] = []


def render_tutor_tab(labels: dict) -> None:
    """The Tutor tab: a chat with the agent (vivaprep_tutor), limited to the chosen session scope."""
    # First visit: create the chat. session_state keeps it across reruns (every click reruns the script).
    if "chat_id" not in st.session_state:
        start_new_chat()

    col_scope, col_new = st.columns([4, 1], vertical_alignment="bottom")
    with col_scope:
        # The same values as the Ask tab: None = all sessions, or a session number.
        # A key of its own, so it doesn't clash with the Ask tab's Session dropdown.
        course_session = st.selectbox(
            "Session scope",
            list(labels.keys()),
            format_func=lambda value: labels[value],
            key="tutor_scope",
        )
    with col_new:
        st.button("New chat", on_click=start_new_chat, use_container_width=True)

    # A box for the messages, made BEFORE the chat input, so new messages appear above the input box
    messages_box = st.container()
    with messages_box:
        if not st.session_state["chat_messages"]:
            st.caption("Ask anything about your course. The tutor searches the course and cites what it uses.")
        for chat_message in st.session_state["chat_messages"]:
            render_chat_message(chat_message)

    prompt = st.chat_input("Ask the tutor anything about your course...", key="tutor_input")
    if not prompt:
        return                              # no new message on this rerun: nothing to send

    user_message = {"role": "user", "content": prompt}
    st.session_state["chat_messages"].append(user_message)

    with messages_box:
        render_chat_message(user_message)
        with st.chat_message("assistant"):
            try:
                with st.spinner("The tutor is searching the course..."):
                    start_time = time.perf_counter()
                    reply = call_chat_api(st.session_state["chat_id"], prompt, course_session)
                    latency_s = time.perf_counter() - start_time
            except ApiError as e:
                st.error(str(e))
                st.session_state["chat_messages"].pop()    # take back the unanswered message
                return
            except Exception as e:
                print(f"Unexpected error calling the chat API: {e!r}")
                st.error("Something unexpected went wrong. Please try again.")
                st.session_state["chat_messages"].pop()
                return

            assistant_message = {"role": "assistant", "content": reply["answer"], "reply": reply, "latency_s": latency_s}
            st.session_state["chat_messages"].append(assistant_message)
            render_assistant_body(assistant_message)


def render_chat_message(chat_message: dict) -> None:
    """One chat bubble: the student's message, or the tutor's answer with its stats and trace."""
    with st.chat_message(chat_message["role"]):
        if chat_message["role"] == "user":
            st.markdown(chat_message["content"])
        else:
            render_assistant_body(chat_message)


def render_assistant_body(chat_message: dict) -> None:
    """The inside of a tutor bubble: answer, one stats line, and "How I got this answer"."""
    reply = chat_message["reply"]
    if chat_message["content"].strip() == "":
        st.warning("The tutor returned an empty answer. Please try asking again.")
    else:
        st.markdown(chat_message["content"])

    searches = len(reply["trace"])
    st.caption(
        f"{searches} search(es) · {reply['model_calls']} model calls · "
        f"{reply['input_tokens']:,} in / {reply['output_tokens']:,} out tokens · "
        f"${reply['cost_usd']:.4f} · {chat_message['latency_s']:.1f}s"
    )
    render_trace(reply)


def render_trace(reply: dict) -> None:
    """ "How I got this answer": every tool call the agent made, and the passages each one returned.

    This is what makes the AGENT visible: Claude chose the query (and whether to search at all).
    A passage is marked "cited" if its [chunk_id] appears in the answer.
    """
    with st.expander("How I got this answer"):
        if not reply["trace"]:
            # The agent can answer from the earlier messages without searching again
            st.caption("No new search: the tutor answered from the conversation so far.")
            return
        for step_number, step in enumerate(reply["trace"], start=1):
            query = step["args"].get("query", "")
            st.markdown(f"**{step_number}. `{step['tool']}`** · query Claude wrote: `{query}` · status: `{step['status']}`")
            for passage in step["passages"]:
                is_cited = f"[{passage['chunk_id']}]" in reply["answer"]
                mark = "✅ cited" if is_cited else "· not used"
                # One line of the passage: the newlines removed, cut to 120 characters
                preview = " ".join(passage["text"].split())[:120]
                st.caption(f"`{passage['chunk_id']}` (session {passage['session']}) {mark}: {preview}...")


def render_quiz_tab(labels: dict) -> None:
    """The Quiz tab: pick a session and options, generate a quiz, then answer it."""
    # A quiz is always about ONE session, so leave out the "All sessions" entry (its key is None)
    session_numbers = []
    for value in labels:
        if value is not None:
            session_numbers.append(value)
    if not session_numbers:
        st.info("The session list couldn't be loaded, so quizzes aren't available right now.")
        return

    with st.form("quiz_form"):
        session = st.selectbox("Session", session_numbers, format_func=lambda value: labels[value])
        col1, col2, col3 = st.columns(3)
        with col1:
            num_questions = st.number_input("Questions", min_value=1, max_value=10, value=5)
        with col2:
            question_type = st.selectbox(
                "Type",
                list(QUESTION_TYPE_LABELS.keys()),
                format_func=lambda value: QUESTION_TYPE_LABELS[value],
            )
        with col3:
            # index=1: "medium" is the default, same as QuizRequest
            difficulty = st.selectbox("Difficulty", DIFFICULTIES, index=1, format_func=str.capitalize)
        submitted = st.form_submit_button("Generate quiz")

    if submitted:
        try:
            with st.spinner("Picking passages and writing your quiz..."):
                quiz = call_quiz_api(session, int(num_questions), question_type, difficulty)
        except ApiError as e:
            st.error(str(e))
            return
        except Exception as e:
            print(f"Unexpected error calling the quiz API: {e!r}")
            st.error("Something unexpected went wrong. Please try again.")
            return

        # Keep the quiz in session_state. Clicking an answer reruns this whole script, with
        # submitted=False, so without this the quiz would disappear at the first click.
        st.session_state["quiz"] = quiz
        # A new number for every quiz, used in the widget keys, so answers to the old quiz
        # don't stay selected on the new questions.
        st.session_state["quiz_number"] = st.session_state.get("quiz_number", 0) + 1

    if "quiz" in st.session_state:
        render_quiz(st.session_state["quiz"], st.session_state["quiz_number"])


def render_quiz(quiz: dict, quiz_number: int) -> None:
    """Every question as a card. The answer stays hidden until the student answers (mcq) or asks (short/viva)."""
    questions = quiz["questions"]
    st.caption(f"Session {quiz['session']} · {len(questions)} question(s) · ${quiz['cost_usd']:.4f}")

    mcq_total = 0
    mcq_correct = 0
    for number, question in enumerate(questions, start=1):
        # A unique key per quiz and question: Streamlit uses it to remember each answer across reruns
        key = f"quiz{quiz_number}_q{number}"
        with st.container(border=True):
            type_label = QUESTION_TYPE_LABELS[question["question_type"]]
            st.caption(f"Question {number} · {type_label} · {question['difficulty'].capitalize()}")
            st.markdown(f"**{question['question']}**")

            if question["question_type"] == "mcq":
                mcq_total += 1
                if render_mcq(question, key):
                    mcq_correct += 1
            else:
                render_open_question(question, key)

    if mcq_total > 0:
        st.markdown(f"**Multiple choice score: {mcq_correct} / {mcq_total}**")


def render_mcq(question: dict, key: str) -> bool:
    """The options as radio buttons; once one is picked, say right or wrong. Returns True if correct."""
    # index=None: nothing selected at first (otherwise Streamlit pre-selects option 1 and it looks answered)
    choice = st.radio("Your answer", question["options"], index=None, key=key, label_visibility="collapsed")
    if choice is None:
        return False                        # not answered yet: keep the answer key hidden

    # An exact text match: this is why the quiz prompt says "copy correct_answer word for word"
    if choice == question["correct_answer"]:
        st.success("Correct!")
        is_correct = True
    else:
        st.error(f"Not quite. The answer is: {question['correct_answer']}")
        is_correct = False
    render_key_points(question)
    return is_correct


def render_open_question(question: dict, key: str) -> None:
    """A text box for short and viva questions, and the model answer behind an expander.

    No automatic grading yet: the student compares their answer with the key points.
    (evaluate_answer, D1, will grade it later.)
    The mic is the viva practice: speak the answer, and the text appears in the box to check or edit.
    """
    recording = st.audio_input("Or speak your answer", key=f"{key}_audio")
    if recording is not None:
        # Streamlit gives back the same recording on every rerun (every click on the page).
        # Remember which recording was already transcribed, so each one is sent only once.
        audio_id_key = f"{key}_audio_id"
        if st.session_state.get(audio_id_key) != recording.file_id:
            # Store the id BEFORE calling: if it fails, a rerun won't retry the same recording forever
            st.session_state[audio_id_key] = recording.file_id
            try:
                with st.spinner("Turning your answer into text..."):
                    result = call_transcribe_api(recording.getvalue())
            except ApiError as e:
                st.error(f"{e} You can record again or type your answer.")
            else:
                if result["text"].strip() == "":
                    st.warning("No speech was heard in that recording. Please try again.")
                else:
                    # Put the text in the answer box below. This works because the box isn't drawn yet
                    # in this run: a widget's value can be set in session_state before it is created.
                    st.session_state[key] = result["text"]

    st.text_area(
        "Your answer",
        key=key,
        placeholder="Write or speak your answer, then open the model answer to compare.",
        label_visibility="collapsed",
    )
    with st.expander("Show model answer"):  # collapsed by default = hidden until the student asks
        st.markdown(question["correct_answer"])
        render_key_points(question)


def render_key_points(question: dict) -> None:
    """The ideas a good answer must contain, and the chunk the question came from."""
    st.markdown("**Key points**")
    for point in question["key_points"]:
        st.markdown(f"- {point}")
    st.caption(f"Source: {question['source_chunk_id']}")


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

    # Two tabs. Streamlit runs the code of BOTH tabs on every rerun; the tab only decides where it's drawn.
    # That's fine here: each tab calls its API only when its own form is submitted.
    # :material/...: Google Material icons, built into Streamlit labels (no image files needed)
    ask_tab, tutor_tab, quiz_tab = st.tabs([
        ":material/search: Ask",
        ":material/forum: Tutor",
        ":material/quiz: Quiz",
    ])
    with ask_tab:
        render_mode_hint("One question, one search, an answer with its sources.")
        render_ask_tab(labels)
    with tutor_tab:
        render_mode_hint("A conversation. The tutor decides what to search and remembers what you said.")
        render_tutor_tab(labels)
    with quiz_tab:
        render_mode_hint("Practice questions from one session. Answer by typing or speaking.")
        render_quiz_tab(labels)


main()
