#!/usr/bin/env python3
"""
scripts/test_graph.py
Standalone verification script for DietSync's LangGraph interaction checker.

Pulls two interacting drugs from PostgreSQL (e.g. Disprin/Aspirin [NSAID] + Warfarin [Anticoagulant]),
runs them through the compiled graph, and streams the node-by-node state trace.
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure repo root and app directory are on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "app"))

from app.db.models import Drug, DrugIngredient, FDALabel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from worker.langgraph.graph import graph
from worker.langgraph.nodes import InteractionState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("test_graph")

DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/dietsync"


def get_db_session():
    db_url = os.getenv("DATABASE_URL", DEFAULT_DB_URL)
    if db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg2://" + db_url.split("://", 1)[1]

    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect():
            pass
        SessionLocal = sessionmaker(bind=engine)
        return SessionLocal()
    except Exception as exc:
        err_msg = str(exc).lower()
        is_conn_refused = "connection refused" in err_msg or "10061" in err_msg or "timeout" in err_msg
        if sys.platform == "win32" and is_conn_refused and "--no-wsl-delegate" not in sys.argv:
            logger.info("Local Windows connection refused. Delegating execution to WSL...")
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
                "/opt/dietsync_venv/bin/python scripts/test_graph.py --no-wsl-delegate "
                + " ".join(f'"{a}"' for a in sys.argv[1:] if a != "--no-wsl-delegate"),
            ]
            res = subprocess.run(wsl_cmd)
            sys.exit(res.returncode)
        raise exc


def run_graph_trace(drug_a_id: int, drug_b_id: int, label_title: str):
    session = get_db_session()
    drug_a = session.query(Drug).filter(Drug.id == drug_a_id).first()
    drug_b = session.query(Drug).filter(Drug.id == drug_b_id).first()

    if not drug_a or not drug_b:
        logger.error(f"Could not find drugs in DB with IDs {drug_a_id}, {drug_b_id}")
        session.close()
        return

    print("\n" + "=" * 75)
    print(f"RUNNING GRAPH TRACE: {label_title}")
    print(f"Drug A: {drug_a.brand_name} (ID: {drug_a.id})")
    print(f"Drug B: {drug_b.brand_name} (ID: {drug_b.id})")
    print("=" * 75)

    initial_state: InteractionState = {
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
        "patient_allergies": [],
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

    session.close()

    step_count = 1
    current_state = dict(initial_state)

    for output in graph.stream(initial_state):
        for node_name, node_update in output.items():
            print(f"\n>>> [STEP {step_count}] NODE EXECUTED: '{node_name}'")
            print("-" * 60)

            current_state.update(node_update)

            if node_name == "fetch_context":
                a_len = len(current_state["drug_a"].get("fda_label_text", ""))
                b_len = len(current_state["drug_b"].get("fda_label_text", ""))
                print(f"  Drug A: {current_state['drug_a'].get('generic_name')} | Label text length: {a_len} chars")
                print(f"  Drug B: {current_state['drug_b'].get('generic_name')} | Label text length: {b_len} chars")

            elif node_name == "check_interaction":
                print(f"  Interaction Claim: {current_state.get('interaction_claim')}")
                print(f"  Quoted Citation:   {repr(current_state.get('citation_text'))}")

            elif node_name == "verify_groundedness":
                print(f"  Is Grounded:       {current_state.get('is_grounded')}")

            elif node_name in ("format_grounded_answer", "format_unverifiable_answer"):
                print(f"  Final Status:      {current_state.get('final_status')}")
                print(f"  Final Answer:\n{json.dumps(current_state.get('final_answer'), indent=4)}")

            step_count += 1

    print("\n" + "=" * 75)
    print(f"TRACE COMPLETED: Final Status -> '{current_state.get('final_status')}'")
    print("=" * 75)


def main():
    session = get_db_session()

    # Find candidate interacting pair from database
    # Pair 1: Disprin (Aspirin - NSAID) + Warfarin (Anticoagulant)
    disprin = session.query(Drug).filter(Drug.brand_name.ilike("%disprin%")).first()
    warfarin = session.query(Drug).filter(Drug.brand_name.ilike("%warfarin%")).first()

    # Pair 2: Klaricid (Clarithromycin) + Lipitor (Atorvastatin)
    klaricid = session.query(Drug).filter(Drug.brand_name.ilike("%klaricid%")).first()
    lipitor = session.query(Drug).filter(Drug.brand_name.ilike("%lipitor%")).first()

    # Pair 3: Zestril (Lisinopril) + Lasix (Furosemide)
    zestril = session.query(Drug).filter(Drug.brand_name.ilike("%zestril%")).first()
    lasix = session.query(Drug).filter(Drug.brand_name.ilike("%lasix%")).first()

    session.close()

    if disprin and warfarin:
        run_graph_trace(disprin.id, warfarin.id, "NSAID (Disprin / Aspirin) + Anticoagulant (Warfarin)")

    if klaricid and lipitor:
        run_graph_trace(klaricid.id, lipitor.id, "Macrolide CYP3A4 Inhibitor (Klaricid) + Statin (Lipitor)")

    # Demonstration of the Refusal Safety Gate (Conditional Edge -> format_unverifiable_answer)
    print("\n" + "=" * 75)
    print("DEMONSTRATION: Safety Gate Refusal (Ungrounded / Fabricated Citation)")
    print("=" * 75)
    from worker.langgraph.nodes import verify_groundedness, format_grounded_answer, format_unverifiable_answer
    from worker.langgraph.graph import route_groundedness

    fake_state: InteractionState = {
        "drug_a": {"generic_name": "aspirin", "fda_label_text": "Aspirin is indicated for relief of minor aches..."},
        "drug_b": {"generic_name": "warfarin", "fda_label_text": "Warfarin sodium is an anticoagulant..."},
        "patient_allergies": [],
        "patient_diet_factors": [],
        "interaction_claim": "Aspirin causes immediate loss of eyesight when taken with warfarin.",
        "citation_text": "Aspirin causes immediate loss of eyesight when taken with warfarin under direct sunlight.",
        "is_grounded": None,
        "allergy_flags": [],
        "food_interaction_claim": None,
        "food_citation_text": None,
        "final_status": "none_found",
        "final_answer": None,
    }

    # Step: verify_groundedness
    v_update = verify_groundedness(fake_state)
    fake_state.update(v_update)
    print(f"\n>>> [STEP] NODE EXECUTED: 'verify_groundedness'")
    print(f"  Proposed Claim:    {fake_state['interaction_claim']}")
    print(f"  Fabricated Quote:  {fake_state['citation_text']}")
    print(f"  Audit Outcome:     is_grounded = {fake_state['is_grounded']}")

    # Conditional Routing
    next_node = route_groundedness(fake_state)
    print(f"\n>>> [CONDITIONAL ROUTING] Evaluated next node -> '{next_node}'")
    assert next_node == "format_unverifiable_answer", f"Expected format_unverifiable_answer, got {next_node}"

    if next_node == "format_unverifiable_answer":
        f_update = format_unverifiable_answer(fake_state)
        fake_state.update(f_update)
        print(f"\n>>> [STEP] NODE EXECUTED: 'format_unverifiable_answer'")
        print(f"  Final Status: {fake_state['final_status']}")
        print(f"  Final Answer:\n{json.dumps(fake_state['final_answer'], indent=4)}")

    print("\n" + "=" * 75)
    print("SAFETY GATE DEMONSTRATION COMPLETE: Refusal gate successfully enforced!")
    print("=" * 75)


if __name__ == "__main__":
    main()
