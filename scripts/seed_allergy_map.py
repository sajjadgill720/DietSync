#!/usr/bin/env python3
"""
scripts/seed_allergy_map.py
Seeds the allergy_class_map reference table with well-known cross-reactivity pairs
and real pharmacological literature citations per PROJECT_SPEC.md lines 205-224.
"""

import sys
from pathlib import Path

# Add project root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.db.models import AllergyClassMap
from app.db.session import SessionLocal

SEED_ENTRIES = [
    {
        "allergy_term": "penicillin",
        "rxclass_id": "J01DB",
        "rxclass_source": "ATC",
        "cross_reactivity_note": (
            "Cross-reactivity between penicillins and first-generation cephalosporins occurs in approximately "
            "1% to 3% of patients, primarily driven by shared R1 side-chain structural similarity rather than the core beta-lactam ring."
        ),
        "reference": "Goodman & Gilman's: The Pharmacological Basis of Therapeutics, 14th Ed. (2023), Chapter 57; Pichichero ME, et al. J Allergy Clin Immunol. 2006;118(4):755-763.",
    },
    {
        "allergy_term": "penicillin",
        "rxclass_id": "J01DC",
        "rxclass_source": "ATC",
        "cross_reactivity_note": (
            "Cross-reactivity between penicillins and second-generation cephalosporins is low (<2%) except where "
            "specific acyl side chains are structurally homologous."
        ),
        "reference": "Goodman & Gilman's The Pharmacological Basis of Therapeutics, 14th Ed., Chapter 57; Joint Task Force on Practice Parameters. Ann Allergy Asthma Immunol. 2010;105(4):259-273.",
    },
    {
        "allergy_term": "penicillin",
        "rxclass_id": "J01DD",
        "rxclass_source": "ATC",
        "cross_reactivity_note": (
            "Third-generation cephalosporins exhibit minimal (<1%) IgE-mediated cross-reactivity with benzylpenicillin/amoxicillin, "
            "though caution is recommended when side chains share similar oxyimino determinants."
        ),
        "reference": "Goodman & Gilman's The Pharmacological Basis of Therapeutics, 14th Ed., Chapter 57; Pichichero ME. J Fam Pract. 2006;55(2):106-112.",
    },
    {
        "allergy_term": "penicillin",
        "rxclass_id": "J01CA",
        "rxclass_source": "ATC",
        "cross_reactivity_note": (
            "Direct cross-allergenicity across all extended-spectrum aminopenicillins (amoxicillin, ampicillin) due to recognition "
            "of the common penicilloyl major antigenic determinant and core beta-lactam thiazolidine nucleus."
        ),
        "reference": "Goodman & Gilman's Pharmacological Basis of Therapeutics, 14th Ed., Chapter 57; Warrington R, et al. Allergy Asthma Clin Immunol. 2018;14(Suppl 2):60.",
    },
    {
        "allergy_term": "penicillin",
        "rxclass_id": "J01DH",
        "rxclass_source": "ATC",
        "cross_reactivity_note": (
            "Carbapenems (meropenem, imipenem) share the bicyclic beta-lactam core but prospective clinical studies demonstrate "
            "a true cross-reactivity rate of <1% in confirmed penicillin-allergic patients."
        ),
        "reference": "Frumin J, et al. Clin Infect Dis. 2009;48(11):1640-1641; Goodman & Gilman's 14th Ed.",
    },
    {
        "allergy_term": "sulfonamide",
        "rxclass_id": "C03CA",
        "rxclass_source": "ATC",
        "cross_reactivity_note": (
            "Sulfonamide antimicrobial hypersensitivity is mediated by stereospecific recognition of N4 aromatic amines, absent in "
            "non-antibiotic sulfonamide loop diuretics (furosemide). True immunologic cross-reactivity is extremely rare, though cautionary monitoring is advised."
        ),
        "reference": "Strom BL, et al. Absence of cross-reactivity between sulfonamide antibiotics and sulfonamide nonantibiotics. N Engl J Med. 2003;349(17):1628-1635.",
    },
    {
        "allergy_term": "sulfonamide",
        "rxclass_id": "C03A",
        "rxclass_source": "ATC",
        "cross_reactivity_note": (
            "Thiazide diuretics possess an arylsulfonamide moiety without the N4 arylamine of antimicrobial sulfonamides; "
            "cross-reactivity risk is predominantly idiosyncratic rather than IgE-mediated."
        ),
        "reference": "Strom BL, et al. N Engl J Med. 2003;349:1628-1635; UpToDate: Sulfonamide allergy in non-antimicrobial drugs (2024).",
    },
    {
        "allergy_term": "aspirin",
        "rxclass_id": "M01AE",
        "rxclass_source": "ATC",
        "cross_reactivity_note": (
            "Patients with aspirin-exacerbated respiratory disease (AERD) or chronic urticaria cross-react with other non-selective "
            "COX-1 inhibiting NSAIDs (e.g. ibuprofen) due to pharmacological inhibition of prostaglandin E2 and excessive leukotriene generation."
        ),
        "reference": "Goodman & Gilman's Pharmacological Basis of Therapeutics, 14th Ed., Chapter 38; Kowalski ML, et al. Allergy. 2013;68(10):1219-1232.",
    },
    {
        "allergy_term": "aspirin",
        "rxclass_id": "M01AB",
        "rxclass_source": "ATC",
        "cross_reactivity_note": (
            "Cross-reactivity among non-selective COX inhibitors occurs in up to 90% of patients with AERD, extending to acetic acid derivatives "
            "such as diclofenac."
        ),
        "reference": "Kowalski ML, et al. Allergy. 2013;68(10):1219-1232; Stevenson DD, et al. Clin Rev Allergy Immunol. 2003;24(2):159-168.",
    },
    {
        "allergy_term": "codeine",
        "rxclass_id": "N02AA",
        "rxclass_source": "ATC",
        "cross_reactivity_note": (
            "Codeine is bioactivated to morphine via CYP2D6; allergic or severe pseudoallergic hypersensitivity cross-reacts across "
            "6-hydroxyl phenanthrene structural congeners (morphine, hydromorphone, oxycodone)."
        ),
        "reference": "Goodman & Gilman's Pharmacological Basis of Therapeutics, 14th Ed., Chapter 24; Sole D, et al. J Allergy Clin Immunol Pract. 2017;5(6):1522-1533.",
    },
    {
        "allergy_term": "cephalosporin",
        "rxclass_id": "J01CA",
        "rxclass_source": "ATC",
        "cross_reactivity_note": (
            "Patients with verified cephalosporin allergy have documented cross-reactivity with penicillins (amoxicillin/ampicillin) "
            "sharing identical or similar R1 acyl side chains (documented in 2% to 5% of cases)."
        ),
        "reference": "Romano A, et al. Ann Intern Med. 2004;141(1):16-22; Pichichero ME. J Allergy Clin Immunol. 2006;118:755-763.",
    },
]


def seed():
    session = SessionLocal()
    try:
        print(f"Seeding allergy_class_map with {len(SEED_ENTRIES)} curated cross-reactivity pairs...")
        count_created = 0
        count_existing = 0

        for entry in SEED_ENTRIES:
            existing = (
                session.query(AllergyClassMap)
                .filter(
                    AllergyClassMap.allergy_term == entry["allergy_term"],
                    AllergyClassMap.rxclass_id == entry["rxclass_id"],
                    AllergyClassMap.rxclass_source == entry["rxclass_source"],
                )
                .first()
            )
            if existing:
                count_existing += 1
            else:
                row = AllergyClassMap(
                    allergy_term=entry["allergy_term"],
                    rxclass_id=entry["rxclass_id"],
                    rxclass_source=entry["rxclass_source"],
                    cross_reactivity_note=entry["cross_reactivity_note"],
                    reference=entry["reference"],
                )
                session.add(row)
                count_created += 1

        session.commit()
        print(f"Seeding complete: {count_created} inserted, {count_existing} already present.")
    except Exception as e:
        session.rollback()
        print(f"Error seeding allergy_class_map: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    seed()
