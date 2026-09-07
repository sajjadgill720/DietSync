# DietSync — Agent Orientation

## What This Project Is

A pharmacist-facing clinical decision-support tool that:
1. Resolves Pakistani drug brand names (e.g. "Panadol", "Augmentin") to generic ingredients via DRAP (internal-only)
2. Normalizes ingredient names across INN ↔ USAN conventions via RxNorm
3. Retrieves official FDA manufacturer label text via openFDA
4. Uses a LangGraph state machine to extract drug-drug and food-drug interactions with exact verbatim citations
5. Independently verifies every claim against the source text before presenting it
6. Performs deterministic allergy cross-reactivity checks via RxClass (zero LLM calls)

**This is a prototype/portfolio project, not production clinical software.**

## Key Directories

| Directory | Purpose |
|:---|:---|
| `app/` | FastAPI web process (routes, schemas, services, db models) |
| `worker/` | RabbitMQ consumer + LangGraph state machine (separate service) |
| `services/` | Re-exports from `app/services/` for import convenience |
| `db/` | Re-exports from `app/db/` for import convenience |
| `frontend/` | React SPA (Vite) |
| `scripts/` | Dataset builders, seeders, and test scripts |
| `alembic/` | Database migrations |
| `data/` | Seed data CSV and evaluation dataset JSON |

## Critical Constraints (Read Before Any Change)

1. **DRAP is internal-only.** Never expose DRAP endpoints, registration numbers, or mention DRAP as a source in API responses, UI, or any user-facing text. The `source` field is always `"openFDA"`.
2. **PostgreSQL is the sole data store.** No Redis. Postgres handles data, caching, job tracking, and push notifications (`LISTEN/NOTIFY`).
3. **Patient allergy/diet data is ephemeral.** Never persist `patient_allergies` or `patient_diet_factors` to any database table.
4. **Recall over precision.** The system over-flags for pharmacist review rather than clearing combinations.
5. **Refusal is valid.** `"none_found"` and `"unverifiable"` are first-class outcomes, not failures.
6. **`rxcui` is the canonical join key** between `drug_ingredients` and `fda_labels` — never join on name strings.
7. **LangGraph is non-cyclic.** Failed verification → unverifiable answer. No retry loops.
8. **Allergy checking is deterministic.** Zero LLM calls in `allergy_check()`.

## Tech Stack

- **Backend**: FastAPI + SQLAlchemy + Pydantic
- **Worker**: RabbitMQ consumer + LangGraph + LangChain + OpenAI
- **Database**: PostgreSQL 16
- **Frontend**: React + Vite
- **Evaluation**: LangSmith custom evaluators
- **External APIs**: DRAP (internal), RxNorm, openFDA, RxClass (all NIH/free)
