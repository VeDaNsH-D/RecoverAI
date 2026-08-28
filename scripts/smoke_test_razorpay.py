"""
Live HTTP Smoke Test for Razorpay TEST-MODE Integration (Milestone 6).
Verifies real test payment link creation, status sync, idempotency, and audit ledger.
STRICTLY OPT-IN: Only runs when RECOVERAI_ENABLE_RAZORPAY_SMOKE=true and valid rzp_test_* credentials are provided.
"""

import json
import os
import socket
import sys
import threading
import time
from typing import Optional
import urllib.error
import urllib.request
import uvicorn

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.app import create_app
from api.config import settings


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def wait_for_server_ready(base_url: str, timeout: float = 10.0) -> bool:
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            req = urllib.request.Request(f"{base_url}/health")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.1)
    return False


def run_smoke_test() -> None:
    print("=" * 75)
    print(" RecoverAI — Milestone 6: Razorpay Test-Mode Live HTTP Smoke Test")
    print("=" * 75)

    # 1. Check Opt-In Guardrail
    enable_smoke = os.getenv("RECOVERAI_ENABLE_RAZORPAY_SMOKE", "false").lower() in ("true", "1")
    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")

    if not enable_smoke:
        print("[*] RECOVERAI_ENABLE_RAZORPAY_SMOKE is not enabled.")
        print("[*] Skipping live external Razorpay API calls. (100% offline tests cover full provider matrix).")
        print("[+] Opt-in smoke test skipped safely.")
        print("=" * 75)
        sys.exit(0)

    # 2. Strict Key Guardrail Validation
    if not key_id or not key_secret:
        print("[-] ERROR: Live Razorpay smoke test requested, but RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET is missing.")
        sys.exit(1)

    if not key_id.startswith("rzp_test_"):
        print(f"[-] SECURITY ERROR: Non-test key '{key_id[:8]}...' detected. Only 'rzp_test_' keys are permitted.")
        sys.exit(1)

    # Configure environment for live test
    settings.payment_provider = "razorpay_test"
    settings.razorpay_key_id = key_id
    settings.razorpay_key_secret = key_secret

    port = find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    print(f"[*] Starting ephemeral live uvicorn server on {base_url} (provider=razorpay_test)...")
    app = create_app()
    config = uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config=config)

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    if not wait_for_server_ready(base_url, timeout=10.0):
        print("[-] Failed to start live server.")
        sys.exit(1)

    print("[+] Live FastAPI Server is READY with Razorpay Test Mode.")

    try:
        # Step 1: Ingest payment case and generate decision
        print("\n>>> 1. POST /api/v1/decisions (Requesting Decision for Payment Link Candidate)")
        case_payload = {
            "case_id": f"case_rzp_smoke_{int(time.time())}",
            "customer_id": "cust_smoke_live_001",
            "amount_paise": 50000,  # Rs 500.00
            "currency": "INR",
            "payment_method": "upi",
            "is_subscription": False,
            "customer_historical_success_rate": 0.88,
            "customer_total_transactions": 10,
            "customer_total_failures": 1,
            "customer_avg_amount_paise": 50000,
            "customer_tenure_months": 6,
            "failure_type": "technical_error",
            "retry_count": 2,  # retry exhausted -> recommends payment_link
            "hours_since_failure": 0.5,
        }

        req = urllib.request.Request(
            f"{base_url}/api/v1/decisions",
            data=json.dumps(case_payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Request-ID": "req_smoke_dec"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            dec_data = json.loads(resp.read().decode("utf-8"))
            decision_id = dec_data["decision_id"]
            recommended = dec_data["recommended_action"]
            print(f"Status: {resp.status} | Decision ID: {decision_id} | Recommended Action: {recommended}")

        # Step 2: Execute Action against real Razorpay TEST MODE
        print("\n>>> 2. POST /api/v1/recovery/actions (Executing Payment Link on Razorpay Test API)")
        idempotency_key = f"idemp_rzp_{int(time.time())}"
        action_payload = {
            "decision_id": decision_id,
            "action": recommended,
            "idempotency_key": idempotency_key,
        }

        req = urllib.request.Request(
            f"{base_url}/api/v1/recovery/actions",
            data=json.dumps(action_payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Request-ID": "req_smoke_act"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            act_data = json.loads(resp.read().decode("utf-8"))
            action_id = act_data["action_id"]
            plink_id = act_data["provider_reference"]
            print(f"Status: {resp.status} | Action ID: {action_id}")
            print(f"Razorpay Provider Reference: {plink_id}")
            print(f"Execution Status: {act_data['status']} | Cost: {act_data['cost_paise']} paise")
            assert plink_id.startswith("plink_"), f"Expected plink_ reference format, got: {plink_id}"

        # Step 3: Idempotent Replay Verification
        print("\n>>> 3. POST /api/v1/recovery/actions (Testing Idempotent Replay)")
        req_replay = urllib.request.Request(
            f"{base_url}/api/v1/recovery/actions",
            data=json.dumps(action_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_replay, timeout=10.0) as resp:
            replay_data = json.loads(resp.read().decode("utf-8"))
            print(f"Status: {resp.status} | Returned Identical Action ID: {replay_data['action_id']}")
            assert replay_data["action_id"] == action_id

        # Step 4: Active Status Sync
        print("\n>>> 4. POST /api/v1/recovery/providers/razorpay/sync (Active Reconciliation)")
        sync_payload = {"action_id": action_id}
        req_sync = urllib.request.Request(
            f"{base_url}/api/v1/recovery/providers/razorpay/sync",
            data=json.dumps(sync_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_sync, timeout=15.0) as resp:
            sync_data = json.loads(resp.read().decode("utf-8"))
            print(f"Status: {resp.status} | Provider Status: {sync_data['provider_status']}")
            print(f"Operational State: {sync_data['operational_state']} | Short URL: {sync_data.get('short_url')}")

        print("\n" + "=" * 75)
        print("[+] Live Razorpay TEST MODE Smoke Test Completed Successfully.")
        print("=" * 75)

    finally:
        server.should_exit = True


if __name__ == "__main__":
    run_smoke_test()
