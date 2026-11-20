"""Tools the VivaPrep tutor agent can call.

Each tool is a plain Python function. Claude can't see this code: ADK describes
each tool to Claude using the function name, its input types and its docstring,
so the docstrings below are written for Claude, not only for humans.

BGE-M3 comes from get_shared_model(): loaded on the first search, then reused.
Inside the API, that is the same copy the API loaded at startup (one copy per process).
generate_quiz lives in rag/quiz.py because the API uses it too; it is imported
here so every tool the agent can use is listed in this one file.
"""

from google.adk.tools import ToolContext

from rag.embeddings import get_shared_model
from rag.quiz import generate_quiz  # noqa: F401  (used in agent.py's tools list)
from rag.search import search


def search_course(query: str, tool_context: ToolContext) -> dict:
    """Search the AI engineering course (17 sessions) and return the most relevant passages.

    If the student picked one session, only that session is searched.

    The course covers: how LLMs work (tokens, context window, sampling, hallucination),
    classical ML/DL, Python tooling, model APIs and failure handling, prompting and
    context engineering, structured output and tool calling, RAG and retrieval,
    fine-tuning, evals, agents, multi-modal, production and observability, serving and
    infra, AI security, system design, DSA, and communication.

    Write the query as a short phrase about one concept, for example
    'what is a context window' or 'can RAG still hallucinate'.
    If the question mixes two concepts, call this tool once per concept.
    If the passages look off-topic, search again with different words.

    Returns up to 5 passages, each with a chunk_id and a session number.
    Cite every passage you use by its chunk_id.
    If no passages are found, tell the student the course does not cover it.
    """

    # The session scope is set by OUR code (POST /chat writes it into the chat's state), not by Claude.
    # tool_context is filled in by ADK and hidden from Claude: Claude only sees `query`, so it can't change the scope.
    # "course_session", not "session": in ADK a "session" means one chat, so this name avoids mixing them up.
    # .get(): None if no scope was set (e.g. in `adk run`), and search() treats None as "all sessions".
    course_session = tool_context.state.get("course_session")

    # get_shared_model(), not load_model(): load_model() would load a new ~2 GB copy on every search
    chunks = search(query, k=5, model=get_shared_model(), session=course_session)
    if not chunks:
        return {"status": "no_results", "passages": []}
    passages = []
    for chunk in chunks:
        #heading_path is already the first line of the text hence dropped
        passage = {"chunk_id": chunk["chunk_id"],"session": chunk["session"],"text": chunk["text"] }
        passages.append(passage)
    return {"status": "ok", "passages": passages}
