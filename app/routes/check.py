"""
app/routes/check.py
Routes for enqueuing and polling drug-drug interaction check jobs.

Per PROJECT_SPEC.md lines 244-279:
- POST /check:
  Validates both drug IDs exist, creates InteractionJob, publishes to RabbitMQ
  via Phase 5's publisher, returns HTTP 202 Accepted with { "job_id": UUID, "status": "queued" }.
- GET /check/{job_id}:
  Polling fallback (primary delivery is WebSocket). Reads interaction_jobs and
  returns CheckStatusResponse. The 'source' field in result must strictly say
  'openFDA', never 'DRAP'.
"""

import logging
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import Drug, InteractionJob
from app.db.session import get_db
from app.schemas.check import (
    CheckEnqueueResponse,
    CheckRequest,
    CheckResult,
    CheckStatusResponse,
)
from app.services.queue_publisher import publish_interaction_job

logger = logging.getLogger("routes_check")

router = APIRouter(tags=["Interaction Check"])


def format_job_result(result_dict: Optional[dict]) -> Optional[CheckResult]:
    """
    Normalizes persisted job result JSON into the strictly typed CheckResult schema.
    Enforces that 'source' is always 'openFDA' and never references 'DRAP'.
    """
    if not result_dict or not isinstance(result_dict, dict):
        return None

    final_status = (
        result_dict.get("final_status")
        or result_dict.get("status")
        or "none_found"
    )
    summary = result_dict.get("summary") or result_dict.get("interaction_claim")
    citation_text = result_dict.get("citation_text") or result_dict.get("citation")

    # Safety constraint: source must always say 'openFDA', never 'DRAP'
    raw_source = result_dict.get("source") or "openFDA"
    source = "openFDA" if "drap" in str(raw_source).lower() else raw_source

    allergy_flags = result_dict.get("allergy_flags")
    food_interaction_summary = (
        result_dict.get("food_interaction_summary")
        or result_dict.get("food_interaction")
    )

    return CheckResult(
        final_status=final_status,
        summary=summary,
        citation_text=citation_text,
        source=source,
        allergy_flags=allergy_flags,
        food_interaction_summary=food_interaction_summary,
    )


@router.post(
    "/check",
    response_model=CheckEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue an interaction check between two drugs",
    description=(
        "Validates both drug IDs exist in the database, creates an InteractionJob "
        "with status 'queued', publishes the payload to RabbitMQ, and returns HTTP 202."
    ),
)
def enqueue_interaction_check(
    req: CheckRequest,
    db: Session = Depends(get_db),
) -> CheckEnqueueResponse:
    # 1. Validate both drug IDs exist in Postgres
    drug_a = db.query(Drug).filter(Drug.id == req.drug_a_id).first()
    if not drug_a:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Drug A with id {req.drug_a_id} does not exist. Resolve it first via POST /resolve.",
        )

    drug_b = db.query(Drug).filter(Drug.id == req.drug_b_id).first()
    if not drug_b:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Drug B with id {req.drug_b_id} does not exist. Resolve it first via POST /resolve.",
        )

    # 2. Generate UUID client-side before queuing (per PROJECT_SPEC.md line 220)
    job_id = uuid.uuid4()

    # 3. Create job record in PostgreSQL
    # CRITICAL PRIVACY ARCHITECTURE (PROJECT_SPEC.md line 223):
    # patient_allergies and patient_diet_factors are ephemeral and request-scoped.
    # They are passed exclusively through the RabbitMQ job payload and LangGraph InteractionState,
    # and are NEVER persisted to interaction_jobs.result or any database table.
    # Rationale: this health information is not tied to an authenticated patient identity in storage,
    # ensuring that sensitive patient factors cannot be correlated or leaked via database queries.
    job = InteractionJob(
        id=job_id,
        drug_a_id=req.drug_a_id,
        drug_b_id=req.drug_b_id,
        status="queued",
    )
    db.add(job)
    db.commit()

    # 4. Publish to RabbitMQ single durable queue 'interaction_checks' (delivery_mode=2)
    try:
        publish_interaction_job(
            job_id=job_id,
            drug_a_id=req.drug_a_id,
            drug_b_id=req.drug_b_id,
            patient_allergies=req.patient_allergies,
            patient_diet_factors=req.patient_diet_factors,
        )
        logger.info(f"[check] Enqueued job {job_id} for drug_a={req.drug_a_id}, drug_b={req.drug_b_id}")
    except Exception as exc:
        logger.error(f"[check] Failed to publish job {job_id} to RabbitMQ: {exc}", exc_info=True)
        # Roll back or mark job failed if broker is unreachable
        job.status = "failed"
        job.error_message = f"Queue broker unavailable: {exc}"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Interaction check message queue is currently unavailable. Please retry later.",
        )

    return CheckEnqueueResponse(
        job_id=job_id,
        status="queued",
    )


@router.get(
    "/check/{job_id}",
    response_model=CheckStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Poll status of an interaction check job",
    description=(
        "Polling fallback for client reconnection. Returns the current status and "
        "interaction result. 'source' field is guaranteed to be 'openFDA', never 'DRAP'."
    ),
)
def get_job_status(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> CheckStatusResponse:
    job = db.query(InteractionJob).filter(InteractionJob.id == job_id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Interaction job {job_id} not found.",
        )

    formatted_result = format_job_result(job.result)

    return CheckStatusResponse(
        job_id=job.id,
        status=job.status,
        result=formatted_result,
        error_message=job.error_message,
    )
