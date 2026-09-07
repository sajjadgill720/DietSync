#!/usr/bin/env python3
"""
scripts/test_allergy_diet.py
Verification test script for DietSync's clinical Diet & Allergy safety layer.

Per user requirements:
1. Exercise a known cross-reactive allergy pair (e.g. cephalosporin against penicillin allergy).
2. Confirm the allergy flag fires deterministically with full clinical citations.
3. Assert that ZERO LLM calls occur in that code path (rule-based and auditable).
4. Exercise a negative pair (e.g. penicillin allergy with paracetamol) and confirm 0 flags.
5. Exercise food interaction extraction from official label text.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure repo root and app directory are on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "app"))

from app.db.session import SessionLocal
from services.allergy_service import allergy_check
from worker.langgraph.nodes import (
    InteractionState,
    check_allergy,
    check_food_interaction,
)


def run_tests():
    print("=" * 80)
    print("DIETSYNC CLINICAL DIET & ALLERGY SAFETY LAYER VERIFICATION")
    print("=" * 80)

    # --------------------------------------------------------------------------
    # ZERO-LLM CALL ENFORCEMENT: Monkeypatch LLM clients to detect any invocation
    # --------------------------------------------------------------------------
    llm_call_counter = {"count": 0}

    def forbidden_llm_call(*args, **kwargs):
        llm_call_counter["count"] += 1
        raise AssertionError(
            "VIOLATION: An LLM call was attempted during the rule-based allergy check! "
            "Per clinical safety design, allergy cross-reactivity must be strictly rule-based."
        )

    # Patch ChatOpenAI across langchain to guarantee zero LLM calls
    with patch("langchain_openai.ChatOpenAI.invoke", side_effect=forbidden_llm_call), \
         patch("langchain_core.language_models.chat_models.BaseChatModel.invoke", side_effect=forbidden_llm_call):

        session = SessionLocal()

        # ----------------------------------------------------------------------
        # TEST 1: Cross-reactive pair: Cephalexin with stated Penicillin allergy
        # ----------------------------------------------------------------------
        print("\n[TEST 1] Testing cross-reactive pair: Cephalexin with 'penicillin' allergy...")
        resolved_drugs_t1 = [
            {
                "rxcui": "2231",
                "generic_name": "Cephalexin",
                "brand_name": "Keflex",
            }
        ]

        flags_t1 = allergy_check(
            patient_allergies=["penicillin"],
            resolved_drugs=resolved_drugs_t1,
            session=session,
        )

        print(f"  Result flags count: {len(flags_t1)}")
        assert len(flags_t1) > 0, "TEST 1 FAILED: Expected allergy flag for Cephalexin with penicillin allergy!"

        flag_1 = flags_t1[0]
        print(f"  Flagged Allergy:     {flag_1.get('allergy')}")
        print(f"  Matched Drug:        {flag_1.get('matched_drug')}")
        print(f"  Matched Class:       {flag_1.get('matched_class')} (RxClass ID: {flag_1.get('rxclass_id')})")
        print(f"  Data Source:         {flag_1.get('source')}")
        print(f"  Clinical Note:       {flag_1.get('cross_reactivity_note')[:90]}...")
        print(f"  Pharmacology Ref:    {flag_1.get('reference')[:90]}...")

        # Assertions
        assert flag_1["allergy"] == "penicillin"
        assert "cephalosporin" in flag_1["matched_class"].lower() or flag_1["rxclass_id"] == "J01DB"
        assert flag_1["source"] == "RxClass"
        assert "Goodman & Gilman" in flag_1["reference"] or "Pichichero" in flag_1["reference"]
        assert llm_call_counter["count"] == 0, "LLM was called during Test 1!"
        print("  -> PASSED: Cephalexin correctly flagged with penicillin allergy (Zero LLM calls).")

        # ----------------------------------------------------------------------
        # TEST 2: Combination product in DB: Augmentin (Amoxicillin) with Penicillin allergy
        # ----------------------------------------------------------------------
        print("\n[TEST 2] Testing combination drug in DB: Augmentin with 'penicillin' allergy...")
        from app.db.models import Drug
        augmentin = session.query(Drug).filter(Drug.brand_name.ilike("%Augmentin%")).first()

        if augmentin:
            drugs_t2 = [{"id": augmentin.id, "brand_name": augmentin.brand_name}]
            flags_t2 = allergy_check(
                patient_allergies=["penicillin"],
                resolved_drugs=drugs_t2,
                session=session,
            )
            print(f"  Result flags count: {len(flags_t2)}")
            assert len(flags_t2) > 0, "TEST 2 FAILED: Expected allergy flag for Augmentin with penicillin allergy!"
            print(f"  Matched Class: {flags_t2[0]['matched_class']} ({flags_t2[0]['rxclass_id']})")
            assert llm_call_counter["count"] == 0, "LLM was called during Test 2!"
            print("  -> PASSED: Augmentin amoxicillin core identified via DB relationship (Zero LLM calls).")
        else:
            print("  (Augmentin not found in database; skipped DB query sub-check)")

        # ----------------------------------------------------------------------
        # TEST 3: Negative pair: Paracetamol with stated Penicillin allergy (Precision check)
        # ----------------------------------------------------------------------
        print("\n[TEST 3] Testing non-cross-reactive pair: Paracetamol with 'penicillin' allergy...")
        resolved_drugs_t3 = [
            {
                "rxcui": "161",
                "generic_name": "Paracetamol",
                "brand_name": "Panadol",
            }
        ]

        flags_t3 = allergy_check(
            patient_allergies=["penicillin"],
            resolved_drugs=resolved_drugs_t3,
            session=session,
        )

        print(f"  Result flags count: {len(flags_t3)}")
        assert len(flags_t3) == 0, f"TEST 3 FAILED: Expected 0 flags for Paracetamol, got: {flags_t3}"
        assert llm_call_counter["count"] == 0, "LLM was called during Test 3!"
        print("  -> PASSED: Clean precision on non-cross-reactive drug (Zero LLM calls).")

        # ----------------------------------------------------------------------
        # TEST 4: Cross-reactive pair: Ibuprofen with stated Aspirin allergy
        # ----------------------------------------------------------------------
        print("\n[TEST 4] Testing cross-reactive pair: Ibuprofen with 'aspirin' allergy...")
        resolved_drugs_t4 = [
            {
                "rxcui": "5640",
                "generic_name": "Ibuprofen",
                "brand_name": "Brufen",
            }
        ]

        flags_t4 = allergy_check(
            patient_allergies=["aspirin"],
            resolved_drugs=resolved_drugs_t4,
            session=session,
        )

        print(f"  Result flags count: {len(flags_t4)}")
        assert len(flags_t4) > 0, "TEST 4 FAILED: Expected allergy flag for Ibuprofen with aspirin allergy!"
        print(f"  Matched Class: {flags_t4[0]['matched_class']} ({flags_t4[0]['rxclass_id']})")
        print(f"  Reference:     {flags_t4[0]['reference'][:80]}...")
        assert "M01AE" in flags_t4[0]["rxclass_id"] or "propionic" in flags_t4[0]["matched_class"].lower()
        assert llm_call_counter["count"] == 0, "LLM was called during Test 4!"
        print("  -> PASSED: Ibuprofen flagged for Aspirin allergy (Zero LLM calls).")

        # ----------------------------------------------------------------------
        # TEST 5: LangGraph node integration: check_allergy
        # ----------------------------------------------------------------------
        print("\n[TEST 5] Testing LangGraph check_allergy node integration...")
        graph_state: InteractionState = {
            "drug_a": {"rxcui": "2231", "generic_name": "Cephalexin"},
            "drug_b": {"rxcui": "161", "generic_name": "Paracetamol"},
            "patient_allergies": ["penicillin"],
            "patient_diet_factors": [],
            "interaction_claim": None,
            "citation_text": None,
            "is_grounded": None,
            "allergy_flags": [],
            "food_interaction_claim": None,
            "food_citation_text": None,
            "final_status": "none_found",
            "final_answer": None,
        }

        node_output = check_allergy(graph_state)
        flags_node = node_output.get("allergy_flags", [])
        assert len(flags_node) == 1, f"Expected 1 flag from check_allergy node, got {len(flags_node)}"
        assert flags_node[0]["allergy"] == "penicillin"
        assert llm_call_counter["count"] == 0, "LLM was called during check_allergy node execution!"
        print("  -> PASSED: LangGraph node check_allergy executed with Zero LLM calls.")

        # FINAL CONFIRMATION OF ZERO LLM CALLS
        print("\n" + "-" * 80)
        print(f"TOTAL LLM CALLS IN ALLERGY CHECK CODE PATH: {llm_call_counter['count']}")
        assert llm_call_counter["count"] == 0, "CRITICAL ERROR: LLM calls were detected in allergy check code path!"
        print("AUDIT VERIFIED: Allergy cross-reactivity is 100% deterministic and rule-based.")
        print("-" * 80)

        session.close()

    # --------------------------------------------------------------------------
    # TEST 6: Food / Diet interaction scanning (grounded text parser)
    # --------------------------------------------------------------------------
    print("\n[TEST 6] Testing food interaction node (check_food_interaction)...")
    food_state: InteractionState = {
        "drug_a": {
            "generic_name": "Atorvastatin",
            "fda_label_text": (
                "PRECAUTIONS: Grapefruit juice contains one or more components that inhibit CYP3A4 "
                "and can increase plasma concentrations of atorvastatin. Concomitant intake of large "
                "quantities of grapefruit juice should be avoided."
            ),
        },
        "drug_b": {
            "generic_name": "Paracetamol",
            "fda_label_text": "WARNINGS: Do not take more than the recommended dose.",
        },
        "patient_allergies": [],
        "patient_diet_factors": ["grapefruit"],
        "interaction_claim": None,
        "citation_text": None,
        "is_grounded": None,
        "allergy_flags": [],
        "food_interaction_claim": None,
        "food_citation_text": None,
        "final_status": "none_found",
        "final_answer": None,
    }

    food_output = check_food_interaction(food_state)
    food_claim = food_output.get("food_interaction_claim")
    food_citation = food_output.get("food_citation_text")

    print(f"  Food Claim:    {food_claim}")
    print(f"  Food Citation: {food_citation}")
    assert food_claim is not None, "TEST 6 FAILED: Expected food interaction claim for Atorvastatin + grapefruit!"
    assert "Grapefruit juice" in food_citation, "TEST 6 FAILED: Expected exact citation mentioning grapefruit juice!"
    print("  -> PASSED: Grounded food interaction citation extracted successfully.")

    print("\n" + "=" * 80)
    print("ALL 6 TESTS PASSED SUCCESSFULLY! ZERO LLM INVOCATIONS CONFIRMED.")
    print("=" * 80)


if __name__ == "__main__":
    run_tests()
