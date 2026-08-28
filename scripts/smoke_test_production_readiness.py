"""
Live HTTP integration smoke test for RecoverAI Production Readiness & Reliability (Phase D).
Boots live uvicorn server, exercises health/readiness, request correlation, decisions,
recovery operations, analytics, error handling, and observability telemetry.
"""

import json
import time
import uuid
import subprocess
import sys
from pathlib import Path
import httpx

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))


def run_production_readiness_smoke_test():
    port = 8012
    url_base = f"http://127.0.0.1:{port}"
    print(f"[*] Starting live uvicorn server on {url_base}...")

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

        # 1. Health Liveness Probe
        print(">>> 1. GET /api/v1/health (Liveness Probe)")
        resp_health = httpx.get(f"{url_base}/api/v1/health")
        assert resp_health.status_code == 200
        assert "x-request-id" in resp_health.headers
        print(f"Status: {resp_health.status_code} | Request ID: {resp_health.headers['x-request-id']}")
        print(json.dumps(resp_health.json(), indent=2))
        print("-" * 75)

        # 2. Deep Readiness Probe
        print(">>> 2. GET /api/v1/ready (Readiness Probe)")
        resp_ready = httpx.get(f"{url_base}/api/v1/ready")
        assert resp_ready.status_code == 200
        ready_data = resp_ready.json()
        assert ready_data["status"] == "ready"
        assert ready_data["model_status"] == "ready"
        assert ready_data["database_status"] == "connected"
        print(f"Status: {resp_ready.status_code} | Model: {ready_data['model_status']} | DB: {ready_data['database_status']}")
        print("-" * 75)

        # 3. Decision Creation with Custom Correlation ID
        custom_req_id = f"merch_req_{uuid.uuid4().hex[:8]}"
        print(f">>> 3. POST /api/v1/decisions (Correlation ID: {custom_req_id})")
        case_payload = {
            "case_id": f"case_prod_{uuid.uuid4().hex[:6]}",
            "customer_id": "cust_prod_9981",
            "merchant_id": "merch_acme_corp",
            "amount_paise": 750000,  # ₹7,500.00
            "currency": "INR",
            "payment_method": "upi",
            "is_subscription": True,
            "customer_historical_success_rate": 0.95,
            "customer_total_transactions": 40,
            "customer_total_failures": 1,
            "customer_avg_amount_paise": 700000,
            "customer_tenure_months": 20,
            "failure_type": "temporary_failure",
            "retry_count": 0,
            "hours_since_failure": 0.2,
        }
        resp_dec = httpx.post(
            f"{url_base}/api/v1/decisions",
            json=case_payload,
            headers={"X-Request-ID": custom_req_id},
        )
        assert resp_dec.status_code == 200
        assert resp_dec.headers.get("x-request-id") == custom_req_id
        dec_data = resp_dec.json()
        decision_id = dec_data["decision_id"]
        rec_action = dec_data["recommended_action"]
        print(f"Status: {resp_dec.status_code} | Decision ID: {decision_id} | Recommended Action: {rec_action}")
        print("-" * 75)

        # 4. Action Execution
        print(f">>> 4. POST /api/v1/recovery/actions (Executing Action: {rec_action})")
        run_id = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
        action_payload = {
            "decision_id": decision_id,
            "action": rec_action,
            "idempotency_key": f"idemp_prod_{run_id}",
            "merchant_reference": f"ref_prod_{run_id}",
        }
        resp_act = httpx.post(f"{url_base}/api/v1/recovery/actions", json=action_payload)
        assert resp_act.status_code == 200
        act_data = resp_act.json()
        action_id = act_data["action_id"]
        print(f"Status: {resp_act.status_code} | Action ID: {action_id} | Cost: INR {act_data['cost_inr']:.2f}")
        print("-" * 75)

        # 5. Outcome Recording
        print(">>> 5. POST /api/v1/recovery/outcomes (Recording Recovered Outcome)")
        outcome_payload = {
            "case_id": case_payload["case_id"],
            "action_id": action_id,
            "decision_id": decision_id,
            "outcome_status": "recovered",
            "recovered_amount_paise": 750000,
            "provider_reference": act_data["provider_reference"],
            "metadata": {"channel": "gateway_instant_retry"},
        }
        resp_out = httpx.post(f"{url_base}/api/v1/recovery/outcomes", json=outcome_payload)
        assert resp_out.status_code == 200
        print(f"Status: {resp_out.status_code} | Outcome: {resp_out.json()['outcome_status']}")
        print("-" * 75)

        # 6. Analytics Overview & Reconciliation
        print(">>> 6. GET /api/v1/analytics/overview")
        resp_ov = httpx.get(f"{url_base}/api/v1/analytics/overview")
        assert resp_ov.status_code == 200
        ov_data = resp_ov.json()
        assert ov_data["net_recovered_paise"] == ov_data["gross_recovered_paise"] - ov_data["total_action_cost_paise"]
        print(f"Status: {resp_ov.status_code} | Financial Reconciliation: Gross ({ov_data['gross_recovered_paise']}p) - Cost ({ov_data['total_action_cost_paise']}p) == Net ({ov_data['net_recovered_paise']}p)")
        print("-" * 75)

        # 7. Operational Observability Telemetry
        print(">>> 7. GET /api/v1/observability/metrics")
        resp_obs = httpx.get(f"{url_base}/api/v1/observability/metrics")
        assert resp_obs.status_code == 200
        obs_data = resp_obs.json()
        print(json.dumps(obs_data, indent=2))
        assert obs_data["requests_total"] >= 6
        assert obs_data["decisions_generated"] >= 1
        assert obs_data["actions_dispatched"] >= 1
        assert obs_data["outcomes_recorded"] >= 1
        print("-" * 75)

        # 8. Standardized Error Handling Verification
        print(">>> 8. POST /api/v1/decisions (Testing Malformed Payload Rejection -> 422)")
        resp_err = httpx.post(
            f"{url_base}/api/v1/decisions",
            json={"forbidden_ground_truth_prob": 0.95},
            headers={"X-Request-ID": "err_test_req_422"},
        )
        assert resp_err.status_code == 422
        assert resp_err.headers.get("x-request-id") == "err_test_req_422"
        err_json = resp_err.json()
        assert "error" in err_json
        assert err_json["error"]["code"] == "VALIDATION_ERROR"
        assert err_json["error"]["request_id"] == "err_test_req_422"
        print(f"Status: {resp_err.status_code} | Error Code: {err_json['error']['code']} | Request ID: {err_json['error']['request_id']}")
        print("=" * 75)
        print("[+] Live Production Readiness HTTP Smoke Test Completed Successfully.")

    finally:
        print("[*] Terminating uvicorn server...")
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    run_production_readiness_smoke_test()
