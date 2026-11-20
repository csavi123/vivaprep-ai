"""Find the chunks closest in meaning to a question (M4 step 5: the "R" in RAG).

Run from the repo root:
    python -m rag.search "What is a token?"
    python -m rag.search "What is a token?" 1      # only search session 1
"""

import os
import sys

import numpy as np
import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector

from rag.embeddings import embed, load_model

# <=> is pgvector's cosine DISTANCE: 0 = same meaning, bigger = less similar.
SEARCH_SQL = """
SELECT chunk_id, session, subtopic, heading_path, text,
       embedding <=> %s AS distance
FROM chunks
ORDER BY distance
LIMIT %s
"""

# Same query, but only looks at chunks from one session.
# WHERE goes after FROM and before ORDER BY, so the 3 %s slots are: vector, session, k
SEARCH_SQL_BY_SESSION = """
SELECT chunk_id, session, subtopic, heading_path, text,
       embedding <=> %s AS distance
FROM chunks
WHERE session = %s
ORDER BY distance
LIMIT %s
"""

# One row per session, for the UI dropdown. DISTINCT collapses the many chunks of a session into one row.
LIST_SESSIONS_SQL = """
SELECT DISTINCT session, title
FROM chunks
ORDER BY session
"""
# Every chunk of one session, in reading order (for quizzes and session overviews).
SESSION_CHUNKS_SQL = """
SELECT chunk_id, session, heading_path, text
FROM chunks
WHERE session = %s
ORDER BY chunk_id
"""

def search(question: str, k: int = 5, model=None, session: int | None = None) -> list[dict]:
    """Return the k chunks closest in meaning to the question, best first.

    session=None searches every session; session=1 searches only session 1.
    """
    if model is None:
        model = load_model()        # slow: callers asking many questions should pass a model in

    question_vector = np.array(embed(model, [question])[0])  # normalise_embeddings= True

    load_dotenv(".env")             # for DATABASE_URL
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        register_vector(conn)
        if session is None:
            # 2 %s slots, left to right: the question vector, then k
            rows = conn.execute(SEARCH_SQL, (question_vector, k)).fetchall()
        else:
            # 3 %s slots, left to right: the question vector, the session, then k
            rows = conn.execute(SEARCH_SQL_BY_SESSION, (question_vector, session, k)).fetchall()

    results = []
    for row in rows:
        chunk_id, session_of_chunk, subtopic, heading_path, text, distance = row
        score = 1 - distance          # distance 0 = same meaning, so score 1 = most similar
        results.append({
            "chunk_id": chunk_id,
            "session": session_of_chunk,
            "subtopic": subtopic,
            "heading_path": heading_path,
            "text": text,
            "score": score,
        })
    return results


def list_sessions() -> list[dict]:
    """Return every session once, in order, e.g. [{"session": 1, "title": "..."}, ...]."""
    load_dotenv(".env")             # for DATABASE_URL
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute(LIST_SESSIONS_SQL).fetchall()

    sessions = []
    for row in rows:
        session, title = row
        sessions.append({"session": session, "title": title})
    return sessions

def get_session_chunks(session: int) -> list[dict]:
    """It returns every chunk of one session in reading order"""
    load_dotenv(".env")             # for DATABASE_URL
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute(SESSION_CHUNKS_SQL, (session,)).fetchall()
    chunks = []
    for row in rows:
        chunk_id,session_of_chunk, heading_path, text  = row
        chunks.append({"chunk_id": chunk_id, "session": session_of_chunk, "heading_path":heading_path, "text":text})
    return chunks

def main() -> None:
    # sys.argv = ['rag/search.py', 'your question', optional session number]
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python -m rag.search "your question" [session]')
    question = sys.argv[1]

    session = None
    if len(sys.argv) >= 3:
        session = int(sys.argv[2])  # command-line arguments are strings, the column is INT

    for rank, result in enumerate(search(question, session=session), start=1):
        print(f"{rank}. score {result['score']:.3f} | {result['chunk_id']} | {result['heading_path']}")
        print(f"   {result['text'][:150]!r}")


if __name__ == "__main__":
    main()
