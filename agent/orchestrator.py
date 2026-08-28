"""
Recovery Agent orchestrator for RecoverAI (Milestones 4 & 5).
Provides the primary public programmatic interface for running agentic revenue recovery
with Deterministic or LLM Tool-Calling drivers.
"""

from typing import Any, Dict, Optional, Union
from simulator.schemas.case import PaymentCase
from api.schemas import PaymentCaseRequest
from agent.models import AgentContext
from agent.result import AgentResult
from agent.runtime import AgentRuntime, AgentModel, DeterministicAgentModel
from agent.llm.model import LLMAgentModel
from agent.tools.registry import ToolRegistry, default_tool_registry


class RecoveryAgent:
    """
    Autonomous Recovery Agent.
    Orchestrates the recovery workflow from observable payment failure to decision, execution, and trace logging.
    Supports both Deterministic and LLM Tool-Calling drivers.
    """

    def __init__(
        self,
        tool_registry: Optional[ToolRegistry] = None,
        agent_model: Optional[AgentModel] = None,
    ):
        self.tool_registry = tool_registry or default_tool_registry
        self.agent_model = agent_model

    def run(
        self,
        case: Union[PaymentCase, PaymentCaseRequest, Dict[str, Any]],
        idempotency_key: Optional[str] = None,
        force_failure: bool = False,
        outcome_status: Optional[str] = None,
        recovered_amount_paise: Optional[int] = None,
        driver: Optional[str] = None,
    ) -> AgentResult:
        """
        Executes an autonomous recovery workflow for an observable failed payment incident.
        """
        # 1. Initialize AgentContext from observable case
        if isinstance(case, PaymentCase):
            context = AgentContext(
                case_id=case.case_id,
                customer_id=case.customer_id,
                amount_paise=case.amount_paise,
                currency="INR",
                payment_method=case.payment_method.value if hasattr(case.payment_method, "value") else str(case.payment_method),
                is_subscription=bool(case.is_subscription),
                failure_type=case.failure_type.value if hasattr(case.failure_type, "value") else str(case.failure_type),
                retry_count=int(case.retry_count),
                hours_since_failure=float(case.hours_since_failure),
            )
        elif isinstance(case, PaymentCaseRequest):
            context = AgentContext(
                case_id=case.case_id,
                customer_id=case.customer_id,
                amount_paise=case.amount_paise,
                currency=case.currency,
                payment_method=case.payment_method.value if hasattr(case.payment_method, "value") else str(case.payment_method),
                is_subscription=bool(case.is_subscription),
                failure_type=case.failure_type.value if hasattr(case.failure_type, "value") else str(case.failure_type),
                retry_count=int(case.retry_count),
                hours_since_failure=float(case.hours_since_failure),
            )
        elif isinstance(case, dict):
            context = AgentContext(
                case_id=case["case_id"],
                customer_id=case.get("customer_id"),
                amount_paise=case.get("amount_paise"),
                currency=case.get("currency", "INR"),
                payment_method=case.get("payment_method", "upi"),
                is_subscription=case.get("is_subscription", False),
                failure_type=case.get("failure_type", "temporary_failure"),
                retry_count=case.get("retry_count", 0),
                hours_since_failure=case.get("hours_since_failure", 0.0),
            )
        else:
            raise ValueError(f"Unsupported case type: {type(case)}")

        # 2. Select Agent Model Strategy
        driver_str = driver or ("llm" if isinstance(self.agent_model, LLMAgentModel) else "deterministic")
        if driver == "llm":
            model = self.agent_model if isinstance(self.agent_model, LLMAgentModel) else LLMAgentModel()
            driver_type = "llm"
        elif driver == "deterministic":
            model = DeterministicAgentModel(force_failure=force_failure)
            driver_type = "deterministic"
        else:
            if self.agent_model is not None:
                model = self.agent_model
                driver_type = "llm" if isinstance(self.agent_model, LLMAgentModel) else "deterministic"
            else:
                model = DeterministicAgentModel(force_failure=force_failure)
                driver_type = "deterministic"

        # 3. Instantiate runtime
        runtime = AgentRuntime(tool_registry=self.tool_registry, agent_model=model, driver_type=driver_type)

        # 4. Execute run
        result = runtime.execute_run(context, idempotency_key=idempotency_key)

        # 5. Optional outcome settlement (e.g. webhook simulation)
        if outcome_status and result.action_id and result.execution_status == "EXECUTED":
            outcome_tool = self.tool_registry.get("record_recovery_outcome")
            if outcome_tool:
                outcome_tool.execute(
                    context,
                    case_id=context.case_id,
                    action_id=result.action_id,
                    decision_id=result.decision_id,
                    outcome_status=outcome_status,
                    recovered_amount_paise=recovered_amount_paise or (context.amount_paise if outcome_status == "recovered" else 0),
                )
                runtime.repository.update_agent_run(
                    result.agent_run_id,
                    final_operational_state=outcome_status.upper(),
                )
                return runtime.execute_run(context, idempotency_key=idempotency_key)

        return result

    def get_run(self, agent_run_id: str) -> Optional[AgentResult]:
        """Retrieves a previously executed agent run and its trace."""
        runtime = AgentRuntime(tool_registry=self.tool_registry)
        run_record = runtime.repository.get_agent_run(agent_run_id)
        if not run_record:
            return None
        return runtime._load_persisted_result(run_record)


# Default global RecoveryAgent instance
recovery_agent = RecoveryAgent()
