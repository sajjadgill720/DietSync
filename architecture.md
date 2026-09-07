# Architecture & System Design

## 1. Project Overview & Purpose

The **Local Drug Interaction & Brand Resolution Assistant** is a pharmacist-facing decision-support system designed to answer a specific, high-stakes question:

> *"Does taking Drug A and Drug B together carry a known interaction risk?"*

In clinical and community pharmacy practice across Pakistan, drug-drug interaction (DDI) checks are predominantly manual and reliant on memory. When digital tools (e.g., Drugs.com, Medscape, Micromedex) are consulted, they operate strictly on generic/chemical names and lack any awareness of local Pakistani brand names (e.g., *Panadol*, *Brufen*, *Augmentin*). A pharmacist must manually know or search for the generic ingredient before performing any check.

This project closes that gap by acting as:
1. **The missing translation layer**: Resolving local Pakistani brand names to generic chemical names (via DRAP) and standardizing them across international naming conventions (INN to USAN via RxNorm).
2. **A citation-grounded clinical interaction check**: Retrieving authentic manufacturer label text (via openFDA) and using an LLM to extract and independently verify documented interactions with exact source quotes.

### Scope & Audience
- **Target Users**: Licensed pharmacists and clinical staff. It is deliberately **not** built for direct consumer/patient self-diagnosis.
- **Role**: Clinical decision support, not a diagnostic or prescribing authority. The system **never** declares a drug combination to be "safe"; it either cites a specific, sourced interaction warning or explicitly states that no interaction was found in the examined documentation.
- **Context**: An AI engineering portfolio prototype demonstrating rigorous grounding, entity resolution, and evaluation methodology—not intended for production clinical deployment.

---

## 2. Safety Philosophy

The system's design is guided by three non-negotiable safety principles:

1. **Recall Over Precision on Flagging**
   - In drug interaction screening, a false negative (missing a dangerous interaction) is a severe safety failure, whereas a false positive (advising caution when risk is marginal) is manageable for a trained clinician.
   - The system intentionally leans toward flagging potential concerns for human pharmacist review rather than clearing combinations prematurely.

2. **Never Infer Beyond Retrieved Sources**
   - Every interaction claim must be directly traceable to an exact, quoted sentence from retrieved clinical label documentation.
   - If retrieved sources do not explicitly state an interaction, the model is strictly forbidden from extrapolating or synthesizing claims using its parametric pre-training knowledge.

3. **Refusal is a First-Class Outcome, Not a Failure State**
   - Outcomes such as `"unverifiable"` or `"no interaction found in available sources"` are valid, expected, and safe conclusions.
   - The system does not attempt to force a resolution or loop indefinitely when sources are ambiguous or absent.

---

## 3. Strict DRAP Internal-Only Policy

> [!CAUTION]
> **DRAP (Drug Regulatory Authority of Pakistan) is an internal entity-resolution tool only.**
> DRAP endpoints and registration identifiers must **NEVER** be cited, displayed, or mentioned in user-facing outputs, API responses, UI text, or explanations of how an interaction was determined.

- **Purpose**: DRAP is utilized solely to map local brand names to active generic ingredients (an entity-resolution task, not a clinical claim).
- **Rationale**: DRAP's official portal disclaims that its data is a provisional list not intended as an authoritative clinical reference for research or citation.
- **Enforcement**:
  - API responses return `source: "openFDA"` or reference clinical texts—never DRAP.
  - DRAP registration numbers (`drap_reg_no`) remain internal database fields only.
  - Autocomplete/disambiguation interfaces present only standard product display names and dosage forms without DRAP identifiers.

---

## 4. End-to-End Pipeline & Resolution Chain

```
Pharmacist enters local brand name(s)
        ↓
[Stage 1: Resolution] Brand name → generic ingredient(s)          (DRAP, internal-only)
        ↓
[Stage 2: Normalization] Generic name (INN) → Standard name (USAN) (RxNorm)
        ↓
[Stage 3: Retrieval] Standardized concept → Clinical label text   (openFDA)
        ↓
[Stage 4: Reasoning] LLM inspects label text for mutual mentions  (LangGraph node: check_interaction)
        ↓
[Stage 5: Verification] Independent check: is claim grounded?     (LangGraph node: verify_groundedness)
        ↓
[Stage 6: Output Gate] Grounded cited finding OR explicit refusal (format_grounded_answer / format_unverifiable_answer)
```

### Hybrid Systems Strategy
- **Pre-resolved Dataset**: Common Pakistani drugs are pre-resolved in PostgreSQL (DRAP → RxNorm → openFDA) via batch scripts (`scripts/build_dataset.py`).
- **Live Fallback**: Live sequential API queries are triggered only when a brand is missing from the local database, minimizing latency, rate limits, and external network fragility.

---

## 5. Technology Stack Summary

| Layer | Choice | Rationale |
|---|---|---|
| **Backend framework** | FastAPI | Async-native, high performance, strict typed schemas via Pydantic |
| **Frontend** | React | Single Page Application (SPA), autocomplete, disambiguation flow, WebSocket client |
| **Database** | PostgreSQL | Unified store for curated drug dataset, label cache, job tracking, and LISTEN/NOTIFY push — avoids Redis operational overhead |
| **Message broker** | RabbitMQ | Decouples long-running, multi-step LLM chains from web processes; persistent delivery (`delivery_mode=2`) and fair dispatch (`prefetch_count=1`) |
| **Orchestration** | LangGraph | State machine enforcing structural safety gates and independent verification; refuse-rather-than-guess graph routing |
| **Agent / Tooling** | LangChain | Standardized tool wrappers for DRAP, RxNorm, openFDA, and RxClass lookups |
| **Evaluation / Observability**| LangSmith | Trace visibility across all nodes, regression testing, custom groundedness and refusal-correctness evaluators |
| **Brand resolution** | DRAP (undocumented endpoints) | The only comprehensive source for Pakistani drug registrations and active compositions; internal-only |
| **Name normalization** | RxNorm (NIH, free) | Robust INN ↔ USAN crosswalk (e.g. Paracetamol ↔ Acetaminophen via RxCUI concept mapping) |
| **Clinical label data** | openFDA (free) | Authoritative, free-text manufacturer label warnings, boxed warnings, and interaction sections |
| **Allergy cross-reactivity** | RxClass (NIH, free) | Class-membership lookups by RxCUI; deterministic rule-based checks paired with curated clinical reference |
| **Deployment** | CI/CD pipeline | Containerized services (`app/` web service and `worker/` consumer service) |

---

## 6. Repository Layout

The codebase follows the structure defined in `Proj_spec.md`, cleanly separating the web process, async worker process, frontend, and offline data pipeline:

```
DietSync/
├── architecture.md             # System architecture, safety principles, and design specification
├── Proj_spec.md                # Source product and technical specification
├── Agents.md                   # Project background and specifications draft
├── requirements.txt            # Python dependencies for backend (app/ and worker/)
├── .gitignore                  # Git ignore rules for Python, Node, and environments
│
├── app/                        # FastAPI web process
│   ├── __init__.py
│   ├── main.py                 # FastAPI application factory and router registration
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── resolve.py          # POST /resolve (brand name resolution)
│   │   ├── check.py            # POST /check, GET /check/{job_id} (async interaction jobs)
│   │   └── ws.py               # WS /ws/jobs/{job_id} (real-time notification via PostgreSQL LISTEN)
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── resolve.py          # Pydantic schemas for drug resolution
│   │   └── check.py            # Pydantic schemas for interaction check payloads & responses
│   ├── services/
│   │   ├── __init__.py
│   │   ├── drug_resolution.py  # Dataset lookup + DRAP fallback + RxNorm normalization
│   │   ├── rxclass_client.py   # RxClass drug-class lookups for allergy checking
│   │   └── queue_publisher.py  # RabbitMQ job producer
│   └── db/
│       ├── __init__.py
│       ├── models.py           # SQLAlchemy ORM models (drugs, ingredients, labels, jobs)
│       └── listeners.py        # PostgreSQL LISTEN/NOTIFY async notification handler
│
├── worker/                     # RabbitMQ consumer process (separate deployable service)
│   ├── __init__.py
│   ├── consumer.py             # Message consumer loop (prefetch=1, ack/fail handling)
│   └── langgraph/
│       ├── __init__.py
│       ├── graph.py            # LangGraph StateGraph topology and conditional routing
│       └── nodes.py            # Execution nodes (fetch_context, check_interaction, verify_groundedness, check_food_interaction, check_allergy, format_*)
│
├── frontend/                   # React application
│   └── package.json            # Base package skeleton for React SPA
│
└── scripts/                    # Offline tooling and batch jobs
    ├── __init__.py
    └── build_dataset.py        # Batch resolver populating PostgreSQL from DRAP -> RxNorm -> openFDA
```

### Architectural Highlights
- **Service Decoupling**: `app/` (web API) and `worker/` (LLM processing) are distinct services that can scale independently.
- **Shared Data Layer**: Both services access database definitions through SQLAlchemy models in `app/db/models.py`.
- **Zero Redis Dependency**: PostgreSQL handles data persistence, interaction caching, job status tracking, and pub/sub notifications via `LISTEN/NOTIFY`.
