"""Tools the VivaPrep tutor agent can call.

Each tool is a plain Python function. Claude can't see this code: ADK describes
each tool to Claude using the function name, its input types and its docstring,
so the docstrings below are written for Claude, not only for humans.

BGE-M3 is loaded once when this file is imported (slow: several seconds).
"""

from rag.embeddings import load_model
from rag.search import search

# Load the embedding model so that it runs once, when it imports the file. 
# Loading BGE-M3 takes several seconds and a lot of memory.
# If loaded inside search_course(), every single tool call would reload it. 
# The agent may search 2-3 times per question.

MODEL = load_model()


def search_course(query: str) -> dict:
    """Search the AI engineering course (17 sessions) and return the most relevant passages.

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
    If no passages are found, tell the user the course does not cover it.
    """

    chunks = search(query, k=5, model=MODEL)
    if not chunks:
        return {"status": "no_results", "passages": []}
    passages =[]
    for chunk in chunks:
        #Heading_path is already the first line of teh text hence dropped
        passage = {"chunk_id": chunk["chunk_id"] ,"session": chunk["session"] , "text": chunk["text"] }
        passages.append(passage)
    return {"status": "ok", "passages": passages}
