"""
Payment case schema (Observable Features ONLY).
Contains strictly the features exposed to recovery policies, ML models, and agents.
All monetary amounts are strictly represented in integer paise.
"""

from pydantic import BaseModel, ConfigDict, Field
from simulator.config import FailureType, PaymentMethod


class PaymentCase(BaseModel):
    """
    Observable features of a failed transaction case.
    GUARANTEE: Contains zero hidden ground-truth fields or potential outcomes.
    """
    model_config = ConfigDict(frozen=True)

    case_id: str = Field(description="Unique case identifier (e.g. case_00001)")
    customer_id: str = Field(description="Associated customer identifier")
    merchant_id: str = Field(default="merch_recoverai_prod", description="Merchant account ID")
    
    # Financial data (Strict Integer Paise)
    amount_paise: int = Field(ge=0, description="Transaction amount in integer paise (1 INR = 100 paise)")
    currency: str = Field(default="INR", description="Currency code")

    # Payment Context
    payment_method: PaymentMethod = Field(description="Payment method used for the failed attempt")
    is_subscription: bool = Field(default=False, description="Whether transaction is a recurring subscription charge")
    
    # Historical Customer Context (Observable aggregate features)
    customer_historical_success_rate: float = Field(ge=0.0, le=1.0, description="Customer historical success rate")
    customer_total_transactions: int = Field(ge=0, description="Lifetime transactions recorded")
    customer_total_failures: int = Field(ge=0, description="Lifetime failures recorded")
    customer_avg_amount_paise: int = Field(ge=0, description="Customer average transaction amount in paise")
    customer_tenure_months: int = Field(ge=0, description="Customer tenure in months")

    # Incident Context
    failure_type: FailureType = Field(description="Diagnosed failure reason category")
    retry_count: int = Field(default=0, ge=0, description="Number of recovery retries already attempted")
    hours_since_failure: float = Field(default=0.0, ge=0.0, description="Elapsed time in hours since failure occurred")
    created_at: str = Field(description="ISO 8601 timestamp string of incident")

    @property
    def amount_inr(self) -> float:
        """Helper for presentation/reporting: returns transaction value in INR (rupees)."""
        return self.amount_paise / 100.0

    @property
    def customer_avg_amount_inr(self) -> float:
        """Helper for presentation/reporting: returns avg amount in INR (rupees)."""
        return self.customer_avg_amount_paise / 100.0
