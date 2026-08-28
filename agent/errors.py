"""
Domain error classes for RecoverAI Agent Orchestration.
"""


class AgentError(Exception):
    """Base exception for all agent errors."""
    pass


class AgentExecutionError(AgentError):
    """Raised when an agent workflow execution encounters a fatal error."""
    pass


class ToolExecutionError(AgentError):
    """Raised when a specific recovery tool execution fails."""
    pass


class ActionMismatchError(AgentError):
    """Raised when an action execution tool is called with an action that does not match the decision recommendation."""
    pass


class InvalidAgentStateError(AgentError):
    """Raised when an agent operation is attempted in an invalid state."""
    pass


class AgentIdempotencyConflictError(AgentError):
    """Raised when an idempotency key is reused with a different case or payload."""
    pass
