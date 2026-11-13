"""Embed the chunks with BGE-M3 (local) and store them in Postgres (M4 step 4).

Run from the repo root, after `python rag/chunker.py --write`:
    python -m rag.embed_store
(-m runs it as a module, so `from rag.embeddings import ...` is found.)
Safe to re-run: rows are upserted by chunk_id, so there are never duplicates.
Takes ~5 min on the Mac GPU (591 chunks, 2026-11-13).
"""

import json
import os
import time
from pathlib import Path

import numpy as np
import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector

from rag.embeddings import MODEL_NAME, count_tokens, embed, load_model

CHUNKS_FILE = Path(__file__).parent.parent / "data" / "processed" / "chunks.jsonl"
BATCH_SIZE = 16   # chunks per batch; the limit is now the laptop's memory, not an API

UPSERT_SQL = """
INSERT INTO chunks (chunk_id, session, title, url, subtopic, sections, heading_path, text, tokens_est, embedding)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (chunk_id) DO UPDATE SET
    session = EXCLUDED.session, title = EXCLUDED.title, url = EXCLUDED.url,
    subtopic = EXCLUDED.subtopic, sections = EXCLUDED.sections,
    heading_path = EXCLUDED.heading_path, text = EXCLUDED.text,
    tokens_est = EXCLUDED.tokens_est, embedding = EXCLUDED.embedding
"""


def load_chunks() -> list[dict]:
    """Read chunks.jsonl: one JSON chunk per line."""
    chunks = []
    for line in CHUNKS_FILE.read_text(encoding="utf-8").splitlines():
        chunk = json.loads(line)    # one line of JSON text -> one Python dict
        chunks.append(chunk)
    return chunks


def check_token_limit(model, chunks: list[dict]) -> int:
    """Stop if any chunk is longer than the model can read. Returns the total real tokens.

    sentence-transformers cuts long texts silently (there's no truncation=False like Voyage),
    so we check ourselves and fail loudly instead.
    """
    limit = model.max_seq_length       # 8192 for BGE-M3
    total = 0
    longest_id = ""
    longest = 0
    for chunk in chunks:
        n = count_tokens(model, chunk["text"])
        total = total + n
        if n > longest:
            longest_id = chunk["chunk_id"]
            longest = n
        if n > limit:
            raise SystemExit(f"{chunk['chunk_id']} has {n} tokens, over the model's limit of {limit}")
    print(f"Token check OK: longest chunk {longest_id} = {longest:,} real tokens (limit {limit:,})")
    return total


def main() -> None:
    load_dotenv(".env")             # for DATABASE_URL
    chunks = load_chunks()
    if not chunks:
        raise SystemExit("0 chunks loaded: run python rag/chunker.py --write")

    model = load_model()            # load once, before the loop
    total_tokens = check_token_limit(model, chunks)
    print(f"{len(chunks)} chunks to embed with {MODEL_NAME}, {BATCH_SIZE} per batch")

    started = time.time()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        register_vector(conn)       # teaches psycopg the pgvector "vector" type

        for start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[start:start + BATCH_SIZE]

            texts = []
            for chunk in batch:
                texts.append(chunk["text"])

            batch_started = time.time()
            vectors = embed(model, texts)
            seconds = time.time() - batch_started

            # zip pairs chunk 1 with vector 1, chunk 2 with vector 2, ...
            for chunk, embedding in zip(batch, vectors):
                conn.execute(UPSERT_SQL, (
                    chunk["chunk_id"],      # the 10 values fill the 10 %s slots, left to right,
                    chunk["session"],       # in the same order as the columns in UPSERT_SQL
                    chunk["title"],
                    chunk["url"],
                    chunk["subtopic"],
                    chunk["sections"],      # a Python list -> Postgres TEXT[]
                    chunk["heading_path"],
                    chunk["text"],
                    chunk["tokens_est"],
                    np.array(embedding),    # 1024 numbers -> Postgres VECTOR(1024)
                ))

            conn.commit()           # save this batch
            print(f"  batch {start // BATCH_SIZE + 1}: {len(batch)} chunks in {seconds:.1f}s")

        rows = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]

    minutes = (time.time() - started) / 60
    print(f"Done: {rows} rows in the table | {total_tokens:,} real tokens | "
          f"{minutes:.1f} min | $0 (local model)")


if __name__ == "__main__":
    main()
