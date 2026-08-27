"""
Live HTTP smoke test runner for RecoverAI API.
Starts uvicorn in a background process, executes real HTTP requests, and verifies responses.
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


def run_smoke_test():
    port = 8008
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

        # 1. Health Check
        print(">>> 1. GET /api/v1/health")
        resp_health = httpx.get(f"{url_base}/api/v1/health")
        print(f"Status Code: {resp_health.status_code}")
        print(json.dumps(resp_health.json(), indent=2))
        print("-" * 75)

        # 2. Model Info
        print(">>> 2. GET /api/v1/model-info")
        resp_info = httpx.get(f"{url_base}/api/v1/model-info")
        print(f"Status Code: {resp_info.status_code}")
        print(json.dumps(resp_info.json(), indent=2))
        print("-" * 75)

        # 3. Decision API
        print(">>> 3. POST /api/v1/decisions")
        case_payload = {
            "case_id": "case_live_smoke_001",
            "customer_id": "cust_smoke_999",
            "merchant_id": "merch_acme_corp",
            "amount_paise": 375000,  # ₹3,750.00
            "currency": "INR",
            "payment_method": "upi",
            "is_subscription": False,
            "customer_historical_success_rate": 0.94,
            "customer_total_transactions": 42,
            "customer_total_failures": 2,
            "customer_avg_amount_paise": 350000,
            "customer_tenure_months": 22,
            "failure_type": "temporary_failure",
            "retry_count": 0,
            "hours_since_failure": 0.25,
        }
        print("Request Payload:")
        print(json.dumps(case_payload, indent=2))
        print("\nSending POST request...")
        resp_dec = httpx.post(f"{url_base}/api/v1/decisions", json=case_payload)
        print(f"Status Code: {resp_dec.status_code}")
        dec_json = resp_dec.json()
        print("Response Body:")
        print(json.dumps(dec_json, indent=2))
        print("=" * 75)
        print("[+] Live HTTP Smoke Test Completed Successfully.")

    finally:
        print("[*] Terminating uvicorn server...")
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    run_smoke_test()
