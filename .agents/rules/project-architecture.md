---
trigger: always_on
glob:
description: Enforces DietSync's architectural invariants across all code changes.
---

# DietSync Project Architecture Rules

## Service Topology

- `app/` (FastAPI web process) and `worker/` (RabbitMQ consumer) are **separate deployable services** with independent entry points. Never merge them into a single process.
- `services/` at project root re-exports from `app/services/` for import convenience. The canonical implementations live in `app/services/`.
- `db/` at project root re-exports from `app/db/`. The canonical ORM models live in `app/db/models.py`.
- `app/schemas/` contains all Pydantic request/response models. API shapes are defined here, not inline in route handlers.
- `app/routes/` contains FastAPI router modules. Each router is registered in `app/main.py`.
- `worker/langgraph/` contains the LangGraph state machine (`graph.py`) and all node functions (`nodes.py`).
- `frontend/` is a standalone React SPA (Vite). It communicates with the backend via REST and WebSocket only.
- `scripts/` contains offline tooling: dataset builders, seeders, and test scripts. These are CLI entry points, not imported by `app/` or `worker/` at runtime.

## DRAP Internal-Only Policy (CRITICAL)

- DRAP (Drug Regulatory Authority of Pakistan) is used **exclusively** for brand-name → generic ingredient entity resolution.
- DRAP endpoints, registration numbers (`drap_reg_no`), and any reference to DRAP as a data source must **NEVER** appear in:
  - API response payloads
  - User-facing UI text or explanations
  - WebSocket messages
  - The `source` field of any `CheckResult` (must always be `"openFDA"`)
- `drap_reg_no` is an internal-only column in the `drugs` table — never serialize it to API responses.
- DRAP is never queried live per-keystroke for autocomplete. Live DRAP calls are minimized via the dataset-first design.

## Data Store Constraints

- **PostgreSQL is the sole data store.** Do not introduce Redis, Memcached, or any secondary data store.
- PostgreSQL handles: curated drug dataset, FDA label cache, async job tracking, and real-time push notifications (via `LISTEN/NOTIFY`).
- **RabbitMQ** is the message broker for async job dispatch. Single durable queue: `interaction_checks`.

## Canonical Join Key

- `rxcui` (RxNorm Concept Unique Identifier) is the **canonical join key** between `drug_ingredients` and `fda_labels`. Never join on name strings — they are fragile to casing, whitespace, and regional naming variations.

## Patient Data Privacy

- `patient_allergies` and `patient_diet_factors` are **ephemeral, request-scoped** inputs.
- They are passed through the RabbitMQ job payload and `InteractionState` in-memory only.
- They must **NEVER** be persisted to `interaction_jobs.result`, any database table, or any log that could be correlated with a patient identity.

## Deployment Model

- `app/` and `worker/` are containerized as separate services in `docker-compose.yml`.
- Database migrations are managed exclusively via Alembic (`alembic/`). Never apply raw DDL in application code.
