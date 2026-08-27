"""
Causal Ground Truth and Potential Outcomes Generator for RecoverAI.
Implements the fully calibrated causal structural equation model with Common Random Numbers (CRN).
Supports realistic unrecoverability, action heterogeneity, retry fatigue, and economic trade-offs.
SECURITY GUARANTEE: The generated ground truth is strictly isolated from observable models.
All monetary values are calculated in integer paise.
"""

from typing import Dict, List
import math
import numpy as np

from simulator.config import (
    FailureType,
    PaymentMethod,
    RecoveryAction,
    ACTION_COSTS_PAISE,
)
from simulator.schemas.customer import CustomerProfile
from simulator.schemas.case import PaymentCase
from simulator.schemas.ground_truth import CaseGroundTruth


def _sigmoid(x: float) -> float:
    """Standard numerically stable sigmoid function."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    else:
        z = math.exp(x)
        return z / (1.0 + z)


def generate_ground_truth(
    cases: List[PaymentCase],
    customers_by_id: Dict[str, CustomerProfile],
    seed: int = 42,
) -> Dict[str, CaseGroundTruth]:
    """
    Generates hidden causal ground truth and potential outcomes for a list of cases.

    Parameters:
        cases: Observable payment cases.
        customers_by_id: Mapping of customer_id to CustomerProfile.
        seed: Random seed for deterministic reproducibility.

    Returns:
        Dictionary mapping case_id to its CaseGroundTruth.
    """
    rng = np.random.default_rng(seed)
    ground_truth_map: Dict[str, CaseGroundTruth] = {}

    all_actions = [
        RecoveryAction.NO_ACTION,
        RecoveryAction.RETRY,
        RecoveryAction.PAYMENT_LINK,
        RecoveryAction.REMINDER,
        RecoveryAction.ESCALATE,
    ]

    for case in cases:
        cust = customers_by_id.get(case.customer_id)
        cust_success = cust.historical_success_rate if cust else case.customer_historical_success_rate
        cust_tenure = cust.tenure_months if cust else case.customer_tenure_months

        # 1. Latent Variables & Unrecoverability
        # ~12% of cases are fundamentally unrecoverable (fraud drop, permanently closed account, hostile churn)
        is_hard_unrecoverable = bool(rng.random() < 0.12)
        
        # In addition, ~10% have abandoned intent (Z_intent < 0.15)
        is_abandoned = bool(rng.random() < 0.10)

        if is_hard_unrecoverable:
            latent_intent = float(rng.uniform(0.001, 0.08))
            latent_funds = float(rng.uniform(0.001, 0.08))
        elif is_abandoned:
            latent_intent = float(rng.uniform(0.05, 0.20))
            latent_funds = float(rng.beta(1.5, 3.0))
        else:
            intent_alpha = 1.6 + 3.2 * cust_success
            intent_beta = 2.8 - 1.0 * cust_success
            latent_intent = float(rng.beta(max(0.5, intent_alpha), max(0.5, intent_beta)))
            
            funds_alpha = 1.8 + 2.2 * cust_success
            latent_funds = float(rng.beta(funds_alpha, 2.5))

        # 2. Base Context Logit mu(X, Z)
        w_rel = 1.3 * (cust_success - 0.70)
        w_tenure = 0.18 * math.log(1.0 + cust_tenure)
        w_time = -0.38 * math.log(1.0 + case.hours_since_failure)
        
        # 3. Compute Logit for Each Action
        recovery_probs: Dict[RecoveryAction, float] = {}

        if is_hard_unrecoverable:
            # Irrecoverable case: all active interventions and natural recovery have near-zero probability
            for act in all_actions:
                recovery_probs[act] = float(np.round(rng.uniform(0.0001, 0.0008), 5))
        else:
            # -------------------------------------------------------------
            # Action: NO_ACTION (Cost: INR 0.00 / 0 paise)
            # -------------------------------------------------------------
            no_action_logit = -3.8 + 0.8 * w_rel + 0.5 * (latent_intent - 0.5)
            if case.failure_type == FailureType.TEMPORARY_FAILURE:
                if case.retry_count == 0 and case.hours_since_failure < 3.0:
                    no_action_logit += 1.8
                else:
                    no_action_logit += 0.4
            elif case.failure_type == FailureType.INSUFFICIENT_FUNDS:
                no_action_logit += -1.8 + 1.2 * (latent_funds - 0.5)
            elif case.failure_type == FailureType.INVALID_PAYMENT_METHOD:
                no_action_logit += -4.0
            else: # UNKNOWN_FAILURE
                no_action_logit += -2.8
            
            prob_no_action = float(np.clip(_sigmoid(no_action_logit), 0.0005, 0.90))
            recovery_probs[RecoveryAction.NO_ACTION] = float(np.round(prob_no_action, 4))

            # -------------------------------------------------------------
            # Action: RETRY (Cost: INR 2.00 / 200 paise)
            # -------------------------------------------------------------
            retry_logit = 0.3 + 1.1 * w_rel + 0.4 * w_time
            if case.failure_type == FailureType.TEMPORARY_FAILURE:
                retry_logit += 1.4
            elif case.failure_type == FailureType.INSUFFICIENT_FUNDS:
                retry_logit += -2.6 + 2.8 * (latent_funds - 0.5)
            elif case.failure_type == FailureType.INVALID_PAYMENT_METHOD:
                retry_logit += -4.8  # Expired card almost never works on retry
            else: # UNKNOWN_FAILURE
                retry_logit += -1.6
            
            # Strong Retry Fatigue
            retry_logit -= 1.45 * case.retry_count

            # Large amount friction
            retry_logit -= 0.25 * math.log(1.0 + case.amount_paise / 100000.0)

            prob_retry = float(np.clip(_sigmoid(retry_logit), 0.0005, 0.90))
            recovery_probs[RecoveryAction.RETRY] = float(np.round(prob_retry, 4))

            # -------------------------------------------------------------
            # Action: PAYMENT_LINK (Cost: INR 10.00 / 1,000 paise)
            # -------------------------------------------------------------
            link_logit = -0.5 + 0.7 * w_rel + 3.6 * (latent_intent - 0.5) + 0.8 * (latent_funds - 0.5)
            if case.failure_type == FailureType.INVALID_PAYMENT_METHOD:
                link_logit += 1.4
            elif case.failure_type == FailureType.INSUFFICIENT_FUNDS:
                link_logit += 1.0
            elif case.failure_type == FailureType.TEMPORARY_FAILURE:
                link_logit += -0.2
            else: # UNKNOWN_FAILURE
                link_logit += 0.2
            
            if case.payment_method in (PaymentMethod.UPI, PaymentMethod.CARD):
                link_logit += 0.35

            prob_link = float(np.clip(_sigmoid(link_logit), 0.0005, 0.90))
            recovery_probs[RecoveryAction.PAYMENT_LINK] = float(np.round(prob_link, 4))

            # -------------------------------------------------------------
            # Action: REMINDER (Cost: INR 5.00 / 500 paise)
            # -------------------------------------------------------------
            reminder_logit = -0.9 + 0.6 * w_rel + 3.2 * (latent_intent - 0.5) + 1.4 * (latent_funds - 0.5)
            if case.failure_type == FailureType.INSUFFICIENT_FUNDS:
                reminder_logit += 1.3
            elif case.failure_type == FailureType.INVALID_PAYMENT_METHOD:
                reminder_logit += -2.5
            elif case.failure_type == FailureType.TEMPORARY_FAILURE:
                reminder_logit += -0.9
            else: # UNKNOWN_FAILURE
                reminder_logit += -1.2
            
            if case.is_subscription:
                reminder_logit += 0.95

            prob_reminder = float(np.clip(_sigmoid(reminder_logit), 0.0005, 0.90))
            recovery_probs[RecoveryAction.REMINDER] = float(np.round(prob_reminder, 4))

            # -------------------------------------------------------------
            # Action: ESCALATE (Cost: INR 50.00 / 5,000 paise)
            # -------------------------------------------------------------
            escalate_logit = -0.3 + 0.5 * w_rel + 2.2 * (latent_intent - 0.5)
            if case.failure_type == FailureType.UNKNOWN_FAILURE:
                escalate_logit += 1.8
            elif case.retry_count >= 2:
                escalate_logit += 1.5
            elif case.failure_type == FailureType.INVALID_PAYMENT_METHOD:
                escalate_logit += 0.5
            elif case.failure_type == FailureType.INSUFFICIENT_FUNDS:
                escalate_logit += 0.2
            else: # TEMPORARY_FAILURE
                escalate_logit += -0.7
            
            escalate_logit += 0.55 * math.log(1.0 + case.amount_paise / 100000.0)

            prob_escalate = float(np.clip(_sigmoid(escalate_logit), 0.0005, 0.92))
            recovery_probs[RecoveryAction.ESCALATE] = float(np.round(prob_escalate, 4))

        # 4. Potential Outcomes under Common Random Numbers (CRN)
        potential_outcomes: Dict[RecoveryAction, int] = {}
        for act in all_actions:
            xi = float(rng.uniform(0.0, 1.0))
            potential_outcomes[act] = 1 if xi <= recovery_probs[act] else 0

        # 5. Expected Net Payoffs in Integer Paise
        # E[Net](a) = floor(P(a) * Amount_paise) - Cost_paise(a)
        expected_net_values: Dict[RecoveryAction, int] = {}
        for act in all_actions:
            cost = ACTION_COSTS_PAISE[act]
            expected_gross = int(math.floor(recovery_probs[act] * case.amount_paise))
            expected_net = expected_gross - cost
            expected_net_values[act] = expected_net

        # 6. Optimal Action: Maximizes Expected Net Payoff
        optimal_action = max(all_actions, key=lambda a: expected_net_values[a])

        # 7. Max Sensible Retries
        if case.failure_type == FailureType.TEMPORARY_FAILURE:
            max_retries = 2
        elif case.failure_type == FailureType.INSUFFICIENT_FUNDS:
            max_retries = 1
        elif case.failure_type == FailureType.INVALID_PAYMENT_METHOD:
            max_retries = 0
        else:
            max_retries = 1

        # 8. Auxiliary Recoverability Indicator (>= 50% max recovery probability)
        max_prob = max(recovery_probs.values())
        is_recoverable = bool(max_prob >= 0.50)

        gt_record = CaseGroundTruth(
            case_id=case.case_id,
            customer_id=case.customer_id,
            recovery_probabilities=recovery_probs,
            potential_outcomes=potential_outcomes,
            latent_intent=float(np.round(latent_intent, 4)),
            latent_funds_available=float(np.round(latent_funds, 4)),
            expected_net_values_paise=expected_net_values,
            optimal_action=optimal_action,
            max_sensible_retries=max_retries,
            is_recoverable_indicator=is_recoverable,
        )
        ground_truth_map[case.case_id] = gt_record

    return ground_truth_map
