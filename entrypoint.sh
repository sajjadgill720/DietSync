#!/bin/sh
set -e

# Default port to 8000 if PORT is not set by cloud provider (Render sets PORT=10000)
PORT="${PORT:-8000}"

# If argument is just calling entrypoint itself, shift it off to prevent loops
if [ "$1" = "/app/entrypoint.sh" ] || [ "$1" = "entrypoint.sh" ] || [ "$1" = "./entrypoint.sh" ]; then
    shift
fi

# If first argument is 'worker', start the consumer
if [ "$1" = "worker" ]; then
    echo "[entrypoint] Starting DietSync LangGraph Async Worker..."
    exec python -m worker.consumer
fi

# If custom command passed, execute it
if [ "$#" -gt 0 ]; then
    echo "[entrypoint] Executing custom command: $@"
    exec "$@"
fi

# Default: Run FastAPI with dynamic port binding for Render/Cloud providers
echo "[entrypoint] Starting DietSync FastAPI on 0.0.0.0:$PORT..."
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
