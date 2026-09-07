"""
worker/consumer.py
RabbitMQ consumer for DietSync's asynchronous interaction check pipeline.

Per PROJECT_SPEC.md:
- Uses prefetch_count=1 for predictable load distribution across worker instances.
- Re-fetches full drug context from Postgres using drug IDs (never trusts queue
  payload as source of truth).
- Runs the LangGraph interaction checking state machine.
- Writes the result to interaction_jobs with status 'done' or 'failed'.
- Acks failed jobs (preventing infinite poison message loops against the LLM API).
- Fires a PostgreSQL NOTIFY on a per-job channel (job_<job_id>) for WebSocket delivery.
"""

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pika
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure repo root and app directory are on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "app"))

from app.db.listeners import notify_channel
from app.db.models import Drug, DrugIngredient, FDALabel, InteractionJob
from app.services.queue_publisher import (
    DEFAULT_RABBITMQ_URL,
    QUEUE_NAME,
    get_connection_parameters,
)
from worker.langgraph.graph import graph, invoke_interaction_graph
from worker.langgraph.nodes import InteractionState


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("worker_consumer")


def get_db_session():
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/dietsync")
    if db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg2://" + db_url.split("://", 1)[1]
    engine = create_engine(db_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def process_message(ch, method, properties, body: bytes):
    """
    Callback processing each interaction job message.
    """
    logger.info(f"[consumer] Received message delivery_tag={method.delivery_tag}")

    session = get_db_session()
    job_id = None

    try:
        payload = json.loads(body.decode("utf-8"))
        job_id_str = payload.get("job_id")
        drug_a_id = payload.get("drug_a_id")
        drug_b_id = payload.get("drug_b_id")
        patient_allergies = payload.get("patient_allergies", [])
        patient_diet_factors = payload.get("patient_diet_factors", [])

        if not job_id_str or drug_a_id is None or drug_b_id is None:
            raise ValueError(f"Malformed queue payload: {payload}")

        job_id = uuid.UUID(job_id_str)
        logger.info(f"[consumer] Processing job {job_id} (Drug A: {drug_a_id}, Drug B: {drug_b_id})")

        # Mark job as processing in PostgreSQL
        job = session.query(InteractionJob).filter(InteractionJob.id == job_id).first()
        if job:
            job.status = "processing"
            session.commit()

        # RE-FETCH FULL CONTEXT FROM POSTGRES (Never trust queue payload as source of truth)
        drug_a = session.query(Drug).filter(Drug.id == drug_a_id).first()
        drug_b = session.query(Drug).filter(Drug.id == drug_b_id).first()

        if not drug_a:
            raise RuntimeError(f"Drug A (id={drug_a_id}) not found in PostgreSQL")
        if not drug_b:
            raise RuntimeError(f"Drug B (id={drug_b_id}) not found in PostgreSQL")

        # Prepare state for LangGraph
        initial_state: InteractionState = {
            "drug_a": {
                "id": drug_a.id,
                "brand_name": drug_a.brand_name,
                "generic_name": drug_a.ingredients[0].generic_name if drug_a.ingredients else None,
                "rxcui": drug_a.ingredients[0].rxcui if drug_a.ingredients else None,
            },
            "drug_b": {
                "id": drug_b.id,
                "brand_name": drug_b.brand_name,
                "generic_name": drug_b.ingredients[0].generic_name if drug_b.ingredients else None,
                "rxcui": drug_b.ingredients[0].rxcui if drug_b.ingredients else None,
            },
            "patient_allergies": patient_allergies,
            "patient_diet_factors": patient_diet_factors,
            "interaction_claim": None,
            "citation_text": None,
            "is_grounded": None,
            "allergy_flags": [],
            "food_interaction_claim": None,
            "food_citation_text": None,
            "final_status": "none_found",
            "final_answer": None,
        }

        # Run the compiled LangGraph workflow with LangSmith tracing enabled
        logger.info(f"[consumer] Executing LangGraph for job {job_id}...")
        final_state = invoke_interaction_graph(
            initial_state,
            config={"metadata": {"job_id": str(job_id)}},
        )

        final_answer = final_state.get("final_answer")


        # Record completed result in PostgreSQL
        # PRIVACY GUARANTEE: final_answer contains only clinical findings (allergy_flags,
        # food_interaction, drug_interaction summary, citations). The ephemeral patient_allergies
        # and patient_diet_factors inputs are NEVER persisted to job.result or any database table,
        # as they are request-scoped and deliberately not tied to a patient identity in storage.
        job = session.query(InteractionJob).filter(InteractionJob.id == job_id).first()
        if job:
            job.status = "done"
            job.result = final_answer
            job.completed_at = datetime.now(timezone.utc)
            job.error_message = None
            session.commit()
            logger.info(f"[consumer] Job {job_id} successfully persisted with status='done'")

        # Fire Postgres NOTIFY on per-job channel
        notify_payload = json.dumps({
            "job_id": str(job_id),
            "status": "done",
            "result": final_answer,
        })
        channel_name = f"job_{str(job_id).replace('-', '_')}"
        notify_channel(channel_name, notify_payload)
        logger.info(f"[consumer] Fired NOTIFY on channel '{channel_name}'")

    except Exception as exc:
        session.rollback()
        err_msg = str(exc)
        logger.error(f"[consumer] Error processing job {job_id}: {err_msg}", exc_info=True)

        # Record failed job in PostgreSQL (prevent poison messages from looping)
        if job_id:
            try:
                job = session.query(InteractionJob).filter(InteractionJob.id == job_id).first()
                if job:
                    job.status = "failed"
                    job.error_message = err_msg
                    job.completed_at = datetime.now(timezone.utc)
                    session.commit()

                notify_payload = json.dumps({
                    "job_id": str(job_id),
                    "status": "failed",
                    "error": err_msg,
                })
                channel_name = f"job_{str(job_id).replace('-', '_')}"
                notify_channel(channel_name, notify_payload)
            except Exception as notify_err:
                logger.error(f"[consumer] Failed to update job failure record: {notify_err}")

    finally:
        session.close()
        # Always ACK message so failed jobs do not loop forever
        ch.basic_ack(delivery_tag=method.delivery_tag)


def start_consumer(
    rabbitmq_url: Optional[str] = None,
    max_messages: Optional[int] = None,
    stop_event=None,
):
    """
    Starts the RabbitMQ consumer with prefetch_count=1.
    """
    params = get_connection_parameters(rabbitmq_url)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()

    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    # prefetch_count=1 ensures worker takes only one job at a time
    channel.basic_qos(prefetch_count=1)

    logger.info(f"[consumer] Connected to RabbitMQ. Listening on '{QUEUE_NAME}' (prefetch=1)...")

    messages_processed = 0

    for method, properties, body in channel.consume(queue=QUEUE_NAME, auto_ack=False):
        process_message(channel, method, properties, body)
        messages_processed += 1

        if stop_event and stop_event.is_set():
            logger.info("[consumer] Stop event received, exiting loop.")
            break
        if max_messages and messages_processed >= max_messages:
            logger.info(f"[consumer] Reached limit of {max_messages} message(s), exiting loop.")
            break

    channel.cancel()
    channel.close()
    connection.close()


if __name__ == "__main__":
    start_consumer()
