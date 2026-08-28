"""
Metric calculation utilities for RecoverAI Analytics.
Guarantees:
1. Exact integer paise arithmetic for all financial operations.
2. Safe zero-division handling (returning 0.0).
3. Zero causal claims — purely descriptive calculations.
"""

from typing import Tuple


def calculate_rate(numerator: int, denominator: int) -> float:
    """
    Computes a fractional rate safely handling zero denominators.
    """
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def calculate_recovery_rate(recovered_cases: int, not_recovered_cases: int) -> float:
    """
    Computes observed recovery rate over resolved terminal outcomes:
    recovered / (recovered + not_recovered)
    Pending cases are excluded from the denominator.
    """
    total_resolved = recovered_cases + not_recovered_cases
    if total_resolved <= 0:
        return 0.0
    return float(recovered_cases) / float(total_resolved)


def paise_to_inr(amount_paise: int) -> float:
    """
    Converts integer paise into INR presentation float.
    """
    return amount_paise / 100.0


def calculate_net_paise(gross_recovered_paise: int, total_action_cost_paise: int) -> int:
    """
    Exact integer paise net recovery calculation: Gross - Cost.
    """
    return gross_recovered_paise - total_action_cost_paise


def calculate_average_paise(total_paise: int, count: int) -> int:
    """
    Computes integer average in paise using integer floor division.
    """
    if count <= 0:
        return 0
    return total_paise // count
