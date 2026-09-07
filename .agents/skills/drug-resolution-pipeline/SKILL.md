---
name: drug-resolution-pipeline
description: Guide for the DRAP → RxNorm → openFDA three-stage entity resolution chain and the hybrid dataset strategy.
---

# Drug Resolution Pipeline Skill

## Overview

The core technical contribution of DietSync is the three-stage resolution chain that translates local Pakistani brand names to standardized drug entities with cached FDA label text.

## Key Files

- **Service implementation**: `app/services/drug_resolution.py` — all resolution logic (DRAP, RxNorm, openFDA clients)
- **Re-export wrapper**: `services/drug_resolution.py` — convenience re-exports for root-level imports
- **Batch builder**: `scripts/build_dataset.py` — offline pipeline that pre-resolves common brands into PostgreSQL
- **Demo seeder**: `scripts/demo_seed.py` — instant offline seed with pre-cached FDA labels
- **Route endpoint**: `app/routes/resolve.py` — `POST /resolve` handler

## Three-Stage Resolution Chain

```
Brand Name (e.g. "Panadol")
    ↓
[Stage 1: DRAP] → Generic Ingredient(s) (e.g. "Paracetamol")
    ↓
[Stage 2: RxNorm] → Standardized Name + RxCUI (e.g. "Acetaminophen", RxCUI 161)
    ↓
[Stage 3: openFDA] → Manufacturer Label Text (drug_interactions, warnings, boxed_warning)
```

### Stage 1: DRAP (Drug Regulatory Authority of Pakistan)

**INTERNAL-ONLY. Never exposed in any user-facing output.**

Two undocumented public endpoints (discovered via browser DevTools):

1. **Autocomplete search**:
   ```
   GET https://eapp.dra.gov.pk/productView.php?search={query}&_type=brand%20name
   ```
   Returns: `{"results": [{"id": reg_no, "text": display_name}, ...]}`
   ⚠️ Response has a UTF-8 BOM that must be stripped before JSON parsing.

2. **Product details**:
   ```
   POST https://eapp.dra.gov.pk/productView.php
   Body: webRegNo={reg_no}
   ```
   Returns: HTML fragment parsed with BeautifulSoup.

**Composition parsing** handles two formats:
- Dotted-leader: `"Guaifenesin ...... 100 mg"` → `{name: "Guaifenesin", amount: "100 mg"}`
- Plain trailing-dose: `"PARACETAMOL 500 mg"` → `{name: "PARACETAMOL", amount: "500 mg"}`

### Stage 2: RxNorm (NIH, free, no auth)

Two-step lookup via `rxnav.nlm.nih.gov`:

1. **Name → RxCUI**:
   ```
   GET /REST/rxcui.json?name={generic_name}&search=2
   ```
   Uses normalized/fuzzy matching. Correctly resolves INN names (e.g. "Paracetamol") to USAN equivalents (e.g. "Acetaminophen", RxCUI 161).

2. **RxCUI → Canonical Name**:
   ```
   GET /REST/rxcui/{rxcui}/property.json?propName=RxNorm%20Name
   ```

If RxNorm returns no match, the resolver falls back to using the original (unnormalized) name.

### Stage 3: openFDA (free, no auth)

```
GET https://api.fda.gov/drug/label.json?search=openfda.generic_name:"{normalized_name}"&limit=1
```

Extracts fields:
- `drug_interactions` — free-text prose about drug-drug interactions
- `warnings` — general warnings section
- `boxed_warning` — FDA black box warnings

Missing fields are stored as `"(not present in this label)"` — never treated as errors.

## Hybrid Dataset Strategy

### Why Pre-Resolution Matters

Live resolution requires 3 sequential network round-trips per drug (DRAP → RxNorm → openFDA). For common drugs, this is:
- **Slow**: multiple seconds per drug pair
- **Fragile**: dependent on DRAP uptime during live demos
- **Wasteful**: repetitive traffic against a government system

### The Hybrid Design

1. **Pre-resolved dataset** (fast path): `scripts/build_dataset.py` runs the full chain over `data/seed_brands.csv` and populates `drugs`, `drug_ingredients`, and `fda_labels` tables.
2. **Live fallback** (cache miss): when a brand isn't in the database, `resolve_drug()` triggers live sequential API queries and persists the result for future use.
3. **Demo seed** (instant): `scripts/demo_seed.py` inserts pre-cached data with zero external API calls — used for demos and testing.

### Database Tables Populated

| Table | Populated By | Content |
|:---|:---|:---|
| `drugs` | build_dataset / resolve_drug | Brand name, dosage form, company, DRAP reg (internal) |
| `drug_ingredients` | build_dataset / resolve_drug | Generic name, dose, RxCUI, RxNorm name |
| `fda_labels` | build_dataset / resolve_drug | Cached FDA label text keyed by RxCUI |

## Key Functions in `app/services/drug_resolution.py`

- `search_drap(query)` / `search(query)` — DRAP autocomplete search
- `get_drap_product_details(reg_no)` / `get_product_details(reg_no)` — DRAP product detail fetcher
- `parse_composition(html)` — extracts structured ingredients from DRAP HTML
- `rxnorm_normalize(generic_name)` — Stage 2 normalization
- `fetch_fda_label(normalized_name)` — Stage 3 label retrieval
- `resolve_drug(query, db)` — full resolution with database-first lookup
- `resolve_and_persist_product(reg_no, db)` — resolves and persists a single product

## Critical Constraints

- DRAP is **never** referenced in user-facing outputs.
- `rxcui` is the canonical join key, not name strings.
- `resolved_at` on `drugs` tracks staleness — re-resolution policy is a deferred decision.
- All async variants (`*_async`) exist for use in async contexts.
