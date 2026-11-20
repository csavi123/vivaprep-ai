"""FastAPI backend for VivaPrep AI: POST /ask -> RagResult.

Run from the repo root (API_TOKEN must be set, in .env or the shell):
    uvicorn api.main:app --host 127.0.0.1 --port 8000
Then open http://127.0.0.1:8000/docs to try it.

Design rules:
1. No RAG logic here: the API only checks the request, calls answer(), and returns the RagResult.
2. Expensive things (BGE-M3) load ONCE at startup, never per request.
3. Fail closed: no API_TOKEN -> the server refuses to start; wrong token -> 401.
4. Errors: full details go to the server log, the client only gets a short, safe message.
"""

import logging
import os
import secrets
from contextlib import asynccontextmanager

import dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile

from agents.vivaprep_tutor.chat import run_chat
from rag.answer import answer
from rag.embeddings import get_shared_model
from rag.quiz import generate_quiz
from rag.search import list_sessions
from schemas import AskRequest, ChatRequest, QuizRequest, RagResult
from speech import transcribe

# Load .env first, before anything reads the environment (the Step 2 lesson).
# In the container there is no .env: HF Secrets are already in the environment, and they win.
dotenv.load_dotenv()

TOP_K = 5                                # how many chunks to retrieve per question (same as the UI)
# The largest recording /transcribe accepts. The browser records WAV (~90 KB per second),
# so 10 MB is about 2 minutes: plenty for one viva answer, and it stops huge uploads early.
MAX_AUDIO_BYTES = 10 * 1024 * 1024
logger = logging.getLogger("vivaprep.api")

# Things loaded once at startup and shared by every request: {"model": ..., "token": ...}
state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once when the server starts (before `yield`) and once when it stops (after `yield`)."""
    # 1. The token. os.environ[...] (not .get): there is no safe default, so a missing token
    #    must stop the server right here with a KeyError, instead of running an open API.
    token = os.environ["API_TOKEN"]
    if token.strip() == "":
        # An empty token would "match" an empty header, so treat it like a missing one
        raise RuntimeError("API_TOKEN is empty: set it in .env or the environment")
    state["token"] = token

    # 2. The embedding model: ~2 GB and several seconds to load, so only once.
    #    get_shared_model(): the agent's search_course tool (POST /chat) gets this same copy.
    print("loading BGE-M3")              # should appear once per server start, never per request
    state["model"] = get_shared_model()

    yield                                # the server handles requests while paused here

    state.clear()                        # on shutdown: drop the references


app = FastAPI(title="VivaPrep AI API", lifespan=lifespan)


def check_token(x_api_token: str | None = Header(default=None)) -> None:
    """Reject the request unless the X-API-Token header matches API_TOKEN.

    FastAPI turns the parameter name x_api_token into the header name X-API-Token
    (underscores become dashes; header names ignore upper/lower case).
    Used as a dependency, so every protected endpoint gets the same check in one line.
    """
    if x_api_token is None:
        raise HTTPException(status_code=401, detail="Missing X-API-Token header")

    # compare_digest takes the same time whether the first or the last character differs,
    # so an attacker can't guess the token one character at a time by timing the replies.
    # (.encode(): compare_digest only accepts ASCII text, but it accepts any bytes.)
    if not secrets.compare_digest(x_api_token.encode(), state["token"].encode()):
        raise HTTPException(status_code=401, detail="Invalid X-API-Token")


@app.get("/health")
def health() -> dict:
    """Is the server up? No token needed: it reveals nothing and costs nothing,
    and start scripts / Docker can call it without knowing the secret."""
    return {"status": "ok"}


# `def`, not `async def`: answer() blocks for seconds (BGE-M3 + Postgres + Claude).
# FastAPI runs a plain `def` endpoint in a separate thread, so other requests are not blocked.
# Inside an `async def`, that same blocking call would freeze the whole server until it finished.
@app.post("/ask", response_model=RagResult, dependencies=[Depends(check_token)])
def ask_endpoint(request: AskRequest) -> RagResult:
    """Answer one question from the course, with citations."""
    # By the time we get here, FastAPI has already checked the token (check_token)
    # and the body (AskRequest: 3 to 1000 characters). Bad requests never reach this line.
    try:
        return answer(request.question, k=TOP_K, model=state["model"], session=request.session)
    except Exception:
        # logger.exception writes the full traceback to the server log (for me),
        # but the client only gets a short message: no internal details, paths, or config.
        logger.exception("answer() failed")
        raise HTTPException(status_code=502, detail="The tutor couldn't answer right now. Please try again.")


# `def`, not `async def`: list_sessions() waits on Postgres, the same reason as /ask above.
# Token required: the titles come from the TAI Labs course and the call hits the database,
# so it is protected like /ask, not public like /health.
@app.get("/sessions", dependencies=[Depends(check_token)])
def sessions_endpoint() -> list[dict]:
    """Every session once, in order, for the UI dropdown: [{"session": 1, "title": "..."}, ...]."""
    try:
        return list_sessions()
    except Exception:
        # Same rule as /ask: full details to the server log, a short safe message to the client
        logger.exception("list_sessions() failed")
        raise HTTPException(status_code=502, detail="Couldn't load the session list right now. Please try again.")


# `def`, not `async def`: generate_quiz() waits on Postgres and Claude, the same reason as /ask.
# Token required: it costs a Claude call, so it is protected like /ask.
@app.post("/quiz", dependencies=[Depends(check_token)])
def quiz_endpoint(request: QuizRequest) -> dict:
    """Write a practice quiz from one session: {"status", "session", "questions", "cost_usd"}."""
    # FastAPI has already checked the token and the body (QuizRequest: session >= 1, 1-10 questions,
    # a valid type and difficulty), so bad requests never reach this line.
    try:
        result = generate_quiz(
            session=request.session,
            num_questions=request.num_questions,
            question_type=request.question_type,
            difficulty=request.difficulty,
        )
    except Exception:
        # A crash (database down, Claude API error): same rule as /ask
        logger.exception("generate_quiz() failed")
        raise HTTPException(status_code=502, detail="Couldn't write a quiz right now. Please try again.")

    # generate_quiz() doesn't raise for these two cases, it returns a status instead.
    # Turn each one into the right HTTP status code, so the client can tell them apart.
    if result["status"] == "no_chunks":
        # The session doesn't exist: the client's mistake, so 404 (not 502)
        raise HTTPException(status_code=404, detail=f"Session {request.session} not found")
    if result["status"] == "error":
        # Claude's reply couldn't be parsed into a Quiz (e.g. max_tokens): our side, so 502
        logger.error("generate_quiz() returned no quiz: %s", result["message"])
        raise HTTPException(status_code=502, detail="Couldn't write a quiz right now. Please try again.")

    return result


# `def`, not `async def`: run_chat() blocks for seconds (search + one or more Claude calls),
# the same reason as /ask. Token required: every message costs Claude calls.
@app.post("/chat", dependencies=[Depends(check_token)])
def chat_endpoint(request: ChatRequest) -> dict:
    """One message to the tutor agent: {"answer", "trace", "model_calls", "input_tokens", "output_tokens", "cost_usd"}."""
    # FastAPI has already checked the token and the body (ChatRequest), so bad requests never reach this line.
    # No agent logic here (design rule 1): run_chat() in agents/vivaprep_tutor/chat.py does all the ADK work.
    try:
        return run_chat(request.chat_id, request.message, request.course_session)
    except Exception:
        # Same rule as /ask: full details to the server log, a short safe message to the client
        logger.exception("run_chat() failed")
        raise HTTPException(status_code=502, detail="The tutor couldn't answer right now. Please try again.")


# `def`, not `async def`: Whisper blocks for seconds, the same reason as /ask.
# Token required: it uses CPU time, and the audio is the student's voice.
# UploadFile + File(...): the audio comes as a file upload (multipart form), not JSON,
# because JSON can't carry raw audio bytes. FastAPI needs the python-multipart package for this.
@app.post("/transcribe", dependencies=[Depends(check_token)])
def transcribe_endpoint(audio: UploadFile = File(...)) -> dict:
    """Turn a spoken answer into text: {"text", "duration_s", "latency_s"}."""
    # Read at most one byte more than the limit: enough to know it's too big, without reading all of it
    audio_bytes = audio.file.read(MAX_AUDIO_BYTES + 1)
    if len(audio_bytes) == 0:
        raise HTTPException(status_code=422, detail="The recording is empty.")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        # 413 = "Content Too Large"
        raise HTTPException(status_code=413, detail="The recording is too long. Keep answers under 2 minutes.")

    try:
        return transcribe(audio_bytes)
    except Exception:
        # e.g. a file that isn't audio, or Whisper failing to load. Same rule as /ask.
        logger.exception("transcribe() failed")
        raise HTTPException(status_code=502, detail="Couldn't turn the recording into text. Please try again.")
