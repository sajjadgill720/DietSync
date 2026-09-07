---
trigger: always_on
glob:
description: Enforces code style, naming, and structural conventions for all DietSync source files.
---

# DietSync Code Style Rules

## Python (Backend & Worker)

- **Type hints** on all function signatures — parameters and return types.
- Use `TypedDict` for LangGraph state definitions (see `InteractionState` in `worker/langgraph/nodes.py`).
- Use Pydantic `BaseModel` with `Field(...)` for all API request/response schemas (in `app/schemas/`).
- Use `logging.getLogger(__name__)` or a descriptive logger name — never `print()` for operational output.
- Prefer `f-strings` for string interpolation.
- Constants and sentinel values (e.g. `NOT_PRESENT_IN_LABEL = "(not present in this label)"`) are defined at module top level.
- `import` ordering: stdlib → third-party → project-local, separated by blank lines.

## FastAPI Routes

- Each route module (`app/routes/*.py`) defines a `router = APIRouter(tags=[...])` and is registered in `app/main.py`.
- Use dependency injection via `Depends(get_db)` for database sessions (from `app/db/session.py`).
- Synchronous routes use `def`; async routes use `async def`. The resolve endpoint is synchronous by design.
- Include `response_model`, `status_code`, `summary`, and `description` on every route decorator.

## SQLAlchemy ORM

- ORM models live in `app/db/models.py` (canonical location).
- Use `declarative_base()` from `sqlalchemy.orm`.
- Column types: `Text` (not `String`), `Integer`, `DateTime(timezone=True)`, `JSONB`, `UUID(as_uuid=True)`.
- Indexes and constraints are declared in `__table_args__`.
- The `pg_trgm` GIN index on `drugs.brand_name` enables fuzzy/prefix autocomplete.

## Database Migrations

- All schema changes go through **Alembic** (`alembic/versions/`). Never apply raw DDL in application code or startup hooks.
- Migration messages should be descriptive: e.g. `"add_allergy_class_map"`, `"initial_schema"`.

## LangGraph Nodes

- Each node function takes `state: InteractionState` and returns a `dict` of state updates.
- Node functions in `worker/langgraph/nodes.py` must be pure with respect to state — read from `state`, return partial updates.
- LLM system prompts must include explicit "reason ONLY from provided text" instructions.
- JSON responses from LLMs are cleaned of markdown fences before parsing.

## Frontend (React)

- Functional components only, using JSX.
- Vite as the build tool (`frontend/vite.config.js`).
- Styles in `frontend/src/index.css`.
- API base URL configured in Vite config proxy or environment variables.

## General

- Docstrings on all public functions and classes. Reference `PROJECT_SPEC.md` or `Proj_spec.md` line numbers where applicable for traceability.
- Preserve all existing comments that reference spec lines (e.g. `# Per PROJECT_SPEC.md lines 111-123`).
- No `TODO` or `FIXME` without a linked issue or explicit note about what is deferred and why.

## Quick-Check Code Patterns

### ✅ Correct: Import ordering

```python
import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import Drug, InteractionJob
from app.db.session import get_db
from app.schemas.check import CheckRequest, CheckResult
```

### ❌ Wrong: Mixed import order

```python
from app.db.models import Drug
import json
from sqlalchemy.orm import Session
import os
from fastapi import APIRouter
```

### ✅ Correct: ORM column definition

```python
brand_name = Column(Text, nullable=False)  # Use Text, not String
rxcui = Column(Text, nullable=True)        # Canonical join key
resolved_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
raw_response = Column(JSONB, nullable=True)
```

### ❌ Wrong: Using String, no timezone, raw defaults

```python
brand_name = Column(String(255), nullable=False)       # Use Text
resolved_at = Column(DateTime, default=datetime.now)    # Use timezone=True + server_default
```

### ✅ Correct: LangGraph node return (partial state update)

```python
def check_interaction(state: InteractionState) -> dict:
    """Reads label text and identifies interactions with exact citations."""
    # ... reasoning logic ...
    return {
        "interaction_claim": claim,
        "citation_text": citation,
    }
```

### ❌ Wrong: Returning full state or mutating state in-place

```python
def check_interaction(state: InteractionState) -> InteractionState:
    state["interaction_claim"] = claim  # Don't mutate state
    return state                        # Don't return full state
```

### ✅ Correct: Cleaning LLM JSON fences

```python
raw_content = resp.content.strip()
if raw_content.startswith("```"):
    raw_content = re.sub(r"^```(?:json)?\n?", "", raw_content)
    raw_content = re.sub(r"\n?```$", "", raw_content)
parsed = json.loads(raw_content)
```

### ❌ Wrong: Parsing LLM output without cleaning

```python
parsed = json.loads(resp.content)  # Will crash on ```json fences
```
