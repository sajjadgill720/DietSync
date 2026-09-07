#!/usr/bin/env python3
"""
scripts/test_api_endpoints.py
Comprehensive test suite for DietSync's FastAPI endpoints:
- POST /resolve (dataset lookup first, DRAP fallback, no DRAP exposure)
- POST /check (validation, 202 Accepted, job_id, RabbitMQ publish)
- GET /check/{job_id} (polling fallback, source must say "openFDA", never "DRAP")
- WS /ws/jobs/{job_id} (Postgres LISTEN/NOTIFY subscription, pushes once, closes)
"""

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

# Ensure repo root and app are on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "app"))

from fastapi.testclient import TestClient
from app.main import app
from app.db.models import Drug, InteractionJob
from app.db.session import SessionLocal
from app.db.listeners import notify_channel


def test_connection_or_delegate_to_wsl():
    """
    Since PostgreSQL and RabbitMQ run inside WSL, delegating execution on Windows
    avoids Hyper-V socket bridge drops and connection aborts.
    """
    if sys.platform == "win32" and "--no-wsl-delegate" not in sys.argv:
        print("Running tests in WSL Linux environment (where PostgreSQL & RabbitMQ reside)...")
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
            "/opt/dietsync_venv/bin/python scripts/test_api_endpoints.py --no-wsl-delegate "
            + " ".join(f'"{arg}"' for arg in sys.argv[1:] if arg != "--no-wsl-delegate"),
        ]
        result = subprocess.run(wsl_cmd)
        sys.exit(result.returncode)



def run_tests():
    print("=" * 70)
    print("RUNNING DIETSYNC API LAYER TEST SUITE")
    print("=" * 70)

    client = TestClient(app)
    db = SessionLocal()

    try:
        # 1. Test GET /health and GET /
        print("\n[1] Testing GET /health and GET / ...")
        resp_health = client.get("/health")
        assert resp_health.status_code == 200, f"Health check failed: {resp_health.text}"
        assert resp_health.json().get("status") == "healthy"
        print("    PASS: GET /health -> 200 {'status': 'healthy'}")

        resp_root = client.get("/")
        assert resp_root.status_code == 200
        print("    PASS: GET / -> 200")

        # 2. Test POST /resolve with known dataset brand
        print("\n[2] Testing POST /resolve with dataset brand ...")
        # Query seeded brand, e.g. 'Panadol'
        resp_resolve = client.post("/resolve", json={"query": "Panadol"})
        assert resp_resolve.status_code == 200, f"Resolve failed: {resp_resolve.text}"
        data = resp_resolve.json()
        print(f"    Response: {data}")

        assert data["status"] in ("resolved", "ambiguous")
        # Critical verification: never return drap_reg_no
        assert "drap_reg_no" not in str(data)
        assert "reg_no" not in str(data)
        assert "drap" not in str(data).lower() or data.get("drug", {}).get("display_name")

        if data["status"] == "resolved":
            assert data["drug"] is not None
            assert "drug_id" in data["drug"]
            assert "display_name" in data["drug"]
            print(f"    PASS: Resolved directly to drug_id={data['drug']['drug_id']} ({data['drug']['display_name']})")
        else:
            assert data["candidates"] is not None
            assert len(data["candidates"]) > 0
            print(f"    PASS: Ambiguous returned {len(data['candidates'])} candidates with clean display names")

        # 3. Test POST /resolve with empty query -> 400
        print("\n[3] Testing POST /resolve with empty query ...")
        resp_bad = client.post("/resolve", json={"query": "   "})
        assert resp_bad.status_code in (400, 422), f"Expected 400/422 but got {resp_bad.status_code}"
        print(f"    PASS: Empty query rejected with HTTP {resp_bad.status_code}")

        # 4. Test POST /resolve with nonexistent brand -> not_found
        print("\n[4] Testing POST /resolve with nonexistent query ...")
        resp_none = client.post("/resolve", json={"query": "xyzgibberishbrandnotexist999"})
        assert resp_none.status_code == 200
        assert resp_none.json()["status"] == "not_found"
        assert resp_none.json()["drug"] is None
        assert resp_none.json()["candidates"] is None
        print("    PASS: Unknown brand returns status='not_found'")

        # 5. Test POST /check with invalid drug IDs -> 404
        print("\n[5] Testing POST /check with invalid drug IDs ...")
        resp_check_invalid = client.post("/check", json={"drug_a_id": 999999, "drug_b_id": 888888})
        assert resp_check_invalid.status_code == 404
        print(f"    PASS: Nonexistent drug IDs rejected with HTTP 404: {resp_check_invalid.json()}")

        # 6. Test POST /check with valid drug IDs
        print("\n[6] Testing POST /check with valid drug IDs ...")
        drugs = db.query(Drug).limit(2).all()
        assert len(drugs) >= 2, "Need at least 2 drugs in DB to test check endpoint"
        drug_a = drugs[0]
        drug_b = drugs[1]

        resp_check = client.post(
            "/check",
            json={
                "drug_a_id": drug_a.id,
                "drug_b_id": drug_b.id,
                "patient_allergies": ["penicillin"],
                "patient_diet_factors": ["grapefruit juice"],
            },
        )
        assert resp_check.status_code == 202, f"Expected 202 Accepted but got {resp_check.status_code}: {resp_check.text}"
        check_data = resp_check.json()
        print(f"    Response: {check_data}")
        assert "job_id" in check_data
        assert check_data["status"] == "queued"
        job_id = check_data["job_id"]
        print(f"    PASS: POST /check returned HTTP 202 with job_id={job_id}")

        # 7. Test GET /check/{job_id}
        print("\n[7] Testing GET /check/{job_id} ...")
        resp_poll = client.get(f"/check/{job_id}")
        assert resp_poll.status_code == 200, f"Poll failed: {resp_poll.text}"
        poll_data = resp_poll.json()
        print(f"    Response: {poll_data}")
        assert poll_data["job_id"] == job_id
        assert poll_data["status"] in ("queued", "processing", "done", "failed")
        if poll_data.get("result"):
            assert poll_data["result"]["source"] == "openFDA"
            assert "drap" not in str(poll_data["result"]["source"]).lower()
        print("    PASS: GET /check/{job_id} returned expected schema")

        # 8. Test WS /ws/jobs/{job_id} with completed job simulation
        print("\n[8] Testing WS /ws/jobs/{job_id} ...")
        # Create a test job and mark it done with result
        test_job_id = uuid.uuid4()
        test_job = InteractionJob(
            id=test_job_id,
            drug_a_id=drug_a.id,
            drug_b_id=drug_b.id,
            status="done",
            result={
                "final_status": "interaction_found",
                "summary": "Co-administration may increase bleeding risk.",
                "citation_text": "Concomitant use increases the risk of bleeding events.",
                "source": "openFDA",
                "allergy_flags": [],
                "food_interaction_summary": None,
            },
        )
        db.add(test_job)
        db.commit()

        # Connect via WebSocket and receive the pushed result
        with client.websocket_connect(f"/ws/jobs/{test_job_id}") as websocket:
            ws_data = websocket.receive_json()
            print(f"    WebSocket received payload: {ws_data}")
            assert ws_data["job_id"] == str(test_job_id)
            assert ws_data["status"] == "done"
            assert ws_data["result"]["final_status"] == "interaction_found"
            assert ws_data["result"]["source"] == "openFDA"
            assert "drap" not in str(ws_data["result"]["source"]).lower()
            print("    PASS: WebSocket received completed CheckStatusResponse and closed cleanly")

        # 9. Test WS /ws/jobs/{job_id} with live LISTEN/NOTIFY trigger
        print("\n[9] Testing WS /ws/jobs/{job_id} with live PostgreSQL NOTIFY ...")
        pending_job_id = uuid.uuid4()
        pending_job = InteractionJob(
            id=pending_job_id,
            drug_a_id=drug_a.id,
            drug_b_id=drug_b.id,
            status="queued",
        )
        db.add(pending_job)
        db.commit()

        # Connect websocket for pending job
        with client.websocket_connect(f"/ws/jobs/{pending_job_id}") as ws:
            # Simulate worker completing job and notifying Postgres channel
            time.sleep(0.2)
            pending_job.status = "done"
            pending_job.result = {
                "final_status": "none_found",
                "summary": "No drug-drug interaction found.",
                "citation_text": None,
                "source": "openFDA",
                "allergy_flags": [],
                "food_interaction_summary": None,
            }
            db.commit()

            channel_name = f"job_{str(pending_job_id).replace('-', '_')}"
            notify_channel(channel_name, '{"status": "done"}')

            # Wait for notification delivery
            ws_msg = ws.receive_json()
            print(f"    Live WebSocket received notification: {ws_msg}")
            assert ws_msg["job_id"] == str(pending_job_id)
            assert ws_msg["status"] == "done"
            assert ws_msg["result"]["source"] == "openFDA"
            print("    PASS: Live LISTEN/NOTIFY push delivered via WebSocket successfully")

        print("\n" + "=" * 70)
        print("ALL API ENDPOINT TESTS PASSED SUCCESSFULLY!")
        print("=" * 70)

    finally:
        db.close()


if __name__ == "__main__":
    test_connection_or_delegate_to_wsl()
    run_tests()
