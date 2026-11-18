# VivaPrep AI: one image with the FastAPI backend (internal) + the Streamlit UI (public, port 7860).
# Build:  docker build -t vivaprep .
# Run:    docker run --rm -p 7860:7860 --env-file .env.docker vivaprep
# Secrets (ANTHROPIC_API_KEY, DATABASE_URL, API_TOKEN) are NOT in this file: they arrive at runtime
# as environment variables (--env-file locally, Space secrets on Hugging Face).

FROM python:3.12-slim

# HF runs containers as user ID 1000 (from HF's Docker Spaces docs), so we build as that user too
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    EMBED_DEVICE=cpu
# PATH: pip installs as a non-root user go to ~/.local, so uvicorn/streamlit commands live in ~/.local/bin
# PYTHONUNBUFFERED: print() shows up in the logs immediately, not in delayed batches
# EMBED_DEVICE: no GPU here (read by rag/embeddings.py load_model())

# Create the app folder (and logs/, where llm.py writes the cost log) as `user`, so both are writable
RUN mkdir -p $HOME/app/logs
WORKDIR $HOME/app

# 1. CPU-only torch first. The default Linux build includes CUDA (several GB we can't use).
#    Same version as requirements.txt, because sentence-transformers was tested with it.
RUN pip install --no-cache-dir torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu

# 2. The other runtime dependencies. Copied BEFORE the code: Docker reuses this slow layer
#    from its cache as long as requirements-deploy.txt hasn't changed, even when the code has.
COPY --chown=user requirements-deploy.txt .
RUN pip install --no-cache-dir -r requirements-deploy.txt

# 3. Download BGE-M3 (~2 GB) at BUILD time, so the container doesn't download it on every start.
#    Reuses our own load_model(), so the pinned MODEL_REVISION lives in one place only.
#
#    The download leaves TWO copies of the weights (2.2 GB each):
#      - pytorch_model.bin   from our pinned revision -> the one actually loaded at runtime
#      - model.safetensors   a format conversion transformers fetches from another revision.
#        Offline it can't find it, so it's never used (tested: deleting it gives identical embeddings,
#        deleting the .bin instead breaks loading).
#    So we delete the safetensors: image ~9.8 GB -> ~5.5 GB.
#
#    Line by line:
#      1. download the model (as before)
#      2. find the safetensors shortcut (a symlink in snapshots/<revision>/); ls fails the build if it's missing
#      3. delete the real file (readlink -f follows the shortcut into blobs/) AND the shortcut itself
#      4. guard: load again OFFLINE, exactly like at runtime, so the build fails if we deleted the wrong file
#    All in ONE RUN: a delete in a later RUN only hides the file; it would still sit in this layer.
COPY --chown=user rag/embeddings.py rag/embeddings.py
RUN python -c "from rag.embeddings import load_model; load_model()" \
 && SHORTCUT=$(ls $HOME/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/*/model.safetensors) \
 && rm "$(readlink -f "$SHORTCUT")" "$SHORTCUT" \
 && HF_HUB_OFFLINE=1 python -c "from rag.embeddings import load_model; load_model()"
# From now on, use the downloaded copy and never call the Hugging Face Hub at runtime
ENV HF_HUB_OFFLINE=1

# 4. The app code (last, because it changes most often). .dockerignore keeps .env, data/, etc. out.
COPY --chown=user . .

EXPOSE 7860
CMD ["sh", "start.sh"]
