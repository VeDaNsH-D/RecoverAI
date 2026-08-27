"""
Hidden Ground Truth schema for RecoverAI.
Contains true causal recovery probabilities, latent variables, and deterministic potential outcomes.
SECURITY / PRIVACY: This data is NEVER exposed to policies, agents, or ML training features.
"""

from typing import Dict
from pydantic import BaseModel, ConfigDict, Field
from simulator.config import RecoveryAction


class CaseGroundTruth(BaseModel):
    """
    Hidden ground truth for a single payment case.
    Held exclusively by the simulator and evaluator.
    """
    model_config = ConfigDict(frozen=True)

    case_id: str = Field(description="Associated case identifier")
    customer_id: str = Field(description="Associated customer identifier")

    # True Causal Probabilities for each action P(Y(a)=1 | X, Z)
    recovery_probabilities: Dict[RecoveryAction, float] = Field(
        description="True recovery probabilities for every available recovery action"
    )

    # Fixed Potential Outcomes Y(a) in {0, 1} under Common Random Numbers (CRN)
    potential_outcomes: Dict[RecoveryAction, int] = Field(
        description="Pre-determined binary outcome (1=recovered, 0=failed) for every action under fixed seed"
    )

    # Hidden Latent Variables
    latent_intent: float = Field(
        ge=0.0, le=1.0, description="Unobservable customer willingness to pay"
    )
    latent_funds_available: float = Field(
        ge=0.0, le=1.0, description="Unobservable liquidity / fund availability"
    )

    # Expected Values (in Integer Paise)
    expected_net_values_paise: Dict[RecoveryAction, int] = Field(
        description="True expected net payoff in integer paise: P(a)*Amount - Cost(a)"
    )

    # Optimal Action under ground-truth economics
    optimal_action: RecoveryAction = Field(
        description="The action that maximizes expected net revenue in paise"
    )

    # Operational safety limit
    max_sensible_retries: int = Field(
        default=3, description="Maximum retries before customer churn or gateway ban occurs"
    )

    # Auxiliary recoverability indicator (documented as auxiliary, not primary)
    is_recoverable_indicator: bool = Field(
        description="Auxiliary indicator: True if max action recovery probability >= 0.50"
    )
