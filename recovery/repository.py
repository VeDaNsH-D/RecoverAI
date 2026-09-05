"""
SQLite persistence repository for RecoverAI Recovery Operations.
Provides atomic, thread-safe database interactions for cases, decisions, actions, and outcomes.
"""

import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional
import uuid

from simulator.config import RecoveryAction
from recovery.models import (
    CaseState,
    ActionExecutionStatus,
    OutcomeStatus,
    DecisionRecord,
    ActionRecord,
    OutcomeRecord,
    RecoveryCaseRecord,
)
from recovery.subscriptions.models import (
    SubscriptionRecord,
    RazorpaySubscriptionStatus,
    RecoverySource,
    RecoveryResolutionSource,
)


class IdempotencyConflictError(Exception):
    """Raised when an idempotency key is reused with a different request payload."""
    pass


class RecoveryRepository:
    """
    Thread-safe SQLite repository managing recovery lifecycle persistence.
    """

    def __init__(self, db_path: str = "data/recovery_operations.db"):
        self.db_path = str(db_path)
        self.is_memory = self.db_path == ":memory:" or "mode=memory" in self.db_path
        if self.is_memory:
            if self.db_path == ":memory:":
                self._connect_path = f"file:recoverai_mem_{uuid.uuid4().hex}?mode=memory&cache=shared"
            else:
                self._connect_path = self.db_path
            self._uri = True
        else:
            self._connect_path = self.db_path
            self._uri = False
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Returns a thread-local SQLite connection with WAL mode and foreign keys enabled."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._connect_path, uri=self._uri, timeout=30.0, check_same_thread=False)
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA busy_timeout = 5000;")
            if not self.is_memory:
                conn.execute("PRAGMA journal_mode = WAL;")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
            self._create_tables(conn)
        return self._local.conn

    def is_ready(self) -> bool:
        """Verifies database connectivity and responsiveness."""
        try:
            conn = self._get_connection()
            cur = conn.execute("SELECT 1;")
            row = cur.fetchone()
            return row is not None and row[0] == 1
        except Exception:
            return False

    def close(self) -> None:
        """Closes thread-local connection."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            try:
                self._local.conn.close()
            except Exception:
                pass
            self._local.conn = None

    def _init_db(self) -> None:
        """Initializes tables and unique indexes."""
        conn = self._get_connection()
        self._create_tables(conn)

    def _create_tables(self, conn: sqlite3.Connection) -> None:
        """Creates tables and indexes idempotently, ensuring schema migration for legacy DB files."""
        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    amount_paise INTEGER NOT NULL,
                    current_state TEXT NOT NULL,
                    decision_id TEXT NOT NULL,
                    recommended_action TEXT NOT NULL,
                    payment_method TEXT DEFAULT 'upi',
                    is_subscription INTEGER DEFAULT 0,
                    failure_type TEXT DEFAULT 'temporary_failure',
                    retry_count INTEGER DEFAULT 0,
                    subscription_id TEXT,
                    billing_cycle_id TEXT,
                    recovery_source TEXT DEFAULT 'one_off',
                    resolution_source TEXT,
                    last_action_id TEXT,
                    last_action_status TEXT,
                    outcome_status TEXT,
                    recovered_amount_paise INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS subscriptions (
                    subscription_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    plan_id TEXT,
                    status TEXT NOT NULL,
                    current_cycle INTEGER DEFAULT 1,
                    total_cycles INTEGER,
                    amount_due_paise INTEGER DEFAULT 0,
                    currency TEXT DEFAULT 'INR',
                    charge_attempt_count INTEGER DEFAULT 0,
                    next_charge_at TEXT,
                    last_case_id TEXT,
                    source TEXT DEFAULT 'razorpay_test',
                    is_recoverable INTEGER DEFAULT 1,
                    metadata_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

            # Ensure columns exist if table was created in an earlier session
            cur = conn.execute("PRAGMA table_info(cases);")
            existing_cols = {row["name"] for row in cur.fetchall()}
            if "payment_method" not in existing_cols:
                conn.execute("ALTER TABLE cases ADD COLUMN payment_method TEXT DEFAULT 'upi';")
            if "is_subscription" not in existing_cols:
                conn.execute("ALTER TABLE cases ADD COLUMN is_subscription INTEGER DEFAULT 0;")
            if "failure_type" not in existing_cols:
                conn.execute("ALTER TABLE cases ADD COLUMN failure_type TEXT DEFAULT 'temporary_failure';")
            if "retry_count" not in existing_cols:
                conn.execute("ALTER TABLE cases ADD COLUMN retry_count INTEGER DEFAULT 0;")
            if "subscription_id" not in existing_cols:
                conn.execute("ALTER TABLE cases ADD COLUMN subscription_id TEXT;")
            if "billing_cycle_id" not in existing_cols:
                conn.execute("ALTER TABLE cases ADD COLUMN billing_cycle_id TEXT;")
            if "recovery_source" not in existing_cols:
                conn.execute("ALTER TABLE cases ADD COLUMN recovery_source TEXT DEFAULT 'one_off';")
            if "resolution_source" not in existing_cols:
                conn.execute("ALTER TABLE cases ADD COLUMN resolution_source TEXT;")

            conn.executescript("""
                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    amount_paise INTEGER NOT NULL,
                    recommended_action TEXT NOT NULL,
                    recommended_action_recovery_probability REAL NOT NULL,
                    expected_gross_recovery_paise INTEGER NOT NULL,
                    action_cost_paise INTEGER NOT NULL,
                    expected_net_recovery_paise INTEGER NOT NULL,
                    decision_margin_paise INTEGER NOT NULL,
                    explanation TEXT NOT NULL,
                    model_family TEXT NOT NULL,
                    feature_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (case_id) REFERENCES cases(case_id)
                );

                CREATE TABLE IF NOT EXISTS actions (
                    action_id TEXT PRIMARY KEY,
                    decision_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    cost_paise INTEGER NOT NULL,
                    provider_reference TEXT NOT NULL,
                    error_message TEXT,
                    executed_at TEXT NOT NULL,
                    FOREIGN KEY (decision_id) REFERENCES decisions(decision_id),
                    FOREIGN KEY (case_id) REFERENCES cases(case_id)
                );

                CREATE TABLE IF NOT EXISTS outcomes (
                    event_id TEXT PRIMARY KEY,
                    action_id TEXT UNIQUE NOT NULL,
                    case_id TEXT NOT NULL,
                    decision_id TEXT NOT NULL,
                    outcome_status TEXT NOT NULL,
                    recovered_amount_paise INTEGER NOT NULL,
                    provider_reference TEXT,
                    metadata_json TEXT,
                    event_timestamp TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (action_id) REFERENCES actions(action_id),
                    FOREIGN KEY (decision_id) REFERENCES decisions(decision_id),
                    FOREIGN KEY (case_id) REFERENCES cases(case_id)
                );

                CREATE TABLE IF NOT EXISTS agent_runs (
                    agent_run_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    decision_id TEXT,
                    idempotency_key TEXT UNIQUE,
                    status TEXT NOT NULL,
                    recommended_action TEXT,
                    final_action TEXT,
                    final_operational_state TEXT,
                    driver_type TEXT DEFAULT 'deterministic',
                    failure_category TEXT,
                    error_message TEXT,
                    llm_provider TEXT,
                    llm_model TEXT,
                    prompt_version TEXT,
                    total_tokens INTEGER DEFAULT 0,
                    llm_latency_ms REAL DEFAULT 0.0,
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS agent_steps (
                    step_id TEXT PRIMARY KEY,
                    agent_run_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    step_type TEXT NOT NULL,
                    tool_name TEXT,
                    input_summary_json TEXT,
                    output_summary_json TEXT,
                    status TEXT NOT NULL,
                    failure_category TEXT,
                    error_message TEXT,
                    llm_prompt_tokens INTEGER,
                    llm_completion_tokens INTEGER,
                    llm_latency_ms REAL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY (agent_run_id) REFERENCES agent_runs(agent_run_id)
                );

                CREATE TABLE IF NOT EXISTS webhook_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    provider_reference TEXT,
                    case_id TEXT,
                    action_id TEXT,
                    processing_status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    processed_at TEXT NOT NULL
                );

                -- Indexes for fast analytics aggregations
                CREATE INDEX IF NOT EXISTS idx_cases_failure_type ON cases(failure_type);
                CREATE INDEX IF NOT EXISTS idx_cases_is_sub ON cases(is_subscription);
                CREATE INDEX IF NOT EXISTS idx_cases_retry_count ON cases(retry_count);
                CREATE INDEX IF NOT EXISTS idx_cases_created_at ON cases(created_at);
                CREATE INDEX IF NOT EXISTS idx_cases_state ON cases(current_state);
                CREATE INDEX IF NOT EXISTS idx_actions_action ON actions(action);
                CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status);
                CREATE INDEX IF NOT EXISTS idx_actions_executed_at ON actions(executed_at);
                CREATE INDEX IF NOT EXISTS idx_actions_provider_ref ON actions(provider_reference);
                CREATE INDEX IF NOT EXISTS idx_outcomes_status ON outcomes(outcome_status);
                CREATE INDEX IF NOT EXISTS idx_outcomes_timestamp ON outcomes(event_timestamp);
                CREATE INDEX IF NOT EXISTS idx_agent_runs_case ON agent_runs(case_id);
                CREATE INDEX IF NOT EXISTS idx_agent_runs_idemp ON agent_runs(idempotency_key);
                CREATE INDEX IF NOT EXISTS idx_agent_steps_run ON agent_steps(agent_run_id);
                CREATE INDEX IF NOT EXISTS idx_webhook_events_ref ON webhook_events(provider_reference);
                CREATE INDEX IF NOT EXISTS idx_cases_sub_id ON cases(subscription_id);
                CREATE INDEX IF NOT EXISTS idx_cases_cycle_id ON cases(billing_cycle_id);
                CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);
                CREATE INDEX IF NOT EXISTS idx_subscriptions_customer ON subscriptions(customer_id);
            """)

            # Ensure outcomes columns exist if table was created in an earlier session
            cur_out = conn.execute("PRAGMA table_info(outcomes);")
            existing_out_cols = {row["name"] for row in cur_out.fetchall()}
            if "resolution_source" not in existing_out_cols:
                conn.execute("ALTER TABLE outcomes ADD COLUMN resolution_source TEXT;")

            # Ensure agent_runs columns exist if table was created in an earlier session
            cur_runs = conn.execute("PRAGMA table_info(agent_runs);")
            existing_run_cols = {row["name"] for row in cur_runs.fetchall()}
            if "driver_type" not in existing_run_cols:
                conn.execute("ALTER TABLE agent_runs ADD COLUMN driver_type TEXT DEFAULT 'deterministic';")
            if "failure_category" not in existing_run_cols:
                conn.execute("ALTER TABLE agent_runs ADD COLUMN failure_category TEXT;")
            if "llm_provider" not in existing_run_cols:
                conn.execute("ALTER TABLE agent_runs ADD COLUMN llm_provider TEXT;")
            if "llm_model" not in existing_run_cols:
                conn.execute("ALTER TABLE agent_runs ADD COLUMN llm_model TEXT;")
            if "prompt_version" not in existing_run_cols:
                conn.execute("ALTER TABLE agent_runs ADD COLUMN prompt_version TEXT;")
            if "total_tokens" not in existing_run_cols:
                conn.execute("ALTER TABLE agent_runs ADD COLUMN total_tokens INTEGER DEFAULT 0;")
            if "llm_latency_ms" not in existing_run_cols:
                conn.execute("ALTER TABLE agent_runs ADD COLUMN llm_latency_ms REAL DEFAULT 0.0;")

            # Ensure agent_steps columns exist if table was created in an earlier session
            cur_steps = conn.execute("PRAGMA table_info(agent_steps);")
            existing_step_cols = {row["name"] for row in cur_steps.fetchall()}
            if "failure_category" not in existing_step_cols:
                conn.execute("ALTER TABLE agent_steps ADD COLUMN failure_category TEXT;")
            if "llm_prompt_tokens" not in existing_step_cols:
                conn.execute("ALTER TABLE agent_steps ADD COLUMN llm_prompt_tokens INTEGER;")
            if "llm_completion_tokens" not in existing_step_cols:
                conn.execute("ALTER TABLE agent_steps ADD COLUMN llm_completion_tokens INTEGER;")
            if "llm_latency_ms" not in existing_step_cols:
                conn.execute("ALTER TABLE agent_steps ADD COLUMN llm_latency_ms REAL;")

    def save_decision(
        self,
        decision: DecisionRecord,
        payment_method: str = "upi",
        is_subscription: bool = False,
        failure_type: str = "temporary_failure",
        retry_count: int = 0,
        subscription_id: Optional[str] = None,
        billing_cycle_id: Optional[str] = None,
        recovery_source: Optional[str] = "one_off",
    ) -> None:
        """
        Atomically persists a decision record and initializes/updates the case in DECIDED state.
        """
        conn = self._get_connection()
        with conn:
            # Insert or update case record
            conn.execute(
                """
                INSERT INTO cases (
                    case_id, customer_id, amount_paise, current_state,
                    decision_id, recommended_action, payment_method,
                    is_subscription, failure_type, retry_count,
                    subscription_id, billing_cycle_id, recovery_source,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    decision_id=excluded.decision_id,
                    recommended_action=excluded.recommended_action,
                    current_state=excluded.current_state,
                    payment_method=excluded.payment_method,
                    is_subscription=excluded.is_subscription,
                    failure_type=excluded.failure_type,
                    retry_count=excluded.retry_count,
                    subscription_id=COALESCE(excluded.subscription_id, cases.subscription_id),
                    billing_cycle_id=COALESCE(excluded.billing_cycle_id, cases.billing_cycle_id),
                    recovery_source=COALESCE(excluded.recovery_source, cases.recovery_source),
                    updated_at=excluded.updated_at;
                """,
                (
                    decision.case_id,
                    decision.customer_id,
                    decision.amount_paise,
                    CaseState.DECIDED.value,
                    decision.decision_id,
                    decision.recommended_action.value,
                    payment_method,
                    1 if is_subscription else 0,
                    failure_type,
                    retry_count,
                    subscription_id,
                    billing_cycle_id,
                    recovery_source,
                    decision.created_at,
                    decision.created_at,
                ),
            )

            # Insert decision record
            conn.execute(
                """
                INSERT INTO decisions (
                    decision_id, case_id, customer_id, amount_paise,
                    recommended_action, recommended_action_recovery_probability,
                    expected_gross_recovery_paise, action_cost_paise,
                    expected_net_recovery_paise, decision_margin_paise,
                    explanation, model_family, feature_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    decision.decision_id,
                    decision.case_id,
                    decision.customer_id,
                    decision.amount_paise,
                    decision.recommended_action.value,
                    decision.recommended_action_recovery_probability,
                    decision.expected_gross_recovery_paise,
                    decision.action_cost_paise,
                    decision.expected_net_recovery_paise,
                    decision.decision_margin_paise,
                    decision.explanation,
                    decision.model_family,
                    decision.feature_version,
                    decision.created_at,
                ),
            )

    def get_decision(self, decision_id: str) -> Optional[DecisionRecord]:
        """Retrieves a historical decision record by ID."""
        conn = self._get_connection()
        cur = conn.execute("SELECT * FROM decisions WHERE decision_id = ?;", (decision_id,))
        row = cur.fetchone()
        if not row:
            return None

        return DecisionRecord(
            decision_id=row["decision_id"],
            case_id=row["case_id"],
            customer_id=row["customer_id"],
            amount_paise=row["amount_paise"],
            recommended_action=RecoveryAction(row["recommended_action"]),
            recommended_action_recovery_probability=row["recommended_action_recovery_probability"],
            expected_gross_recovery_paise=row["expected_gross_recovery_paise"],
            action_cost_paise=row["action_cost_paise"],
            expected_net_recovery_paise=row["expected_net_recovery_paise"],
            decision_margin_paise=row["decision_margin_paise"],
            explanation=row["explanation"],
            model_family=row["model_family"],
            feature_version=row["feature_version"],
            created_at=row["created_at"],
        )

    def get_case(self, case_id: str) -> Optional[RecoveryCaseRecord]:
        """Retrieves a recovery case record by ID."""
        conn = self._get_connection()
        cur = conn.execute("SELECT * FROM cases WHERE case_id = ?;", (case_id,))
        row = cur.fetchone()
        if not row:
            return None

        return RecoveryCaseRecord(
            case_id=row["case_id"],
            customer_id=row["customer_id"],
            amount_paise=row["amount_paise"],
            current_state=CaseState(row["current_state"]),
            decision_id=row["decision_id"],
            recommended_action=RecoveryAction(row["recommended_action"]),
            payment_method=row["payment_method"] if "payment_method" in row.keys() else None,
            is_subscription=bool(row["is_subscription"]) if "is_subscription" in row.keys() else False,
            failure_type=row["failure_type"] if "failure_type" in row.keys() else None,
            retry_count=row["retry_count"] if "retry_count" in row.keys() else 0,
            subscription_id=row["subscription_id"] if "subscription_id" in row.keys() else None,
            billing_cycle_id=row["billing_cycle_id"] if "billing_cycle_id" in row.keys() else None,
            recovery_source=row["recovery_source"] if "recovery_source" in row.keys() else "one_off",
            resolution_source=row["resolution_source"] if "resolution_source" in row.keys() else None,
            last_action_id=row["last_action_id"],
            last_action_status=ActionExecutionStatus(row["last_action_status"]) if row["last_action_status"] else None,
            outcome_status=OutcomeStatus(row["outcome_status"]) if row["outcome_status"] else None,
            recovered_amount_paise=row["recovered_amount_paise"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_action_by_idempotency_key(self, idempotency_key: str) -> Optional[ActionRecord]:
        """Looks up an existing action execution by its unique idempotency key."""
        conn = self._get_connection()
        cur = conn.execute("SELECT * FROM actions WHERE idempotency_key = ?;", (idempotency_key,))
        row = cur.fetchone()
        if not row:
            return None

        return ActionRecord(
            action_id=row["action_id"],
            decision_id=row["decision_id"],
            case_id=row["case_id"],
            action=RecoveryAction(row["action"]),
            idempotency_key=row["idempotency_key"],
            payload_hash=row["payload_hash"],
            status=ActionExecutionStatus(row["status"]),
            cost_paise=row["cost_paise"],
            provider_reference=row["provider_reference"],
            error_message=row["error_message"],
            executed_at=row["executed_at"],
        )

    def get_action(self, action_id: str) -> Optional[ActionRecord]:
        """Retrieves an action execution record by ID."""
        conn = self._get_connection()
        cur = conn.execute("SELECT * FROM actions WHERE action_id = ?;", (action_id,))
        row = cur.fetchone()
        if not row:
            return None

        return ActionRecord(
            action_id=row["action_id"],
            decision_id=row["decision_id"],
            case_id=row["case_id"],
            action=RecoveryAction(row["action"]),
            idempotency_key=row["idempotency_key"],
            payload_hash=row["payload_hash"],
            status=ActionExecutionStatus(row["status"]),
            cost_paise=row["cost_paise"],
            provider_reference=row["provider_reference"],
            error_message=row["error_message"],
            executed_at=row["executed_at"],
        )

    def get_action_by_decision(self, decision_id: str) -> Optional[ActionRecord]:
        """Retrieves the latest action execution record associated with a decision ID."""
        conn = self._get_connection()
        cur = conn.execute(
            "SELECT * FROM actions WHERE decision_id = ? ORDER BY executed_at DESC LIMIT 1;",
            (decision_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        return ActionRecord(
            action_id=row["action_id"],
            decision_id=row["decision_id"],
            case_id=row["case_id"],
            action=RecoveryAction(row["action"]),
            idempotency_key=row["idempotency_key"],
            payload_hash=row["payload_hash"],
            status=ActionExecutionStatus(row["status"]),
            cost_paise=row["cost_paise"],
            provider_reference=row["provider_reference"],
            error_message=row["error_message"],
            executed_at=row["executed_at"],
        )

    def get_action_by_provider_reference(self, provider_reference: str) -> Optional[ActionRecord]:
        """Retrieves an action execution record by external provider reference (e.g. plink_xxx)."""
        if not provider_reference:
            return None
        conn = self._get_connection()
        cur = conn.execute(
            "SELECT * FROM actions WHERE provider_reference = ? ORDER BY executed_at DESC LIMIT 1;",
            (provider_reference,),
        )
        row = cur.fetchone()
        if not row:
            return None

        return ActionRecord(
            action_id=row["action_id"],
            decision_id=row["decision_id"],
            case_id=row["case_id"],
            action=RecoveryAction(row["action"]),
            idempotency_key=row["idempotency_key"],
            payload_hash=row["payload_hash"],
            status=ActionExecutionStatus(row["status"]),
            cost_paise=row["cost_paise"],
            provider_reference=row["provider_reference"],
            error_message=row["error_message"],
            executed_at=row["executed_at"],
        )

    def is_webhook_event_processed(self, event_id: str) -> bool:
        """Checks if a webhook event has already been durably recorded and successfully processed or definitively ignored."""
        if not event_id:
            return False
        conn = self._get_connection()
        cur = conn.execute(
            "SELECT 1 FROM webhook_events WHERE event_id = ? AND processing_status NOT LIKE 'error%';",
            (event_id,),
        )
        return cur.fetchone() is not None

    def save_webhook_event(
        self,
        event_id: str,
        event_type: str,
        provider_reference: Optional[str],
        case_id: Optional[str],
        action_id: Optional[str],
        processing_status: str,
        payload_json: str,
        processed_at: str,
    ) -> None:
        """Durably logs a received webhook event for idempotency and auditability."""
        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO webhook_events (
                    event_id, event_type, provider_reference, case_id, action_id,
                    processing_status, payload_json, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    event_id,
                    event_type,
                    provider_reference,
                    case_id,
                    action_id,
                    processing_status,
                    payload_json,
                    processed_at,
                ),
            )

    def record_action_execution(
        self,
        action: ActionRecord,
        new_state: CaseState,
    ) -> None:
        """
        Atomically records action execution and transitions case to new_state.
        """
        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO actions (
                    action_id, decision_id, case_id, action, idempotency_key,
                    payload_hash, status, cost_paise, provider_reference,
                    error_message, executed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    action.action_id,
                    action.decision_id,
                    action.case_id,
                    action.action.value,
                    action.idempotency_key,
                    action.payload_hash,
                    action.status.value,
                    action.cost_paise,
                    action.provider_reference,
                    action.error_message,
                    action.executed_at,
                ),
            )

            conn.execute(
                """
                UPDATE cases SET
                    current_state = ?,
                    last_action_id = ?,
                    last_action_status = ?,
                    updated_at = ?
                WHERE case_id = ?;
                """,
                (
                    new_state.value,
                    action.action_id,
                    action.status.value,
                    action.executed_at,
                    action.case_id,
                ),
            )

    def record_outcome(
        self,
        outcome: OutcomeRecord,
        new_state: CaseState,
    ) -> None:
        """
        Atomically records an outcome event and transitions the case to RECOVERED or NOT_RECOVERED.
        """
        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO outcomes (
                    event_id, action_id, case_id, decision_id, outcome_status,
                    recovered_amount_paise, provider_reference, resolution_source,
                    metadata_json, event_timestamp, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    outcome.event_id,
                    outcome.action_id,
                    outcome.case_id,
                    outcome.decision_id,
                    outcome.outcome_status.value,
                    outcome.recovered_amount_paise,
                    outcome.provider_reference,
                    outcome.resolution_source,
                    json.dumps(outcome.metadata),
                    outcome.event_timestamp,
                    outcome.created_at,
                ),
            )

            conn.execute(
                """
                UPDATE cases SET
                    current_state = ?,
                    outcome_status = ?,
                    recovered_amount_paise = ?,
                    resolution_source = COALESCE(?, resolution_source),
                    updated_at = ?
                WHERE case_id = ?;
                """,
                (
                    new_state.value,
                    outcome.outcome_status.value,
                    outcome.recovered_amount_paise,
                    outcome.resolution_source,
                    outcome.created_at,
                    outcome.case_id,
                ),
            )

    def get_outcome_by_action_id(self, action_id: str) -> Optional[OutcomeRecord]:
        """Retrieves outcome record by action ID."""
        conn = self._get_connection()
        cur = conn.execute("SELECT * FROM outcomes WHERE action_id = ?;", (action_id,))
        row = cur.fetchone()
        if not row:
            return None

        return OutcomeRecord(
            event_id=row["event_id"],
            action_id=row["action_id"],
            case_id=row["case_id"],
            decision_id=row["decision_id"],
            outcome_status=OutcomeStatus(row["outcome_status"]),
            recovered_amount_paise=row["recovered_amount_paise"],
            provider_reference=row["provider_reference"],
            resolution_source=row["resolution_source"] if "resolution_source" in row.keys() else None,
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            event_timestamp=row["event_timestamp"],
            created_at=row["created_at"],
        )

    def save_subscription(self, subscription: SubscriptionRecord) -> None:
        """
        Atomically saves or updates a subscription record.
        """
        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, customer_id, plan_id, status,
                    current_cycle, total_cycles, amount_due_paise, currency,
                    charge_attempt_count, next_charge_at, last_case_id,
                    source, is_recoverable, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(subscription_id) DO UPDATE SET
                    status=excluded.status,
                    current_cycle=excluded.current_cycle,
                    total_cycles=COALESCE(excluded.total_cycles, subscriptions.total_cycles),
                    amount_due_paise=excluded.amount_due_paise,
                    charge_attempt_count=excluded.charge_attempt_count,
                    next_charge_at=excluded.next_charge_at,
                    last_case_id=COALESCE(excluded.last_case_id, subscriptions.last_case_id),
                    is_recoverable=excluded.is_recoverable,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at;
                """,
                (
                    subscription.subscription_id,
                    subscription.customer_id,
                    subscription.plan_id,
                    subscription.status.value,
                    subscription.current_cycle,
                    subscription.total_cycles,
                    subscription.amount_due_paise,
                    subscription.currency,
                    subscription.charge_attempt_count,
                    subscription.next_charge_at,
                    subscription.last_case_id,
                    subscription.source,
                    1 if subscription.is_recoverable else 0,
                    json.dumps(subscription.metadata),
                    subscription.created_at,
                    subscription.updated_at,
                ),
            )

    def get_subscription(self, subscription_id: str) -> Optional[SubscriptionRecord]:
        """Retrieves a subscription record by subscription ID."""
        conn = self._get_connection()
        cur = conn.execute("SELECT * FROM subscriptions WHERE subscription_id = ?;", (subscription_id,))
        row = cur.fetchone()
        if not row:
            return None

        raw_status = row["status"]
        try:
            sub_status = RazorpaySubscriptionStatus(raw_status)
        except (ValueError, KeyError):
            sub_status = RazorpaySubscriptionStatus.UNKNOWN

        return SubscriptionRecord(
            subscription_id=row["subscription_id"],
            customer_id=row["customer_id"],
            plan_id=row["plan_id"],
            status=sub_status,
            current_cycle=row["current_cycle"],
            total_cycles=row["total_cycles"],
            amount_due_paise=row["amount_due_paise"],
            currency=row["currency"],
            charge_attempt_count=row["charge_attempt_count"],
            next_charge_at=row["next_charge_at"],
            last_case_id=row["last_case_id"],
            source=row["source"],
            is_recoverable=bool(row["is_recoverable"]),
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_case_by_billing_cycle(self, subscription_id: str, billing_cycle_id: str) -> Optional[RecoveryCaseRecord]:
        """Retrieves a recovery case record by subscription ID and billing cycle ID."""
        conn = self._get_connection()
        cur = conn.execute(
            "SELECT * FROM cases WHERE subscription_id = ? AND billing_cycle_id = ? ORDER BY created_at DESC LIMIT 1;",
            (subscription_id, billing_cycle_id),
        )
        row = cur.fetchone()
        if not row:
            return None

        return RecoveryCaseRecord(
            case_id=row["case_id"],
            customer_id=row["customer_id"],
            amount_paise=row["amount_paise"],
            current_state=CaseState(row["current_state"]),
            decision_id=row["decision_id"],
            recommended_action=RecoveryAction(row["recommended_action"]),
            payment_method=row["payment_method"] if "payment_method" in row.keys() else None,
            is_subscription=bool(row["is_subscription"]) if "is_subscription" in row.keys() else False,
            failure_type=row["failure_type"] if "failure_type" in row.keys() else None,
            retry_count=row["retry_count"] if "retry_count" in row.keys() else 0,
            subscription_id=row["subscription_id"] if "subscription_id" in row.keys() else None,
            billing_cycle_id=row["billing_cycle_id"] if "billing_cycle_id" in row.keys() else None,
            recovery_source=row["recovery_source"] if "recovery_source" in row.keys() else "one_off",
            resolution_source=row["resolution_source"] if "resolution_source" in row.keys() else None,
            last_action_id=row["last_action_id"],
            last_action_status=ActionExecutionStatus(row["last_action_status"]) if row["last_action_status"] else None,
            outcome_status=OutcomeStatus(row["outcome_status"]) if row["outcome_status"] else None,
            recovered_amount_paise=row["recovered_amount_paise"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_subscriptions(
        self,
        status: Optional[str] = None,
        status_filter: Optional[str] = None,
        customer_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[SubscriptionRecord]:
        """Lists subscription records with optional status and customer filters."""
        conn = self._get_connection()
        query = "SELECT * FROM subscriptions WHERE 1=1"
        params: List[Any] = []
        effective_status = status or status_filter
        if effective_status:
            query += " AND status = ?"
            params.append(effective_status.lower())
        if customer_id:
            query += " AND customer_id = ?"
            params.append(customer_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        cur = conn.execute(query, tuple(params))
        rows = cur.fetchall()
        results = []
        for r in rows:
            raw_status = r["status"]
            try:
                sub_status = RazorpaySubscriptionStatus(raw_status)
            except (ValueError, KeyError):
                sub_status = RazorpaySubscriptionStatus.UNKNOWN

            results.append(
                SubscriptionRecord(
                    subscription_id=r["subscription_id"],
                    customer_id=r["customer_id"],
                    plan_id=r["plan_id"],
                    status=sub_status,
                    current_cycle=r["current_cycle"],
                    total_cycles=r["total_cycles"],
                    amount_due_paise=r["amount_due_paise"],
                    currency=r["currency"],
                    charge_attempt_count=r["charge_attempt_count"],
                    next_charge_at=r["next_charge_at"],
                    last_case_id=r["last_case_id"],
                    source=r["source"],
                    is_recoverable=bool(r["is_recoverable"]),
                    metadata=json.loads(r["metadata_json"]) if r["metadata_json"] else {},
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
            )
        return results

    def update_subscription_status(
        self,
        subscription_id: str,
        status: RazorpaySubscriptionStatus,
        amount_due_paise: Optional[int] = None,
        charge_attempt_count: Optional[int] = None,
        last_case_id: Optional[str] = None,
    ) -> None:
        """Updates subscription state and associated attributes."""
        conn = self._get_connection()
        now_ts = datetime.now(timezone.utc).isoformat()
        is_rec = 0 if status in (RazorpaySubscriptionStatus.CANCELLED, RazorpaySubscriptionStatus.COMPLETED) else 1

        with conn:
            conn.execute(
                """
                UPDATE subscriptions SET
                    status = ?,
                    amount_due_paise = COALESCE(?, amount_due_paise),
                    charge_attempt_count = COALESCE(?, charge_attempt_count),
                    last_case_id = COALESCE(?, last_case_id),
                    is_recoverable = ?,
                    updated_at = ?
                WHERE subscription_id = ?;
                """,
                (
                    status.value,
                    amount_due_paise,
                    charge_attempt_count,
                    last_case_id,
                    is_rec,
                    now_ts,
                    subscription_id,
                ),
            )

    def update_case_resolution_source(self, case_id: str, resolution_source: str) -> None:
        """Updates resolution source on a recovery case."""
        conn = self._get_connection()
        now_ts = datetime.now(timezone.utc).isoformat()
        with conn:
            conn.execute(
                "UPDATE cases SET resolution_source = ?, updated_at = ? WHERE case_id = ?;",
                (resolution_source, now_ts, case_id),
            )

    def get_summary_metrics(self) -> Dict[str, Any]:
        """
        Computes observational operational and financial metrics across all persisted cases.
        Uses exact integer paise sums.
        """
        conn = self._get_connection()

        # Operational counts
        cur = conn.execute("SELECT COUNT(*) as total FROM cases;")
        total_cases = cur.fetchone()["total"]

        cur = conn.execute("SELECT COUNT(*) as total FROM decisions;")
        decisions_made = cur.fetchone()["total"]

        cur = conn.execute("SELECT COUNT(*) as total FROM actions WHERE status = 'EXECUTED';")
        actions_executed = cur.fetchone()["total"]

        cur = conn.execute("SELECT COUNT(*) as total FROM actions WHERE status = 'FAILED';")
        execution_failures = cur.fetchone()["total"]

        cur = conn.execute("SELECT COUNT(*) as total FROM outcomes WHERE outcome_status = 'recovered';")
        recovered_cases = cur.fetchone()["total"]

        cur = conn.execute("SELECT COUNT(*) as total FROM outcomes WHERE outcome_status = 'not_recovered';")
        not_recovered_cases = cur.fetchone()["total"]

        total_terminal_outcomes = recovered_cases + not_recovered_cases
        recovery_rate = (recovered_cases / total_terminal_outcomes) if total_terminal_outcomes > 0 else 0.0

        # Financial sums (Integer paise)
        cur = conn.execute("SELECT COALESCE(SUM(recovered_amount_paise), 0) as gross FROM outcomes WHERE outcome_status = 'recovered';")
        gross_recovered_paise = cur.fetchone()["gross"]

        cur = conn.execute("SELECT COALESCE(SUM(cost_paise), 0) as total_cost FROM actions WHERE status = 'EXECUTED';")
        action_cost_paise = cur.fetchone()["total_cost"]

        net_recovered_paise = gross_recovered_paise - action_cost_paise

        # Action distributions
        cur = conn.execute(
            """
            SELECT action, COUNT(*) as cnt
            FROM actions
            WHERE status = 'EXECUTED'
            GROUP BY action;
            """
        )
        action_counts = {row["action"]: row["cnt"] for row in cur.fetchall()}

        # Recovery by action
        cur = conn.execute(
            """
            SELECT a.action,
                   COUNT(o.event_id) as total_outcomes,
                   SUM(CASE WHEN o.outcome_status = 'recovered' THEN 1 ELSE 0 END) as recovered_count,
                   COALESCE(SUM(CASE WHEN o.outcome_status = 'recovered' THEN o.recovered_amount_paise ELSE 0 END), 0) as gross_paise,
                   COALESCE(SUM(a.cost_paise), 0) as cost_paise
            FROM actions a
            LEFT JOIN outcomes o ON a.action_id = o.action_id
            WHERE a.status = 'EXECUTED'
            GROUP BY a.action;
            """
        )
        recovery_by_action = {}
        for row in cur.fetchall():
            act = row["action"]
            g_paise = row["gross_paise"]
            c_paise = row["cost_paise"]
            tot_o = row["total_outcomes"]
            rec_c = row["recovered_count"]
            recovery_by_action[act] = {
                "action": act,
                "executed_count": action_counts.get(act, 0),
                "recovered_count": rec_c,
                "recovery_rate": (rec_c / tot_o) if tot_o > 0 else 0.0,
                "gross_recovered_paise": g_paise,
                "gross_recovered_inr": g_paise / 100.0,
                "action_cost_paise": c_paise,
                "action_cost_inr": c_paise / 100.0,
                "net_recovered_paise": g_paise - c_paise,
                "net_recovered_inr": (g_paise - c_paise) / 100.0,
            }

        # Execution failures by action
        cur = conn.execute(
            """
            SELECT action, COUNT(*) as cnt
            FROM actions
            WHERE status = 'FAILED'
            GROUP BY action;
            """
        )
        failures_by_action = {row["action"]: row["cnt"] for row in cur.fetchall()}

        return {
            "total_cases": total_cases,
            "decisions_made": decisions_made,
            "actions_executed": actions_executed,
            "execution_failures": execution_failures,
            "recovered_cases": recovered_cases,
            "not_recovered_cases": not_recovered_cases,
            "recovery_rate": recovery_rate,
            "gross_recovered_paise": gross_recovered_paise,
            "gross_recovered_inr": gross_recovered_paise / 100.0,
            "action_cost_paise": action_cost_paise,
            "action_cost_inr": action_cost_paise / 100.0,
            "net_recovered_paise": net_recovered_paise,
            "net_recovered_inr": net_recovered_paise / 100.0,
            "action_distribution": action_counts,
            "recovery_by_action": recovery_by_action,
            "execution_failures_by_action": failures_by_action,
        }

    def save_agent_run(self, run_data: Dict[str, Any]) -> None:
        """Atomically saves an initial agent run record."""
        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO agent_runs (
                    agent_run_id, case_id, decision_id, idempotency_key,
                    status, recommended_action, final_action, final_operational_state,
                    driver_type, failure_category, error_message,
                    llm_provider, llm_model, prompt_version, total_tokens, llm_latency_ms,
                    started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    run_data["agent_run_id"],
                    run_data["case_id"],
                    run_data.get("decision_id"),
                    run_data.get("idempotency_key"),
                    run_data["status"],
                    run_data.get("recommended_action"),
                    run_data.get("final_action"),
                    run_data.get("final_operational_state"),
                    run_data.get("driver_type", "deterministic"),
                    run_data.get("failure_category"),
                    run_data.get("error_message"),
                    run_data.get("llm_provider"),
                    run_data.get("llm_model"),
                    run_data.get("prompt_version"),
                    run_data.get("total_tokens", 0),
                    run_data.get("llm_latency_ms", 0.0),
                    run_data["started_at"],
                    run_data.get("completed_at"),
                ),
            )

    def update_agent_run(self, agent_run_id: str, **kwargs) -> None:
        """Updates fields of an existing agent run record."""
        if not kwargs:
            return
        conn = self._get_connection()
        set_clauses = [f"{k} = ?" for k in kwargs.keys()]
        values = list(kwargs.values()) + [agent_run_id]
        with conn:
            conn.execute(
                f"UPDATE agent_runs SET {', '.join(set_clauses)} WHERE agent_run_id = ?;",
                values,
            )

    def get_agent_run(self, agent_run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves an agent run by its ID."""
        conn = self._get_connection()
        cur = conn.execute(
            """
            SELECT * FROM agent_runs WHERE agent_run_id = ?;
            """,
            (agent_run_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return dict(row)

    def get_agent_run_by_idempotency_key(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        """Retrieves an agent run by its unique idempotency key."""
        conn = self._get_connection()
        cur = conn.execute(
            """
            SELECT * FROM agent_runs WHERE idempotency_key = ?;
            """,
            (idempotency_key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return dict(row)

    def save_agent_step(self, step_data: Dict[str, Any]) -> None:
        """Appends an auditable step to an agent run."""
        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO agent_steps (
                    step_id, agent_run_id, step_index, step_type,
                    tool_name, input_summary_json, output_summary_json,
                    status, failure_category, error_message,
                    llm_prompt_tokens, llm_completion_tokens, llm_latency_ms,
                    started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    step_data["step_id"],
                    step_data["agent_run_id"],
                    step_data["step_index"],
                    step_data["step_type"],
                    step_data.get("tool_name"),
                    step_data.get("input_summary_json"),
                    step_data.get("output_summary_json"),
                    step_data["status"],
                    step_data.get("failure_category"),
                    step_data.get("error_message"),
                    step_data.get("llm_prompt_tokens"),
                    step_data.get("llm_completion_tokens"),
                    step_data.get("llm_latency_ms"),
                    step_data["started_at"],
                    step_data.get("completed_at"),
                ),
            )

    def get_agent_steps(self, agent_run_id: str) -> List[Dict[str, Any]]:
        """Retrieves all steps for an agent run in sequential order."""
        conn = self._get_connection()
        cur = conn.execute(
            """
            SELECT * FROM agent_steps WHERE agent_run_id = ? ORDER BY step_index ASC;
            """,
            (agent_run_id,),
        )
        return [dict(row) for row in cur.fetchall()]

    def update_case_resolution_source(self, case_id: str, resolution_source: str) -> None:
        """Updates resolution source on a case record."""
        conn = self._get_connection()
        now_ts = datetime.now(timezone.utc).isoformat()
        with conn:
            conn.execute(
                """
                UPDATE cases
                SET resolution_source = ?, updated_at = ?
                WHERE case_id = ?;
                """,
                (resolution_source, now_ts, case_id),
            )
