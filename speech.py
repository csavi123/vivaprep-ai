"""Speech-to-text for spoken quiz answers (faster-whisper, running locally).

Used by POST /transcribe in api/main.py. Claude's API takes text, not audio,
so the student's recording is turned into text here first.

Why local Whisper (same reasons as BGE-M3, D018): free, and the audio never leaves this machine.
"""

import io
import os
import time

from faster_whisper import WhisperModel

# "base.en": English-only, ~145 MB, a few seconds for a 30-second answer on a Mac CPU.
# Override with WHISPER_MODEL in .env (e.g. "small.en": better with technical words, ~3x slower).
DEFAULT_WHISPER_MODEL = "base.en"

# Course words a generic speech model often mishears. Whisper reads this as "earlier text",
# so it expects these spellings (e.g. "pgvector", not "PG vector").
COURSE_VOCABULARY = (
    "AI engineering course: LLM, tokens, context window, RAG, retrieval-augmented generation, "
    "embeddings, cosine similarity, pgvector, BM25, hybrid search, reranker, chunking, top-k, "
    "hallucination, grounding, fine-tuning, LoRA, evals, LLM-as-judge, agents, tool calling, MCP, "
    "Pydantic, FastAPI, structured output, prompt injection."
)

# The one Whisper model in this process. None = not loaded yet (loaded on the first transcription,
# so starting the API, and every /ask or /chat request, doesn't pay for it).
_whisper_model = None


def get_whisper_model() -> WhisperModel:
    """Load Whisper on the first call, then return the same copy (the get_shared_model() pattern)."""
    global _whisper_model
    if _whisper_model is None:
        model_name = os.environ.get("WHISPER_MODEL", DEFAULT_WHISPER_MODEL)
        # device="cpu": faster-whisper doesn't use the Mac GPU (mps).
        # compute_type="int8": smaller numbers in the weights, faster on CPU with almost the same accuracy.
        _whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
    return _whisper_model


def transcribe(audio_bytes: bytes) -> dict:
    """Turn one recording (WAV, MP3, ...) into text.

    Returns {"text", "duration_s", "latency_s"}: what was said, how long the recording is,
    and how long transcribing took.
    """
    start_time = time.perf_counter()
    model = get_whisper_model()

    # io.BytesIO: faster-whisper reads a file, so wrap the bytes to look like one (no temp file on disk)
    segments, info = model.transcribe(
        io.BytesIO(audio_bytes),
        language="en",                     # the course is in English: skip language detection
        initial_prompt=COURSE_VOCABULARY,
        vad_filter=True,                   # skip silent parts (voice activity detection), so pauses aren't transcribed
    )

    # segments is a generator: the transcription actually runs while we loop over it
    texts = []
    for segment in segments:
        texts.append(segment.text.strip())
    text = " ".join(texts)

    return {
        "text": text,
        "duration_s": info.duration,
        "latency_s": time.perf_counter() - start_time,
    }
