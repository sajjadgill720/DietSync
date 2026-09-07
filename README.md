# DietSync

> **Citation-Grounded Drug Interaction & Pakistani Brand Resolution Assistant**  
> *A clinical decision-support engine translating local Pakistani pharmaceutical brands into standardized entities and evaluating drug-drug, allergy, and dietary hazards with verifiable manufacturer citations.*

---

## 1. System Overview

In community and clinical pharmacy practice across Pakistan, drug interaction checks are largely manual or reliant on international tools (Drugs.com, Micromedex, Medscape) that only recognize generic chemical names. A pharmacist searching for local brands like **Panadol**, **Brufen**, or **Augmentin** must manually know or look up active generic ingredients before screening for interactions.

**DietSync solves this by providing:**
1. **The Translation Layer**: Reverse-engineers undocumented public endpoints from the Drug Regulatory Authority of Pakistan (**DRAP**) to resolve local brand names to active pharmaceutical ingredients, then standardizes them across international naming conventions (**INN to USAN**) via the National Library of Medicine's **RxNorm**.
2. **Grounded Interaction Screening**: Fetches official manufacturer drug labels via **openFDA** and orchestrates an explicit **LangGraph** state machine that requires exact, verbatim citations from the label text before any interaction claim can be accepted.
3. **Deterministic Allergy Cross-Reactivity**: Rule-based screening using NIH **RxClass** (ATC / MEDRT) paired with a curated pharmacological reference table (`allergy_class_map`) to flag drug-class cross-reactivity with **zero LLM invocations**.
4. **Dietary & Food Interaction Scanning**: Parallel inspection of manufacturer label text for food, alcohol, and patient dietary factors, routed through the same independent verification auditor.
5. **Async Backend Architecture**: **RabbitMQ** job queue + **PostgreSQL** persistence and `LISTEN`/`NOTIFY` event streaming via **WebSockets** to decouple multi-step LLM reasoning from HTTP request cycles.

---

## 2. Architecture Diagram

```mermaid
flowchart TD
    subgraph Client ["Client Layer"]
        UI["React Frontend (Autocomplete & Result Display)"]
    end

    subgraph API ["FastAPI Gateway"]
        Resolve["POST /resolve\n(Internal DRAP & Cache)"]
        Check["POST /check\n(Enqueue UUID Job)"]
        WS["WS /ws/jobs/{id}\n(Postgres LISTEN / NOTIFY)"]
    end

    subgraph Broker ["Message Broker"]
        RabbitMQ[("RabbitMQ\n'interaction_checks' queue\ndelivery_mode=2")]
    end

    subgraph Resolution ["External Data & Entity Resolution"]
        DRAP["DRAP Portal (Internal-Only)\nBrand → Generic Ingredients"]
        RxNorm["NIH RxNorm REST API\nINN ↔ USAN Normalization (RxCUI)"]
        openFDA["openFDA Drug Label API\nOfficial Manufacturer Text"]
        RxClass["NIH RxClass REST API\nATC & MEDRT Class Hierarchy"]
    end

    subgraph Worker ["Async Worker & LangGraph Orchestration"]
        Consumer["worker.consumer\n(prefetch_count=1)"]
        
        subgraph Graph ["LangGraph State Machine"]
            N1["fetch_context\n(Load FDA Labels into State)"]
            N2a["check_interaction\n(Extract Claim + Exact Citation)"]
            N2b["check_food_interaction\n(Scan Label for Food/Diet Warnings)"]
            N2c["check_allergy\n(Rule-Based RxClass Cross-Reactivity: 0 LLM Calls)"]
            N3["verify_groundedness\n(Independent LLM Auditor vs Raw Label)"]
            Gate{"is_grounded == True?"}
            N4a["format_grounded_answer\n(Assemble Verified Citations & Flags)"]
            N4b["format_unverifiable_answer\n(Refuse to Guess — Explicit Safety Abstention)"]
        end
    end

    subgraph Storage ["PostgreSQL 16"]
        DB_Drugs[("drugs & drug_ingredients")]
        DB_Labels[("fda_labels (Cached openFDA)")]
        DB_Allergy[("allergy_class_map (Curated Reference)")]
        DB_Jobs[("interaction_jobs (JSONB Results)")]
    end

    %% Client Interactions
    UI -->|1. Resolve Brand| Resolve
    UI -->|2. Submit Check| Check
    UI -->|3. Subscribe Result| WS

    %% API to DB & Queue
    Resolve <--> DB_Drugs
    Resolve -.-> DRAP
    Resolve -.-> RxNorm
    Resolve -.-> openFDA
    Check -->|Persist Job State| DB_Jobs
    Check -->|Publish Payload| RabbitMQ

    %% Worker Execution
    RabbitMQ -->|Consume Payload| Consumer
    Consumer -->|Re-fetch Drug & Label State| DB_Drugs
    Consumer -->|Re-fetch Cached Labels| DB_Labels
    Consumer --> Graph

    N1 --> N2a --> N2b --> N2c --> N3 --> Gate
    Gate -->|Yes| N4a
    Gate -->|No| N4b
    N2c <--> DB_Allergy
    N2c -.-> RxClass

    N4a --> Consumer
    N4b --> Consumer

    Consumer -->|Update status='done'| DB_Jobs
    Consumer -->|pg_notify 'job_{id}'| DB_Jobs
    DB_Jobs -->|LISTEN event| WS
```

### ASCII Flowchart

```
Pharmacist / React Frontend
   │
   ├── [POST /resolve] ─────────► DRAP (Internal) ──► RxNorm (INN→USAN) ──► openFDA Label
   │                                                                               │
   ├── [POST /check] ──────────► RabbitMQ (Job Queue) ◄───────────────────────────┘
   │                                   │
   │                          [worker/consumer.py]
   │                                   │
   │                        ┌──────────▼──────────┐
   │                        │   LangGraph State   │
   │                        │   Machine Pipeline  │
   │                        └──────────┬──────────┘
   │                                   │
   │         ┌─────────────────────────┴─────────────────────────┐
   │         ▼                                                   ▼
   │   check_interaction                                 check_allergy
   │   (Exact Verbatim Quotes)                           (Deterministic RxClass Lookup;
   │         │                                            0 LLM Calls)
   │         ▼                                                   │
   │   check_food_interaction                                    │
   │   (Diet / Alcohol Warnings)                                 │
   │         │                                                   │
   │         └─────────────────────────┬─────────────────────────┘
   │                                   ▼
   │                         verify_groundedness
   │                         (Independent LLM Auditor)
   │                                   │
   │                        ┌──────────┴──────────┐
   │                  [Grounded]             [Ungrounded]
   │                        │                     │
   │                        ▼                     ▼
   │               format_grounded_answer   format_unverifiable_answer
   │                        │                     │
   │                        └──────────┬──────────┘
   │                                   ▼
   │                            PostgreSQL 16
   │                       (NOTIFY per-job channel)
   │                                   │
   └── [WS /ws/jobs/{id}] ◄────────────┘
```

---

## 3. Core Safety Principles

DietSync is built on clinical safety guardrails rather than freeform generative responses:

1. **Recall Over Precision on Flagging**: A false negative (missing a true clinical hazard) is dangerous; a false positive is cautious. The system prioritizes identifying genuine hazards for pharmacist review.
2. **Never Infer Beyond Retrieved Sources**: Every clinical claim must cite a verbatim sentence from manufacturer label documentation. The model is strictly forbidden from extrapolating from general training data.
3. **Refusal is a Valid Outcome**: `"none_found"` and `"unverifiable"` are explicit safety states, cleanly differentiated from each other and from positive findings.
4. **DRAP Internal-Only Policy**: DRAP endpoints and registration IDs are internal-only translation mechanisms. They are **never** returned in API responses, cited as clinical authorities, or displayed in the UI. User-facing clinical data is strictly sourced from openFDA, RxNorm, and RxClass.
5. **Deterministic Allergy Decisions**: Cross-reactivity matching between stated patient allergies and drugs is purely rule-based via NIH RxClass and curated pharmacology references (`allergy_class_map`). **Zero LLM calls are made in the allergy matching path.**
6. **Ephemeral Request-Scoped Health Privacy**: `patient_allergies` and `patient_diet_factors` are request-scoped inputs passed through the queue payload and in-memory state only. They are **never persisted** to `interaction_jobs.result` or any database table.

---

## 4. Setup & Running Instructions

### Prerequisites
- **Docker** & **Docker Compose**
- **Python 3.11+** (virtual environment recommended)
- **Node.js 18+** & `npm`

### Step 1: Clone and Configure Environment
```bash
git clone https://github.com/your-username/dietsync.git
cd dietsync

# Create local python virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

Create a `.env` file in the project root:
```ini
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/dietsync
RABBITMQ_URL=amqp://guest:guest@localhost:5672/
OPENAI_API_KEY=your-openai-api-key-here
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your-langsmith-key-here       # Optional: for LangSmith tracing
LANGCHAIN_PROJECT=dietsync
```

### Step 2: Start Infrastructure (PostgreSQL & RabbitMQ)
```bash
docker compose up -d
```
Verify that PostgreSQL (port `5432`) and RabbitMQ (port `5672`, management UI on `15672`) are healthy.

### Step 3: Run Database Migrations
Apply all Alembic migrations (`initial_schema` and `add_allergy_class_map`):
```bash
python -m alembic upgrade head
```

### Step 4: Seed Database
You have two options for seeding data:

#### Option A: Instant Offline Demo Seed (Recommended for quick testing & pitches)
Resets and seeds high-reliability curated demo pairs with pre-cached FDA labels and 11 verified allergy cross-reactivity rules (requires zero external network calls):
```bash
python scripts/demo_seed.py
```

#### Option B: Full Real-World Resolution Batch Pipeline
Reads `data/seed_brands.csv` and queries live DRAP $\rightarrow$ RxNorm $\rightarrow$ openFDA APIs:
```bash
python scripts/build_dataset.py
python scripts/seed_allergy_map.py
```

### Step 5: Start the Async Worker
In a dedicated terminal tab:
```bash
python -m worker.consumer
```
The consumer connects to RabbitMQ with `prefetch_count=1`, runs LangGraph workflows, records results in Postgres, and triggers real-time `NOTIFY` events.

### Step 6: Start the FastAPI Backend
In another terminal tab:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Interactive OpenAPI documentation is accessible at `http://localhost:8000/docs`.

### Step 7: Start the React Frontend
In a third terminal tab:
```bash
cd frontend
npm install
npm run dev
```
Open your browser at `http://localhost:5173`.

---

## 5. Live Pitch & Demonstration Scenarios

Use these reliable, pre-cached pairs seeded by `scripts/demo_seed.py`:

| Scenario | Drug A | Drug B | Patient Allergy / Diet | Expected Outcome |
| :--- | :--- | :--- | :--- | :--- |
| **1. Severe Interaction** | `Disprin Tablet` (Aspirin) | `WARFARIN TABLETS 1MG` (Warfarin) | None | **`interaction_found`** with verbatim manufacturer warning citing major bleeding hazard. |
| **2. Contraindicated Pair + Diet Hazard** | `Lipitor Tablet 10mg` (Atorvastatin) | `Klaricid 250mg Tablets` (Clarithromycin) | Diet: `grapefruit` | **`interaction_found`** citing rhabdomyolysis contraindication + grounded grapefruit warning. |
| **3. Clean Safety Abstention** | `Panadol Tablet.` (Paracetamol) | `Norvasc Tablet 5mg` (Amlodipine) | None | **`none_found`** explicit refusal to hallucinate; clearly differentiates "no interaction" from "unverifiable". |
| **4. Deterministic Allergy Cross-Reactivity** | `Keflex 250mg Capsule` (Cephalexin) OR `Augmentin BD Suspension` | `Panadol Tablet.` | Allergy: `penicillin` | Immediate allergy warning citing Goodman & Gilman; **zero LLM invocations**. |

---

## 6. Automated Testing & Evaluation

Run the verification and evaluation scripts:

```bash
# 1. Standalone Allergy & Diet Verification (Asserts 0 LLM calls)
python scripts/test_allergy_diet.py

# 2. FastAPI API Endpoint Regression Suite (All 9 tests)
python scripts/test_api_endpoints.py --no-wsl-delegate

# 3. Comprehensive Evaluation Benchmark (21 labeled test cases)
python scripts/run_eval.py --no-wsl-delegate
```

### Evaluation Benchmark Results
- **Drug-Drug Recall**: `100.0%` (Zero false negatives on documented interactions)
- **Drug-Drug Groundedness Rate**: `100.0%` (Zero unverified claims)
- **Allergy Cross-Reactivity Recall**: `100.0%` (Zero missed allergen cross-reactivities)
- **Allergy Precision**: `100.0%` (Zero false allergy alarms)
- **Food / Dietary Recall**: `100.0%` (All documented dietary warnings detected)

---

## 7. Production Deployment & Cloud Hosting

Detailed instructions for deploying DietSync after pushing to GitHub are in [DEPLOYMENT.md](file:///DEPLOYMENT.md).

Quick Overview of deployment paths:
- **One-Command Cloud VPS (Docker Compose)**: Clone repo on Ubuntu VPS and run `docker compose -f docker-compose.prod.yml up -d --build`. Automatic SSL available with Caddy.
- **Managed PaaS (Railway / Render)**: Connect GitHub repo, add managed PostgreSQL and RabbitMQ, set API start command and Worker start command.
- **Hybrid (Vercel Frontend + Cloud Backend)**: Connect GitHub repo to Vercel (Root directory: `frontend`), set `VITE_API_BASE` and `VITE_WS_BASE`.
- **Automated CI/CD**: Every push to GitHub runs automated backend allergy/diet regression tests and frontend build verification via [`.github/workflows/ci.yml`](file:///.github/workflows/ci.yml).

---

## 8. Known Limitations / Explicitly Deferred Decisions


*(Copied verbatim from `PROJECT_SPEC.md` lines 340–353 — documented as honest scope boundaries rather than gaps to hide)*

- **Brand disambiguation at the DRAP layer** takes the first search match by default; full disambiguation is handled at the UI layer (`/resolve` returning `ambiguous` with candidates) rather than the backend guessing — this is implemented, but worth noting the backend resolver function itself has a "naive first match" fallback path that should never be hit once the UI flow is used correctly.
- **No bounded retry logic yet on failed worker jobs** — currently fail-and-record rather than fail-and-requeue-with-limit. Planned as a `retry_count` column addition.
- **Cache staleness policy for the `drugs` table is not yet enforced** — `resolved_at` is tracked, but no automatic re-resolution job exists yet.
- **RxNorm coverage is not guaranteed exhaustive** — the normalizer falls back to using the original (unnormalized) name if RxNorm returns no match, meaning some rare/obscure ingredients may still fail to resolve against openFDA. No comprehensive fallback beyond this exists yet.
- **Multi-drug (3+) interaction checking is not yet designed** — current architecture is pairwise (Drug A vs Drug B); real prescriptions often involve more.
- **`allergy_class_map` is a small, manually curated seed set** — it covers well-known cross-reactivity families (e.g. penicillin/cephalosporin, sulfonamide classes, NSAIDs, opioids) but is not an exhaustive clinical allergy-cross-reactivity database.
- **Food/diet interaction detection relies on the same openFDA label text as drug-drug checking** — it will only catch what's documented in that free text, not a comprehensive food-drug interaction database.
- **Patient allergy/diet input is intentionally not persisted anywhere** — this is a deliberate privacy choice, not an oversight, but it also means there's no history/audit trail of past allergy checks for a given patient across sessions.
- **This is explicitly a prototype/portfolio project, not a clinically validated or deployed tool.** It should never be described, in documentation or in interviews, as production-ready clinical software.
