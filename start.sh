#!/bin/sh
set -e

PORT="${PORT:-8000}"

echo "=================================================="
echo " Starting DietSync All-in-One Service (API + Worker) "
echo " Port: $PORT"
echo "=================================================="

# Start LangGraph worker in background with auto-reconnect
(
    while true; do
        echo "[worker] Starting LangGraph RabbitMQ Consumer..."
        python -m worker.consumer || true
        echo "[worker] Consumer disconnected or stopped. Reconnecting in 5s..."
        sleep 5
    done
) &

# Start FastAPI Uvicorn in foreground binding to 0.0.0.0:$PORT
echo "[api] Starting FastAPI on 0.0.0.0:$PORT..."
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
