-- The chunks table: one row per chunk, with its embedding (M4, D014/D017).
-- Safe to run again: IF NOT EXISTS skips anything that already exists.

-- 1. Turn on pgvector in this database (adds the "vector" type)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. The table
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id      TEXT PRIMARY KEY,          -- e.g. 's01-c003'
    session       INT    NOT NULL,
    title         TEXT   NOT NULL,
    url           TEXT   NOT NULL,
    subtopic      TEXT   NOT NULL,
    sections      TEXT[] NOT NULL,           -- a list of section names
    heading_path  TEXT   NOT NULL,
    text          TEXT   NOT NULL,
    tokens_est    INT    NOT NULL,
    embedding     VECTOR(1024) NOT NULL      -- Voyage voyage-4-lite: 1024 numbers
);

-- 3. The vector index, for fast cosine-similarity search
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
