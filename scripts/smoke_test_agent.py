"""
Live HTTP Integration Smoke Test for RecoverAI Autonomous Recovery Agent (Milestone 4).
Runs against a live uvicorn instance without external network or LLM dependencies.
"""

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_request(url: str, method: str = "GET", data: dict = None, headers: dict = None) -> tuple[int, dict, dict]:
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            resp_body = resp.read().decode("utf-8")
            resp_headers = dict(resp.headers)
            json_data = json.loads(resp_body) if resp_body else {}
            return resp.status, json_data, resp_headers
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8")
        json_data = json.loads(err_body) if err_body else {}
        return err.code, json_data, dict(err.headers)


def main():
    print("=" * 75)
    print(" RecoverAI — Milestone 4: Autonomous Recovery Agent Live HTTP Smoke Test")
    print("=" * 75)

    port = find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    print(f"[*] Starting live uvicorn server on {base_url}...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.app:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Wait for server readiness
        ready = False
        for _ in range(30):
            time.sleep(0.3)
            try:
                st, data, _ = make_request(f"{base_url}/api/v1/ready")
                if st == 200 and data.get("status") == "ready":
                    ready = True
                    break
            except Exception:
                pass

        if not ready:
            print("[!] Server failed to start within timeout.")
            sys.exit(1)

        print("[+] Live FastAPI Server is READY.\n")

        # ---------------------------------------------------------
        # 1. Execute Autonomous Agent Run (POST /api/v1/agent/recover)
        # ---------------------------------------------------------
        print(">>> 1. POST /api/v1/agent/recover (Initiating Autonomous Recovery Run)")
        case_payload = {
            "case_id": "case_smoke_agent_001",
            "customer_id": "cust_smoke_agent_001",
            "amount_paise": 750000,
            "currency": "INR",
            "payment_method": "upi",
            "is_subscription": False,
            "customer_historical_success_rate": 0.95,
            "customer_total_transactions": 40,
            "customer_total_failures": 1,
            "customer_avg_amount_paise": 750000,
            "customer_tenure_months": 20,
            "failure_type": "temporary_failure",
            "retry_count": 0,
            "hours_since_failure": 0.1,
            "idempotency_key": "idemp_smoke_agent_001",
        }

        st, res, headers = make_request(
            f"{base_url}/api/v1/agent/recover",
            method="POST",
            data=case_payload,
            headers={"X-Request-ID": "req_smoke_agent_init"},
        )
        assert st == 200, f"Expected 200, got {st}: {res}"
        run_id = res["agent_run_id"]
        print(f"Status: {st} | Agent Run ID: {run_id}")
        print(f"Decision ID: {res['decision_id']} | Action ID: {res['action_id']}")
        print(f"Recommended Action: {res['recommended_action']} | Executed Action: {res['executed_action']}")
        print(f"Execution Status: {res['execution_status']} | Final State: {res['final_operational_state']}")
        print(f"Financials: Gross {res['expected_gross_paise']}p - Cost {res['action_cost_paise']}p == Net {res['expected_net_paise']}p (INR {res['expected_net_inr']:.2f})")
        print(f"Request Correlation Header: {headers.get('x-request-id', headers.get('X-Request-ID'))}\n")

        # ---------------------------------------------------------
        # 2. Verify Idempotent Replay (POST /api/v1/agent/recover with same key)
        # ---------------------------------------------------------
        print(">>> 2. POST /api/v1/agent/recover (Testing Idempotent Replay)")
        st_re, res_re, _ = make_request(
            f"{base_url}/api/v1/agent/recover",
            method="POST",
            data=case_payload,
        )
        assert st_re == 200, f"Expected 200, got {st_re}: {res_re}"
        assert res_re["agent_run_id"] == run_id, "Idempotent replay failed to return identical run ID"
        print(f"Status: {st_re} | Returned Identical Run ID: {res_re['agent_run_id']} (Provider not executed twice)\n")

        # ---------------------------------------------------------
        # 3. Retrieve Audit Trace (GET /api/v1/agent/runs/{agent_run_id})
        # ---------------------------------------------------------
        print(f">>> 3. GET /api/v1/agent/runs/{run_id} (Retrieving Run Audit Trace)")
        st_get, res_get, _ = make_request(f"{base_url}/api/v1/agent/runs/{run_id}")
        assert st_get == 200, f"Expected 200, got {st_get}: {res_get}"
        steps = res_get["trace"]["steps"]
        print(f"Status: {st_get} | Total Auditable Steps: {len(steps)}")
        for s in steps:
            tool_info = f" [Tool: {s['tool_name']}]" if s.get("tool_name") else ""
            print(f"  - Step {s['step_index']}: {s['step_type']}{tool_info} ({s['status']})")
        print()

        # ---------------------------------------------------------
        # 4. Anti-Leakage / Closed Schema Verification (422)
        # ---------------------------------------------------------
        print(">>> 4. POST /api/v1/agent/recover (Testing Anti-Leakage Rejection of Forbidden Latent Fields)")
        leak_payload = dict(case_payload)
        leak_payload["case_id"] = "case_smoke_agent_leak"
        leak_payload["forbidden_latent_intent"] = 0.99
        st_err, res_err, _ = make_request(f"{base_url}/api/v1/agent/recover", method="POST", data=leak_payload)
        assert st_err == 422, f"Expected 422, got {st_err}: {res_err}"
        print(f"Status: {st_err} | Correctly Rejected: {res_err.get('error', {}).get('code')}\n")

        print("=" * 75)
        print("[+] Live Autonomous Recovery Agent HTTP Smoke Test Completed Successfully.")
        print("=" * 75)

    finally:
        proc.terminate()
        proc.wait()


if __name__ == "__main__":
    main()
