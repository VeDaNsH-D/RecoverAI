"""
Customer profile schema for RecoverAI.
All monetary fields are strictly in integer paise.
"""

from pydantic import BaseModel, ConfigDict, Field
from simulator.config import PaymentMethod


class CustomerProfile(BaseModel):
    """
    Represents a synthetic merchant customer with historical transaction behavior.
    """
    model_config = ConfigDict(frozen=True)

    customer_id: str = Field(description="Unique customer identifier (e.g. cust_000123)")
    historical_success_rate: float = Field(
        ge=0.0, le=1.0, description="Historical payment success rate between 0.0 and 1.0"
    )
    total_transactions: int = Field(
        ge=0, description="Total number of lifetime transaction attempts"
    )
    total_failures: int = Field(
        ge=0, description="Total number of lifetime failed payment attempts"
    )
    avg_transaction_amount_paise: int = Field(
        ge=0, description="Average transaction value in integer paise"
    )
    default_payment_method: PaymentMethod = Field(
        description="Preferred payment method (upi, card, netbanking, mandate)"
    )
    is_subscription: bool = Field(
        default=False, description="Whether customer has an active recurring subscription"
    )
    tenure_months: int = Field(
        ge=0, description="Customer relationship age in months"
    )

    @property
    def avg_transaction_amount_inr(self) -> float:
        """Helper for presentation: returns amount in INR (rupees)."""
        return self.avg_transaction_amount_paise / 100.0
