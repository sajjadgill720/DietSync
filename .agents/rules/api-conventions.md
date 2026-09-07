---
trigger: always_on
glob:
description: Enforces consistent API design conventions across all DietSync FastAPI endpoints.
---

# DietSync API Convention Rules

## Endpoint Contracts

### `POST /resolve` — Synchronous Drug Resolution
- **Request**: `{ "query": str }`
- **Response**: `{ "status": "resolved" | "ambiguous" | "not_found", "drug": { "drug_id": int, "display_name": str, "dosage_form": str | null } | null, "candidates": [...] | null }`
- Deliberately synchronous — DRAP fallback is expected to complete in well under a second. Do NOT add async job machinery here.
- Never return `drap_reg_no` or any DRAP-sourced field in the response.
- When `ambiguous`, candidate objects surface only `display_name` and `dosage_form`.

### `POST /check` — Async Interaction Check
- **Request**: `{ "drug_a_id": int, "drug_b_id": int, "patient_allergies": [str] | null, "patient_diet_factors": [str] | null }`
- **Response** (HTTP **202** Accepted): `{ "job_id": UUID, "status": "queued" }`
- Both drug IDs must already be resolved via `/resolve`. Validate existence in PostgreSQL before queuing.
- `job_id` is a UUID generated client-side (in FastAPI) before the RabbitMQ message is published.
- `patient_allergies` and `patient_diet_factors` are passed through the queue payload only — never persisted to `interaction_jobs.result`.

### `GET /check/{job_id}` — Polling Fallback
- **Response**: `{ "job_id": UUID, "status": "queued" | "processing" | "done" | "failed", "result": { ... } | null, "error_message": str | null }`
- Primary delivery is via WebSocket — this endpoint exists for clients that reconnect after missing the push.

### `WS /ws/jobs/{job_id}` — Real-Time Push
- Client opens immediately after receiving `job_id` from `POST /check`.
- Server subscribes to that job's Postgres `LISTEN` channel, pushes the completed `CheckStatusResponse` when the worker marks the job done/failed, then closes.

## Response Schema Rules

- The `source` field in `CheckResult` must **always** be `"openFDA"`. The Pydantic validator `enforce_openfda_source` in `app/schemas/check.py` enforces this — do not remove or weaken it.
- `CheckResult.final_status` is a `Literal["interaction_found", "none_found", "unverifiable"]` — no other values.
- `CheckStatusResponse.status` is a `Literal["queued", "processing", "done", "failed"]` — matches the `CHECK` constraint on `interaction_jobs.status`.

## General Conventions

- All request/response models live in `app/schemas/`. Do not define inline Pydantic models in route handlers.
- Route modules live in `app/routes/` and are registered on the main `app` in `app/main.py` via `include_router()`.
- Use FastAPI `Depends(get_db)` for database session injection (from `app/db/session.py`).
- Tag routers with descriptive tags: `"Resolution"`, `"Interaction Check"`, `"WebSocket"`, `"System"`.
- Include descriptive `summary` and `description` on all route decorators for OpenAPI docs at `/docs`.

## Common Mistakes

- ❌ **Returning `drap_reg_no` in any response.** The `Drug` ORM model has this field, but it must never be serialized to API output. Use `ResolvedDrug` (which only exposes `drug_id`, `display_name`, `dosage_form`).

- ❌ **Setting `source` to anything other than `"openFDA"`.** The Pydantic validator `enforce_openfda_source` in `app/schemas/check.py` catches this at serialization time, but don't rely on it — always set `source="openFDA"` explicitly.

- ❌ **Persisting `patient_allergies` or `patient_diet_factors` in the `InteractionJob` record.** These are passed through the RabbitMQ payload only. The `InteractionJob` model has no columns for them by design.

- ❌ **Making `POST /resolve` async/queued.** This endpoint is deliberately synchronous. DRAP fallback completes in under a second — async job machinery would over-engineer the wrong layer.

- ❌ **Defining Pydantic models inline in route handlers.** All schemas live in `app/schemas/resolve.py` and `app/schemas/check.py`.

## Quick-Check Code Patterns

### ✅ Correct: Route with full decorator and DB dependency

```python
@router.post(
    "/check",
    response_model=CheckEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue an interaction check between two drugs",
    description="Validates both drug IDs exist, creates job, publishes to RabbitMQ.",
)
def enqueue_interaction_check(
    req: CheckRequest,
    db: Session = Depends(get_db),
) -> CheckEnqueueResponse:
    ...
```

### ❌ Wrong: Missing decorator metadata, no dependency injection

```python
@router.post("/check")
def check(req: dict):
    db = SessionLocal()  # Don't manually create sessions
    ...
```

### ✅ Correct: Building a CheckResult with enforced source

```python
return CheckResult(
    final_status="interaction_found",
    summary=claim,
    citation_text=citation,
    source="openFDA",  # Always "openFDA", never "DRAP"
    allergy_flags=flags,
    food_interaction_summary=food_claim,
)
```

### ❌ Wrong: Exposing DRAP fields in resolve response

```python
# NEVER do this — drap_reg_no is internal only
return {"drug_id": drug.id, "name": drug.brand_name, "reg_no": drug.drap_reg_no}
```

### ✅ Correct: Resolve response using schema models

```python
return ResolveResponse(
    status="resolved",
    drug=ResolvedDrug(
        drug_id=drug.id,
        display_name=drug.brand_name,
        dosage_form=drug.dosage_form,
    ),
    candidates=None,
)
```
