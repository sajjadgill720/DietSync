---
name: langgraph-workflow
description: Guide for modifying or extending the LangGraph interaction-checking state machine in worker/langgraph/.
---

# LangGraph Workflow Skill

## Overview

DietSync's interaction checker is a **LangGraph StateGraph** defined in `worker/langgraph/graph.py` with node functions in `worker/langgraph/nodes.py`. It enforces clinical safety gates through graph structure, not just prompting.

## Key Files

- **Graph topology**: `worker/langgraph/graph.py` — defines nodes, edges, conditional routing, and the compiled `interaction_graph` instance.
- **Node functions**: `worker/langgraph/nodes.py` — all node implementations and the `InteractionState` TypedDict.
- **Consumer**: `worker/consumer.py` — RabbitMQ message handler that invokes the graph.
- **LangSmith tracing**: `invoke_interaction_graph()` in `graph.py` wraps execution with `@traceable`.

## InteractionState Schema

```python
class InteractionState(TypedDict):
    drug_a: dict              # {id, brand_name, generic_name, rxcui, fda_label_text, ...}
    drug_b: dict
    patient_allergies: list[str]        # ephemeral, request-scoped — never persisted
    patient_diet_factors: list[str]     # ephemeral, request-scoped — never persisted
    interaction_claim: str | None       # LLM-extracted or parser-extracted claim
    citation_text: str | None           # exact verbatim quote from label text
    is_grounded: bool | None            # set by verify_groundedness
    allergy_flags: list[dict]           # [{allergy, matched_drug, matched_class, source: "RxClass"}]
    food_interaction_claim: str | None
    food_citation_text: str | None
    final_status: str                   # "interaction_found" | "none_found" | "unverifiable"
    final_answer: dict | None           # assembled response payload
```

## Graph Flow

```
START → fetch_context → check_interaction → check_food_interaction → check_allergy → verify_groundedness
                                                                                           │
                                                                               ┌───────────┴───────────┐
                                                                         is_grounded?           is_grounded?
                                                                           True                    False
                                                                               │                       │
                                                                   format_grounded_answer   format_unverifiable_answer
                                                                               │                       │
                                                                              END                     END
```

## Node Details

### `fetch_context`
- Loads FDA label text for both drugs from PostgreSQL via `_fetch_label_from_db()`.
- Populates `drug_a.fda_label_text` and `drug_b.fda_label_text` in state.
- Explicit node for LangSmith trace visibility.

### `check_interaction` (LLM call with grounded parser fallback)
- Reads both drugs' label text, determines if either mentions the other drug by name, synonym, or pharmacological class.
- If `OPENAI_API_KEY` is set: uses `gpt-4o-mini` with strict system prompt forbidding outside knowledge.
- Fallback: regex-based sentence scanner using `drug_classes` mapping and `_find_exact_source_sentence()`.
- Returns `{interaction_claim, citation_text}`.

### `check_food_interaction` (LLM call with grounded parser fallback)
- Scans same already-fetched label text for food/alcohol/diet warnings.
- Evaluates `patient_diet_factors` from state.
- Returns `{food_interaction_claim, food_citation_text}`.

### `check_allergy` (ZERO LLM calls — deterministic)
- Delegates to `app/services/allergy_service.allergy_check()`.
- Flow: patient allergy term → `allergy_class_map` DB table → RxClass API class membership → flag or not.
- Returns `{allergy_flags: [...]}`.

### `verify_groundedness` (independent LLM call)
- Audits BOTH drug-drug and food interaction claims via `_verify_claim_citation()`.
- Uses a separate `gpt-4o-mini` call with auditor-role system prompt.
- Checks: (1) citation appears verbatim in source text, (2) citation entails the claim.
- Fallback: normalized substring containment check.
- Returns `{is_grounded: bool}`.

### `format_grounded_answer`
- Routes here when `is_grounded == True`.
- Assembles `final_answer` dict with claim, citation, allergy_flags, and food_interaction.
- Sets `final_status` to `"interaction_found"` or `"none_found"`.

### `format_unverifiable_answer`
- Routes here when `is_grounded == False`.
- Sets `final_status = "unverifiable"`, nulls out citation and food fields.
- Preserves `allergy_flags` (they are deterministic, not LLM-generated).

## How to Add a New Node

1. Define the node function in `worker/langgraph/nodes.py`:
   ```python
   def my_new_node(state: InteractionState) -> dict:
       # Read from state, return partial update dict
       return {"my_new_field": value}
   ```

2. Add the field to `InteractionState` TypedDict.

3. Register in `worker/langgraph/graph.py`:
   ```python
   builder.add_node("my_new_node", my_new_node)
   builder.add_edge("previous_node", "my_new_node")
   builder.add_edge("my_new_node", "next_node")
   ```

4. If the new node produces a claim, route it through the existing `verify_groundedness` node — do NOT create a separate verifier.

## Critical Rules

- The graph is **non-cyclic**: failed verification terminates to `format_unverifiable_answer`, never loops back.
- `verify_groundedness` is **independent** from `check_interaction` — different LLM call, no shared reasoning context.
- Allergy checks are **deterministic** — never introduce LLM reasoning into the allergy code path.
- All LLM system prompts must include "reason ONLY from the provided text" instructions.
