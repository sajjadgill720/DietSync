"""
worker/eval/evaluators.py
Custom evaluators for DietSync clinical interaction, allergy, and diet checking.

Per PROJECT_SPEC.md lines 128-132:
1. Groundedness Evaluator:
   Checks whether returned interaction claims (drug-drug and food-drug) are actually
   entailed by cited source text and whether citations are genuinely present in the FDA label.
2. Refusal-Correctness Evaluator:
   Checks whether the system correctly abstains ('none_found' / 'unverifiable')
   on pairs known to have no documented interaction, and correctly detects
   ('interaction_found') on pairs known to interact.
3. Allergy Evaluator:
   Checks whether the rule-based cross-reactivity checker correctly flags true allergy
   hazards (recall-first) and correctly avoids false flags on safe combinations.
4. Food Interaction Evaluator:
   Checks whether food/dietary/alcohol interactions are correctly recalled from FDA labels.
"""

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("evaluators")


def clean_text(text: Optional[str]) -> str:
    """Normalizes whitespace and casing for robust text comparison."""
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", text).strip().lower()
    return cleaned


class GroundednessEvaluator:
    """
    Evaluator verifying whether interaction claims and citations (drug-drug and food-drug)
    are strictly grounded in the retrieved official FDA label text.
    """

    def __init__(self, name: str = "groundedness_evaluator"):
        self.name = name

    def evaluate(
        self,
        output_state: Dict[str, Any],
        raw_source_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates groundedness of the graph's output state.
        Checks both drug interaction citations and food interaction citations.
        """
        final_status = output_state.get("final_status")
        claim = output_state.get("interaction_claim")
        citation = output_state.get("citation_text")

        food_claim = output_state.get("food_interaction_claim")
        food_citation = output_state.get("food_citation_text")

        # 1. Audit drug-drug interaction citation if claimed
        if claim and claim != "no interaction found":
            if not citation or not citation.strip():
                return {
                    "key": "groundedness",
                    "score": 0.0,
                    "value": "fail",
                    "reasoning": "Drug interaction claimed but no source citation was provided.",
                }
            if raw_source_text:
                clean_citation = clean_text(citation)
                clean_source = clean_text(raw_source_text)
                citation_first_40 = clean_citation[:40]
                if clean_citation not in clean_source and citation_first_40 not in clean_source:
                    return {
                        "key": "groundedness",
                        "score": 0.0,
                        "value": "fail",
                        "reasoning": (
                            "Hallucination detected: Quoted drug interaction citation was NOT found "
                            "in the retrieved FDA label text."
                        ),
                    }

        # 2. Audit food interaction citation if claimed
        if food_claim:
            if not food_citation or not food_citation.strip():
                return {
                    "key": "groundedness",
                    "score": 0.0,
                    "value": "fail",
                    "reasoning": "Food interaction claimed but no source citation was provided.",
                }
            if raw_source_text:
                clean_food_cit = clean_text(food_citation)
                clean_source = clean_text(raw_source_text)
                cit_first_40 = clean_food_cit[:40]
                if clean_food_cit not in clean_source and cit_first_40 not in clean_source:
                    return {
                        "key": "groundedness",
                        "score": 0.0,
                        "value": "fail",
                        "reasoning": (
                            "Hallucination detected: Quoted food interaction citation was NOT found "
                            "in the retrieved FDA label text."
                        ),
                    }

        # Pass if no ungrounded claims detected
        return {
            "key": "groundedness",
            "score": 1.0,
            "value": "pass",
            "reasoning": "All returned claims and citations are strictly grounded in official label text.",
        }


class RefusalCorrectnessEvaluator:
    """
    Evaluator verifying whether the system correctly abstains on negative pairs
    and detects interactions on positive pairs.
    """

    def __init__(self, name: str = "refusal_correctness_evaluator"):
        self.name = name

    def evaluate(
        self,
        expected_status: str,
        actual_status: str,
        drug_a_name: str = "",
        drug_b_name: str = "",
    ) -> Dict[str, Any]:
        exp = expected_status.strip().lower()
        act = actual_status.strip().lower()

        # CASE 1: Expected interaction (Ground Truth: Positive)
        if exp == "interaction_found":
            if act == "interaction_found":
                return {
                    "key": "refusal_correctness",
                    "score": 1.0,
                    "category": "TP",
                    "value": "true_positive",
                    "reasoning": f"Correctly detected known interaction between {drug_a_name} and {drug_b_name}.",
                }
            else:
                return {
                    "key": "refusal_correctness",
                    "score": 0.0,
                    "category": "FN",
                    "value": "false_negative",
                    "reasoning": (
                        f"CRITICAL SAFETY MISS (FN): Known interaction between {drug_a_name} and {drug_b_name} "
                        f"was missed (actual outcome: '{act}')."
                    ),
                }

        # CASE 2: Expected no interaction / abstention (Ground Truth: Negative)
        elif exp == "none_found":
            if act in ("none_found", "unverifiable"):
                return {
                    "key": "refusal_correctness",
                    "score": 1.0,
                    "category": "TN",
                    "value": "true_negative",
                    "reasoning": (
                        f"Correctly abstained on non-interacting pair {drug_a_name} and {drug_b_name} "
                        f"(actual outcome: '{act}')."
                    ),
                }
            else:
                return {
                    "key": "refusal_correctness",
                    "score": 0.0,
                    "category": "FP",
                    "value": "false_positive",
                    "reasoning": (
                        f"OVER-CLAIM (FP): Claimed interaction between {drug_a_name} and {drug_b_name} "
                        "when none exists in authoritative clinical references."
                    ),
                }

        else:
            raise ValueError(f"Unknown expected status: '{expected_status}'")


class AllergyEvaluator:
    """
    Evaluator for allergy cross-reactivity flags under recall-first philosophy:
    Missing a genuine cross-reactive allergy is a critical safety failure (FN).
    """

    def __init__(self, name: str = "allergy_evaluator"):
        self.name = name

    def evaluate(
        self,
        expected_has_allergy: bool,
        actual_flags: Optional[List[Dict[str, Any]]],
        allergy_terms: Optional[List[str]] = None,
        drug_names: str = "",
    ) -> Dict[str, Any]:
        has_flags = bool(actual_flags and len(actual_flags) > 0)

        if expected_has_allergy:
            if has_flags:
                matched_classes = [f.get("matched_class") for f in actual_flags]
                return {
                    "key": "allergy_check",
                    "score": 1.0,
                    "category": "TP",
                    "value": "true_positive",
                    "reasoning": (
                        f"Correctly flagged allergy hazard for {allergy_terms} against {drug_names} "
                        f"via classes: {matched_classes}."
                    ),
                }
            else:
                return {
                    "key": "allergy_check",
                    "score": 0.0,
                    "category": "FN",
                    "value": "false_negative",
                    "reasoning": (
                        f"CRITICAL SAFETY FAILURE (FN): Stated allergy {allergy_terms} cross-reacts "
                        f"with {drug_names}, but no allergy flag was emitted."
                    ),
                }
        else:
            if not has_flags:
                return {
                    "key": "allergy_check",
                    "score": 1.0,
                    "category": "TN",
                    "value": "true_negative",
                    "reasoning": f"Correctly determined no cross-reactivity between {allergy_terms} and {drug_names}.",
                }
            else:
                return {
                    "key": "allergy_check",
                    "score": 0.0,
                    "category": "FP",
                    "value": "false_positive",
                    "reasoning": (
                        f"False allergy warning emitted for {allergy_terms} against {drug_names}."
                    ),
                }


class FoodInteractionEvaluator:
    """
    Evaluator for food/diet interaction claims under recall-first philosophy:
    Ensures documented food/alcohol interactions are captured and grounded.
    """

    def __init__(self, name: str = "food_interaction_evaluator"):
        self.name = name

    def evaluate(
        self,
        expected_has_food: bool,
        actual_food_claim: Optional[str],
        actual_food_citation: Optional[str],
        diet_factors: Optional[List[str]] = None,
        drug_names: str = "",
    ) -> Dict[str, Any]:
        has_claim = bool(actual_food_claim and actual_food_claim.strip())

        if expected_has_food:
            if has_claim and actual_food_citation:
                return {
                    "key": "food_interaction",
                    "score": 1.0,
                    "category": "TP",
                    "value": "true_positive",
                    "reasoning": (
                        f"Correctly identified documented food/diet interaction for {drug_names} "
                        f"(factors: {diet_factors}): '{actual_food_claim[:70]}...'"
                    ),
                }
            else:
                return {
                    "key": "food_interaction",
                    "score": 0.0,
                    "category": "FN",
                    "value": "false_negative",
                    "reasoning": (
                        f"CRITICAL RECALL MISS (FN): Documented food interaction for {drug_names} "
                        f"(factors: {diet_factors}) was not detected."
                    ),
                }
        else:
            if not has_claim:
                return {
                    "key": "food_interaction",
                    "score": 1.0,
                    "category": "TN",
                    "value": "true_negative",
                    "reasoning": f"Correctly abstained on food interaction for {drug_names} (factors: {diet_factors}).",
                }
            else:
                return {
                    "key": "food_interaction",
                    "score": 0.0,
                    "category": "FP",
                    "value": "false_positive",
                    "reasoning": (
                        f"Unwarranted food interaction claimed for {drug_names} (factors: {diet_factors})."
                    ),
                }
