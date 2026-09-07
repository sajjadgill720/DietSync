#!/usr/bin/env python3
"""
scripts/test_normalize_chain.py
Standalone test script to verify RxNorm normalization (INN -> USAN crosswalk)
and openFDA label retrieval.

Verifies:
1. "Paracetamol" resolves to RxCUI 161 (Acetaminophen).
2. openFDA label retrieval for Acetaminophen and prints its drug_interactions field
   (handling absent fields gracefully with "(not present in this label)").
3. Demonstrated behavior on drugs with present interactions (e.g., Warfarin).
"""

import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.drug_resolution import (
    NOT_PRESENT_IN_LABEL,
    fetch_fda_label,
    rxnorm_normalize,
)


def test_paracetamol_normalization_and_fda():
    print("=" * 70)
    print("1. Testing RxNorm Normalization for 'Paracetamol'")
    print("=" * 70)

    generic_query = "Paracetamol"
    print(f"[*] Calling rxnorm_normalize('{generic_query}')...")
    rxcui, canonical_name = rxnorm_normalize(generic_query)

    print(f"[+] Result: RxCUI = {repr(rxcui)}, Canonical Name = {repr(canonical_name)}")

    # Verification per spec confirmation:
    # "Confirmed via testing that RxNorm correctly resolves INN names (e.g. 'Paracetamol')
    # to the same underlying concept as their USAN equivalent (e.g. 'Acetaminophen' — RxCUI 161)"
    assert rxcui == "161", f"Expected RxCUI '161', got {rxcui!r}"
    assert canonical_name is not None and canonical_name.lower() == "acetaminophen", (
        f"Expected canonical name 'acetaminophen', got {canonical_name!r}"
    )
    print("  [PASSED] Successfully confirmed INN 'Paracetamol' -> USAN 'acetaminophen' (RxCUI 161)\n")

    print("=" * 70)
    print("2. Fetching openFDA Drug Label for Canonical Name ('acetaminophen')")
    print("=" * 70)

    print(f"[*] Calling fetch_fda_label('{canonical_name}')...")
    label = fetch_fda_label(canonical_name)

    print(f"  - Label Found:        {label.get('found')}")
    print(f"  - Generic Name:       {label.get('generic_name')}")
    print(f"  - Drug Interactions:  {label.get('drug_interactions')}")

    # Acetaminophen labels typically lack a dedicated DRUG INTERACTIONS section
    # The spec explicitly requires storing "(not present in this label)" rather than raising
    assert "drug_interactions" in label, "Expected 'drug_interactions' key in label dict"
    if label.get("drug_interactions") == NOT_PRESENT_IN_LABEL:
        print("    -> Note: Properly handled missing drug_interactions section as '(not present in this label)'.")

    # Verify warnings are present to confirm valid label retrieval from openFDA
    warnings = label.get("warnings", "")
    print(f"  - Warnings (preview): {warnings[:120]}...\n")
    assert warnings != NOT_PRESENT_IN_LABEL, "Expected warnings to be present for acetaminophen"
    print("  [PASSED] openFDA label fetched and parsed successfully!\n")


def test_drug_with_active_interactions():
    print("=" * 70)
    print("3. Verification with Drug Having Populated Interactions ('warfarin')")
    print("=" * 70)

    rxcui, canonical_name = rxnorm_normalize("Warfarin")
    print(f"[+] RxNorm: RxCUI = {rxcui}, Name = {canonical_name}")

    label = fetch_fda_label(canonical_name)
    interactions = label.get("drug_interactions", "")
    print(f"  - Interactions Present: {interactions != NOT_PRESENT_IN_LABEL}")
    print(f"  - Interactions Preview: {interactions[:150]}...\n")
    assert interactions != NOT_PRESENT_IN_LABEL, "Expected warfarin to have drug_interactions section"
    print("  [PASSED] Successfully verified extraction of populated drug_interactions!\n")


def test_unknown_drug_handling():
    print("=" * 70)
    print("4. Testing Unknown Drug Fallback Handling")
    print("=" * 70)

    unknown_drug = "NonExistentChemicalX999"
    rxcui, canonical_name = rxnorm_normalize(unknown_drug)
    print(f"[+] rxnorm_normalize('{unknown_drug}') -> ({rxcui}, {canonical_name})")
    assert (rxcui, canonical_name) == (None, None), "Expected (None, None) for unknown drug"

    label = fetch_fda_label("NonExistentChemicalX999")
    print(f"[+] fetch_fda_label('NonExistentChemicalX999') -> found={label.get('found')}")
    assert label.get("drug_interactions") == NOT_PRESENT_IN_LABEL
    assert label.get("found") is False
    print("  [PASSED] Graceful handling of missing/unknown drugs verified!\n")


def main():
    try:
        test_paracetamol_normalization_and_fda()
        test_drug_with_active_interactions()
        test_unknown_drug_handling()
        print("=" * 70)
        print("ALL NORMALIZATION AND FDA LABEL TESTS PASSED SUCCESSFULLY!")
        print("=" * 70)
        sys.exit(0)
    except AssertionError as ae:
        print(f"\n[!] Assertion failed: {ae}")
        sys.exit(1)
    except Exception as exc:
        print(f"\n[!] Unexpected error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
