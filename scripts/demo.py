"""
Interactive End-to-End Demo CLI for RecoverAI.
Demonstrates observable-feature inference, expected-value optimization, and safety guardrails across 8 representative failure scenarios.
"""

import sys
from pathlib import Path

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from simulator.config import FailureType, PaymentMethod, RecoveryAction
from simulator.schemas.case import PaymentCase
from ml.dataset import load_split_dataset_bundle
from ml.models.bundle import create_multi_action_model
from ml.inference import RecoverAIInferenceEngine


def create_demo_scenarios():
    """Builds 8 realistic payment failure scenarios for demonstration."""
    return [
        (
            "Scenario 1: Fresh Temporary Failure (High Propensity UPI Retry)",
            PaymentCase(
                case_id="case_demo_001",
                customer_id="cust_000142",
                merchant_id="merch_recoverai_prod",
                amount_paise=185000,  # ₹1,850.00
                currency="INR",
                payment_method=PaymentMethod.UPI,
                is_subscription=False,
                customer_historical_success_rate=0.92,
                customer_total_transactions=35,
                customer_total_failures=2,
                customer_avg_amount_paise=180000,
                customer_tenure_months=18,
                failure_type=FailureType.TEMPORARY_FAILURE,
                retry_count=0,
                hours_since_failure=0.5,
                created_at="2026-08-27T08:00:00Z",
            ),
        ),
        (
            "Scenario 2: Exhausted Retries (Safety Guardrail Triggered: retry_count >= 2)",
            PaymentCase(
                case_id="case_demo_002",
                customer_id="cust_000518",
                merchant_id="merch_recoverai_prod",
                amount_paise=350000,  # ₹3,500.00
                currency="INR",
                payment_method=PaymentMethod.CARD,
                is_subscription=False,
                customer_historical_success_rate=0.78,
                customer_total_transactions=15,
                customer_total_failures=3,
                customer_avg_amount_paise=300000,
                customer_tenure_months=8,
                failure_type=FailureType.INSUFFICIENT_FUNDS,
                retry_count=2,  # Retries exhausted
                hours_since_failure=12.0,
                created_at="2026-08-27T08:00:00Z",
            ),
        ),
        (
            "Scenario 3: Invalid Payment Method (Direct Payment Link Required)",
            PaymentCase(
                case_id="case_demo_003",
                customer_id="cust_000889",
                merchant_id="merch_recoverai_prod",
                amount_paise=240000,  # ₹2,400.00
                currency="INR",
                payment_method=PaymentMethod.NETBANKING,
                is_subscription=False,
                customer_historical_success_rate=0.81,
                customer_total_transactions=22,
                customer_total_failures=4,
                customer_avg_amount_paise=220000,
                customer_tenure_months=14,
                failure_type=FailureType.INVALID_PAYMENT_METHOD,
                retry_count=0,
                hours_since_failure=2.0,
                created_at="2026-08-27T08:00:00Z",
            ),
        ),
        (
            "Scenario 4: High-Value Enterprise Ticket (Human Escalation Justified)",
            PaymentCase(
                case_id="case_demo_004",
                customer_id="cust_001205",
                merchant_id="merch_recoverai_prod",
                amount_paise=4800000,  # ₹48,000.00
                currency="INR",
                payment_method=PaymentMethod.CARD,
                is_subscription=False,
                customer_historical_success_rate=0.88,
                customer_total_transactions=40,
                customer_total_failures=3,
                customer_avg_amount_paise=4500000,
                customer_tenure_months=24,
                failure_type=FailureType.UNKNOWN_FAILURE,
                retry_count=1,
                hours_since_failure=6.0,
                created_at="2026-08-27T08:00:00Z",
            ),
        ),
        (
            "Scenario 5: Recurring SaaS Subscription Mandate Failure",
            PaymentCase(
                case_id="case_demo_005",
                customer_id="cust_001740",
                merchant_id="merch_recoverai_prod",
                amount_paise=129900,  # ₹1,299.00
                currency="INR",
                payment_method=PaymentMethod.MANDATE,
                is_subscription=True,  # Recurring subscription
                customer_historical_success_rate=0.95,
                customer_total_transactions=28,
                customer_total_failures=1,
                customer_avg_amount_paise=129900,
                customer_tenure_months=20,
                failure_type=FailureType.TEMPORARY_FAILURE,
                retry_count=1,
                hours_since_failure=3.5,
                created_at="2026-08-27T08:00:00Z",
            ),
        ),
        (
            "Scenario 6: Micro-Ticket Transaction (Guardrail: Escalate Suppressed for < INR 200)",
            PaymentCase(
                case_id="case_demo_006",
                customer_id="cust_000312",
                merchant_id="merch_recoverai_prod",
                amount_paise=15000,  # ₹150.00 (< ₹200)
                currency="INR",
                payment_method=PaymentMethod.UPI,
                is_subscription=False,
                customer_historical_success_rate=0.80,
                customer_total_transactions=8,
                customer_total_failures=1,
                customer_avg_amount_paise=15000,
                customer_tenure_months=4,
                failure_type=FailureType.TEMPORARY_FAILURE,
                retry_count=0,
                hours_since_failure=1.0,
                created_at="2026-08-27T08:00:00Z",
            ),
        ),
        (
            "Scenario 7: Micro-Ticket with Negative Intervention EV (Safe NO_ACTION Fallback)",
            PaymentCase(
                case_id="case_demo_007",
                customer_id="cust_000088",
                merchant_id="merch_recoverai_prod",
                amount_paise=2000,  # ₹20.00
                currency="INR",
                payment_method=PaymentMethod.UPI,
                is_subscription=False,
                customer_historical_success_rate=0.45,
                customer_total_transactions=2,
                customer_total_failures=2,
                customer_avg_amount_paise=2000,
                customer_tenure_months=1,
                failure_type=FailureType.INVALID_PAYMENT_METHOD,
                retry_count=2,
                hours_since_failure=48.0,
                created_at="2026-08-27T08:00:00Z",
            ),
        ),
        (
            "Scenario 8: Insufficient Funds with High Customer Tenure (WhatsApp / SMS Payment Link)",
            PaymentCase(
                case_id="case_demo_008",
                customer_id="cust_001920",
                merchant_id="merch_recoverai_prod",
                amount_paise=275000,  # ₹2,750.00
                currency="INR",
                payment_method=PaymentMethod.UPI,
                is_subscription=False,
                customer_historical_success_rate=0.86,
                customer_total_transactions=45,
                customer_total_failures=5,
                customer_avg_amount_paise=250000,
                customer_tenure_months=30,
                failure_type=FailureType.INSUFFICIENT_FUNDS,
                retry_count=1,
                hours_since_failure=8.0,
                created_at="2026-08-27T08:00:00Z",
            ),
        ),
    ]


def main():
    data_dir = Path("data/sim_v1")
    print("=" * 85)
    print(" RecoverAI -- Autonomous AI Revenue Recovery Engine (Milestone 2 Demo)")
    print("=" * 85)
    print("[*] Initializing RecoverAI Champion Inference Engine (Calibrated Logistic)...")

    train_bundle = load_split_dataset_bundle(data_dir, split="train")
    champion_model = create_multi_action_model("logistic", calibrate=True, random_state=42).fit_all(train_bundle)
    inference_engine = RecoverAIInferenceEngine(model=champion_model)

    print("[+] Engine ready for real-time observable inference.\n")

    scenarios = create_demo_scenarios()

    for title, case in scenarios:
        print(f"\n>>> {title.upper()}")
        explanation = inference_engine.explain_decision(case)
        print(explanation)

    print("\n" + "=" * 85)
    print(" [+] RecoverAI Demo Completed Successfully across all 8 representative scenarios.")
    print("=" * 85 + "\n")


if __name__ == "__main__":
    main()
