"""
Agent runtime and LLM-compatible tool calling driver for RecoverAI Agent.
Manages step execution, persistence, trace assembly, idempotency boundaries, and failure categorization.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import json
import time
from typing import Any, Dict, List, Optional
import uuid

from agent.errors import AgentExecutionError, AgentIdempotencyConflictError, ToolExecutionError
from agent.models import AgentContext, AgentModel, AgentRun, AgentRunStatus, AgentStep, StepStatus, StepType, FailureCategory
from agent.result import AgentResult
from agent.trace import AgentTrace
from agent.tools.registry import ToolRegistry, default_tool_registry
from agent.llm.validator import ToolValidationError
from api.services.operations_service import operations_service


class DeterministicAgentModel(AgentModel):
    """
    Deterministic Agent v0 driver.
    Directs the workflow sequentially through approved tools.
    """

    def __init__(self, idempotency_key_prefix: str = "agent_idemp", force_failure: bool = False):
        self.idempotency_key_prefix = idempotency_key_prefix
        self.force_failure = force_failure

    def decide_next_tool(
        self,
        context: AgentContext,
        available_tools: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        # 1. If context doesn't have case amount/customer info, retrieve case
        if context.amount_paise is None or context.customer_id is None:
            return {
                "tool": "get_payment_case",
                "arguments": {"case_id": context.case_id},
            }

        # 2. If decision has not been obtained, request decision
        if context.decision_id is None:
            return {
                "tool": "get_recovery_decision",
                "arguments": {"case_id": context.case_id},
            }

        # 3. If decision is obtained and action not yet executed, execute recommended action
        if context.action_id is None and context.recommended_action:
            idemp_key = f"{self.idempotency_key_prefix}_{context.case_id}_{context.decision_id}"
            return {
                "tool": "execute_recovery_action",
                "arguments": {
                    "decision_id": context.decision_id,
                    "action": context.recommended_action,
                    "idempotency_key": idemp_key,
                    "force_failure": self.force_failure,
                },
            }

        # 4. Workflow finished
        return None


class AgentRuntime:
    """
    Stateful execution runtime for RecoverAI Recovery Agent.
    Coordinates tool execution, idempotency checking, SQLite persistence, and trace assembly.
    """

    def __init__(
        self,
        tool_registry: Optional[ToolRegistry] = None,
        agent_model: Optional[AgentModel] = None,
        driver_type: str = "deterministic",
    ):
        self.tool_registry = tool_registry or default_tool_registry
        self.agent_model = agent_model or DeterministicAgentModel()
        self.driver_type = driver_type
        self.repository = operations_service.repository

    def execute_run(
        self,
        context: AgentContext,
        idempotency_key: Optional[str] = None,
        max_steps: int = 10,
    ) -> AgentResult:
        """
        Executes an end-to-end agent run with persistence, idempotency, and audit tracing.
        """
        # 1. Idempotency Check
        if idempotency_key:
            existing_run = self.repository.get_agent_run_by_idempotency_key(idempotency_key)
            if existing_run:
                if existing_run["case_id"] != context.case_id:
                    raise AgentIdempotencyConflictError(
                        f"Idempotency key '{idempotency_key}' was previously used for case '{existing_run['case_id']}' "
                        f"and cannot be reused for case '{context.case_id}'."
                    )
                # Reconstruct and return existing AgentResult
                return self._load_persisted_result(existing_run)

        agent_run_id = f"run_{uuid.uuid4().hex[:12]}"
        started_at = datetime.now(timezone.utc).isoformat()
        steps: List[AgentStep] = []

        # 2. Persist initial agent run record
        self.repository.save_agent_run({
            "agent_run_id": agent_run_id,
            "case_id": context.case_id,
            "decision_id": None,
            "idempotency_key": idempotency_key,
            "status": AgentRunStatus.STARTED.value,
            "recommended_action": None,
            "final_action": None,
            "final_operational_state": "STARTED",
            "driver_type": self.driver_type,
            "failure_category": None,
            "error_message": None,
            "llm_provider": getattr(self.agent_model, "provider", None).__class__.__name__ if hasattr(self.agent_model, "provider") else None,
            "llm_model": getattr(self.agent_model, "provider", None).model if hasattr(self.agent_model, "provider") and hasattr(self.agent_model.provider, "model") else None,
            "prompt_version": getattr(self.agent_model, "prompt_version", None),
            "total_tokens": 0,
            "llm_latency_ms": 0.0,
            "started_at": started_at,
            "completed_at": None,
        })

        # Record initial CASE_RETRIEVED step
        step_idx = 0
        step_id = f"step_{uuid.uuid4().hex[:12]}"
        init_step = AgentStep(
            step_id=step_id,
            agent_run_id=agent_run_id,
            step_index=step_idx,
            step_type=StepType.CASE_RETRIEVED,
            tool_name=None,
            input_summary={"case_id": context.case_id},
            output_summary={"case_id": context.case_id, "amount_paise": context.amount_paise},
            status=StepStatus.SUCCESS,
            failure_category=None,
            started_at=started_at,
            completed_at=started_at,
        )
        steps.append(init_step)
        self._persist_step(init_step)

        # 3. Main Tool Execution Loop
        run_status = AgentRunStatus.STARTED
        failure_category: Optional[str] = None
        error_msg: Optional[str] = None
        total_tokens = 0
        cumulative_latency_ms = 0.0
        last_tool_sig: Optional[str] = None

        while step_idx < max_steps:
            step_idx += 1
            available_tools = self.tool_registry.list_tools()

            try:
                tool_decision = self.agent_model.decide_next_tool(context, available_tools)
            except ToolValidationError as exc:
                failure_category = exc.category.value
                error_msg = str(exc)
                step_start = datetime.now(timezone.utc).isoformat()
                step_id = f"step_{uuid.uuid4().hex[:12]}"
                failed_step = AgentStep(
                    step_id=step_id,
                    agent_run_id=agent_run_id,
                    step_index=step_idx,
                    step_type=StepType.ACTION_FAILED,
                    tool_name=None,
                    input_summary={},
                    output_summary={},
                    status=StepStatus.FAILED,
                    failure_category=failure_category,
                    error_message=error_msg,
                    started_at=step_start,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
                steps.append(failed_step)
                self._persist_step(failed_step)
                run_status = AgentRunStatus.FAILED
                break
            except Exception as exc:
                failure_category = FailureCategory.MODEL_ERROR.value
                error_msg = f"Unexpected agent model failure: {str(exc)}"
                step_start = datetime.now(timezone.utc).isoformat()
                step_id = f"step_{uuid.uuid4().hex[:12]}"
                failed_step = AgentStep(
                    step_id=step_id,
                    agent_run_id=agent_run_id,
                    step_index=step_idx,
                    step_type=StepType.ACTION_FAILED,
                    tool_name=None,
                    input_summary={},
                    output_summary={},
                    status=StepStatus.FAILED,
                    failure_category=failure_category,
                    error_message=error_msg,
                    started_at=step_start,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
                steps.append(failed_step)
                self._persist_step(failed_step)
                run_status = AgentRunStatus.FAILED
                break

            if not tool_decision:
                # Agent completed workflow cleanly
                run_status = AgentRunStatus.COMPLETED
                break

            tool_name = tool_decision.get("tool")
            tool_args = tool_decision.get("arguments", {})
            meta = tool_decision.get("metadata", {})

            # Telemetry tracking
            step_prompt_tokens = meta.get("prompt_tokens")
            step_comp_tokens = meta.get("completion_tokens")
            step_lat_ms = meta.get("latency_ms")
            total_tokens += meta.get("total_tokens", 0)
            cumulative_latency_ms += meta.get("latency_ms", 0.0)

            # Loop protection: detect identical duplicate call without state progress
            curr_tool_sig = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
            if curr_tool_sig == last_tool_sig:
                failure_category = FailureCategory.WORKFLOW_FAILURE.value
                error_msg = "Repeated identical tool call loop detected without progress."
                step_start = datetime.now(timezone.utc).isoformat()
                step_id = f"step_{uuid.uuid4().hex[:12]}"
                failed_step = AgentStep(
                    step_id=step_id,
                    agent_run_id=agent_run_id,
                    step_index=step_idx,
                    step_type=StepType.ACTION_FAILED,
                    tool_name=tool_name,
                    input_summary=tool_args,
                    output_summary={},
                    status=StepStatus.FAILED,
                    failure_category=failure_category,
                    error_message=error_msg,
                    started_at=step_start,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
                steps.append(failed_step)
                self._persist_step(failed_step)
                run_status = AgentRunStatus.FAILED
                break

            last_tool_sig = curr_tool_sig
            step_start = datetime.now(timezone.utc).isoformat()
            step_id = f"step_{uuid.uuid4().hex[:12]}"

            tool = self.tool_registry.get(tool_name)
            if not tool:
                failure_category = FailureCategory.INVALID_TOOL_CALL.value
                error_msg = f"Unknown or unapproved tool '{tool_name}'."
                failed_step = AgentStep(
                    step_id=step_id,
                    agent_run_id=agent_run_id,
                    step_index=step_idx,
                    step_type=StepType.ACTION_FAILED,
                    tool_name=tool_name,
                    input_summary=tool_args,
                    output_summary={},
                    status=StepStatus.FAILED,
                    failure_category=failure_category,
                    error_message=error_msg,
                    started_at=step_start,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
                steps.append(failed_step)
                self._persist_step(failed_step)
                run_status = AgentRunStatus.FAILED
                break

            # Map step type
            if tool_name == "get_recovery_decision":
                step_type = StepType.DECISION_OBTAINED
            elif tool_name == "execute_recovery_action":
                step_type = StepType.ACTION_EXECUTED
            elif tool_name == "record_recovery_outcome":
                step_type = StepType.OUTCOME_RECORDED
            else:
                step_type = StepType.CASE_RETRIEVED

            try:
                out_summary = tool.execute(context, **tool_args)
                step_end = datetime.now(timezone.utc).isoformat()
                step_record = AgentStep(
                    step_id=step_id,
                    agent_run_id=agent_run_id,
                    step_index=step_idx,
                    step_type=step_type,
                    tool_name=tool_name,
                    input_summary=tool_args,
                    output_summary=out_summary,
                    status=StepStatus.SUCCESS,
                    failure_category=None,
                    llm_prompt_tokens=step_prompt_tokens,
                    llm_completion_tokens=step_comp_tokens,
                    llm_latency_ms=step_lat_ms,
                    started_at=step_start,
                    completed_at=step_end,
                )
                steps.append(step_record)
                self._persist_step(step_record)

                if tool_name == "get_recovery_decision":
                    run_status = AgentRunStatus.DECISION_OBTAINED
                elif tool_name == "execute_recovery_action":
                    if out_summary.get("status") == "EXECUTED":
                        run_status = AgentRunStatus.ACTION_EXECUTED
                    else:
                        run_status = AgentRunStatus.ACTION_FAILED
                        failure_category = FailureCategory.EXECUTION_FAILURE.value
                        error_msg = out_summary.get("error_message") or "Provider action technical failure."

            except Exception as exc:
                error_msg = str(exc)
                from agent.errors import ActionMismatchError
                if isinstance(exc, ActionMismatchError):
                    failure_category = FailureCategory.POLICY_VIOLATION.value
                else:
                    failure_category = FailureCategory.EXECUTION_FAILURE.value

                step_end = datetime.now(timezone.utc).isoformat()
                failed_step = AgentStep(
                    step_id=step_id,
                    agent_run_id=agent_run_id,
                    step_index=step_idx,
                    step_type=StepType.ACTION_FAILED,
                    tool_name=tool_name,
                    input_summary=tool_args,
                    output_summary={},
                    status=StepStatus.FAILED,
                    failure_category=failure_category,
                    error_message=error_msg,
                    started_at=step_start,
                    completed_at=step_end,
                )
                steps.append(failed_step)
                self._persist_step(failed_step)
                run_status = AgentRunStatus.FAILED
                break

        # Check for max step exhaustion
        if step_idx >= max_steps and run_status not in (AgentRunStatus.COMPLETED, AgentRunStatus.ACTION_EXECUTED):
            if run_status != AgentRunStatus.FAILED:
                failure_category = FailureCategory.WORKFLOW_FAILURE.value
                error_msg = f"Maximum execution steps ({max_steps}) exceeded without reaching terminal state."
                run_status = AgentRunStatus.FAILED

        # 4. Finalize Run Record
        completed_at = datetime.now(timezone.utc).isoformat()
        final_status = "completed" if run_status in (AgentRunStatus.COMPLETED, AgentRunStatus.ACTION_EXECUTED) else "failed"

        self.repository.update_agent_run(
            agent_run_id,
            decision_id=context.decision_id,
            status=final_status,
            recommended_action=context.recommended_action,
            final_action=context.recommended_action if context.action_id else None,
            final_operational_state=context.current_operational_state or "UNKNOWN",
            failure_category=failure_category,
            error_message=error_msg,
            total_tokens=total_tokens,
            llm_latency_ms=cumulative_latency_ms,
            completed_at=completed_at,
        )

        trace = AgentTrace(
            agent_run_id=agent_run_id,
            case_id=context.case_id,
            steps=steps,
        )

        return AgentResult(
            agent_run_id=agent_run_id,
            case_id=context.case_id,
            decision_id=context.decision_id,
            action_id=context.action_id,
            recommended_action=context.recommended_action,
            executed_action=context.recommended_action if context.action_id else None,
            execution_status=context.execution_status or ("FAILED" if final_status == "failed" else None),
            final_operational_state=context.current_operational_state or ("ACTION_EXECUTED" if final_status == "completed" else "FAILED"),
            recovery_probability=context.recovery_probability,
            expected_gross_paise=context.expected_gross_paise,
            expected_gross_inr=context.expected_gross_paise / 100.0 if context.expected_gross_paise is not None else None,
            action_cost_paise=context.action_cost_paise,
            action_cost_inr=context.action_cost_paise / 100.0 if context.action_cost_paise is not None else None,
            expected_net_paise=context.expected_net_paise,
            expected_net_inr=context.expected_net_paise / 100.0 if context.expected_net_paise is not None else None,
            decision_margin_paise=context.decision_margin_paise,
            outcome_status=context.outcome_status,
            recovered_amount_paise=context.recovered_amount_paise,
            recovered_amount_inr=context.recovered_amount_paise / 100.0 if context.recovered_amount_paise is not None else None,
            provider_reference=context.provider_reference,
            explanation=context.explanation,
            status=final_status,
            driver_type=self.driver_type,
            failure_category=failure_category,
            error_message=error_msg,
            total_tokens=total_tokens,
            llm_latency_ms=cumulative_latency_ms,
            started_at=started_at,
            completed_at=completed_at,
            trace=trace,
        )

    def _persist_step(self, step: AgentStep) -> None:
        """Persists a single step to SQLite."""
        self.repository.save_agent_step({
            "step_id": step.step_id,
            "agent_run_id": step.agent_run_id,
            "step_index": step.step_index,
            "step_type": step.step_type.value if hasattr(step.step_type, "value") else str(step.step_type),
            "tool_name": step.tool_name,
            "input_summary_json": json.dumps(step.input_summary),
            "output_summary_json": json.dumps(step.output_summary),
            "status": step.status.value if hasattr(step.status, "value") else str(step.status),
            "failure_category": step.failure_category,
            "error_message": step.error_message,
            "llm_prompt_tokens": step.llm_prompt_tokens,
            "llm_completion_tokens": step.llm_completion_tokens,
            "llm_latency_ms": step.llm_latency_ms,
            "started_at": step.started_at,
            "completed_at": step.completed_at,
        })

    def _load_persisted_result(self, run_row: Dict[str, Any]) -> AgentResult:
        """Reconstructs full AgentResult and trace from SQLite for idempotent replays."""
        steps_raw = self.repository.get_agent_steps(run_row["agent_run_id"])
        steps: List[AgentStep] = []
        for s in steps_raw:
            steps.append(
                AgentStep(
                    step_id=s["step_id"],
                    agent_run_id=s["agent_run_id"],
                    step_index=s["step_index"],
                    step_type=StepType(s["step_type"]),
                    tool_name=s["tool_name"],
                    input_summary=json.loads(s["input_summary_json"]) if s.get("input_summary_json") else {},
                    output_summary=json.loads(s["output_summary_json"]) if s.get("output_summary_json") else {},
                    status=StepStatus(s["status"]),
                    failure_category=s.get("failure_category"),
                    error_message=s.get("error_message"),
                    llm_prompt_tokens=s.get("llm_prompt_tokens"),
                    llm_completion_tokens=s.get("llm_completion_tokens"),
                    llm_latency_ms=s.get("llm_latency_ms"),
                    started_at=s["started_at"],
                    completed_at=s.get("completed_at"),
                )
            )

        # Hydrate financial records if decision exists
        dec_id = run_row.get("decision_id")
        rec_act = run_row.get("recommended_action")
        gross_p = None
        cost_p = None
        net_p = None
        prob = None
        margin_p = None
        expl = None
        act_id = None
        prov_ref = None

        execution_status = None
        outcome_status = None
        recovered_amount_paise = None

        if dec_id:
            dec = self.repository.get_decision(dec_id)
            if dec:
                rec_act = dec.recommended_action.value if hasattr(dec.recommended_action, "value") else str(dec.recommended_action)
                gross_p = dec.expected_gross_recovery_paise
                cost_p = dec.action_cost_paise
                net_p = dec.expected_net_recovery_paise
                prob = getattr(dec, "recommended_action_recovery_probability", getattr(dec, "recovery_probability", None))
                margin_p = dec.decision_margin_paise
                expl = dec.explanation

            act = self.repository.get_action_by_decision(dec_id)
            if act:
                act_id = act.action_id
                prov_ref = act.provider_reference
                execution_status = act.status.value
                out_rec = self.repository.get_outcome_by_action_id(act.action_id)
                if out_rec:
                    outcome_status = out_rec.outcome_status.value
                    recovered_amount_paise = out_rec.recovered_amount_paise
            else:
                execution_status = "EXECUTED" if run_row.get("final_operational_state") in ("ACTION_EXECUTED", "RECOVERED", "NOT_RECOVERED") else None

        trace = AgentTrace(
            agent_run_id=run_row["agent_run_id"],
            case_id=run_row["case_id"],
            steps=steps,
        )

        return AgentResult(
            agent_run_id=run_row["agent_run_id"],
            case_id=run_row["case_id"],
            decision_id=dec_id,
            action_id=act_id,
            recommended_action=rec_act,
            executed_action=run_row.get("final_action"),
            execution_status=execution_status,
            final_operational_state=run_row.get("final_operational_state"),
            recovery_probability=prob,
            expected_gross_paise=gross_p,
            expected_gross_inr=gross_p / 100.0 if gross_p is not None else None,
            action_cost_paise=cost_p,
            action_cost_inr=cost_p / 100.0 if cost_p is not None else None,
            expected_net_paise=net_p,
            expected_net_inr=net_p / 100.0 if net_p is not None else None,
            decision_margin_paise=margin_p,
            outcome_status=outcome_status,
            recovered_amount_paise=recovered_amount_paise,
            recovered_amount_inr=recovered_amount_paise / 100.0 if recovered_amount_paise is not None else None,
            provider_reference=prov_ref,
            explanation=expl,
            status=run_row["status"],
            driver_type=run_row.get("driver_type", "deterministic"),
            failure_category=run_row.get("failure_category"),
            error_message=run_row.get("error_message"),
            total_tokens=run_row.get("total_tokens", 0),
            llm_latency_ms=run_row.get("llm_latency_ms", 0.0),
            started_at=run_row["started_at"],
            completed_at=run_row.get("completed_at"),
            trace=trace,
        )
