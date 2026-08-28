# RecoverAI — Milestone 5: LLM / Tool-Calling Recovery Agent

---

## 1. Overview & Core Mission

**Milestone 5** introduces an LLM-driven structured tool-calling orchestration layer to RecoverAI. The LLM functions as a **workflow reasoning and tool invocation agent**, navigating the multi-step recovery lifecycle while strictly respecting the deterministic ML models and economic decision engine as the authoritative decision maker.

> **Non-Negotiable Architectural Principles**:
> - **The LLM selects the next approved tool; it does not select the recovery action.**
> - **RecoveryDecisionEngine remains the authoritative decision authority.**

```
                            +------------------------------------------------+
                            |           CLIENT / MERCHANT REQUEST            |
                            +-----------------------+------------------------+
                                                    |
                                                    v
                            +------------------------------------------------+
                            |               AgentRuntime                     |
                            +-----------------------+------------------------+
                                                    |
                                                    v
                            +------------------------------------------------+
                            |           LLMAgentModel (Strategy)             |
                            |  - Formats Context & Approved Tool Schemas     |
                            |  - Invokes LLMProvider (Mock / External API)   |
                            |  - Parses & Validates Structured Tool Calls    |
                            +-----------------------+------------------------+
                                                    |
                                                    v
                            +------------------------------------------------+
                            |            Tool Validation & Registry          |
                            |  - Verifies Tool Approval & JSON Schema        |
                            |  - Enforces Action-Match Decision Guardrail    |
                            +-----------------------+------------------------+
                                                    |
                       +----------------------------+----------------------------+
                       |                                                         |
                       v                                                         v
         +-----------------------------+                           +-----------------------------+
         |  get_recovery_decision      |                           |   execute_recovery_action   |
         |  (RecoveryDecisionEngine)   |                           |   (ActionExecutor & Mocks)  |
         +-----------------------------+                           +-----------------------------+
```

---

## 2. Decision Authority & Safety Boundaries

The hierarchy of authority remains unchanged:

$$\text{ML Probability Models} \longrightarrow \text{RecoveryDecisionEngine} \longrightarrow \text{Recovery Operations} \longrightarrow \text{Action Providers}$$

### The LLM MUST NOT:
1. Calculate recovery probabilities or expected recovery values.
2. Choose, rank, or substitute recovery actions independently.
3. Override safety guardrails (e.g., retry limits, micro-ticket protection).
4. Perform financial calculations or floating-point arithmetic.
5. Directly access SQLite internals, file systems, or network endpoints.
6. Access unobservable latent simulator variables or ground truth.

---

## 3. Approved Tool Registry & Hard Semantic Validation

The agent interacts **strictly** through approved tools managed by `ToolCallValidator` (`agent/llm/validator.py`):

| Tool Name | Input Parameters | Output Response | Semantic Validation & Safety Rules |
| :--- | :--- | :--- | :--- |
| `get_payment_case` | `case_id` | Observable payment attributes | Excludes latent simulator variables (`latent_intent`, `latent_funds`). |
| `get_recovery_decision` | `case_id` | `decision_id`, `recommended_action`, `expected_net_paise`, `margin` | Authoritative ML decision request. |
| `execute_recovery_action` | `decision_id`, `action`, `idempotency_key` | `action_id`, `status`, `cost_paise`, `provider_ref` | **Action Match Verification**: Rejects any action differing from `context.recommended_action` with `POLICY_VIOLATION`. Prevents duplicate executions. |
| `get_action_status` | `action_id` | `status`, `cost_paise`, `executed_at` | Read-only status inspection. |
| `record_recovery_outcome` | `case_id`, `action_id`, `outcome_status`, `recovered_paise` | `event_id`, `outcome_status`, `event_timestamp` | Requires prior `ACTION_EXECUTED` state. |
| `get_recovery_summary` | None | Aggregate counts, rates, integer-paise ledgers | Read-only descriptive summary. |

---

## 4. Failure Taxonomy

RecoverAI categorizes agent errors into explicit, auditable failure classifications (`agent/models.py` / `FailureCategory`):

1. **`MODEL_ERROR`**: LLM provider communication failure, request timeout, or unparseable malformed model output.
2. **`INVALID_TOOL_CALL`**: Tool name not present in approved registry or arguments violating JSON schema.
3. **`POLICY_VIOLATION`**: Attempted action substitution, lifecycle state transition violation, or attempt to bypass authoritative decision recommendations.
4. **`EXECUTION_FAILURE`**: Technical provider/gateway execution failure during action dispatch (cost = 0; same action may be retried).
5. **`WORKFLOW_FAILURE`**: Agent terminated prematurely without executing an action, or exceeded `max_steps` loop limit without reaching a terminal state.

---

## 5. Trusted vs. Untrusted Data & Prompt Injection Defense

All payment, customer, and merchant metadata is treated strictly as **UNTRUSTED DATA**:

```text
<untrusted_incident_data>
Case ID: case_llm_001
Customer ID: cust_001 (Contains potential malicious text)
Amount (Paise): 800000
Failure Type: temporary_failure
</untrusted_incident_data>
```

- **Defense Principle**: System and Developer instructions explicitly instruct the model that instructions embedded within `<untrusted_incident_data>` must be ignored.
- **Structural Guardrail**: Even if an LLM is deceived by prompt injection, `ToolCallValidator` and `ExecuteRecoveryActionTool` reject unauthorized actions below the prompt layer before any provider call can occur.

---

## 6. Provider Abstraction & Offline Determinism

RecoverAI includes a pluggable provider interface (`agent/llm/base.py` / `LLMProvider`):

- **`MockLLMProvider`**: Default provider for unit tests, CI/CD, and offline development. Generates deterministic tool calls without requiring external API keys. Supports simulated timeouts, errors, and custom scripted sequences.
- **`OpenAILLMProvider`**: Client for OpenAI and Azure OpenAI structured tool calling (`gpt-4o`, `gpt-4o-mini`).
- **`AnthropicLLMProvider`**: Client for Anthropic Claude (`claude-3-5-sonnet`).
- **`GeminiLLMProvider`**: Client for Google Gemini (`gemini-2.0-flash`).

---

## 7. Telemetry, Trace, & Auditability

All agent steps record structured telemetry in SQLite (`agent_runs` and `agent_steps`):
- `driver_type`: `"deterministic"` or `"llm"`
- `llm_provider`: Provider name (e.g. `"MockLLMProvider"`, `"OpenAILLMProvider"`)
- `llm_model`: Model identifier (e.g. `"mock-recovery-v1"`, `"gpt-4o-mini"`)
- `prompt_version`: Versioned prompt identifier (e.g. `"v1.0"`)
- `total_tokens`: Cumulative token count
- `llm_latency_ms`: Cumulative LLM latency in milliseconds
- `failure_category`: Explicit failure classification if step failed

> **Security Rule**: Raw system prompts and raw chain-of-thought are **never** persisted or exposed to merchant API consumers.

---

## 8. Representative Auditable Trace

```text
Agent Run [run_d3ac95dbc8f5] (Driver: llm, Tokens: 575, Latency: 10.00ms)
├── CASE_RETRIEVED [success]
│   └── case_id = case_smoke_llm_001
│   └── amount_paise = 650000
├── DECISION_OBTAINED (tool=get_recovery_decision) (tokens=210+35) [success]
│   └── decision_id = dec_02ec6e1ac083
│   └── recommended_action = retry
│   └── recovery_probability = 0.7079
│   └── expected_gross_recovery_paise = 460143
│   └── action_cost_paise = 200
│   └── expected_net_recovery_paise = 459943
└── ACTION_EXECUTED (tool=execute_recovery_action) (tokens=280+50) [success]
    └── action_id = act_4f0105688a19
    └── action = retry
    └── status = EXECUTED
    └── cost_paise = 200
    └── provider_reference = gw_retry_d2e1c94b7a12
```
