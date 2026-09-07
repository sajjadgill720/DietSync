"""
app/schemas/check.py
Pydantic schemas for the drug interaction check endpoints (POST /check, GET /check/{job_id}).

Per PROJECT_SPEC.md lines 248-280:
- POST /check:
  Request:
  {
    "drug_a_id": int,
    "drug_b_id": int,
    "patient_allergies": [str] | null,
    "patient_diet_factors": [str] | null
  }
  Response (HTTP 202): { "job_id": UUID, "status": "queued" }

- GET /check/{job_id}:
  Response:
  {
    "job_id": UUID,
    "status": "queued" | "processing" | "done" | "failed",
    "result": {
      "final_status": "interaction_found" | "none_found" | "unverifiable",
      "summary": str | null,
      "citation_text": str | null,
      "source": str | null,             // "openFDA" — never "DRAP"
      "allergy_flags": [ ... ] | null,
      "food_interaction_summary": str | null
    } | null,
    "error_message": str | null
  }
"""

import uuid
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class CheckRequest(BaseModel):
    drug_a_id: int = Field(..., description="Database primary key of Drug A")
    drug_b_id: int = Field(..., description="Database primary key of Drug B")
    patient_allergies: Optional[List[str]] = Field(
        default=None,
        description="Optional list of reported patient allergies (ephemeral, request-scoped — never persisted)",
    )
    patient_diet_factors: Optional[List[str]] = Field(
        default=None,
        description="Optional list of reported dietary habits/supplements (ephemeral, request-scoped — never persisted)",
    )


class CheckEnqueueResponse(BaseModel):
    job_id: uuid.UUID = Field(..., description="Unique job identifier for polling or WebSocket subscription")
    status: Literal["queued"] = Field(default="queued", description="Initial queue state")


class CheckResult(BaseModel):
    final_status: Literal["interaction_found", "none_found", "unverifiable"] = Field(
        ...,
        description="Outcome of interaction check and groundedness audit",
    )
    summary: Optional[str] = Field(
        default=None,
        description="Human-readable interaction mechanism or 'No drug-drug interaction was found...'",
    )
    citation_text: Optional[str] = Field(
        default=None,
        description="Verbatim quoted sentence from official manufacturer label text",
    )
    source: Optional[str] = Field(
        default="openFDA",
        description="Authoritative source of clinical label data. Strictly 'openFDA', never 'DRAP'.",
    )
    allergy_flags: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Flags identifying potential drug-class allergy cross-reactivity",
    )
    food_interaction_summary: Optional[str] = Field(
        default=None,
        description="Summary of food/grapefruit/alcohol/dietary interactions from label text",
    )

    @field_validator("source", mode="before")
    @classmethod
    def enforce_openfda_source(cls, v: Optional[str]) -> str:
        """
        Enforce architectural constraint: user-facing clinical source must always be
        'openFDA', never 'DRAP'.
        """
        if v and "drap" in v.lower():
            return "openFDA"
        return v or "openFDA"


class CheckStatusResponse(BaseModel):
    job_id: uuid.UUID = Field(..., description="Unique UUID identifier of the job")
    status: Literal["queued", "processing", "done", "failed"] = Field(
        ...,
        description="Current state of the interaction check job",
    )
    result: Optional[CheckResult] = Field(
        default=None,
        description="Evaluation result (populated once job is 'done')",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error description if status is 'failed'",
    )
