#!/usr/bin/env python3
"""
scripts/test_drap.py
Standalone test script to verify live DRAP endpoints and composition parsing.

Usage:
    python scripts/test_drap.py [optional_brand_query]
Example:
    python scripts/test_drap.py Panadol
"""

import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.drug_resolution import (
    get_product_details,
    parse_composition,
    search,
)


def run_unit_tests():
    print("=" * 60)
    print("1. Running Composition Parser Unit Verifications")
    print("=" * 60)

    test_cases = [
        ("Guaifenesin ...... 100 mg", [{"name": "Guaifenesin", "amount": "100 mg"}]),
        ("PARACETAMOL 500 mg", [{"name": "PARACETAMOL", "amount": "500 mg"}]),
        (
            "PARACETAMOL 500mg, CAFFEINE 65mg",
            [
                {"name": "PARACETAMOL", "amount": "500mg"},
                {"name": "CAFFEINE", "amount": "65mg"},
            ],
        ),
        (
            "Amoxicillin trihydrate eq to Amoxicillin ...... 400 mg\nPotassium clavulanate eq to clavulanic acid ...... 57 mg",
            [
                {
                    "name": "Amoxicillin trihydrate eq to Amoxicillin",
                    "amount": "400 mg",
                },
                {
                    "name": "Potassium clavulanate eq to clavulanic acid",
                    "amount": "57 mg",
                },
            ],
        ),
        (
            "Guaifenesin ...... 100 mg<br>Phenylephrine HCl ...... 5 mg<br>Triprolidine HCI ...... 1.25 mg",
            [
                {"name": "Guaifenesin", "amount": "100 mg"},
                {"name": "Phenylephrine HCl", "amount": "5 mg"},
                {"name": "Triprolidine HCI", "amount": "1.25 mg"},
            ],
        ),
    ]

    all_passed = True
    for raw, expected in test_cases:
        result = parse_composition(raw)
        passed = result == expected
        status = "PASSED" if passed else "FAILED"
        if not passed:
            all_passed = False
            print(f"  [{status}] Input:    {repr(raw)}")
            print(f"           Got:      {result}")
            print(f"           Expected: {expected}")
        else:
            print(f"  [{status}] {repr(raw[:45])}... -> {result}")

    if all_passed:
        print("  All local composition test cases passed!\n")
    else:
        print("  WARNING: Some unit test cases failed.\n")


def test_live_drap(query: str):
    print("=" * 60)
    print(f"2. Testing Live DRAP Endpoints for Query: '{query}'")
    print("=" * 60)

    print(f"[*] Calling DRAP search endpoint for '{query}'...")
    try:
        results = search(query)
    except Exception as exc:
        print(f"[!] Error calling DRAP search endpoint: {exc}")
        return False

    print(f"[+] Found {len(results)} matching product(s):")
    for idx, item in enumerate(results[:8], 1):
        print(f"    {idx}. ID: {item.get('id')} | Name: {item.get('text')}")

    if not results:
        print(f"[!] No results returned from DRAP for '{query}'.")
        return False

    # Test product details on the first result
    top_result = results[0]
    reg_no = top_result.get("id")
    print("\n" + "-" * 60)
    print(f"3. Fetching Product Details for Top Result: {reg_no} ({top_result.get('text')})")
    print("-" * 60)

    try:
        details = get_product_details(reg_no)
    except Exception as exc:
        print(f"[!] Error fetching product details for {reg_no}: {exc}")
        return False

    print(f"  - Product Name:        {details.get('product_name')}")
    print(f"  - Registration No:     {details.get('registration_no')}")
    print(f"  - Company Name:        {details.get('company') or '(Not listed)'}")
    print(f"  - Registration Status: {details.get('registration_status')}")
    print(f"  - Dosage Form:         {details.get('dosage_form') or '(Not listed)'}")
    print(f"  - Raw Composition:     {repr(details.get('composition_raw'))}")
    print("  - Parsed Ingredients:")
    for ing in details.get("composition", []):
        name = ing.get("name")
        amount = ing.get("amount") or "N/A"
        print(f"      * {name} -> {amount}")

    # If top result had plain trailing-dose, also test a dotted-leader product if present in results
    dotted_item = None
    for item in results:
        if "expectorant" in item.get("text", "").lower() or "syrup" in item.get("text", "").lower():
            dotted_item = item
            break

    if dotted_item and dotted_item.get("id") != reg_no:
        d_reg_no = dotted_item.get("id")
        print("\n" + "-" * 60)
        print(f"4. Fetching Multi-Ingredient / Dotted-Leader Product: {d_reg_no} ({dotted_item.get('text')})")
        print("-" * 60)
        try:
            d_details = get_product_details(d_reg_no)
            print(f"  - Product Name:        {d_details.get('product_name')}")
            print(f"  - Registration No:     {d_details.get('registration_no')}")
            print(f"  - Company Name:        {d_details.get('company') or '(Not listed)'}")
            print(f"  - Registration Status: {d_details.get('registration_status')}")
            print(f"  - Raw Composition:     {repr(d_details.get('composition_raw'))}")
            print("  - Parsed Ingredients:")
            for ing in d_details.get("composition", []):
                name = ing.get("name")
                amount = ing.get("amount") or "N/A"
                print(f"      * {name} -> {amount}")
        except Exception as exc:
            print(f"[!] Error fetching dotted item {d_reg_no}: {exc}")

    print("\n" + "=" * 60)
    print("DRAP Live Endpoint Verification Complete!")
    print("=" * 60)
    return True


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "Panadol"
    run_unit_tests()
    success = test_live_drap(query)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
