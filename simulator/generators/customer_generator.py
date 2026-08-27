"""
Customer profile generator with realistic behavioral distributions.
All monetary fields generated are in integer paise.
"""

from typing import List
import numpy as np

from simulator.config import PaymentMethod, PAYMENT_METHOD_WEIGHTS
from simulator.schemas.customer import CustomerProfile


def generate_customers(count: int = 2000, seed: int = 42) -> List[CustomerProfile]:
    """
    Generates realistic customer behavioral profiles using seeded distributions.

    Parameters:
        count: Number of customer profiles to generate.
        seed: Random seed for deterministic reproducibility.

    Returns:
        List of CustomerProfile instances.
    """
    rng = np.random.default_rng(seed)
    customers: List[CustomerProfile] = []

    methods = list(PAYMENT_METHOD_WEIGHTS.keys())
    method_probs = [PAYMENT_METHOD_WEIGHTS[m] for m in methods]

    # Pre-sample batch distributions for performance and cleanliness
    # Success rates: Beta(8, 2) shifted slightly to give realistic merchant payment success rates (0.50 to 0.99)
    beta_samples = rng.beta(8.0, 2.0, size=count)
    success_rates = np.clip(0.40 + 0.58 * beta_samples, 0.40, 0.99)

    # Tenure: Exponential with mean 14 months, clipped to [1, 60]
    tenure_samples = np.clip(rng.exponential(scale=14.0, size=count) + 1, 1, 60).astype(int)

    # Avg Transaction Amount in Paise: Log-normal centered around ₹1,800 (180,000 paise)
    # log(180,000) ≈ 12.10
    amount_log_samples = rng.lognormal(mean=12.10, sigma=0.85, size=count)
    # Clip between ₹50 (5,000 paise) and ₹50,000 (5,000,000 paise) and round to integer paise
    amounts_paise = np.clip(np.round(amount_log_samples / 100.0) * 100, 5000, 5000000).astype(int)

    # Payment Methods
    method_indices = rng.choice(len(methods), size=count, p=method_probs)

    for i in range(count):
        cust_id = f"cust_{i + 1:06d}"
        tenure = int(tenure_samples[i])
        succ_rate = float(np.round(success_rates[i], 4))
        avg_amt = int(amounts_paise[i])
        method = methods[method_indices[i]]

        # Transaction frequency: correlated with tenure and customer loyalty
        activity_lambda = max(1.0, float(tenure * 2.2 * (succ_rate + 0.2)))
        tx_count = max(1, int(rng.poisson(lam=activity_lambda)))
        
        # Expected failures
        fail_count = int(np.round(tx_count * (1.0 - succ_rate)))
        fail_count = min(tx_count, max(0, fail_count))

        # Subscription propensity is higher if payment method is mandate or card
        sub_prob = 0.65 if method == PaymentMethod.MANDATE else (0.35 if method == PaymentMethod.CARD else 0.15)
        is_sub = bool(rng.random() < sub_prob)

        profile = CustomerProfile(
            customer_id=cust_id,
            historical_success_rate=succ_rate,
            total_transactions=tx_count,
            total_failures=fail_count,
            avg_transaction_amount_paise=avg_amt,
            default_payment_method=method,
            is_subscription=is_sub,
            tenure_months=tenure,
        )
        customers.append(profile)

    return customers
