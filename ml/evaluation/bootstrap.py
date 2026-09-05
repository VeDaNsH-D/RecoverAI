"""
Customer-Clustered Bootstrap module for RecoverAI Milestone 7.
Computes empirical 95% confidence intervals while properly accounting for customer correlation.
"""

from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import numpy as np

from ml.evaluation.schemas import ConfidenceInterval


class CustomerClusteredBootstrap:
    """
    Performs customer-level block bootstrap resampling to evaluate statistical uncertainty
    on economic and recovery metrics.
    """

    def __init__(
        self,
        customer_ids: List[str],
        reps: int = 500,
        confidence_level: float = 0.95,
        seed: int = 42,
    ):
        """
        Parameters:
            customer_ids: List of customer_id strings corresponding to each case index.
            reps: Number of bootstrap iterations (default: 500).
            confidence_level: Nominal confidence level (default: 0.95).
            seed: Random seed for deterministic replay.
        """
        self.reps = reps
        self.confidence_level = confidence_level
        self.seed = seed

        # Group case indices by unique customer_id
        self.unique_customers: List[str] = []
        self.cust_to_case_indices: Dict[str, np.ndarray] = {}

        grouped: Dict[str, List[int]] = defaultdict(list)
        for idx, cid in enumerate(customer_ids):
            grouped[cid].append(idx)

        for cid, idxs in grouped.items():
            self.unique_customers.append(cid)
            self.cust_to_case_indices[cid] = np.array(idxs, dtype=np.int64)

        self.num_unique_customers = len(self.unique_customers)

    def compute_policy_confidence_intervals(
        self,
        policy_gross_paise: np.ndarray,
        policy_cost_paise: np.ndarray,
        baseline_net_paise: Optional[np.ndarray] = None,
    ) -> Dict[str, ConfidenceInterval]:
        """
        Computes 95% confidence intervals for net recovery, delta vs. baseline,
        recovery rate, and intervention cost.

        Parameters:
            policy_gross_paise: 1D array of gross recovered paise per case.
            policy_cost_paise: 1D array of intervention cost paise per case.
            baseline_net_paise: Optional 1D array of baseline net recovered paise per case.

        Returns:
            Dictionary of ConfidenceInterval objects.
        """
        rng = np.random.default_rng(self.seed)
        n_customers = self.num_unique_customers

        # Precompute boolean recovery indicator and net array
        policy_net_paise = policy_gross_paise - policy_cost_paise
        recovered_mask = (policy_gross_paise > 0).astype(np.int64)

        delta_paise = (
            policy_net_paise - baseline_net_paise
            if baseline_net_paise is not None
            else None
        )

        # Pre-aggregate sums per customer cluster for maximum vectorization speed
        # Array shape: (num_unique_customers,)
        cust_net = np.zeros(n_customers, dtype=np.float64)
        cust_cost = np.zeros(n_customers, dtype=np.float64)
        cust_rec = np.zeros(n_customers, dtype=np.float64)
        cust_count = np.zeros(n_customers, dtype=np.float64)
        cust_delta = np.zeros(n_customers, dtype=np.float64) if delta_paise is not None else None

        for c_idx, cid in enumerate(self.unique_customers):
            case_idxs = self.cust_to_case_indices[cid]
            cust_net[c_idx] = np.sum(policy_net_paise[case_idxs])
            cust_cost[c_idx] = np.sum(policy_cost_paise[case_idxs])
            cust_rec[c_idx] = np.sum(recovered_mask[case_idxs])
            cust_count[c_idx] = len(case_idxs)
            if delta_paise is not None:
                cust_delta[c_idx] = np.sum(delta_paise[case_idxs])

        # Generate all resampled customer indices at once: shape (reps, n_customers)
        resampled_indices = rng.integers(0, n_customers, size=(self.reps, n_customers))

        # Bootstrap estimates across replicates
        boot_net_paise = np.sum(cust_net[resampled_indices], axis=1)
        boot_cost_paise = np.sum(cust_cost[resampled_indices], axis=1)
        boot_rec_cases = np.sum(cust_rec[resampled_indices], axis=1)
        boot_total_cases = np.sum(cust_count[resampled_indices], axis=1)

        boot_rec_rate_pct = (boot_rec_cases / np.maximum(1.0, boot_total_cases)) * 100.0
        boot_net_inr = boot_net_paise / 100.0
        boot_cost_inr = boot_cost_paise / 100.0

        alpha = 1.0 - self.confidence_level
        lower_pct = (alpha / 2.0) * 100.0
        upper_pct = (1.0 - alpha / 2.0) * 100.0

        ci_net = ConfidenceInterval(
            lower=round(float(np.percentile(boot_net_inr, lower_pct)), 2),
            upper=round(float(np.percentile(boot_net_inr, upper_pct)), 2),
            confidence_level=self.confidence_level,
        )

        ci_cost = ConfidenceInterval(
            lower=round(float(np.percentile(boot_cost_inr, lower_pct)), 2),
            upper=round(float(np.percentile(boot_cost_inr, upper_pct)), 2),
            confidence_level=self.confidence_level,
        )

        ci_rec_rate = ConfidenceInterval(
            lower=round(float(np.percentile(boot_rec_rate_pct, lower_pct)), 2),
            upper=round(float(np.percentile(boot_rec_rate_pct, upper_pct)), 2),
            confidence_level=self.confidence_level,
        )

        cis: Dict[str, ConfidenceInterval] = {
            "net_recovered_inr": ci_net,
            "cost_inr": ci_cost,
            "recovery_rate_pct": ci_rec_rate,
        }

        if delta_paise is not None and cust_delta is not None:
            boot_delta_paise = np.sum(cust_delta[resampled_indices], axis=1)
            boot_delta_inr = boot_delta_paise / 100.0
            ci_delta = ConfidenceInterval(
                lower=round(float(np.percentile(boot_delta_inr, lower_pct)), 2),
                upper=round(float(np.percentile(boot_delta_inr, upper_pct)), 2),
                confidence_level=self.confidence_level,
            )
            cis["delta_vs_rule_inr"] = ci_delta

        return cis
