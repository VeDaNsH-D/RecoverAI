# RecoverAI — Milestone 4: Autonomous Recovery Agent Architecture

---

## 1. Overview & Mission

**Milestone 4** establishes the **Autonomous Recovery Agent v0** for the RecoverAI platform. The Recovery Agent serves as a deterministic workflow orchestrator that coordinates the complete payment recovery lifecycle—from observable incident ingestion and ML decision requests to action dispatch, state transitions, outcome settlement, and immutable audit trace recording.

```
                  +----------------------------------------------+
                  |           CLIENT / MERCHANT API              |
                  +----------------------+-----------------------+
                                         |
                                         v
                  +----------------------------------------------+
                  |         Recovery Agent v0 (Orchestrator)     |
                  +----------------------+-----------------------+
                                         |
          +------------------------------+------------------------------+
          |                              |                              |
          v                              v                              v
+--------------------+        +--------------------+        +--------------------+
|  Case Retrieval    |        |   Decision Tool    |        | Action Dispatch    |
|       Tool         |        | (ML Decision Eng)  |        |      Tool          |
+--------------------+        +----------+---------+        +---------+----------+
                                         |                            |
                                         v                            v
                              +--------------------+        +--------------------+
                              | Authoritative ML & |        | Action Executor &  |
                              | Econ Decision Eng  |        |  Provider Mocks    |
                              +--------------------+        +--------------------+
```

---

## 2. Non-Negotiable Decision Authority Boundary

The system maintains a strict separation of concerns between **economic decisioning** and **workflow orchestration**:

$$\text{ML Probability Models} \longrightarrow \text{RecoveryDecisionEngine} \longrightarrow \text{Recovery Operations} \longrightarrow \text{Action Providers}$$

### The Agent MUST NOT:
1. Calculate recovery probabilities independently.
2. Calculate expected net recovery values or action costs independently.
3. Override, substitute, or rank candidate actions independently.
4. Bypass safety policies (e.g. retry exhaustion, micro-ticket protection).
5. Directly manipulate SQLite state or call low-level provider APIs without approved tools.
6. Access unobservable latent simulator variables or ground truth.

---

## 3. Approved Tool Registry & Schemas

The agent interacts with the recovery subsystem **exclusively** through approved, registered tools in `agent/tools/registry.py`:

| Tool Name | Purpose | Primary Input | Primary Output | Safety Constraints |
| :--- | :--- | :--- | :--- | :--- |
| `get_payment_case` | Retrieves observable incident diagnostics | `case_id` | Observable payment attributes | Zero exposure of latent simulator variables |
| `get_recovery_decision` | Ingests observable case and requests decision from ML engine | `case_id` | `decision_id`, `recommended_action`, `expected_net_paise` | Strictly delegates to `RecoveryDecisionEngine` |
| `execute_recovery_action` | Dispatches recommended action to provider | `decision_id`, `action`, `idempotency_key` | `action_id`, `status`, `cost_paise`, `provider_ref` | **Action Match Verification**: Rejects any action differing from `recommended_action` |
| `get_action_status` | Queries execution status of action | `action_id` | `status`, `cost_paise`, `executed_at` | Read-only inspection |
| `record_recovery_outcome` | Records payment settlement outcome | `case_id`, `action_id`, `outcome_status`, `recovered_paise` | `event_id`, `outcome_status`, `event_timestamp` | Requires prior `ACTION_EXECUTED` state |
| `get_recovery_summary` | Returns aggregate ledger and rate metrics | None | Aggregate recovery metrics | Descriptive only |

---

## 4. Execution Failure vs. Settlement Failure

RecoverAI strictly distinguishes between technical provider dispatch errors and payment recovery non-settlement:

```
[ DECIDED ]
    |
    v
[ ACTION_PENDING ]
    |
    +---- Technical Provider Timeout / Failure ----> [ EXECUTION_FAILED ]
    |                                                        |
    |                                                        v
    |                                                 [ ACTION_PENDING ] (Retry same action)
    |
    +---- Dispatch Succeeded ----------------------> [ ACTION_EXECUTED ]
                                                             |
                                                             +---- Payment Settled ----> [ RECOVERED ]
                                                             |
                                                             +---- Unpaid / Expired ---> [ NOT_RECOVERED ]
```

1. **`EXECUTION_FAILED`**: Technical communication failure during action dispatch (e.g., gateway timeout). No action fee is incurred ($\text{Cost} = 0$). The same action may be retried.
2. **`NOT_RECOVERED`**: The action was successfully delivered to the customer/gateway, but payment settlement was not achieved. Action cost is incurred, gross recovery is 0.

---

## 5. Idempotency & Persistence

- **Idempotency Key**: Every agent run accepts an optional `idempotency_key`. Replays with an identical key return the cached `AgentResult` without duplicate provider execution or duplicate decision creation.
- **Conflict Handling**: Reusing an idempotency key with a different case ID immediately raises `409 Conflict` (`AgentIdempotencyConflictError`).
- **Database Schema**:
  - `agent_runs`: Stores run metadata (`agent_run_id`, `case_id`, `decision_id`, `idempotency_key`, `status`, `started_at`, `completed_at`).
  - `agent_steps`: Stores immutable step-level trace history (`step_id`, `agent_run_id`, `step_index`, `step_type`, `tool_name`, `input_summary_json`, `output_summary_json`, `status`, `error_message`).

---

## 6. Representative Auditable Agent Trace

```text
Agent Run [run_5519a1b5fd23] for Case [case_smoke_agent_001]
├── CASE_RETRIEVED [success]
│   └── case_id = case_smoke_agent_001
│   └── amount_paise = 750000
├── DECISION_OBTAINED (tool=get_recovery_decision) [success]
│   └── decision_id = dec_3faab210ea5c
│   └── recommended_action = retry
│   └── recovery_probability = 0.7064
│   └── expected_gross_recovery_paise = 529767
│   └── action_cost_paise = 200
│   └── expected_net_recovery_paise = 529567
│   └── decision_margin_paise = 139125
└── ACTION_EXECUTED (tool=execute_recovery_action) [success]
    └── action_id = act_09130f199ce3
    └── action = retry
    └── status = EXECUTED
    └── cost_paise = 200
    └── provider_reference = gw_retry_833353f0902d
```

---

## 7. LLM-Compatible Pluggable Architecture

Milestone 4 establishes the pluggable `AgentModel` abstraction in `agent/runtime.py`:

```python
class AgentModel(ABC):
    @abstractmethod
    def decide_next_tool(
        self,
        context: AgentContext,
        available_tools: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        pass
```

- **Day 3 / Milestone 4**: Implemented with `DeterministicAgentModel` for 100% reproducible execution and automated CI/CD testing without external API keys.
- **Future Day 5**: Enables dropping in an LLM tool-calling driver without modifying tools, decision safety policies, or database schemas.

---

## 8. Milestone Boundaries & Non-Goals

1. **No External LLM Required**: Milestone 4 contains zero external LLM dependencies (OpenAI/Anthropic/Gemini).
2. **No Real Payment Networks**: Uses deterministic provider-agnostic mocks; live Razorpay test-mode integration is planned for Day 6.
3. **Strictly Observational**: Agent operations are logged for auditability and do not alter the frozen causal ground-truth benchmark.
