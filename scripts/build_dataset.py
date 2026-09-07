#!/usr/bin/env python3
"""
scripts/build_dataset.py
Batch resolution pipeline for populating PostgreSQL from curated Pakistani drug brands:
DRAP Search -> DRAP Details -> RxNorm Normalize -> openFDA Label Fetch -> PostgreSQL.

Reads data/seed_brands.csv and persists resolved data into:
- drugs
- drug_ingredients
- fda_labels

Per PROJECT_SPEC.md:
- Resolves Pakistani brand names to generic names via DRAP.
- Standardizes generic names via NIH RxNorm (INN -> USAN crosswalk, e.g. Paracetamol -> Acetaminophen).
- Fetches FDA manufacturer drug labels via openFDA and caches them keyed by RxCUI.
- Gracefully logs and skips (does not crash on) any single brand that fails resolution.
"""

import csv
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure repository root and app directory are on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "app"))

from app.db.models import Base, Drug, DrugIngredient, FDALabel
from app.services.drug_resolution import (
    fetch_fda_label,
    get_product_details,
    parse_composition,
    rxnorm_normalize,
    search,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("build_dataset")

DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/dietsync"
DEFAULT_CSV_PATH = REPO_ROOT / "data" / "seed_brands.csv"


def get_database_url() -> str:
    db_url = os.getenv("DATABASE_URL", DEFAULT_DB_URL)
    if db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg2://" + db_url.split("://", 1)[1]
    return db_url


def test_connection_or_delegate_to_wsl() -> Optional[Session]:
    """
    Attempts to establish a SQLAlchemy session. If running on Windows host and
    connecting directly to Postgres on localhost fails (e.g. because Postgres
    is running inside WSL2 where Hyper-V firewall prevents port forwarding),
    seamlessly delegates execution to the WSL Python environment.
    """
    db_url = get_database_url()
    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect():
            pass
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        return SessionLocal()
    except Exception as exc:
        err_msg = str(exc).lower()
        is_conn_refused = "connection refused" in err_msg or "10061" in err_msg or "timeout" in err_msg
        if sys.platform == "win32" and is_conn_refused and "--no-wsl-delegate" not in sys.argv:
            logger.info("Local Windows connection to Postgres refused. Delegating execution to WSL2...")
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
                "cd /root/dietsync && DATABASE_URL=postgresql://postgres:postgres@localhost:5432/dietsync "
                "/opt/dietsync_venv/bin/python scripts/build_dataset.py --no-wsl-delegate "
                + " ".join(f'"{arg}"' for arg in sys.argv[1:] if arg != "--no-wsl-delegate"),
            ]
            result = subprocess.run(wsl_cmd)
            sys.exit(result.returncode)
        raise exc


def pick_best_drap_result(query: str, results: List[Dict[str, str]]) -> Dict[str, str]:
    """
    Selects the best matching DRAP search result for the query.
    Prioritizes items starting with the query, or exact word matches.
    """
    if not results:
        raise ValueError(f"Empty results list for query '{query}'")

    q_lower = query.strip().lower()
    # 1. Starts with brand name (e.g. 'Panadol Tablet.')
    for item in results:
        t_lower = item.get("text", "").lower()
        if t_lower.startswith(q_lower):
            return item

    # 2. Contains brand name as a substring
    for item in results:
        t_lower = item.get("text", "").lower()
        if q_lower in t_lower:
            return item

    # 3. Default to first result
    return results[0]


def resolve_and_persist_brand(
    brand_name: str,
    category: str,
    session: Session,
) -> Dict[str, Any]:
    """
    Executes the full pipeline for a single brand:
    DRAP search -> DRAP details -> RxNorm normalize -> openFDA label -> DB.
    """
    logger.info(f"==> Resolving '{brand_name}' ({category})...")

    # Step 1: DRAP Search
    search_results = search(brand_name)
    if not search_results:
        raise RuntimeError(f"No DRAP search results returned for '{brand_name}'")

    best_match = pick_best_drap_result(brand_name, search_results)
    reg_no = best_match.get("id")
    drap_display_name = best_match.get("text", brand_name)
    logger.info(f"    DRAP Match: {drap_display_name} (Reg No: {reg_no})")

    # Step 2: DRAP Product Details
    details = get_product_details(reg_no)
    resolved_brand_name = details.get("product_name") or drap_display_name
    dosage_form = details.get("dosage_form")
    company_name = details.get("company_name") or details.get("company")
    raw_comp = details.get("composition_raw", "")
    ingredients_list = details.get("composition", [])

    if not ingredients_list and raw_comp:
        ingredients_list = parse_composition(raw_comp)

    if not ingredients_list:
        raise RuntimeError(f"No active ingredients could be parsed from DRAP details for '{brand_name}' ({reg_no})")

    logger.info(f"    Parsed {len(ingredients_list)} active ingredient(s) from DRAP")

    # Step 3 & 4: Normalize each ingredient via RxNorm & fetch openFDA label
    resolved_ingredients_data = []

    for ing in ingredients_list:
        raw_ing_name = ing.get("name", "").strip()
        dose = ing.get("amount")
        if not raw_ing_name:
            continue

        rxcui, rxnorm_name = rxnorm_normalize(raw_ing_name)
        # Fallback to original name if RxNorm has no match per spec limitation
        canonical_name = rxnorm_name or raw_ing_name
        logger.info(f"    - Ingredient '{raw_ing_name}' -> RxCUI: {rxcui or 'None'}, Canonical: '{canonical_name}'")

        # openFDA label lookup & caching
        if rxcui and canonical_name:
            # Check if fda_labels already has this RxCUI
            existing_label = session.execute(
                select(FDALabel).where(FDALabel.rxcui == rxcui)
            ).scalar_one_or_none()

            if not existing_label:
                logger.info(f"      Fetching openFDA label for '{canonical_name}' (RxCUI: {rxcui})...")
                fda_data = fetch_fda_label(canonical_name)
                new_label = FDALabel(
                    rxcui=rxcui,
                    rxnorm_name=canonical_name,
                    drug_interactions=fda_data.get("drug_interactions"),
                    warnings=fda_data.get("warnings"),
                    boxed_warning=fda_data.get("boxed_warning"),
                    raw_response=fda_data.get("raw_response"),
                    fetched_at=datetime.now(timezone.utc),
                )
                session.add(new_label)
                session.flush()
                logger.info(f"      Cached openFDA label for RxCUI {rxcui} (Found: {fda_data.get('found')})")
            else:
                logger.info(f"      openFDA label already cached for RxCUI {rxcui}")

        resolved_ingredients_data.append({
            "generic_name": raw_ing_name,
            "dose": dose,
            "rxcui": rxcui,
            "rxnorm_name": rxnorm_name,
        })

    # Step 5: Save or update drug in drugs table
    existing_drug = session.execute(
        select(Drug).where((Drug.drap_reg_no == reg_no) | (Drug.brand_name == resolved_brand_name))
    ).scalar_one_or_none()

    if existing_drug:
        drug = existing_drug
        drug.brand_name = resolved_brand_name
        drug.drap_reg_no = reg_no
        drug.dosage_form = dosage_form
        drug.company_name = company_name
        drug.resolved_at = datetime.now(timezone.utc)
        # Clear old ingredients to prevent stale duplicates
        session.query(DrugIngredient).filter(DrugIngredient.drug_id == drug.id).delete()
    else:
        drug = Drug(
            brand_name=resolved_brand_name,
            drap_reg_no=reg_no,
            dosage_form=dosage_form,
            company_name=company_name,
            resolved_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        session.add(drug)

    session.flush()

    # Insert drug ingredients
    for ing_data in resolved_ingredients_data:
        drug_ingredient = DrugIngredient(
            drug_id=drug.id,
            generic_name=ing_data["generic_name"],
            dose=ing_data["dose"],
            rxcui=ing_data["rxcui"],
            rxnorm_name=ing_data["rxnorm_name"],
        )
        session.add(drug_ingredient)

    session.commit()
    logger.info(f"[SUCCESS] Fully resolved and persisted '{brand_name}' -> Drug ID: {drug.id}\n")

    return {
        "brand_name": brand_name,
        "resolved_name": resolved_brand_name,
        "reg_no": reg_no,
        "drug_id": drug.id,
        "ingredients": resolved_ingredients_data,
    }


def build_dataset(csv_path: Optional[Path] = None):
    target_csv = csv_path or DEFAULT_CSV_PATH
    if not target_csv.exists():
        logger.error(f"Seed brands file not found at: {target_csv}")
        sys.exit(1)

    session = test_connection_or_delegate_to_wsl()

    with open(target_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        seed_entries = [row for row in reader if row.get("brand_name", "").strip()]

    logger.info("=" * 75)
    logger.info(f"STARTING DATASET BUILD: {len(seed_entries)} SEED BRANDS")
    logger.info("=" * 75)

    successes: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []

    for idx, row in enumerate(seed_entries, 1):
        brand = row.get("brand_name", "").strip()
        category = row.get("therapeutic_class", "General").strip()
        logger.info(f"[{idx}/{len(seed_entries)}] Processing brand: '{brand}'...")

        try:
            res = resolve_and_persist_brand(brand, category, session)
            successes.append(res)
        except Exception as exc:
            session.rollback()
            err_msg = str(exc)
            logger.error(f"[SKIPPED] Failed to resolve brand '{brand}': {err_msg}\n")
            failures.append({"brand_name": brand, "category": category, "error": err_msg})

    # Summary Report
    print("\n" + "=" * 75)
    print("                      DATASET BUILD SUMMARY                      ")
    print("=" * 75)
    print(f"Total Seed Brands:     {len(seed_entries)}")
    print(f"Successfully Resolved: {len(successes)} / {len(seed_entries)}")
    print(f"Failed / Skipped:      {len(failures)} / {len(seed_entries)}")
    print("-" * 75)

    if successes:
        print("\n--- SUCCESSFULLY RESOLVED DRUGS ---")
        for s in successes:
            ing_strs = [
                f"{i['generic_name']} ({i['dose'] or 'Dose N/A'}) [RxCUI: {i['rxcui'] or 'None'}]"
                for i in s["ingredients"]
            ]
            print(f"  * {s['brand_name']} -> '{s['resolved_name']}' (Reg: {s['reg_no']})")
            print(f"      Active: {', '.join(ing_strs)}")

    if failures:
        print("\n--- RESOLUTION FAILURES / SKIPPED ---")
        for f in failures:
            print(f"  * {f['brand_name']} ({f['category']}): {f['error']}")

    print("\n" + "=" * 75)
    print(f"RESOLUTION RATE: {len(successes)}/{len(seed_entries)} ({len(successes)/len(seed_entries)*100:.1f}%)")
    print("=" * 75 + "\n")

    session.close()


if __name__ == "__main__":
    csv_file = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else DEFAULT_CSV_PATH
    build_dataset(csv_file)
