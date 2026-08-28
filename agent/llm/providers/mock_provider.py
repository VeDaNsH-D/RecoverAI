"""
Deterministic and Scriptable Mock LLM Provider for RecoverAI (Milestone 5).
Enables 100% offline, reproducible testing, fault injection, and prompt-injection defense verification without API keys.
"""

import time
from typing import Any, Callable, Dict, List, Optional
from agent.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMToolCall


class MockLLMProvider(LLMProvider):
    """
    Mock LLM Provider that executes deterministic recovery orchestration.
    Can be scripted for specific tool sequences, simulated faults, timeouts, or malicious attempts.
    """

    def __init__(
        self,
        scripted_calls: Optional[List[Dict[str, Any]]] = None,
        force_timeout: bool = False,
        force_provider_error: Optional[str] = None,
        simulate_latency_ms: float = 5.0,
        model: str = "mock-recovery-v1",
    ):
        self.scripted_calls = list(scripted_calls) if scripted_calls is not None else None
        self.force_timeout = force_timeout
        self.force_provider_error = force_provider_error
        self.simulate_latency_ms = simulate_latency_ms
        self.model = model
        self.call_count = 0
        self.recorded_messages: List[List[LLMMessage]] = []

    def generate_tool_call(
        self,
        messages: List[LLMMessage],
        tools: List[Dict[str, Any]],
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.call_count += 1
        self.recorded_messages.append(messages)

        # 1. Fault Injection: Timeout
        if self.force_timeout:
            raise TimeoutError("Mock LLM provider request timed out after 10.0s.")

        # 2. Fault Injection: Provider Error
        if self.force_provider_error:
            raise RuntimeError(f"Mock LLM provider internal error: {self.force_provider_error}")

        # 3. Scripted Sequence Mode (for targeted edge case testing)
        if self.scripted_calls is not None:
            if not self.scripted_calls:
                # No more tool calls in script -> conclude
                return LLMResponse(
                    content="Workflow concluded per script.",
                    tool_calls=[],
                    prompt_tokens=150,
                    completion_tokens=20,
                    total_tokens=170,
                    latency_ms=self.simulate_latency_ms,
                    model=self.model,
                    provider="mock",
                )
            next_call = self.scripted_calls.pop(0)
            tool_name = next_call.get("tool")
            tool_args = next_call.get("arguments", {})
            return LLMResponse(
                content=None,
                tool_calls=[LLMToolCall(tool=tool_name, arguments=tool_args)],
                prompt_tokens=180,
                completion_tokens=40,
                total_tokens=220,
                latency_ms=self.simulate_latency_ms,
                model=self.model,
                provider="mock",
            )

        # 4. Default Autonomous Reasoning Mode: Parse last user message for operational context
        last_user_msg = ""
        for m in reversed(messages):
            if m.role == "user" and m.content:
                last_user_msg = m.content
                break

        # Extract case_id and decision state from user prompt
        case_id = "UNKNOWN"
        for line in last_user_msg.splitlines():
            if line.startswith("Case ID:"):
                case_id = line.split(":", 1)[1].strip()
            elif "Decision ID:" in line:
                dec_id_val = line.split(":", 1)[1].strip()
            elif "Current Operational State:" in line:
                op_state_val = line.split(":", 1)[1].strip()
            elif "Recommended Action:" in line:
                rec_act_val = line.split(":", 1)[1].strip()

        # Deterministic Next Step Logic:
        # Step A: If decision not obtained -> get_recovery_decision
        if "Decision ID: NONE" in last_user_msg or "Decision ID:" not in last_user_msg:
            return LLMResponse(
                content="Requesting authoritative ML decision.",
                tool_calls=[
                    LLMToolCall(
                        tool="get_recovery_decision",
                        arguments={"case_id": case_id},
                    )
                ],
                prompt_tokens=210,
                completion_tokens=35,
                total_tokens=245,
                latency_ms=self.simulate_latency_ms,
                model=self.model,
                provider="mock",
            )

        # Step B: If decision obtained and action not yet executed -> execute_recovery_action
        if "Action ID: NONE" in last_user_msg:
            # Extract recommended action
            rec_action = "retry"
            decision_id = "dec_auto"
            for line in last_user_msg.splitlines():
                if "Recommended Action:" in line:
                    val = line.split(":", 1)[1].strip()
                    if val != "NONE":
                        if val.lower().startswith("recoveryaction."):
                            val = val.split(".", 1)[1]
                        rec_action = val.lower()
                elif "Decision ID:" in line:
                    val = line.split(":", 1)[1].strip()
                    if val != "NONE":
                        decision_id = val

            return LLMResponse(
                content=f"Executing recommended action '{rec_action}'.",
                tool_calls=[
                    LLMToolCall(
                        tool="execute_recovery_action",
                        arguments={
                            "decision_id": decision_id,
                            "action": rec_action,
                            "idempotency_key": f"llm_idemp_{case_id}_{decision_id}",
                        },
                    )
                ],
                prompt_tokens=280,
                completion_tokens=50,
                total_tokens=330,
                latency_ms=self.simulate_latency_ms,
                model=self.model,
                provider="mock",
            )

        # Step C: Action executed and state is terminal -> complete workflow
        return LLMResponse(
            content="Payment recovery action successfully executed. Workflow complete.",
            tool_calls=[],
            prompt_tokens=310,
            completion_tokens=25,
            total_tokens=335,
            latency_ms=self.simulate_latency_ms,
            model=self.model,
            provider="mock",
        )
