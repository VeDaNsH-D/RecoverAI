"""
SQLite persistence repository for RecoverAI Recovery Operations.
Provides atomic, thread-safe database interactions for cases, decisions, actions, and outcomes.
"""

import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional

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
            self._connect_path = "file:recoverai_shared_mem?mode=memory&cache=shared"
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
                    last_action_id TEXT,
                    last_action_status TEXT,
                    outcome_status TEXT,
                    recovered_amount_paise INTEGER,
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

                -- Indexes for fast analytics aggregations
                CREATE INDEX IF NOT EXISTS idx_cases_failure_type ON cases(failure_type);
                CREATE INDEX IF NOT EXISTS idx_cases_is_sub ON cases(is_subscription);
                CREATE INDEX IF NOT EXISTS idx_cases_retry_count ON cases(retry_count);
                CREATE INDEX IF NOT EXISTS idx_cases_created_at ON cases(created_at);
                CREATE INDEX IF NOT EXISTS idx_cases_state ON cases(current_state);
                CREATE INDEX IF NOT EXISTS idx_actions_action ON actions(action);
                CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status);
                CREATE INDEX IF NOT EXISTS idx_actions_executed_at ON actions(executed_at);
                CREATE INDEX IF NOT EXISTS idx_outcomes_status ON outcomes(outcome_status);
                CREATE INDEX IF NOT EXISTS idx_outcomes_timestamp ON outcomes(event_timestamp);
            """)

    def save_decision(
        self,
        decision: DecisionRecord,
        payment_method: str = "upi",
        is_subscription: bool = False,
        failure_type: str = "temporary_failure",
        retry_count: int = 0,
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
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    decision_id=excluded.decision_id,
                    recommended_action=excluded.recommended_action,
                    current_state=excluded.current_state,
                    payment_method=excluded.payment_method,
                    is_subscription=excluded.is_subscription,
                    failure_type=excluded.failure_type,
                    retry_count=excluded.retry_count,
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
                    recovered_amount_paise, provider_reference, metadata_json,
                    event_timestamp, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    outcome.event_id,
                    outcome.action_id,
                    outcome.case_id,
                    outcome.decision_id,
                    outcome.outcome_status.value,
                    outcome.recovered_amount_paise,
                    outcome.provider_reference,
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
                    updated_at = ?
                WHERE case_id = ?;
                """,
                (
                    new_state.value,
                    outcome.outcome_status.value,
                    outcome.recovered_amount_paise,
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
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            event_timestamp=row["event_timestamp"],
            created_at=row["created_at"],
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
