"""
Oracle Benchmark Policy for RecoverAI.
IMPORTANT: Used exclusively by the evaluation engine as a theoretical performance ceiling.
Normal policies and ML models NEVER receive or access ground truth.
"""

from typing import Dict
from simulator.config import RecoveryAction
from simulator.schemas.case import PaymentCase
from simulator.schemas.ground_truth import CaseGroundTruth
from simulator.policies.base import BasePolicy


class OraclePolicy(BasePolicy):
    """
    Evaluator-only benchmark policy that chooses the optimal action maximizing expected net value.
    """

    def __init__(self, ground_truth_map: Dict[str, CaseGroundTruth]):
        """
        Initializes Oracle with full ground-truth registry.
        """
        self._ground_truth_map = ground_truth_map

    @property
    def name(self) -> str:
        return "oracle"

    def predict(self, case: PaymentCase) -> RecoveryAction:
        """
        Returns the optimal recovery action derived from hidden ground truth economics.
        """
        gt = self._ground_truth_map.get(case.case_id)
        if gt is None:
            raise KeyError(f"Oracle cannot find ground truth for case_id: {case.case_id}")
        return gt.optimal_action
