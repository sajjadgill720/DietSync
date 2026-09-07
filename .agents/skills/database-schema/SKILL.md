---
name: database-schema
description: Reference for the PostgreSQL schema, SQLAlchemy ORM models, Alembic migrations, and data model conventions.
---

# Database Schema Skill

## Overview

DietSync uses PostgreSQL 16 as the **sole data store** — no Redis. It handles the curated drug dataset, FDA label cache, async job tracking, and real-time push notifications via `LISTEN/NOTIFY`.

## Key Files

- **ORM Models**: `app/db/models.py` — SQLAlchemy ORM definitions (canonical)
- **DB Session**: `app/db/session.py` — session factory and `get_db` dependency
- **LISTEN/NOTIFY**: `app/db/listeners.py` — async Postgres notification handler
- **Migrations**: `alembic/versions/` — migration scripts
- **Alembic Config**: `alembic/env.py`, `alembic.ini`
- **Re-export**: `db/models.py`, `db/__init__.py` — convenience re-exports

## Table Reference

### `drugs` — Curated Pakistani Brand Dataset

| Column | Type | Notes |
|:---|:---|:---|
| `id` | `SERIAL PK` | Auto-increment |
| `brand_name` | `TEXT NOT NULL` | GIN index with `gin_trgm_ops` for fuzzy/prefix autocomplete |
| `drap_reg_no` | `TEXT` | **Internal only — never exposed via API** |
| `dosage_form` | `TEXT` | e.g. "Tablet", "Syrup" |
| `company_name` | `TEXT` | Manufacturer |
| `resolved_at` | `TIMESTAMPTZ` | Staleness tracking |
| `created_at` | `TIMESTAMPTZ` | Row creation time |

**Relationships**: One-to-many → `drug_ingredients`

### `drug_ingredients` — Active Ingredients per Drug

| Column | Type | Notes |
|:---|:---|:---|
| `id` | `SERIAL PK` | |
| `drug_id` | `INTEGER FK → drugs(id) ON DELETE CASCADE` | |
| `generic_name` | `TEXT NOT NULL` | As parsed from DRAP, e.g. "Guaifenesin" |
| `dose` | `TEXT` | e.g. "100 mg" |
| `rxcui` | `TEXT` | **Canonical join key** to `fda_labels` |
| `rxnorm_name` | `TEXT` | Human-readable standardized name |

**Indexes**: `drug_id`, `rxcui`

### `fda_labels` — Cached openFDA Label Data

| Column | Type | Notes |
|:---|:---|:---|
| `id` | `SERIAL PK` | |
| `rxcui` | `TEXT NOT NULL UNIQUE` | Keyed by RxCUI for stability |
| `rxnorm_name` | `TEXT NOT NULL` | |
| `drug_interactions` | `TEXT` | Free-text prose from label |
| `warnings` | `TEXT` | |
| `boxed_warning` | `TEXT` | |
| `raw_response` | `JSONB` | Full openFDA payload, future-proofing |
| `fetched_at` | `TIMESTAMPTZ` | |

### `interaction_jobs` — Async Job Tracking

| Column | Type | Notes |
|:---|:---|:---|
| `id` | `UUID PK` | Generated client-side before queue publish |
| `drug_a_id` | `INTEGER FK → drugs(id)` | |
| `drug_b_id` | `INTEGER FK → drugs(id)` | |
| `status` | `TEXT CHECK IN ('queued','processing','done','failed')` | |
| `result` | `JSONB` | **Never contains patient_allergies/patient_diet_factors** |
| `error_message` | `TEXT` | |
| `created_at` | `TIMESTAMPTZ` | |
| `completed_at` | `TIMESTAMPTZ` | |

### `allergy_class_map` — Curated Allergy Cross-Reactivity Reference

| Column | Type | Notes |
|:---|:---|:---|
| `id` | `SERIAL PK` | |
| `allergy_term` | `TEXT NOT NULL` | Patient-facing term, e.g. "penicillin" |
| `rxclass_id` | `TEXT NOT NULL` | e.g. ATC J01CA (penicillins) |
| `rxclass_source` | `TEXT NOT NULL` | "ATC" or "MEDRT" |
| `cross_reactivity_note` | `TEXT` | Curated clinical note |
| `reference` | `TEXT` | Source of clinical claim |

**Indexes**: `allergy_term`, `rxclass_id`

## Key Design Decisions

1. **`rxcui` as canonical join key**: RxCUIs are stable identifiers. Name strings are fragile to casing, whitespace, and regional naming.
2. **`JSONB` for `raw_response` and `result`**: Postgres-native semi-structured storage, queryable without migration if new fields are needed.
3. **`UUID` for `interaction_jobs.id`**: Must be generatable client-side (in FastAPI) before RabbitMQ publish, without a DB round-trip.
4. **`resolved_at` on `drugs`**: Tracks data staleness. Re-resolution policy is explicitly deferred.
5. **Patient data never in `result`**: Privacy by design — `patient_allergies` and `patient_diet_factors` are request-scoped only.
6. **`allergy_class_map` is hand-curated**: Small reference table, not auto-generated. Clinical cross-reactivity judgment is domain knowledge.

## Alembic Workflow

```bash
# Apply all migrations
python -m alembic upgrade head

# Create a new migration
python -m alembic revision --autogenerate -m "description_of_change"

# Roll back one step
python -m alembic downgrade -1
```

- Alembic `env.py` imports `Base` from `app.db.models` for autogeneration.
- The `pg_trgm` extension must be enabled for the GIN index on `drugs.brand_name`.

## LISTEN/NOTIFY (Real-Time Push)

- Worker fires `pg_notify('job_{job_id}', payload)` after writing a completed result.
- `app/db/listeners.py` provides the async handler that the WebSocket endpoint (`app/routes/ws.py`) subscribes to.
- This replaces the need for Redis pub/sub.
