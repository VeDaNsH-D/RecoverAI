"""
Workload generation module for RecoverAI Milestone 7: Scale Evaluation & Optimization.
Reuses existing simulator generator primitives to produce deterministic scale workloads
with paired Common Random Numbers (CRN) ground truth.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
import numpy as np

from simulator.generators.customer_generator import generate_customers
from simulator.generators.case_generator import generate_cases
from simulator.generators.ground_truth_generator import generate_ground_truth
from simulator.schemas.customer import CustomerProfile
from simulator.schemas.case import PaymentCase
from simulator.schemas.ground_truth import CaseGroundTruth


WORKLOAD_PROFILES = {
    "smoke": {"cases": 1_000, "customers": 200},
    "standard": {"cases": 10_000, "customers": 2_000},
    "stress": {"cases": 100_000, "customers": 20_000},
    "large": {"cases": 250_000, "customers": 50_000},
    "full": {"cases": 500_000, "customers": 100_000},
}


@dataclass
class ScaleWorkload:
    """
    Container for an independently generated scale evaluation workload.
    Observable cases and hidden ground truth are strictly partitioned.
    """
    profile_name: str
    seed: int
    num_cases: int
    num_customers: int
    cases: List[PaymentCase]
    customers: List[CustomerProfile]
    ground_truth_map: Dict[str, CaseGroundTruth]
    total_revenue_at_risk_paise: int

    @property
    def total_revenue_at_risk_inr(self) -> float:
        return self.total_revenue_at_risk_paise / 100.0


def generate_scale_workload(
    num_cases: int,
    seed: int = 42,
    num_customers: Optional[int] = None,
    profile_name: str = "custom",
) -> ScaleWorkload:
    """
    Generates an independent, deterministic scale workload with paired ground truth.

    Parameters:
        num_cases: Total number of PaymentCases to generate.
        seed: Random seed for deterministic generation.
        num_customers: Optional customer count (defaults to num_cases // 5).
        profile_name: Label for the workload profile.

    Returns:
        ScaleWorkload with observable cases and isolated ground truth map.
    """
    if num_cases < 1:
        raise ValueError(f"num_cases must be >= 1, got {num_cases}")

    derived_customers = num_customers if num_customers is not None else max(50, num_cases // 5)

    # 1. Generate Customer Profiles
    customers = generate_customers(count=derived_customers, seed=seed)
    customer_map = {c.customer_id: c for c in customers}

    # 2. Generate Observable Payment Cases (Seed decoupled)
    cases = generate_cases(customers=customers, total_cases=num_cases, seed=seed + 101)

    # 3. Generate Hidden Potential Outcomes / Ground Truth (Seed decoupled)
    ground_truth_map = generate_ground_truth(cases=cases, customers_by_id=customer_map, seed=seed + 1000)

    total_risk_paise = sum(c.amount_paise for c in cases)

    return ScaleWorkload(
        profile_name=profile_name,
        seed=seed,
        num_cases=len(cases),
        num_customers=len(customers),
        cases=cases,
        customers=customers,
        ground_truth_map=ground_truth_map,
        total_revenue_at_risk_paise=total_risk_paise,
    )


def load_profile_workload(profile: str, seed: int = 42) -> ScaleWorkload:
    """Convenience helper to load a standard named workload profile."""
    prof_lower = profile.lower()
    if prof_lower not in WORKLOAD_PROFILES:
        valid_profs = ", ".join(WORKLOAD_PROFILES.keys())
        raise ValueError(f"Unknown profile '{profile}'. Choose from: {valid_profs}")

    cfg = WORKLOAD_PROFILES[prof_lower]
    return generate_scale_workload(
        num_cases=cfg["cases"],
        num_customers=cfg["customers"],
        seed=seed,
        profile_name=prof_lower,
    )
