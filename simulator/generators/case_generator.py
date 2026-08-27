"""
Payment case generator for RecoverAI.
Generates observable payment failure cases linked to realistic customer profiles.
All monetary fields generated are in integer paise.
"""

from datetime import datetime, timezone, timedelta
from typing import List
import numpy as np

from simulator.config import (
    FailureType,
    PaymentMethod,
    FAILURE_TYPE_WEIGHTS,
    PAYMENT_METHOD_WEIGHTS,
)
from simulator.schemas.customer import CustomerProfile
from simulator.schemas.case import PaymentCase


def generate_cases(
    customers: List[CustomerProfile],
    total_cases: int = 10000,
    seed: int = 42,
) -> List[PaymentCase]:
    """
    Generates observable payment failure cases linked to realistic customer histories.

    Parameters:
        customers: List of generated customer profiles.
        total_cases: Number of payment cases to generate.
        seed: Random seed for deterministic reproducibility.

    Returns:
        List of PaymentCase instances (strictly observable features).
    """
    rng = np.random.default_rng(seed)
    cases: List[PaymentCase] = []

    if not customers:
        raise ValueError("Customer list cannot be empty.")

    # Weight customer selection by their failure propensity (failures + 1 to avoid zero weights)
    weights = np.array([max(1, c.total_failures + 1) for c in customers], dtype=float)
    weights /= weights.sum()

    # Pre-sample customer indices
    selected_cust_indices = rng.choice(len(customers), size=total_cases, p=weights)

    # Failure types
    failure_types = list(FAILURE_TYPE_WEIGHTS.keys())
    failure_probs = [FAILURE_TYPE_WEIGHTS[ft] for ft in failure_types]
    selected_failure_indices = rng.choice(len(failure_types), size=total_cases, p=failure_probs)

    # Payment methods pool
    all_methods = list(PAYMENT_METHOD_WEIGHTS.keys())

    # Retry count distribution: most are fresh failures (0 retries), some have been retried
    # [0: 68%, 1: 20%, 2: 8%, 3: 3%, 4: 1%]
    retry_choices = [0, 1, 2, 3, 4]
    retry_probs = [0.68, 0.20, 0.08, 0.03, 0.01]
    selected_retries = rng.choice(retry_choices, size=total_cases, p=retry_probs)

    # Hours since failure: exponential distribution
    hours_samples = np.clip(rng.exponential(scale=6.5, size=total_cases) + 0.1, 0.1, 72.0)

    # Base reference timestamp
    base_time = datetime(2026, 8, 27, 8, 0, 0, tzinfo=timezone.utc)

    for i in range(total_cases):
        case_id = f"case_{i + 1:06d}"
        cust = customers[selected_cust_indices[i]]
        ft = failure_types[selected_failure_indices[i]]
        retries = int(selected_retries[i])
        hours_elapsed = float(np.round(hours_samples[i], 2))

        # Amount around customer average with lognormal jitter
        amt_multiplier = float(rng.lognormal(mean=0.0, sigma=0.35))
        amt_paise = int(np.clip(np.round(cust.avg_transaction_amount_paise * amt_multiplier / 100.0) * 100, 100, 10000000))

        # Payment method: 85% uses default, 15% uses another method
        if rng.random() < 0.85:
            p_method = cust.default_payment_method
        else:
            p_method = all_methods[rng.choice(len(all_methods))]

        # Failure timestamp
        incident_time = base_time - timedelta(hours=hours_elapsed)
        timestamp_str = incident_time.isoformat()

        case = PaymentCase(
            case_id=case_id,
            customer_id=cust.customer_id,
            merchant_id="merch_recoverai_prod",
            amount_paise=amt_paise,
            currency="INR",
            payment_method=p_method,
            is_subscription=cust.is_subscription,
            customer_historical_success_rate=cust.historical_success_rate,
            customer_total_transactions=cust.total_transactions,
            customer_total_failures=cust.total_failures,
            customer_avg_amount_paise=cust.avg_transaction_amount_paise,
            customer_tenure_months=cust.tenure_months,
            failure_type=ft,
            retry_count=retries,
            hours_since_failure=hours_elapsed,
            created_at=timestamp_str,
        )
        cases.append(case)

    return cases
