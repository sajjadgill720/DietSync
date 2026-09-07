---
name: testing-and-eval
description: Guide for running tests, evaluation benchmarks, and seeding the demo database for DietSync.
---

# Testing & Evaluation Skill

## Overview

DietSync has three layers of verification: standalone unit tests, API endpoint regression tests, and a comprehensive evaluation benchmark with custom LangSmith evaluators.

## Key Files

| File | Purpose |
|:---|:---|
| `scripts/demo_seed.py` | Instant offline seed — zero external API calls |
| `scripts/build_dataset.py` | Full live DRAP → RxNorm → openFDA batch pipeline |
| `scripts/seed_allergy_map.py` | Seeds the `allergy_class_map` table with curated cross-reactivity rules |
| `scripts/test_allergy_diet.py` | Standalone allergy & diet verification (asserts 0 LLM calls in allergy path) |
| `scripts/test_api_endpoints.py` | FastAPI API endpoint regression suite (9 tests) |
| `scripts/test_graph.py` | Direct LangGraph state machine tests |
| `scripts/test_drap.py` | DRAP endpoint connectivity and parsing tests |
| `scripts/test_normalize_chain.py` | RxNorm normalization chain tests |
| `scripts/test_end_to_end_job.py` | Full async job lifecycle test (enqueue → worker → result) |
| `scripts/run_eval.py` | Comprehensive evaluation benchmark (21 labeled test cases) |
| `scripts/build_eval_dataset.py` | Builds the evaluation dataset JSON |
| `worker/eval/evaluators.py` | Custom LangSmith evaluators (groundedness, refusal-correctness) |
| `data/eval_dataset.json` | 21 labeled test cases for the evaluation benchmark |

## Seeding the Database

### Option A: Instant Demo Seed (Recommended for Development & Demos)

```bash
python scripts/demo_seed.py
```

- Resets and seeds high-reliability curated demo pairs
- Pre-cached FDA labels — **zero external network calls**
- Seeds 11 verified allergy cross-reactivity rules
- Includes reliable demo pairs for all 4 scenarios (severe interaction, contraindicated + diet, clean abstention, allergy cross-reactivity)

### Option B: Full Live Pipeline

```bash
python scripts/build_dataset.py      # DRAP → RxNorm → openFDA for all brands in data/seed_brands.csv
python scripts/seed_allergy_map.py   # Seeds allergy_class_map table
```

- Queries live external APIs — requires network access
- Reads brand list from `data/seed_brands.csv`

## Running Tests

### 1. Allergy & Diet Verification (No LLM Required)

```bash
python scripts/test_allergy_diet.py
```

- Verifies deterministic allergy cross-reactivity matching
- Asserts **zero LLM calls** in the allergy code path
- Tests `allergy_check()` against the curated `allergy_class_map` table

### 2. API Endpoint Regression (9 Tests)

```bash
python scripts/test_api_endpoints.py --no-wsl-delegate
```

- Tests all FastAPI endpoints: `/resolve`, `/check`, `/check/{job_id}`, `/health`
- Validates response schemas match Pydantic models
- Checks DRAP-never-in-response constraint
- Requires running FastAPI server (`uvicorn app.main:app`)

### 3. LangGraph State Machine Tests

```bash
python scripts/test_graph.py
```

- Tests individual node functions with mocked state
- Validates graph topology and conditional routing
- Tests both grounded and unverifiable paths

### 4. DRAP Endpoint Tests

```bash
python scripts/test_drap.py
```

- Tests DRAP search and product detail endpoints
- Validates BOM stripping and composition parsing
- Requires network access to DRAP

### 5. Normalization Chain Tests

```bash
python scripts/test_normalize_chain.py
```

- Tests RxNorm INN → USAN normalization
- Validates known mappings (e.g. Paracetamol → Acetaminophen)

### 6. End-to-End Job Lifecycle

```bash
python scripts/test_end_to_end_job.py
```

- Full async pipeline: enqueue → RabbitMQ → worker → PostgreSQL → result
- Requires running worker and RabbitMQ

## Evaluation Benchmark

### Running the Full Benchmark

```bash
python scripts/run_eval.py --no-wsl-delegate
```

- Runs 21 labeled test cases from `data/eval_dataset.json`
- Measures recall, precision, groundedness, and refusal-correctness

### Expected Results

| Metric | Target |
|:---|:---|
| Drug-Drug Recall | 100.0% |
| Drug-Drug Groundedness Rate | 100.0% |
| Allergy Cross-Reactivity Recall | 100.0% |
| Allergy Precision | 100.0% |
| Food / Dietary Recall | 100.0% |

### Custom Evaluators (in `worker/eval/evaluators.py`)

1. **Groundedness Evaluator**: Checks whether a returned interaction claim is actually entailed by the cited source text.
2. **Refusal-Correctness Evaluator**: Checks whether the system correctly abstains ("not found") on pairs known to have no documented interaction, and correctly does not abstain on pairs known to have one.

### Demo Scenario Pairs

Use these for live demos (seeded by `demo_seed.py`):

| Scenario | Drug A | Drug B | Allergy/Diet | Expected |
|:---|:---|:---|:---|:---|
| Severe Interaction | Disprin (Aspirin) | Warfarin | None | `interaction_found` |
| Contraindicated + Diet | Lipitor (Atorvastatin) | Klaricid (Clarithromycin) | Diet: grapefruit | `interaction_found` + food warning |
| Clean Abstention | Panadol (Paracetamol) | Norvasc (Amlodipine) | None | `none_found` |
| Allergy Cross-Reactivity | Keflex (Cephalexin) | Panadol | Allergy: penicillin | Allergy flag (0 LLM calls) |

## Prerequisites

- PostgreSQL and RabbitMQ running (`docker compose up -d`)
- Alembic migrations applied (`python -m alembic upgrade head`)
- Database seeded (Option A or B above)
- For API tests: FastAPI server running (`uvicorn app.main:app`)
- For end-to-end tests: Worker running (`python -m worker.consumer`)
- For LLM-dependent tests: `OPENAI_API_KEY` set in `.env`
