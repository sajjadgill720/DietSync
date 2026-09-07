"""
app/routes/resolve.py
Synchronous drug resolution endpoint: dataset lookup first, DRAP fallback if not found.

Per PROJECT_SPEC.md lines 227-243:
- POST /resolve
- Request: { "query": str }
- Response:
  {
    "status": "resolved" | "ambiguous" | "not_found",
    "drug": { "drug_id": int, "display_name": str, "dosage_form": str | null } | null,
    "candidates": [ ...same shape... ] | null
  }

CRITICAL ARCHITECTURAL CONSTRAINTS:
1. Kept synchronous (deliberately not queued — DRAP fallback is expected to complete
   in well under a second).
2. Never returns drap_reg_no or any DRAP-sourced field name in the response.
3. If ambiguous, candidate objects surface only display names and optional dosage forms.
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.resolve import DrugCandidate, ResolveRequest, ResolveResponse, ResolvedDrug
from app.services.drug_resolution import resolve_drug

logger = logging.getLogger("routes_resolve")

router = APIRouter(tags=["Resolution"])


@router.post(
    "/resolve",
    response_model=ResolveResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve a drug brand or generic name",
    description=(
        "Synchronously resolves a single drug query: checks PostgreSQL dataset first, "
        "falls back to DRAP if not found. Never exposes DRAP registration numbers or internal sources."
    ),
)
def resolve_drug_endpoint(
    req: ResolveRequest,
    db: Session = Depends(get_db),
) -> ResolveResponse:
    query = req.query.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query parameter must not be empty.",
        )

    res_status, drug, candidates_data = resolve_drug(query, db)

    if res_status == "resolved" and drug:
        return ResolveResponse(
            status="resolved",
            drug=ResolvedDrug(
                drug_id=drug.id,
                display_name=drug.brand_name,
                dosage_form=drug.dosage_form,
            ),
            candidates=None,
        )

    elif res_status == "ambiguous" and candidates_data:
        candidates: List[DrugCandidate] = [
            DrugCandidate(
                drug_id=c.get("drug_id"),
                display_name=c.get("display_name"),
                dosage_form=c.get("dosage_form"),
            )
            for c in candidates_data
        ]
        return ResolveResponse(
            status="ambiguous",
            drug=None,
            candidates=candidates,
        )

    else:
        return ResolveResponse(
            status="not_found",
            drug=None,
            candidates=None,
        )
