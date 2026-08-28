"""
Live HTTP integration smoke test for RecoverAI Analytics & Observability Layer (Phase C).
Boots uvicorn server, executes operational workflow, and verifies all analytics endpoints and financial reconciliation.
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


def run_analytics_smoke_test():
    port = 8011
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
        print(">>> 1. POST /api/v1/decisions (Initiating Payment Case)")
        case_payload = {
            "case_id": "case_smoke_an_001",
            "customer_id": "cust_smoke_an_001",
            "merchant_id": "merch_acme_corp",
            "amount_paise": 600000,  # ₹6,000.00
            "currency": "INR",
            "payment_method": "upi",
            "is_subscription": True,
            "customer_historical_success_rate": 0.92,
            "customer_total_transactions": 35,
            "customer_total_failures": 2,
            "customer_avg_amount_paise": 550000,
            "customer_tenure_months": 15,
            "failure_type": "temporary_failure",
            "retry_count": 0,
            "hours_since_failure": 0.3,
        }
        resp_dec = httpx.post(f"{url_base}/api/v1/decisions", json=case_payload)
        assert resp_dec.status_code == 200
        dec_data = resp_dec.json()
        decision_id = dec_data["decision_id"]
        rec_action = dec_data["recommended_action"]
        print(f"Status: {resp_dec.status_code} | Decision ID: {decision_id} | Recommended Action: {rec_action}")
        print("-" * 75)

        # 2. Action Execution
        import uuid
        run_id = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
        print(f">>> 2. POST /api/v1/recovery/actions (Executing Action: {rec_action})")
        idemp_key = f"idemp_smoke_an_{run_id}"
        action_payload = {
            "decision_id": decision_id,
            "action": rec_action,
            "idempotency_key": idemp_key,
            "merchant_reference": f"ref_smoke_an_{run_id}",
        }
        resp_act = httpx.post(f"{url_base}/api/v1/recovery/actions", json=action_payload)
        assert resp_act.status_code == 200
        act_data = resp_act.json()
        action_id = act_data["action_id"]
        print(f"Status: {resp_act.status_code} | Action ID: {action_id} | Cost: INR {act_data['cost_inr']:.2f}")
        print("-" * 75)

        # 3. Outcome Recording
        print(">>> 3. POST /api/v1/recovery/outcomes (Recording Recovered Outcome)")
        outcome_payload = {
            "case_id": "case_smoke_an_001",
            "action_id": action_id,
            "decision_id": decision_id,
            "outcome_status": "recovered",
            "recovered_amount_paise": 600000,
            "provider_reference": act_data["provider_reference"],
            "metadata": {"source": "live_smoke_test"},
        }
        resp_out = httpx.post(f"{url_base}/api/v1/recovery/outcomes", json=outcome_payload)
        assert resp_out.status_code == 200
        print(f"Status: {resp_out.status_code} | Recovered Amount: INR {resp_out.json()['recovered_amount_inr']:.2f}")
        print("-" * 75)

        # 4. Overview Analytics
        print(">>> 4. GET /api/v1/analytics/overview")
        resp_ov = httpx.get(f"{url_base}/api/v1/analytics/overview")
        assert resp_ov.status_code == 200
        ov_data = resp_ov.json()
        print(json.dumps(ov_data, indent=2))
        assert ov_data["net_recovered_paise"] == ov_data["gross_recovered_paise"] - ov_data["total_action_cost_paise"]
        print("[+] Financial reconciliation verified: Gross - Cost = Net.")
        print("-" * 75)

        # 5. Actions Breakdown
        print(">>> 5. GET /api/v1/analytics/actions")
        resp_act_an = httpx.get(f"{url_base}/api/v1/analytics/actions")
        assert resp_act_an.status_code == 200
        act_list = resp_act_an.json()
        print(f"Actions returned ({len(act_list)}): {[a['action'] for a in act_list]}")
        print("-" * 75)

        # 6. Failure Types Breakdown
        print(">>> 6. GET /api/v1/analytics/failure-types")
        resp_ft = httpx.get(f"{url_base}/api/v1/analytics/failure-types")
        assert resp_ft.status_code == 200
        ft_list = resp_ft.json()
        print(f"Failure types returned ({len(ft_list)}): {[f['failure_type'] for f in ft_list]}")
        print("-" * 75)

        # 7. Retry Count Breakdown
        print(">>> 7. GET /api/v1/analytics/retry-count")
        resp_rc = httpx.get(f"{url_base}/api/v1/analytics/retry-count")
        assert resp_rc.status_code == 200
        rc_list = resp_rc.json()
        print(f"Retry counts returned ({len(rc_list)} records)")
        print("-" * 75)

        # 8. Subscription Breakdown
        print(">>> 8. GET /api/v1/analytics/subscriptions")
        resp_sub = httpx.get(f"{url_base}/api/v1/analytics/subscriptions")
        assert resp_sub.status_code == 200
        sub_list = resp_sub.json()
        print(f"Segments returned: {[s['segment'] for s in sub_list]}")
        print("-" * 75)

        # 9. Time Trends
        print(">>> 9. GET /api/v1/analytics/trends?interval=daily")
        resp_tr = httpx.get(f"{url_base}/api/v1/analytics/trends?interval=daily")
        assert resp_tr.status_code == 200
        tr_list = resp_tr.json()
        print(f"Daily buckets returned: {len(tr_list)}")
        print("=" * 75)
        print("[+] Live Analytics HTTP Smoke Test Completed Successfully.")

    finally:
        print("[*] Terminating uvicorn server...")
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    run_analytics_smoke_test()
