"""The one place that turns text into vectors (D018: BGE-M3, running locally).

Chunks (embed_store.py) and questions (search) both use this file,
so they are always embedded by the same model, the same way.
"""

from sentence_transformers import SentenceTransformer

MODEL_NAME = "BAAI/bge-m3"   # 1024 dimensions, reads up to 8192 tokens
# The exact model version downloaded on 2026-11-13 (like a git commit hash).
# Pinned so the weights can't change under us: stored vectors and new question
# vectors must always come from the same model.
MODEL_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
DEVICE = "mps"               # the Mac's GPU; use "cpu" on other machines


def load_model() -> SentenceTransformer:
    """Load BGE-M3 once (a few seconds from the cache). It's slow, so don't call it in a loop."""
    return SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, device=DEVICE)


def count_tokens(model: SentenceTransformer, text: str) -> int:
    """The real token count, using the model's own tokenizer (not the chars/4 estimate)."""
    return len(model.tokenizer(text)["input_ids"])


def embed(model: SentenceTransformer, texts: list[str]) -> list:
    """Turn texts into unit-length vectors (length 1), one per text, in the same order."""
    return model.encode(texts, normalize_embeddings=True)
