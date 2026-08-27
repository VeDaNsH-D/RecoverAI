"""
Action result and execution log schema for RecoverAI.
All monetary fields are strictly in integer paise.
"""

from typing import Any, Dict
from pydantic import BaseModel, ConfigDict, Field
from simulator.config import RecoveryAction


class InterventionResult(BaseModel):
    """
    The realized result of executing an intervention action on a payment case.
    """
    model_config = ConfigDict(frozen=True)

    case_id: str = Field(description="Associated case identifier")
    action_taken: RecoveryAction = Field(description="The recovery action that was executed")
    recovered: bool = Field(description="Whether the intervention successfully recovered the funds")
    
    # Financial results in integer paise
    recovered_amount_paise: int = Field(ge=0, description="Gross recovered revenue in paise (0 if failed)")
    intervention_cost_paise: int = Field(ge=0, description="Friction / operational cost incurred in paise")
    net_recovered_amount_paise: int = Field(description="Net recovered revenue in paise: gross - cost")

    # Timing
    recovery_latency_hours: float = Field(ge=0.0, description="Realized latency until recovery resolution")
    
    # Audit details
    details: Dict[str, Any] = Field(default_factory=dict, description="Metadata / execution context log")

    @property
    def recovered_amount_inr(self) -> float:
        """Returns gross recovered revenue in INR."""
        return self.recovered_amount_paise / 100.0

    @property
    def intervention_cost_inr(self) -> float:
        """Returns intervention cost in INR."""
        return self.intervention_cost_paise / 100.0

    @property
    def net_recovered_amount_inr(self) -> float:
        """Returns net recovered revenue in INR."""
        return self.net_recovered_amount_paise / 100.0
