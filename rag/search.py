"""Find the chunks closest in meaning to a question (M4 step 5: the "R" in RAG).

Run from the repo root:
    python -m rag.search "What is a token?"
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


def search(question: str, k: int = 5, model=None) -> list[dict]:
    """Return the k chunks closest in meaning to the question, best first."""
    if model is None:
        model = load_model()        # slow: callers asking many questions should pass a model in

    question_vector = embed(model, [question])[0]  # normalise_embeddings= True

    load_dotenv(".env")             # for DATABASE_URL
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        register_vector(conn)
        # The 2 %s slots fill left to right: 1st = the question vector, 2nd = k
        rows = conn.execute(SEARCH_SQL, (np.array(question_vector), k)).fetchall()

    results = []
    for row in rows:
        chunk_id, session, subtopic, heading_path, text, distance = row
        score = 1 - distance          # distance 0 = same meaning, so score 1 = most similar
        results.append({
            "chunk_id": chunk_id,
            "session": session,
            "subtopic": subtopic,
            "heading_path": heading_path,
            "text": text,
            "score": score,
        })
    return results


def main() -> None:
    # sys.argv = ['rag/search.py', 'your question']: [0] is the script, [1] is the question
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python -m rag.search "your question"')
    question = sys.argv[1]

    for rank, result in enumerate(search(question), start=1):
        print(f"{rank}. score {result['score']:.3f} | {result['chunk_id']} | {result['heading_path']}")
        print(f"   {result['text'][:150]!r}")


if __name__ == "__main__":
    main()