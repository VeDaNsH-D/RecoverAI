"""
Outcome simulator for RecoverAI.
Executes chosen intervention actions against hidden ground-truth potential outcomes.
Guarantees common random numbers (CRN) evaluation and integer paise financial tracking.
"""

from typing import Dict
from simulator.config import (
    RecoveryAction,
    ACTION_COSTS_PAISE,
    ACTION_NOMINAL_LATENCY_HOURS,
)
from simulator.schemas.case import PaymentCase
from simulator.schemas.ground_truth import CaseGroundTruth
from simulator.schemas.action_result import InterventionResult


class OutcomeSimulator:
    """
    Simulation engine holding hidden ground truth.
    Evaluates policy actions deterministically against potential outcomes.
    """

    def __init__(self, ground_truth_map: Dict[str, CaseGroundTruth]):
        """
        Initializes simulator with ground truth registry.

        Parameters:
            ground_truth_map: Dictionary mapping case_id to CaseGroundTruth.
        """
        self._ground_truth_map = ground_truth_map

    def execute_action(self, case: PaymentCase, action: RecoveryAction) -> InterventionResult:
        """
        Executes an intervention action on a payment case.

        Parameters:
            case: The observable payment case.
            action: The recovery action selected by the policy.

        Returns:
            InterventionResult detailing recovery status, costs, and net revenue in integer paise.
        """
        gt = self._ground_truth_map.get(case.case_id)
        if gt is None:
            raise KeyError(f"No ground truth found for case_id: {case.case_id}")

        # Look up deterministic potential outcome Y(a) under Common Random Numbers
        is_success = bool(gt.potential_outcomes.get(action, 0) == 1)

        # Financial calculations in integer paise
        recovered_paise = case.amount_paise if is_success else 0
        cost_paise = ACTION_COSTS_PAISE[action]
        net_recovered_paise = recovered_paise - cost_paise

        # Recovery latency
        latency = ACTION_NOMINAL_LATENCY_HOURS[action] if is_success else 0.0

        return InterventionResult(
            case_id=case.case_id,
            action_taken=action,
            recovered=is_success,
            recovered_amount_paise=recovered_paise,
            intervention_cost_paise=cost_paise,
            net_recovered_amount_paise=net_recovered_paise,
            recovery_latency_hours=latency,
            details={
                "failure_type": case.failure_type.value,
                "amount_paise": case.amount_paise,
                "retry_count": case.retry_count,
            },
        )
