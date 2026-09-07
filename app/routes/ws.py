"""
app/routes/ws.py
WebSocket route for real-time notification of completed interaction check jobs.

Per PROJECT_SPEC.md line 281:
- WS /ws/jobs/{job_id}:
  Opened by the client immediately after receiving a job_id from POST /check.
  Server subscribes to that job's Postgres LISTEN channel via db/listeners.py,
  pushes the completed CheckStatusResponse the moment the worker marks the job
  done/failed, then closes.
"""

import asyncio
import json
import logging
import uuid
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.db.listeners import listen_channel
from app.db.models import InteractionJob
from app.db.session import SessionLocal
from app.routes.check import format_job_result
from app.schemas.check import CheckResult, CheckStatusResponse

logger = logging.getLogger("routes_ws")

router = APIRouter(tags=["WebSocket Updates"])


def _fetch_job_status_response(job_id: uuid.UUID) -> Optional[CheckStatusResponse]:
    """Helper to query the current job status from DB and return typed response."""
    db = SessionLocal()
    try:
        job = db.query(InteractionJob).filter(InteractionJob.id == job_id).first()
        if not job:
            return None
        return CheckStatusResponse(
            job_id=job.id,
            status=job.status,
            result=format_job_result(job.result),
            error_message=job.error_message,
        )
    finally:
        db.close()


@router.websocket("/ws/jobs/{job_id}")
async def job_status_websocket(
    websocket: WebSocket,
    job_id: uuid.UUID,
):
    """
    Subscribes to the PostgreSQL LISTEN channel for the given job_id.
    Pushes the completed CheckStatusResponse once the job reaches 'done' or 'failed',
    then closes the connection.
    """
    await websocket.accept()
    logger.info(f"[ws] Accepted WebSocket connection for job {job_id}")

    # 1. Check if job is already finished (race condition defense)
    initial_response = _fetch_job_status_response(job_id)
    if initial_response and initial_response.status in ("done", "failed"):
        logger.info(f"[ws] Job {job_id} already finished ({initial_response.status}). Pushing immediately.")
        await websocket.send_text(initial_response.model_dump_json())
        await websocket.close(code=1000)
        return

    # 2. Subscribe to PostgreSQL LISTEN channel via db/listeners.py
    # Channel name matches worker/consumer.py convention: job_<uuid_with_underscores>
    channel_name = f"job_{str(job_id).replace('-', '_')}"

    try:
        # Listen for up to 120 seconds for worker notification
        async for notify in listen_channel(channel=channel_name, timeout=120.0):
            logger.info(f"[ws] Received notification on channel '{channel_name}': {notify.payload}")

            # Re-fetch authoritative job state from PostgreSQL
            latest_response = _fetch_job_status_response(job_id)

            if not latest_response and notify.payload:
                # Fallback parse from notification payload if available
                try:
                    payload_data = json.loads(notify.payload)
                    raw_result = payload_data.get("result")
                    latest_response = CheckStatusResponse(
                        job_id=job_id,
                        status=payload_data.get("status", "done"),
                        result=format_job_result(raw_result),
                        error_message=payload_data.get("error"),
                    )
                except Exception as parse_err:
                    logger.warning(f"[ws] Could not parse notify payload: {parse_err}")

            if latest_response:
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_text(latest_response.model_dump_json())
                    logger.info(f"[ws] Pushed final result for job {job_id} to client. Closing socket.")
                    await websocket.close(code=1000)
                return

        # If timeout elapsed without notification, do one final DB check
        final_check = _fetch_job_status_response(job_id)
        if final_check and websocket.client_state == WebSocketState.CONNECTED:
            await websocket.send_text(final_check.model_dump_json())
            await websocket.close(code=1000)
        elif websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close(code=1000)

    except WebSocketDisconnect:
        logger.info(f"[ws] Client disconnected from job {job_id}")
    except Exception as exc:
        logger.error(f"[ws] Unexpected error in WebSocket for job {job_id}: {exc}", exc_info=True)
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close(code=1011)
            except Exception:
                pass
