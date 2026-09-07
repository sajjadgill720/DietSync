"""
app/schemas/resolve.py
Pydantic schemas for the drug resolution endpoint (POST /resolve).

Per PROJECT_SPEC.md lines 231-244:
- Request: { "query": str }
- Response:
  {
    "status": "resolved" | "ambiguous" | "not_found",
    "drug": { "drug_id": int, "display_name": str, "dosage_form": str | null } | null,
    "candidates": [ ...same shape... ] | null
  }
CRITICAL SAFETY & BRAND INTEGRITY RULE:
Never return drap_reg_no or any DRAP-sourced field name in the response.
"""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class ResolveRequest(BaseModel):
    query: str = Field(..., description="Drug brand or generic name to resolve", min_length=1)


class DrugCandidate(BaseModel):
    drug_id: Optional[int] = Field(
        default=None,
        description="Database primary key of the resolved drug, or null if ambiguous/unpersisted candidate",
    )
    display_name: str = Field(..., description="Normalized or product display name")
    dosage_form: Optional[str] = Field(default=None, description="Dosage form, e.g. Tablet, Syrup, Injection")


# Alias for resolved drug matching the same shape
ResolvedDrug = DrugCandidate


class ResolveResponse(BaseModel):
    status: Literal["resolved", "ambiguous", "not_found"] = Field(
        ...,
        description="Resolution status: 'resolved' when exact match found, 'ambiguous' if multiple matches, 'not_found' otherwise",
    )
    drug: Optional[ResolvedDrug] = Field(
        default=None,
        description="Resolved drug details (populated when status == 'resolved')",
    )
    candidates: Optional[List[DrugCandidate]] = Field(
        default=None,
        description="Candidate products for disambiguation (populated only when status == 'ambiguous')",
    )
