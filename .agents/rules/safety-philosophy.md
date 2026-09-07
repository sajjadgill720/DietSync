---
trigger: always_on
glob:
description: Enforces DietSync's clinical safety design philosophy across all code and prompt changes.
---

# DietSync Safety Philosophy Rules

## 1. Recall Over Precision on Flagging

- A **false negative** (missing a real interaction) is the dangerous failure mode.
- A **false positive** (over-caution) is merely annoying for a trained pharmacist.
- The system must lean toward flagging potential concerns for human review rather than confidently clearing a combination.
- The system **NEVER** states a drug combination is "safe." It either cites a specific, sourced interaction warning, or explicitly states no interaction was found in the sources checked.

## 2. Never Infer Beyond Retrieved Sources

- Every interaction claim must be traceable to an **exact, verbatim sentence** from a real source document (openFDA manufacturer label text).
- If nothing relevant is found in the retrieved label text, the system outputs "no interaction found" — it does NOT reason from the LLM's general training knowledge or parametric memory.
- LLM system prompts in `worker/langgraph/nodes.py` must always include explicit instructions forbidding outside knowledge.

## 3. Refusal is a First-Class Outcome

- `"unverifiable"`, `"none_found"`, and `"no interaction found"` are **valid, expected answers** — not edge cases to be engineered away.
- The `InteractionState.final_status` field has exactly three valid values: `"interaction_found"`, `"none_found"`, `"unverifiable"`.
- These three states must be cleanly differentiated in both backend logic and frontend display.

## 4. Independent Verification (Structural, Not Prompted)

- The `verify_groundedness` node is a **separate, independent LLM call** from `check_interaction`. It must never share context, reasoning, or chain-of-thought with the node that produced the claim.
- This separation is enforced by **graph structure** in `worker/langgraph/graph.py`, not merely by prompt-level instructions.
- A model is not a reliable judge of its own output — that is why verification is a distinct call.

## 5. No Retry Loops on Verification Failure

- The LangGraph is **deliberately non-cyclic** in the current version.
- If `verify_groundedness` sets `is_grounded = False`, the graph routes to `format_unverifiable_answer` and **terminates**. It does NOT loop back to `check_interaction` to retry until something passes verification.
- Retrying would silently defeat the purpose of the groundedness check.

## 6. Deterministic Allergy Cross-Reactivity (Zero LLM Calls)

- The `check_allergy` node is **purely rule-based**: patient allergy term → `allergy_class_map` table → target RxClass IDs → RxClass API membership check.
- **Zero LLM calls** are made in the allergy code path. The LLM is used only to phrase the explanation of a match, never to make the match decision.
- This is enforced in `app/services/allergy_service.py` — never introduce LLM reasoning into `allergy_check()`.

## 7. Food/Diet Interaction Through Same Verification Pipeline

- `check_food_interaction` scans the same already-fetched FDA label text (not a separate data source).
- Food interaction claims route through the **same** `verify_groundedness` node as drug-drug claims — do not duplicate or bypass verification logic.

## Common Mistakes

These are real anti-patterns that violate the safety design. Do not introduce them:

- ❌ **Returning a claim without routing through `verify_groundedness` first.** Every LLM-generated claim (drug-drug or food) must pass independent verification before reaching the user. Skipping this to "speed things up" defeats the entire grounding architecture.

- ❌ **Adding an LLM call inside `allergy_check()` or `check_allergy()`.** Allergy cross-reactivity is deterministic: `allergy_class_map` → RxClass API → match or no match. The LLM may only be used downstream to phrase the explanation text, never to decide whether a match exists.

- ❌ **Adding a retry loop from `format_unverifiable_answer` back to `check_interaction`.** The graph is deliberately non-cyclic. If verification fails, the answer is "unverifiable" — do not loop back hoping the LLM produces a different answer that passes.

- ❌ **Omitting "reason ONLY from provided text" from LLM system prompts.** Both `check_interaction` and `check_food_interaction` system prompts must explicitly forbid the model from using its parametric training knowledge. Without this, the model will confidently hallucinate interactions not in the label text.

- ❌ **Persisting `patient_allergies` or `patient_diet_factors` to `interaction_jobs.result` or any database table.** These are ephemeral, request-scoped health inputs that pass through the RabbitMQ payload and `InteractionState` in-memory only.

- ❌ **Using `drug_a.generic_name` or `drug_b.generic_name` strings as join keys to `fda_labels`.** Always join on `rxcui`. Name strings are fragile to INN/USAN differences (e.g. "Paracetamol" vs "Acetaminophen" are the same RxCUI 161).
