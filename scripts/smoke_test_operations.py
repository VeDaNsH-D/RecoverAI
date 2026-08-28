"""
Live HTTP end-to-end integration smoke test for RecoverAI Recovery Operations Layer (Phase B).
Boots uvicorn server, executes Decision -> Action Execution -> Idempotency -> Outcome Recording -> Analytics Summary.
"""

import json
import time
import subprocess
import sys
from pathlib import Path
import httpx

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))


def run_operations_smoke_test():
    port = 8009
    url_base = f"http://127.0.0.1:{port}"
    print(f"[*] Starting live uvicorn server on {url_base}...")

    # Start uvicorn process
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.app:app", "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(repo_root),
    )

    try:
        # Wait for server startup
        print("[*] Waiting for server to become ready...")
        ready = False
        for _ in range(30):
            try:
                r = httpx.get(f"{url_base}/api/v1/health", timeout=2.0)
                if r.status_code == 200:
                    ready = True
                    break
            except Exception:
                time.sleep(0.3)

        if not ready:
            print("[-] Server failed to start in time.")
            stdout, stderr = proc.communicate(timeout=2.0)
            print("STDOUT:", stdout.decode())
            print("STDERR:", stderr.decode())
            sys.exit(1)

        print("[+] Live FastAPI Server is READY.\n")

        # 1. Decision Creation
        print(">>> 1. POST /api/v1/decisions (Initiating Failed Payment Case)")
        case_payload = {
            "case_id": "case_ops_smoke_001",
            "customer_id": "cust_smoke_888",
            "merchant_id": "merch_acme_corp",
            "amount_paise": 450000,  # ₹4,500.00
            "currency": "INR",
            "payment_method": "upi",
            "is_subscription": False,
            "customer_historical_success_rate": 0.91,
            "customer_total_transactions": 30,
            "customer_total_failures": 2,
            "customer_avg_amount_paise": 400000,
            "customer_tenure_months": 16,
            "failure_type": "temporary_failure",
            "retry_count": 0,
            "hours_since_failure": 0.5,
        }
        resp_dec = httpx.post(f"{url_base}/api/v1/decisions", json=case_payload)
        assert resp_dec.status_code == 200
        dec_data = resp_dec.json()
        decision_id = dec_data["decision_id"]
        rec_action = dec_data["recommended_action"]
        print(f"Status: {resp_dec.status_code} | Decision ID: {decision_id} | Recommended Action: {rec_action}")
        print(f"Explanation: {dec_data['explanation']}")
        print("-" * 75)

        # 2. Action Execution
        run_id = f"{int(time.time())}_{uuid.uuid4().hex[:6]}" if "uuid" in globals() else f"{int(time.time())}"
        import uuid
        run_id = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
        print(f">>> 2. POST /api/v1/recovery/actions (Executing Action: {rec_action})")
        idemp_key = f"idemp_smoke_ops_{run_id}"
        action_payload = {
            "decision_id": decision_id,
            "action": rec_action,
            "idempotency_key": idemp_key,
            "merchant_reference": f"ref_smoke_{run_id}",
        }
        resp_act = httpx.post(f"{url_base}/api/v1/recovery/actions", json=action_payload)
        assert resp_act.status_code == 200
        act_data = resp_act.json()
        action_id = act_data["action_id"]
        print(f"Status: {resp_act.status_code} | Action ID: {action_id} | Execution Status: {act_data['status']}")
        print(f"Provider Ref: {act_data['provider_reference']} | Cost: INR {act_data['cost_inr']:.2f}")
        print("-" * 75)

        # 3. Idempotency Replay Test
        print(">>> 3. POST /api/v1/recovery/actions (Testing Idempotency Replay)")
        resp_replay = httpx.post(f"{url_base}/api/v1/recovery/actions", json=action_payload)
        assert resp_replay.status_code == 200
        assert resp_replay.json()["action_id"] == action_id
        print(f"Status: {resp_replay.status_code} | Confirmed identical action record returned without duplicate dispatch.")
        print("-" * 75)

        # 4. Get Action Details
        print(f">>> 4. GET /api/v1/recovery/actions/{action_id}")
        resp_get_act = httpx.get(f"{url_base}/api/v1/recovery/actions/{action_id}")
        assert resp_get_act.status_code == 200
        print(f"Status: {resp_get_act.status_code} | Status: {resp_get_act.json()['status']}")
        print("-" * 75)

        # 5. Outcome Recording
        print(">>> 5. POST /api/v1/recovery/outcomes (Reporting Recovered Settlement)")
        outcome_payload = {
            "case_id": "case_ops_smoke_001",
            "action_id": action_id,
            "decision_id": decision_id,
            "outcome_status": "recovered",
            "recovered_amount_paise": 450000,
            "provider_reference": act_data["provider_reference"],
            "metadata": {"channel_settlement_id": "setl_9918231"},
        }
        resp_out = httpx.post(f"{url_base}/api/v1/recovery/outcomes", json=outcome_payload)
        assert resp_out.status_code == 200
        out_data = resp_out.json()
        print(f"Status: {resp_out.status_code} | Event ID: {out_data['event_id']}")
        print(f"Outcome: {out_data['outcome_status']} | Recovered Amount: INR {out_data['recovered_amount_inr']:.2f}")
        print("-" * 75)

        # 6. Analytics Summary
        print(">>> 6. GET /api/v1/recovery/summary (Merchant Operational Analytics)")
        resp_sum = httpx.get(f"{url_base}/api/v1/recovery/summary")
        assert resp_sum.status_code == 200
        print(json.dumps(resp_sum.json(), indent=2))
        print("=" * 75)
        print("[+] Live Operations HTTP Smoke Test Completed Successfully.")

    finally:
        print("[*] Terminating uvicorn server...")
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    run_operations_smoke_test()
