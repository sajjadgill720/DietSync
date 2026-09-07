#!/usr/bin/env python3
"""
scripts/build_eval_dataset.py
Constructs, manages, and exports the labeled evaluation dataset for DietSync.

Per PROJECT_SPEC.md lines 124-132:
- Labeled eval dataset built from the curated drug list:
  - Known-interacting pairs (with expected severity language and clinical mechanism)
  - Known-non-interacting pairs (enabling measurement of precision & refusal correctness)
- Supports manual addition of hand-picked pairs with known ground truth.
- Saves to data/eval_dataset.json and optionally syncs to LangSmith dataset.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure repository root and app directory are on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "app"))

from app.db.models import Drug
from app.db.session import SessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("build_eval_dataset")

DATASET_FILE_PATH = REPO_ROOT / "data" / "eval_dataset.json"

# Core curated ground truth seed pairs from Pakistani brands + openFDA labels
CURATED_GROUND_TRUTH_PAIRS = [
    # --------------------------------------------------------------------------
    # POSITIVE INTERACTION PAIRS (Expected: interaction_found)
    # --------------------------------------------------------------------------
    {
        "drug_a_query": "Disprin",
        "drug_b_query": "Warfarin",
        "expected_status": "interaction_found",
        "severity": "major",
        "expected_keywords": ["bleeding", "anticoagulant", "hemorrhage", "salicylate", "platelet"],
        "clinical_mechanism": (
            "Concomitant administration of salicylates (aspirin) with warfarin increases "
            "the risk of major gastrointestinal and systemic bleeding due to platelet inhibition "
            "and mucosal injury."
        ),
        "source": "openFDA",
    },
    {
        "drug_a_query": "Klaricid",
        "drug_b_query": "Lipitor",
        "expected_status": "interaction_found",
        "severity": "contraindicated",
        "expected_keywords": ["rhabdomyolysis", "myopathy", "cyp3a4", "atorvastatin", "clarithromycin"],
        "clinical_mechanism": (
            "Clarithromycin is a potent CYP3A4 inhibitor that markedly elevates atorvastatin "
            "exposure, significantly increasing the hazard of severe myopathy and rhabdomyolysis."
        ),
        "source": "openFDA",
    },
    {
        "drug_a_query": "Brufen",
        "drug_b_query": "Warfarin",
        "expected_status": "interaction_found",
        "severity": "major",
        "expected_keywords": ["bleeding", "gastrointestinal", "inr", "anticoagulant", "hemorrhage"],
        "clinical_mechanism": (
            "NSAIDs such as ibuprofen inhibit platelet function and can cause gastrointestinal "
            "ulceration, potentiating bleeding hazards when co-administered with warfarin."
        ),
        "source": "openFDA",
    },
    {
        "drug_a_query": "Disprin",
        "drug_b_query": "Brufen",
        "expected_status": "interaction_found",
        "severity": "moderate",
        "expected_keywords": ["aspirin", "ibuprofen", "gastrointestinal", "ulceration", "cardioprotective"],
        "clinical_mechanism": (
            "Ibuprofen interferes competitively with the irreversible platelet inhibition of low-dose "
            "aspirin, attenuating its cardioprotective efficacy while increasing ulcer risk."
        ),
        "source": "openFDA",
    },
    {
        "drug_a_query": "Zestril",
        "drug_b_query": "Lasix",
        "expected_status": "interaction_found",
        "severity": "moderate",
        "expected_keywords": ["hypotension", "renal", "diuretic", "blood pressure", "furosemide"],
        "clinical_mechanism": (
            "Combining an ACE inhibitor (lisinopril) with a potent loop diuretic (furosemide) "
            "can induce severe first-dose hypotension and acute renal impairment."
        ),
        "source": "openFDA",
    },
    {
        "drug_a_query": "Flagyl",
        "drug_b_query": "Warfarin",
        "expected_status": "interaction_found",
        "severity": "major",
        "expected_keywords": ["warfarin", "prothrombin", "anticoagulant", "bleeding", "inr"],
        "clinical_mechanism": (
            "Metronidazole significantly potentiates the anticoagulant effect of warfarin "
            "by decreasing the metabolism of S-warfarin, precipitating hemorrhage."
        ),
        "source": "openFDA",
    },
    {
        "drug_a_query": "Klaricid",
        "drug_b_query": "Warfarin",
        "expected_status": "interaction_found",
        "severity": "major",
        "expected_keywords": ["warfarin", "prothrombin", "anticoagulant", "bleeding", "inr"],
        "clinical_mechanism": (
            "Macrolide antibiotics (clarithromycin) inhibit CYP metabolism and gut flora clearance "
            "of warfarin, causing dangerous elevations in prothrombin time."
        ),
        "source": "openFDA",
    },

    # --------------------------------------------------------------------------
    # NEGATIVE / ABSTENTION PAIRS (Expected: none_found)
    # --------------------------------------------------------------------------
    {
        "drug_a_query": "Panadol",
        "drug_b_query": "Norvasc",
        "expected_status": "none_found",
        "severity": "none",
        "expected_keywords": [],
        "clinical_mechanism": "No documented drug-drug interaction between paracetamol and amlodipine.",
        "source": "openFDA",
    },
    {
        "drug_a_query": "Augmentin",
        "drug_b_query": "Panadol",
        "expected_status": "none_found",
        "severity": "none",
        "expected_keywords": [],
        "clinical_mechanism": (
            "Commonly co-prescribed analgesic/antipyretic with penicillin antibiotic; "
            "no mutual drug-drug interaction in official label text."
        ),
        "source": "openFDA",
    },
    {
        "drug_a_query": "Lipitor",
        "drug_b_query": "Panadol",
        "expected_status": "none_found",
        "severity": "none",
        "expected_keywords": [],
        "clinical_mechanism": "No significant pharmacokinetic interaction between paracetamol and atorvastatin.",
        "source": "openFDA",
    },
    {
        "drug_a_query": "Risek",
        "drug_b_query": "Panadol",
        "expected_status": "none_found",
        "severity": "none",
        "expected_keywords": [],
        "clinical_mechanism": "Omeprazole does not significantly interact with standard therapeutic doses of paracetamol.",
        "source": "openFDA",
    },
    {
        "drug_a_query": "Ventolin",
        "drug_b_query": "Panadol",
        "expected_status": "none_found",
        "severity": "none",
        "expected_keywords": [],
        "clinical_mechanism": "No interaction between beta-2 adrenergic agonist salbutamol and paracetamol.",
        "source": "openFDA",
    },
    {
        "drug_a_query": "Norvasc",
        "drug_b_query": "Glucophage",
        "expected_status": "none_found",
        "severity": "none",
        "expected_keywords": [],
        "clinical_mechanism": "Amlodipine and metformin have no documented mutual adverse interactions.",
        "source": "openFDA",
    },
    {
        "drug_a_query": "Risek",
        "drug_b_query": "Glucophage",
        "expected_status": "none_found",
        "severity": "none",
        "expected_keywords": [],
        "clinical_mechanism": "Omeprazole and metformin are co-administered without significant mutual interaction.",
        "source": "openFDA",
    },

    # --------------------------------------------------------------------------
    # ALLERGY CROSS-REACTIVITY EVALUATION CASES
    # --------------------------------------------------------------------------
    {
        "drug_a_query": "Augmentin",
        "drug_b_query": "Panadol",
        "expected_status": "none_found",
        "severity": "none",
        "expected_keywords": [],
        "patient_allergies": ["penicillin"],
        "expected_has_allergy": True,
        "clinical_mechanism": (
            "Augmentin contains amoxicillin (extended-spectrum penicillin, ATC J01CA); "
            "it triggers an allergy cross-reactivity flag for a patient with documented penicillin allergy."
        ),
        "source": "RxClass",
    },
    {
        "drug_a_query": "Brufen",
        "drug_b_query": "Panadol",
        "expected_status": "none_found",
        "severity": "none",
        "expected_keywords": [],
        "patient_allergies": ["aspirin"],
        "expected_has_allergy": True,
        "clinical_mechanism": (
            "Brufen contains ibuprofen (propionic acid NSAID, ATC M01AE); patients with aspirin hypersensitivity "
            "cross-react with ibuprofen due to COX-1 inhibition and leukotriene shift."
        ),
        "source": "RxClass",
    },
    {
        "drug_a_query": "Lasix",
        "drug_b_query": "Panadol",
        "expected_status": "none_found",
        "severity": "none",
        "expected_keywords": [],
        "patient_allergies": ["sulfonamide"],
        "expected_has_allergy": True,
        "clinical_mechanism": (
            "Lasix contains furosemide (sulfonamide loop diuretic, ATC C03CA); triggers a cautionary "
            "allergy warning for patients with stated sulfonamide allergy."
        ),
        "source": "RxClass",
    },
    {
        "drug_a_query": "Panadol",
        "drug_b_query": "Norvasc",
        "expected_status": "none_found",
        "severity": "none",
        "expected_keywords": [],
        "patient_allergies": ["penicillin"],
        "expected_has_allergy": False,
        "clinical_mechanism": "Neither paracetamol nor amlodipine shares structural or immunologic cross-reactivity with penicillin.",
        "source": "RxClass",
    },

    # --------------------------------------------------------------------------
    # FOOD / DIETARY INTERACTION EVALUATION CASES
    # --------------------------------------------------------------------------
    {
        "drug_a_query": "Lipitor",
        "drug_b_query": "Panadol",
        "expected_status": "none_found",
        "severity": "none",
        "expected_keywords": [],
        "patient_diet_factors": ["grapefruit"],
        "expected_has_food": True,
        "clinical_mechanism": (
            "Atorvastatin FDA label explicitly warns that grapefruit juice increases plasma concentrations "
            "of atorvastatin and can increase the risk for myopathy and rhabdomyolysis."
        ),
        "source": "openFDA",
    },
    {
        "drug_a_query": "Flagyl",
        "drug_b_query": "Panadol",
        "expected_status": "none_found",
        "severity": "none",
        "expected_keywords": [],
        "patient_diet_factors": ["alcohol"],
        "expected_has_food": True,
        "clinical_mechanism": (
            "Metronidazole FDA label explicitly warns against alcohol consumption during therapy "
            "due to potential disulfiram-like ethanol intolerance reactions."
        ),
        "source": "openFDA",
    },
    {
        "drug_a_query": "Warfarin",
        "drug_b_query": "Panadol",
        "expected_status": "none_found",
        "severity": "none",
        "expected_keywords": [],
        "patient_diet_factors": ["alcohol"],
        "expected_has_food": True,
        "clinical_mechanism": (
            "Warfarin label explicitly notes that acute alcohol consumption increases INR and bleeding risk."
        ),
        "source": "openFDA",
    },
]


def test_connection_or_delegate_to_wsl():
    """
    Ensures script executes inside WSL when running on Windows,
    matching PostgreSQL host networking.
    """
    if sys.platform == "win32" and "--no-wsl-delegate" not in sys.argv:
        logger.info("Running dataset builder in WSL Linux environment...")
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
            "/opt/dietsync_venv/bin/python scripts/build_eval_dataset.py --no-wsl-delegate "
            + " ".join(f'"{arg}"' for arg in sys.argv[1:] if arg != "--no-wsl-delegate"),
        ]
        res = subprocess.run(wsl_cmd)
        sys.exit(res.returncode)


def find_drug_by_query(query: str, session) -> Optional[Drug]:
    """Finds matching drug record in PostgreSQL database by brand substring."""
    q = query.strip()
    return session.query(Drug).filter(Drug.brand_name.ilike(f"%{q}%")).first()


def build_and_save_dataset(
    extra_pairs: Optional[List[Dict[str, Any]]] = None,
    sync_langsmith: bool = False,
) -> List[Dict[str, Any]]:
    """
    Resolves each evaluation pair against the database, validates IDs,
    and writes the consolidated dataset to data/eval_dataset.json.
    """
    session = SessionLocal()
    all_pairs = list(CURATED_GROUND_TRUTH_PAIRS)
    if extra_pairs:
        all_pairs.extend(extra_pairs)

    resolved_dataset = []

    try:
        logger.info(f"Building evaluation dataset from {len(all_pairs)} labeled pairs...")

        for idx, item in enumerate(all_pairs, 1):
            q_a = item["drug_a_query"]
            q_b = item["drug_b_query"]

            drug_a = find_drug_by_query(q_a, session)
            drug_b = find_drug_by_query(q_b, session)

            if not drug_a or not drug_b:
                missing = []
                if not drug_a:
                    missing.append(q_a)
                if not drug_b:
                    missing.append(q_b)
                logger.warning(f"Skipping pair {q_a} + {q_b}: drug(s) not found in DB: {missing}")
                continue

            entry = {
                "id": f"eval_{idx:03d}",
                "drug_a": {
                    "id": drug_a.id,
                    "brand_name": drug_a.brand_name,
                    "generic_name": drug_a.ingredients[0].generic_name if drug_a.ingredients else None,
                    "rxcui": drug_a.ingredients[0].rxcui if drug_a.ingredients else None,
                },
                "drug_b": {
                    "id": drug_b.id,
                    "brand_name": drug_b.brand_name,
                    "generic_name": drug_b.ingredients[0].generic_name if drug_b.ingredients else None,
                    "rxcui": drug_b.ingredients[0].rxcui if drug_b.ingredients else None,
                },
                "patient_allergies": item.get("patient_allergies", []),
                "patient_diet_factors": item.get("patient_diet_factors", []),
                "expected_status": item["expected_status"],
                "expected_has_allergy": item.get("expected_has_allergy"),
                "expected_has_food": item.get("expected_has_food"),
                "severity": item.get("severity", "none"),
                "expected_keywords": item.get("expected_keywords", []),
                "clinical_mechanism": item.get("clinical_mechanism", ""),
                "source": item.get("source", "openFDA"),
            }
            resolved_dataset.append(entry)
            logger.info(
                f"  [{idx:02d}] {drug_a.brand_name} (ID: {drug_a.id}) + {drug_b.brand_name} (ID: {drug_b.id}) "
                f"-> Expected: {item['expected_status'].upper()} ({item.get('severity')})"
            )

        # Ensure target directory exists
        DATASET_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DATASET_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(resolved_dataset, f, indent=2)

        logger.info(f"Successfully saved {len(resolved_dataset)} evaluation cases to {DATASET_FILE_PATH}")

        # Optional: Sync to LangSmith if requested and API key is set
        if sync_langsmith or os.getenv("LANGCHAIN_API_KEY"):
            sync_to_langsmith(resolved_dataset)

        return resolved_dataset

    finally:
        session.close()


def sync_to_langsmith(dataset: List[Dict[str, Any]], dataset_name: str = "dietsync_interaction_eval"):
    """
    Uploads or updates the evaluation dataset in LangSmith.
    """
    api_key = os.getenv("LANGCHAIN_API_KEY")
    if not api_key:
        logger.info("LANGCHAIN_API_KEY not configured; skipping remote LangSmith upload.")
        return

    try:
        from langsmith import Client

        client = Client()
        logger.info(f"Syncing dataset '{dataset_name}' to LangSmith...")

        # Create or fetch dataset
        if client.has_dataset(dataset_name=dataset_name):
            ds = client.read_dataset(dataset_name=dataset_name)
            logger.info(f"Existing LangSmith dataset found: {ds.id}")
        else:
            ds = client.create_dataset(
                dataset_name=dataset_name,
                description="DietSync clinical drug interaction evaluation dataset with labeled ground truth.",
            )
            logger.info(f"Created new LangSmith dataset: {ds.id}")

        # Add examples
        inputs = [
            {
                "drug_a": item["drug_a"],
                "drug_b": item["drug_b"],
            }
            for item in dataset
        ]
        outputs = [
            {
                "expected_status": item["expected_status"],
                "severity": item["severity"],
                "clinical_mechanism": item["clinical_mechanism"],
            }
            for item in dataset
        ]
        client.create_examples(
            inputs=inputs,
            outputs=outputs,
            dataset_id=ds.id,
        )
        logger.info(f"Uploaded {len(dataset)} examples to LangSmith dataset '{dataset_name}'.")

    except Exception as exc:
        logger.warning(f"Could not sync to LangSmith: {exc}")


def main():
    test_connection_or_delegate_to_wsl()

    parser = argparse.ArgumentParser(description="DietSync Evaluation Dataset Builder")
    parser.add_argument("--no-wsl-delegate", action="store_true", help="Internal flag for WSL execution")
    parser.add_argument("--add", action="store_true", help="Manually add a new labeled drug pair")
    parser.add_argument("--drug-a", type=str, help="Brand query for Drug A")
    parser.add_argument("--drug-b", type=str, help="Brand query for Drug B")
    parser.add_argument(
        "--status",
        choices=["interaction_found", "none_found"],
        default="interaction_found",
        help="Ground truth interaction status",
    )
    parser.add_argument("--severity", type=str, default="moderate", help="Severity classification")
    parser.add_argument("--keywords", type=str, default="", help="Comma-separated expected keywords")
    parser.add_argument("--mechanism", type=str, default="", help="Clinical mechanism description")
    parser.add_argument("--sync", action="store_true", help="Sync dataset with remote LangSmith")

    args = parser.parse_args()

    extra_pairs = []
    if args.add:
        if not args.drug_a or not args.drug_b:
            logger.error("--drug-a and --drug-b are required when using --add.")
            sys.exit(1)

        new_pair = {
            "drug_a_query": args.drug_a,
            "drug_b_query": args.drug_b,
            "expected_status": args.status,
            "severity": args.severity,
            "expected_keywords": [k.strip() for k in args.keywords.split(",") if k.strip()],
            "clinical_mechanism": args.mechanism,
            "source": "openFDA",
        }
        logger.info(f"Adding manual pair: {args.drug_a} + {args.drug_b} ({args.status})")
        extra_pairs.append(new_pair)

    build_and_save_dataset(extra_pairs=extra_pairs, sync_langsmith=args.sync)


if __name__ == "__main__":
    main()
