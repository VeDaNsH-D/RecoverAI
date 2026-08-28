"""
Recovery Agent endpoints for RecoverAI API.
Provides merchant-facing autonomous recovery orchestration and auditable run retrieval.
"""

from typing import Literal, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from agent.orchestrator import recovery_agent
from agent.result import AgentResult
from agent.errors import AgentIdempotencyConflictError, ActionMismatchError
from api.schemas import PaymentCaseRequest, ErrorResponse

router = APIRouter(prefix="/agent", tags=["Recovery Agent"])


class AgentRecoverRequest(PaymentCaseRequest):
    """
    Request payload for autonomous recovery agent execution.
    Inherits all observable PaymentCaseRequest fields and adds optional agent control parameters.
    GUARANTEE: Closed schema (extra='forbid').
    """
    model_config = ConfigDict(extra="forbid")

    idempotency_key: Optional[str] = Field(default=None, description="Unique idempotency key for exactly-once execution")
    force_failure: bool = Field(default=False, description="Simulate technical execution failure (for testing/fault injection)")
    driver: Optional[Literal["deterministic", "llm"]] = Field(default=None, description="Agent driver strategy (deterministic, llm)")


@router.post(
    "/recover",
    response_model=AgentResult,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse, "description": "Action mismatch or invalid case request"},
        404: {"model": ErrorResponse, "description": "Referenced resource not found"},
        409: {"model": ErrorResponse, "description": "Idempotency conflict or invalid state transition"},
        422: {"description": "Unprocessable Entity (Validation failed or forbidden fields)"},
        503: {"model": ErrorResponse, "description": "Recovery decision model unavailable"},
    },
)
async def run_recovery_agent(request: AgentRecoverRequest):
    """
    Orchestrates an autonomous recovery workflow for a failed payment incident.
    Retrieves case context, requests ML decision, dispatches recommended action, and logs full trace.
    """
    try:
        return recovery_agent.run(
            case=request,
            idempotency_key=request.idempotency_key,
            force_failure=request.force_failure,
            driver=request.driver,
        )
    except AgentIdempotencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ActionMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Agent execution error: {str(exc)}")


@router.get(
    "/runs/{agent_run_id}",
    response_model=AgentResult,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"model": ErrorResponse, "description": "Agent run not found"},
    },
)
async def get_agent_run(agent_run_id: str):
    """
    Retrieves the execution status, decision details, financial ledgers, and audit trace of a completed agent run.
    """
    result = recovery_agent.get_run(agent_run_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent run '{agent_run_id}' not found.")
    return result
