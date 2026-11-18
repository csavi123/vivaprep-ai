#!/bin/sh
# Starts the API (internal) and the UI (public) inside one container.
# Run by the Dockerfile's CMD. Locally you still use two terminals instead.
set -e                                   # stop the script if any command fails

# 1. API in the background (&), on localhost only: unreachable from outside the container.
#    Only port 7860 (Streamlit) is exposed by HF, so nobody on the internet can call /ask directly.
uvicorn api.main:app --host 127.0.0.1 --port 8000 &
API_PID=$!                               # $! = the process ID of the command we just put in the background

# 2. Wait until the API answers /health (loading BGE-M3 takes a while).
#    The slim image has no curl, so we ask Python to check.
until python -c "import httpx; httpx.get('http://127.0.0.1:8000/health').raise_for_status()" 2>/dev/null; do
  # If the API process already died (e.g. API_TOKEN missing -> it refuses to start), stop here
  # instead of waiting forever. kill -0 sends no signal: it only checks "is this process alive?"
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "API failed to start: see the error above"
    exit 1
  fi
  echo "waiting for API..."
  sleep 2
done
echo "API is up"

# 3. UI in the foreground, on all interfaces (0.0.0.0) and on HF's port 7860.
#    exec: Streamlit REPLACES this shell, so it becomes the main process and receives
#    HF's stop signal directly (a clean shutdown instead of being killed after a timeout).
#    python -m: puts the current folder (the repo root) on Python's path, so `from schemas import ...` works.
exec python -m streamlit run app/app.py \
  --server.port 7860 \
  --server.address 0.0.0.0 \
  --server.headless true
