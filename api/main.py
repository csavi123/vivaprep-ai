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
from fastapi import Depends, FastAPI, Header, HTTPException

from rag.answer import answer
from rag.embeddings import load_model
from schemas import AskRequest, RagResult

# Load .env first, before anything reads the environment (the Step 2 lesson).
# In the container there is no .env: HF Secrets are already in the environment, and they win.
dotenv.load_dotenv()

TOP_K = 5                                # how many chunks to retrieve per question (same as the UI)
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

    # 2. The embedding model: ~2 GB and several seconds to load, so only once
    print("loading BGE-M3")              # should appear once per server start, never per request
    state["model"] = load_model()

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
        return answer(request.question, k=TOP_K, model=state["model"])
    except Exception:
        # logger.exception writes the full traceback to the server log (for me),
        # but the client only gets a short message: no internal details, paths, or config.
        logger.exception("answer() failed")
        raise HTTPException(status_code=502, detail="The tutor couldn't answer right now. Please try again.")
