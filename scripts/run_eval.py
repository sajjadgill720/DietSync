#!/usr/bin/env python3
"""
scripts/run_eval.py
Evaluation runner for DietSync's LangGraph clinical interaction checker.

Per PROJECT_SPEC.md lines 124-132:
- Full tracing across every graph node with LangSmith enabled.
- Runs the labeled evaluation dataset through the interaction graph.
- Applies Groundedness and Refusal-Correctness evaluators.
- Reports Recall, Precision, and Groundedness metrics to validate
  the safety philosophy: 'Recall over precision on flagging; never infer
  beyond retrieved sources; refusal is a valid outcome.'
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Ensure repository root and app directory are on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "app"))

from worker.eval.evaluators import (
    AllergyEvaluator,
    FoodInteractionEvaluator,
    GroundednessEvaluator,
    RefusalCorrectnessEvaluator,
)
from worker.langgraph.graph import invoke_interaction_graph
from worker.langgraph.nodes import InteractionState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("run_eval")

DATASET_FILE_PATH = REPO_ROOT / "data" / "eval_dataset.json"


def test_connection_or_delegate_to_wsl():
    """
    Ensures script executes inside WSL when running on Windows,
    so database access and local resources are consistent.
    """
    if sys.platform == "win32" and "--no-wsl-delegate" not in sys.argv:
        logger.info("Running evaluation suite in WSL Linux environment...")
        wsl_cmd = [
            "wsl",
            "-d",
            "Ubuntu",
            "-u",
            "root",
            "--",
            "bash",
            "-l",
            "-c",
            "cd /root/dietsync && "
            "DATABASE_URL=postgresql://postgres:postgres@localhost:5432/dietsync "
            "/opt/dietsync_venv/bin/python scripts/run_eval.py --no-wsl-delegate "
            + " ".join(f'"{arg}"' for arg in sys.argv[1:] if arg != "--no-wsl-delegate"),
        ]
        res = subprocess.run(wsl_cmd)
        sys.exit(res.returncode)


def load_eval_dataset(dataset_path: Path = DATASET_FILE_PATH) -> List[Dict[str, Any]]:
    """Loads the labeled eval dataset from JSON file."""
    if not dataset_path.exists():
        logger.error(f"Eval dataset not found at {dataset_path}. Run scripts/build_eval_dataset.py first.")
        sys.exit(1)

    with open(dataset_path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_evaluation(
    max_cases: Optional[int] = None,
    filter_status: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes the full evaluation workflow over the labeled dataset.
    """
    dataset = load_eval_dataset()

    if filter_status:
        dataset = [d for d in dataset if d.get("expected_status") == filter_status]

    if max_cases:
        dataset = dataset[:max_cases]

    total_cases = len(dataset)
    logger.info(f"Starting evaluation on {total_cases} test cases...")

    groundedness_eval = GroundednessEvaluator()
    refusal_eval = RefusalCorrectnessEvaluator()
    allergy_eval = AllergyEvaluator()
    food_eval = FoodInteractionEvaluator()

    tp = 0  # True Positives (Drug-Drug)
    fp = 0  # False Positives
    tn = 0  # True Negatives
    fn = 0  # False Negatives

    allergy_tp = 0
    allergy_tn = 0
    allergy_fp = 0
    allergy_fn = 0

    food_tp = 0
    food_tn = 0
    food_fp = 0
    food_fn = 0

    grounded_passed = 0
    grounded_evaluated = 0

    results = []

    print("\n" + "=" * 105)
    print("DIETSYNC CLINICAL SAFETY EVALUATION SUITE (DRUG-DRUG, ALLERGY, & DIET)")
    print("=" * 105)
    print(f"{'ID':<10} {'Drug Pair':<32} {'Expected':<18} {'Actual':<18} {'D-D':<5} {'Allergy':<8} {'Food':<6} {'Grounded'}")
    print("-" * 105)

    start_time = time.time()

    for item in dataset:
        case_id = item.get("id", "N/A")
        drug_a = item["drug_a"]
        drug_b = item["drug_b"]
        name_a = drug_a.get("brand_name") or drug_a.get("generic_name") or "Drug A"
        name_b = drug_b.get("brand_name") or drug_b.get("generic_name") or "Drug B"
        pair_str = f"{name_a[:14]} + {name_b[:14]}"
        expected_status = item["expected_status"]

        patient_allergies = item.get("patient_allergies", [])
        patient_diet = item.get("patient_diet_factors", [])

        # Prepare initial state for the LangGraph state machine
        initial_state: InteractionState = {
            "drug_a": {
                "id": drug_a.get("id"),
                "brand_name": drug_a.get("brand_name"),
                "generic_name": drug_a.get("generic_name"),
                "rxcui": drug_a.get("rxcui"),
            },
            "drug_b": {
                "id": drug_b.get("id"),
                "brand_name": drug_b.get("brand_name"),
                "generic_name": drug_b.get("generic_name"),
                "rxcui": drug_b.get("rxcui"),
            },
            "patient_allergies": patient_allergies,
            "patient_diet_factors": patient_diet,
            "interaction_claim": None,
            "citation_text": None,
            "is_grounded": None,
            "allergy_flags": [],
            "food_interaction_claim": None,
            "food_citation_text": None,
            "final_status": "none_found",
            "final_answer": None,
        }

        # Run interaction checking graph with LangSmith tracing enabled
        config = {
            "metadata": {
                "eval_case_id": case_id,
                "expected_status": expected_status,
                "drug_a": name_a,
                "drug_b": name_b,
                "patient_allergies": patient_allergies,
                "patient_diet": patient_diet,
            },
            "tags": ["eval_run", expected_status],
        }
        final_state = invoke_interaction_graph(initial_state, config=config)

        actual_status = final_state.get("final_status", "unverifiable")

        # Combine source label texts for groundedness check
        raw_source_text = (
            (final_state.get("drug_a", {}).get("fda_label_text") or "")
            + "\n"
            + (final_state.get("drug_b", {}).get("fda_label_text") or "")
        )

        # 1. Evaluate Groundedness
        g_res = groundedness_eval.evaluate(final_state, raw_source_text=raw_source_text)
        is_grounded_score = g_res.get("score", 0.0)

        if actual_status == "interaction_found" or final_state.get("food_interaction_claim"):
            grounded_evaluated += 1
            if is_grounded_score == 1.0:
                grounded_passed += 1

        # 2. Evaluate Refusal Correctness (Drug-Drug)
        r_res = refusal_eval.evaluate(
            expected_status=expected_status,
            actual_status=actual_status,
            drug_a_name=name_a,
            drug_b_name=name_b,
        )
        cat = r_res.get("category", "N/A")
        if cat == "TP":
            tp += 1
        elif cat == "TN":
            tn += 1
        elif cat == "FP":
            fp += 1
        elif cat == "FN":
            fn += 1

        # 3. Evaluate Allergy Cross-Reactivity
        a_mark = "-"
        if "expected_has_allergy" in item:
            exp_allergy = bool(item["expected_has_allergy"])
            a_res = allergy_eval.evaluate(
                expected_has_allergy=exp_allergy,
                actual_flags=final_state.get("allergy_flags"),
                allergy_terms=patient_allergies,
                drug_names=f"{name_a} / {name_b}",
            )
            a_cat = a_res.get("category")
            if a_cat == "TP":
                allergy_tp += 1
                a_mark = "TP"
            elif a_cat == "TN":
                allergy_tn += 1
                a_mark = "TN"
            elif a_cat == "FP":
                allergy_fp += 1
                a_mark = "FP"
            elif a_cat == "FN":
                allergy_fn += 1
                a_mark = "FN"

        # 4. Evaluate Food Interaction
        f_mark = "-"
        if "expected_has_food" in item:
            exp_food = bool(item["expected_has_food"])
            f_res = food_eval.evaluate(
                expected_has_food=exp_food,
                actual_food_claim=final_state.get("food_interaction_claim"),
                actual_food_citation=final_state.get("food_citation_text"),
                diet_factors=patient_diet,
                drug_names=f"{name_a} / {name_b}",
            )
            f_cat = f_res.get("category")
            if f_cat == "TP":
                food_tp += 1
                f_mark = "TP"
            elif f_cat == "TN":
                food_tn += 1
                f_mark = "TN"
            elif f_cat == "FP":
                food_fp += 1
                f_mark = "FP"
            elif f_cat == "FN":
                food_fn += 1
                f_mark = "FN"

        g_mark = "PASS" if is_grounded_score == 1.0 else "FAIL"
        print(f"{case_id:<10} {pair_str:<32} {expected_status:<18} {actual_status:<18} {cat:<5} {a_mark:<8} {f_mark:<6} {g_mark}")

        results.append({
            "id": case_id,
            "drug_a": name_a,
            "drug_b": name_b,
            "expected_status": expected_status,
            "actual_status": actual_status,
            "category": cat,
            "groundedness": g_res,
            "refusal_correctness": r_res,
            "allergy_flags": final_state.get("allergy_flags", []),
            "food_interaction": final_state.get("food_interaction_claim"),
            "claim": final_state.get("interaction_claim"),
            "citation": final_state.get("citation_text"),
        })

    elapsed_time = time.time() - start_time

    # Calculate metrics
    recall = (tp / (tp + fn)) if (tp + fn) > 0 else 0.0
    precision = (tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    accuracy = ((tp + tn) / total_cases) if total_cases > 0 else 0.0
    groundedness_rate = (grounded_passed / grounded_evaluated) if grounded_evaluated > 0 else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    total_allergy_cases = allergy_tp + allergy_tn + allergy_fp + allergy_fn
    allergy_recall = (allergy_tp / (allergy_tp + allergy_fn)) if (allergy_tp + allergy_fn) > 0 else 0.0
    allergy_precision = (allergy_tp / (allergy_tp + allergy_fp)) if (allergy_tp + allergy_fp) > 0 else 0.0

    total_food_cases = food_tp + food_tn + food_fp + food_fn
    food_recall = (food_tp / (food_tp + food_fn)) if (food_tp + food_fn) > 0 else 0.0
    food_precision = (food_tp / (food_tp + food_fp)) if (food_tp + food_fp) > 0 else 0.0

    print("\n" + "=" * 105)
    print("EVALUATION SUMMARY & METRICS")
    print("=" * 105)
    print(f"Total Test Cases:            {total_cases}")
    print(f"Execution Time:              {elapsed_time:.2f}s ({elapsed_time/total_cases:.2f}s/case)")
    print("-" * 105)
    print(f"DRUG-DRUG INTERACTION METRICS:")
    print(f"  Recall (Safety Sensitivity): {recall * 100:.1f}%   (Target: 100% — Recall over precision)")
    print(f"  Precision:                   {precision * 100:.1f}%")
    print(f"  F1 Score:                    {f1 * 100:.1f}%")
    print(f"  Groundedness Rate:           {groundedness_rate * 100:.1f}%   (Target: 100% — Zero unverified claims)")
    print(f"  Refusal Correctness Rate:    {accuracy * 100:.1f}%")

    if total_allergy_cases > 0:
        print("-" * 105)
        print(f"ALLERGY CROSS-REACTIVITY METRICS ({total_allergy_cases} evaluated cases):")
        print(f"  Recall (Safety Sensitivity): {allergy_recall * 100:.1f}%   (Target: 100% — Never miss cross-reactive allergen)")
        print(f"  Precision:                   {allergy_precision * 100:.1f}%")
        print(f"  TP: {allergy_tp} | TN: {allergy_tn} | FP: {allergy_fp} | FN: {allergy_fn}")

    if total_food_cases > 0:
        print("-" * 105)
        print(f"FOOD / DIETARY INTERACTION METRICS ({total_food_cases} evaluated cases):")
        print(f"  Recall:                      {food_recall * 100:.1f}%")
        print(f"  Precision:                   {food_precision * 100:.1f}%")
        print(f"  TP: {food_tp} | TN: {food_tn} | FP: {food_fp} | FN: {food_fn}")

    print("=" * 105)

    # Print any Critical Safety Warnings (False Negatives)
    if fn > 0:
        print("\n[WARNING] DRUG-DRUG FALSE NEGATIVE DETECTED! Missed interaction pairs:")
        for r in results:
            if r["category"] == "FN":
                print(f"  - {r['drug_a']} + {r['drug_b']} (Actual: {r['actual_status']})")

    if allergy_fn > 0:
        print("\n[WARNING] ALLERGY FALSE NEGATIVE DETECTED! Missed allergy hazard:")
        for r in results:
            if r.get("allergy_fn"):
                print(f"  - {r['drug_a']} + {r['drug_b']}")

    # Print any Unverified Hallucinations
    unverified_claims = [r for r in results if r["groundedness"]["score"] == 0.0]
    if unverified_claims:
        print("\n[CRITICAL] UNGROUNDED CLAIM DETECTED!")
        for r in unverified_claims:
            print(f"  - {r['drug_a']} + {r['drug_b']}: {r['groundedness']['reasoning']}")

    metrics = {
        "total_cases": total_cases,
        "true_positives": tp,
        "true_negatives": tn,
        "false_positives": fp,
        "false_negatives": fn,
        "recall": recall,
        "precision": precision,
        "allergy_recall": allergy_recall,
        "allergy_precision": allergy_precision,
        "food_recall": food_recall,
        "food_precision": food_precision,
        "f1_score": f1,
        "groundedness_rate": groundedness_rate,
        "accuracy": accuracy,
        "elapsed_time": elapsed_time,
        "results": results,
    }

    return metrics

    # Print any Critical Safety Warnings (False Negatives)
    if fn > 0:
        print("\n⚠️ WARNING: FALSE NEGATIVE DETECTED! Missed interaction pairs:")
        for r in results:
            if r["category"] == "FN":
                print(f"  - {r['drug_a']} + {r['drug_b']} (Actual: {r['actual_status']})")

    # Print any Unverified Hallucinations
    unverified_claims = [r for r in results if r["groundedness"]["score"] == 0.0]
    if unverified_claims:
        print("\n🛑 WARNING: UNGROUNDED CLAIM DETECTED!")
        for r in unverified_claims:
            print(f"  - {r['drug_a']} + {r['drug_b']}: {r['groundedness']['reasoning']}")

    metrics = {
        "total_cases": total_cases,
        "true_positives": tp,
        "true_negatives": tn,
        "false_positives": fp,
        "false_negatives": fn,
        "recall": recall,
        "precision": precision,
        "f1_score": f1,
        "groundedness_rate": groundedness_rate,
        "accuracy": accuracy,
        "elapsed_time": elapsed_time,
        "results": results,
    }

    return metrics


def main():
    test_connection_or_delegate_to_wsl()

    parser = argparse.ArgumentParser(description="DietSync Evaluation Runner")
    parser.add_argument("--no-wsl-delegate", action="store_true", help="Internal flag for WSL execution")
    parser.add_argument("--max", type=int, default=None, help="Maximum number of test cases to run")
    parser.add_argument(
        "--filter",
        choices=["interaction_found", "none_found"],
        default=None,
        help="Filter evaluation cases by expected status",
    )
    args = parser.parse_args()

    run_evaluation(max_cases=args.max, filter_status=args.filter)


if __name__ == "__main__":
    main()
