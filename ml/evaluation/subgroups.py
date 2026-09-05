"""
Subgroup stress and segmentation analyzer for RecoverAI Milestone 7.
Evaluates revenue recovery performance across failure types, payment methods, retry tiers, and amount tiers.
"""

from typing import Dict, List
from collections import defaultdict

from simulator.config import RecoveryAction
from simulator.schemas.case import PaymentCase
from ml.evaluation.schemas import SubgroupMetric


def analyze_policy_subgroups(
    cases: List[PaymentCase],
    actions: List[RecoveryAction],
    recovered_flags: List[bool],
    net_paise_list: List[int],
) -> Dict[str, Dict[str, SubgroupMetric]]:
    """
    Computes segmented subgroup metrics across canonical dimensions.

    Parameters:
        cases: List of observable PaymentCases.
        actions: Actions chosen for each case.
        recovered_flags: Boolean recovery outcomes for each case.
        net_paise_list: Net revenue recovered in integer paise for each case.

    Returns:
        Nested dictionary: dimension -> group_key -> SubgroupMetric.
    """
    groups_data = {
        "failure_type": defaultdict(lambda: {"n": 0, "risk": 0, "net": 0, "rec": 0, "int": 0}),
        "payment_method": defaultdict(lambda: {"n": 0, "risk": 0, "net": 0, "rec": 0, "int": 0}),
        "retry_count": defaultdict(lambda: {"n": 0, "risk": 0, "net": 0, "rec": 0, "int": 0}),
        "subscription": defaultdict(lambda: {"n": 0, "risk": 0, "net": 0, "rec": 0, "int": 0}),
        "amount_tier": defaultdict(lambda: {"n": 0, "risk": 0, "net": 0, "rec": 0, "int": 0}),
        "customer_success_tier": defaultdict(lambda: {"n": 0, "risk": 0, "net": 0, "rec": 0, "int": 0}),
    }

    for case, act, rec, net in zip(cases, actions, recovered_flags, net_paise_list):
        ft = case.failure_type.value
        pm = case.payment_method.value
        rc = f"retries_{min(case.retry_count, 3)}"
        sub = "subscription" if case.is_subscription else "one_off"

        amt = case.amount_paise
        if amt < 20000:
            tier = "1. Micro (< INR 200)"
        elif amt <= 100000:
            tier = "2. Low (INR 200 - 1k)"
        elif amt <= 500000:
            tier = "3. Mid (INR 1k - 5k)"
        else:
            tier = "4. High (> INR 5k)"

        sr = case.customer_historical_success_rate
        if sr < 0.60:
            sr_bin = "1. Low (< 60%)"
        elif sr < 0.80:
            sr_bin = "2. Medium (60-80%)"
        else:
            sr_bin = "3. High (> 80%)"

        dims = [
            ("failure_type", ft),
            ("payment_method", pm),
            ("retry_count", rc),
            ("subscription", sub),
            ("amount_tier", tier),
            ("customer_success_tier", sr_bin),
        ]

        for dim_name, group_key in dims:
            entry = groups_data[dim_name][group_key]
            entry["n"] += 1
            entry["risk"] += case.amount_paise
            entry["net"] += net
            if rec:
                entry["rec"] += 1
            if act != RecoveryAction.NO_ACTION:
                entry["int"] += 1

    # Format into SubgroupMetric objects
    result: Dict[str, Dict[str, SubgroupMetric]] = {}
    for dim_name, group_map in groups_data.items():
        result[dim_name] = {}
        for group_key, d in sorted(group_map.items()):
            n = max(1, d["n"])
            result[dim_name][group_key] = SubgroupMetric(
                dimension=dim_name,
                group_key=group_key,
                num_cases=d["n"],
                revenue_at_risk_paise=d["risk"],
                net_recovered_paise=d["net"],
                recovery_rate=round(d["rec"] / n, 4),
                intervention_rate=round(d["int"] / n, 4),
            )

    return result
