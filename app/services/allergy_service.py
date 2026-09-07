"""
services/allergy_service.py
Deterministic rule-based allergy cross-reactivity checker for DietSync.

Per PROJECT_SPEC.md lines 117, 205-224:
- Deterministic and auditable by design: patient allergy term -> allergy_class_map ->
  target RxClass IDs -> check membership via rxclass_client against each resolved drug's RxCUI.
- Zero LLM calls in this code path. The LLM is NEVER used to decide cross-reactivity.
"""

import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.db.models import AllergyClassMap
from app.db.session import SessionLocal
from app.services.rxclass_client import get_drug_classes

logger = logging.getLogger(__name__)


def is_class_match(drug_class_id: str, target_class_id: str, source: str = "ATC") -> bool:
    """
    Checks if a drug's class ID matches the target cross-reactive class ID.
    Handles exact match and hierarchical ATC prefix match.
    e.g. ATC 'J01DB' matches target 'J01D' or 'J01DB'.
    """
    d_clean = drug_class_id.strip().upper()
    t_clean = target_class_id.strip().upper()

    if d_clean == t_clean:
        return True

    # For ATC codes, prefix containment reflects hierarchical taxonomy
    # (e.g. J01DB belongs to J01D; J01CA belongs to J01C)
    if source.upper() == "ATC":
        if d_clean.startswith(t_clean) or t_clean.startswith(d_clean):
            return True

    return False


def allergy_check(
    patient_allergies: Optional[List[str]],
    resolved_drugs: List[Dict[str, Any]],
    session: Optional[Session] = None,
) -> List[Dict[str, Any]]:
    """
    Rule-based allergy cross-reactivity evaluation.

    :param patient_allergies: List of patient-reported allergy strings (e.g. ["penicillin", "aspirin"])
    :param resolved_drugs: List of drug dictionaries containing at least 'rxcui' (and optionally 'generic_name', 'brand_name')
    :param session: Optional SQLAlchemy DB session. If None, creates a temporary session.
    :return: List of structured allergy warning flags:
      [
        {
          "allergy": str,
          "matched_drug": str,
          "matched_class": str,
          "rxclass_id": str,
          "source": "RxClass",
          "cross_reactivity_note": str,
          "reference": str,
        }
      ]
    """
    if not patient_allergies or not resolved_drugs:
        return []

    should_close = False
    if session is None:
        session = SessionLocal()
        should_close = True

    flags: List[Dict[str, Any]] = []
    seen_matches = set()

    try:
        # Load all curated map entries once to avoid repetitive DB round trips
        all_map_entries = session.query(AllergyClassMap).all()

        for raw_allergy in patient_allergies:
            clean_allergy = (raw_allergy or "").strip().lower()
            if not clean_allergy:
                continue

            # Find matching allergy terms in curated table
            # Matches exact term or bidirectional containment (e.g. 'sulfa' in 'sulfonamide' or 'penicillin' in 'penicillins')
            matched_map_rows = [
                row for row in all_map_entries
                if row.allergy_term.lower() in clean_allergy or clean_allergy in row.allergy_term.lower()
            ]

            if not matched_map_rows:
                logger.debug(f"[allergy_check] No cross-reactivity rules found for '{clean_allergy}'.")
                continue

            # For each drug, check RxClass membership
            for drug in resolved_drugs:
                rxcuis_to_check = []
                rxcui = drug.get("rxcui")
                if rxcui:
                    rxcuis_to_check.append(str(rxcui).strip())

                # Check ingredients passed in drug dictionary
                for ing in drug.get("ingredients", []):
                    ing_rxcui = ing.get("rxcui")
                    if ing_rxcui and str(ing_rxcui).strip() not in rxcuis_to_check:
                        rxcuis_to_check.append(str(ing_rxcui).strip())

                # If drug has a database ID, query PostgreSQL for all ingredients (critical for combination drugs)
                drug_id = drug.get("id")
                if drug_id and session:
                    from app.db.models import Drug
                    db_drug = session.query(Drug).filter(Drug.id == drug_id).first()
                    if db_drug and db_drug.ingredients:
                        for ing in db_drug.ingredients:
                            if ing.rxcui and str(ing.rxcui).strip() not in rxcuis_to_check:
                                rxcuis_to_check.append(str(ing.rxcui).strip())

                drug_display_name = (
                    drug.get("generic_name")
                    or drug.get("brand_name")
                    or (f"RxCUI {rxcuis_to_check[0]}" if rxcuis_to_check else "Unknown Drug")
                )

                for curr_rxcui in rxcuis_to_check:
                    for map_row in matched_map_rows:
                        # Fetch classes for this drug's RxCUI
                        classes = get_drug_classes(curr_rxcui, rela_sources=[map_row.rxclass_source])

                        for cls_obj in classes:
                            cls_id = cls_obj.get("class_id", "")
                            cls_name = cls_obj.get("class_name", "")
                            cls_source = cls_obj.get("source", map_row.rxclass_source)

                            if is_class_match(cls_id, map_row.rxclass_id, source=cls_source):
                                dedup_key = (clean_allergy, drug_display_name.lower(), map_row.rxclass_id)
                                if dedup_key not in seen_matches:
                                    seen_matches.add(dedup_key)
                                    flag = {
                                        "allergy": raw_allergy,
                                        "matched_drug": drug_display_name,
                                        "matched_class": cls_name or map_row.rxclass_id,
                                        "rxclass_id": map_row.rxclass_id,
                                        "source": "RxClass",
                                        "cross_reactivity_note": map_row.cross_reactivity_note,
                                        "reference": map_row.reference,
                                    }
                                    flags.append(flag)
                                    logger.info(
                                        f"[allergy_check] Flagged: allergy='{raw_allergy}' cross-reacts with "
                                        f"drug='{drug_display_name}' via class='{cls_name}' ({map_row.rxclass_id})."
                                    )
                                break  # matched this map_row for this drug

    except Exception as exc:
        logger.error(f"[allergy_check] Error during rule-based allergy check: {exc}", exc_info=True)
    finally:
        if should_close:
            session.close()

    return flags
