#!/usr/bin/env python3
"""
scripts/test_end_to_end_job.py
End-to-end integration test verifying DietSync's asynchronous job pipeline:
1. Creates an InteractionJob in PostgreSQL (status='queued').
2. Publishes payload {job_id, drug_a_id, drug_b_id} via services/queue_publisher.py (delivery_mode=2).
3. Executes worker/consumer.py to consume the message, re-fetch context, run LangGraph,
   persist final status ('done'/'failed'), and emit PostgreSQL NOTIFY.
4. Polls interaction_jobs until completion and displays the verified result.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo root and app directory are on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "app"))

from app.db.models import Drug, InteractionJob
from app.services.queue_publisher import publish_interaction_job
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from worker.consumer import start_consumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("test_e2e_job")

DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/dietsync"


def get_db_session():
    db_url = os.getenv("DATABASE_URL", DEFAULT_DB_URL)
    if db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg2://" + db_url.split("://", 1)[1]

    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect():
            pass
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        return SessionLocal()
    except Exception as exc:
        err_msg = str(exc).lower()
        is_conn_refused = "connection refused" in err_msg or "10061" in err_msg or "timeout" in err_msg
        if sys.platform == "win32" and is_conn_refused and "--no-wsl-delegate" not in sys.argv:
            logger.info("Local Windows connection refused. Delegating execution to WSL...")
            wsl_cmd = [
                "wsl",
                "-d",
                "Ubuntu",
                "-u",
                "root",
                "--",
                "bash",
                "-l",
                "-c",
                "cd /root/dietsync && DATABASE_URL=postgresql://postgres:postgres@localhost:5432/dietsync "
                "/opt/dietsync_venv/bin/python scripts/test_end_to_end_job.py --no-wsl-delegate "
                + " ".join(f'"{a}"' for a in sys.argv[1:] if a != "--no-wsl-delegate"),
            ]
            res = subprocess.run(wsl_cmd)
            sys.exit(res.returncode)
        raise exc


def test_end_to_end_pipeline():
    session = get_db_session()

    print("\n" + "=" * 75)
    print("1. Selecting Interacting Drug Pair from PostgreSQL")
    print("=" * 75)

    # Pick Klaricid (Clarithromycin) and Lipitor (Atorvastatin)
    drug_a = session.query(Drug).filter(Drug.brand_name.ilike("%klaricid%")).first()
    drug_b = session.query(Drug).filter(Drug.brand_name.ilike("%lipitor%")).first()

    if not drug_a or not drug_b:
        # Fallback to Disprin and Warfarin if Klaricid/Lipitor not found
        drug_a = session.query(Drug).filter(Drug.brand_name.ilike("%disprin%")).first()
        drug_b = session.query(Drug).filter(Drug.brand_name.ilike("%warfarin%")).first()

    assert drug_a and drug_b, "Could not find a valid test drug pair in PostgreSQL database"

    print(f"[+] Drug A: {drug_a.brand_name} (ID: {drug_a.id})")
    print(f"[+] Drug B: {drug_b.brand_name} (ID: {drug_b.id})")

    print("\n" + "=" * 75)
    print("2. Creating InteractionJob in PostgreSQL (status='queued')")
    print("=" * 75)

    job_id = uuid.uuid4()
    job = InteractionJob(
        id=job_id,
        drug_a_id=drug_a.id,
        drug_b_id=drug_b.id,
        status="queued",
        created_at=datetime.now(timezone.utc),
    )
    session.add(job)
    session.commit()
    print(f"[+] Created InteractionJob with ID: {job_id}, status: '{job.status}'")

    print("\n" + "=" * 75)
    print("3. Publishing to RabbitMQ Queue 'interaction_checks' (delivery_mode=2)")
    print("=" * 75)

    payload = publish_interaction_job(
        job_id=job_id,
        drug_a_id=drug_a.id,
        drug_b_id=drug_b.id,
    )
    print(f"[+] Published payload: {json.dumps(payload)}")

    print("\n" + "=" * 75)
    print("4. Starting Consumer Worker in Background to Process 1 Job")
    print("=" * 75)

    # Start consumer in thread to process the single queued job
    consumer_thread = threading.Thread(
        target=start_consumer,
        kwargs={"max_messages": 1},
        daemon=True,
    )
    consumer_thread.start()
    print("[+] Consumer thread spawned and listening with prefetch_count=1...")

    print("\n" + "=" * 75)
    print("5. Polling PostgreSQL 'interaction_jobs' for Completion")
    print("=" * 75)

    timeout = 15.0
    poll_start = time.time()
    final_job_status = None
    final_result = None

    while (time.time() - poll_start) < timeout:
        session.expire_all()
        current_job = session.query(InteractionJob).filter(InteractionJob.id == job_id).first()
        if current_job:
            status = current_job.status
            elapsed = time.time() - poll_start
            print(f"  [Poll {elapsed:.2f}s] Job status in DB: '{status}'")
            if status in ("done", "failed"):
                final_job_status = status
                final_result = current_job.result
                break
        time.sleep(0.4)

    consumer_thread.join(timeout=3.0)
    session.close()

    print("\n" + "=" * 75)
    print("6. Job Execution Verification Results")
    print("=" * 75)
    print(f"Final Job Status:   '{final_job_status}'")
    print(f"Result Payload:\n{json.dumps(final_result, indent=4)}")

    assert final_job_status == "done", f"Expected job status 'done', got '{final_job_status}'"
    assert final_result is not None, "Expected result to be populated"
    print("\n[PASSED] End-to-end asynchronous job pipeline successfully verified!")


if __name__ == "__main__":
    test_end_to_end_pipeline()
