"""
FastAPI Application Entry Point for RecoverAI Revenue Recovery API.
Provides request correlation, centralized exception handling, and operational routing.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.config import settings
from api.middleware.correlation import RequestCorrelationMiddleware
from api.routes import (
    health,
    model_info,
    decisions,
    actions,
    outcomes,
    summary,
    analytics,
    observability,
    agent,
    webhooks,
    provider_sync,
    subscriptions,
    dashboard,
)
from api.services.recovery_service import recovery_service
from api.services.operations_service import (
    IdempotencyConflictError,
    DecisionNotFoundError,
    ActionMismatchError,
    ActionDisqualifiedError,
    ActionNotFoundError,
    InvalidOutcomeAmountError,
    CaseReferenceMismatchError,
    DuplicateOutcomeError,
)
from recovery.state_machine import InvalidStateTransitionError

logger = logging.getLogger("recoverai.api")


def _get_request_id(request: Request) -> Optional[str]:
    """Helper to extract correlation request ID from request state or header."""
    if hasattr(request.state, "request_id"):
        return request.state.request_id
    return request.headers.get("X-Request-ID")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager: validates startup config and loads champion model.
    """
    settings.validate_startup()
    model_path = Path(settings.model_path)
    logger.info(f"Initializing RecoverAI API in [{settings.env}] mode. Loading model from: {model_path}")

    loaded = recovery_service.load_model(model_path)
    if loaded:
        logger.info("[+] Champion model successfully loaded and ready for inference.")
    else:
        logger.warning(
            f"[-] Champion model not found or failed to load from: {model_path}. "
            "API will operate in degraded mode until model artifact is supplied."
        )

    yield


def create_app() -> FastAPI:
    """
    Creates and configures the FastAPI application instance.
    """
    app = FastAPI(
        title="RecoverAI — Autonomous AI Revenue Recovery API",
        description=(
            "Production-grade merchant decision API for AI Revenue Recovery. "
            "Evaluates observable payment context, predicts action-conditional recovery probabilities, "
            "and optimizes expected net recovered revenue in exact integer paise subject to hard safety guardrails."
        ),
        version=settings.app_version,
        lifespan=lifespan,
    )

    # Middleware: Request correlation & structured access logging
    app.add_middleware(RequestCorrelationMiddleware)

    # Middleware: CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Centralized Global Exception Handlers ---

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        req_id = _get_request_id(request)
        logger.warning(f"Validation error on {request.method} {request.url.path} (request_id={req_id}): {exc.errors()}")
        return JSONResponse(
            status_code=422,
            content={
                "detail": exc.errors(),
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed. Verify request body against schema.",
                    "request_id": req_id,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={"X-Request-ID": req_id} if req_id else None,
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        req_id = _get_request_id(request)
        error_code = f"HTTP_{exc.status_code}"
        if exc.status_code == 404:
            error_code = "NOT_FOUND"
        elif exc.status_code == 400:
            error_code = "BAD_REQUEST"
        elif exc.status_code == 409:
            error_code = "CONFLICT"
        elif exc.status_code == 422:
            error_code = "UNPROCESSABLE_ENTITY"
        elif exc.status_code == 503:
            error_code = "SERVICE_UNAVAILABLE"

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
                "error": {
                    "code": error_code,
                    "message": str(exc.detail),
                    "request_id": req_id,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={"X-Request-ID": req_id} if req_id else None,
        )

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict_handler(request: Request, exc: IdempotencyConflictError):
        req_id = _get_request_id(request)
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(exc),
                "error": {
                    "code": "IDEMPOTENCY_CONFLICT",
                    "message": str(exc),
                    "request_id": req_id,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={"X-Request-ID": req_id} if req_id else None,
        )

    @app.exception_handler(InvalidStateTransitionError)
    async def invalid_state_transition_handler(request: Request, exc: InvalidStateTransitionError):
        req_id = _get_request_id(request)
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(exc),
                "error": {
                    "code": "INVALID_STATE_TRANSITION",
                    "message": str(exc),
                    "request_id": req_id,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={"X-Request-ID": req_id} if req_id else None,
        )

    @app.exception_handler(DuplicateOutcomeError)
    async def duplicate_outcome_handler(request: Request, exc: DuplicateOutcomeError):
        req_id = _get_request_id(request)
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(exc),
                "error": {
                    "code": "DUPLICATE_OUTCOME",
                    "message": str(exc),
                    "request_id": req_id,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={"X-Request-ID": req_id} if req_id else None,
        )

    @app.exception_handler(DecisionNotFoundError)
    async def decision_not_found_handler(request: Request, exc: DecisionNotFoundError):
        req_id = _get_request_id(request)
        return JSONResponse(
            status_code=404,
            content={
                "detail": str(exc),
                "error": {
                    "code": "DECISION_NOT_FOUND",
                    "message": str(exc),
                    "request_id": req_id,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={"X-Request-ID": req_id} if req_id else None,
        )

    @app.exception_handler(ActionNotFoundError)
    async def action_not_found_handler(request: Request, exc: ActionNotFoundError):
        req_id = _get_request_id(request)
        return JSONResponse(
            status_code=404,
            content={
                "detail": str(exc),
                "error": {
                    "code": "ACTION_NOT_FOUND",
                    "message": str(exc),
                    "request_id": req_id,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={"X-Request-ID": req_id} if req_id else None,
        )

    @app.exception_handler(ActionMismatchError)
    async def action_mismatch_handler(request: Request, exc: ActionMismatchError):
        req_id = _get_request_id(request)
        return JSONResponse(
            status_code=400,
            content={
                "detail": str(exc),
                "error": {
                    "code": "ACTION_MISMATCH",
                    "message": str(exc),
                    "request_id": req_id,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={"X-Request-ID": req_id} if req_id else None,
        )

    @app.exception_handler(ActionDisqualifiedError)
    async def action_disqualified_handler(request: Request, exc: ActionDisqualifiedError):
        req_id = _get_request_id(request)
        return JSONResponse(
            status_code=400,
            content={
                "detail": str(exc),
                "error": {
                    "code": "ACTION_DISQUALIFIED",
                    "message": str(exc),
                    "request_id": req_id,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={"X-Request-ID": req_id} if req_id else None,
        )

    @app.exception_handler(InvalidOutcomeAmountError)
    async def invalid_outcome_amount_handler(request: Request, exc: InvalidOutcomeAmountError):
        req_id = _get_request_id(request)
        return JSONResponse(
            status_code=400,
            content={
                "detail": str(exc),
                "error": {
                    "code": "INVALID_OUTCOME_AMOUNT",
                    "message": str(exc),
                    "request_id": req_id,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={"X-Request-ID": req_id} if req_id else None,
        )

    @app.exception_handler(CaseReferenceMismatchError)
    async def case_reference_mismatch_handler(request: Request, exc: CaseReferenceMismatchError):
        req_id = _get_request_id(request)
        return JSONResponse(
            status_code=400,
            content={
                "detail": str(exc),
                "error": {
                    "code": "CASE_REFERENCE_MISMATCH",
                    "message": str(exc),
                    "request_id": req_id,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={"X-Request-ID": req_id} if req_id else None,
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        req_id = _get_request_id(request)
        logger.error(f"Unhandled server error on {request.method} {request.url.path} (request_id={req_id}): {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal Server Error",
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected error occurred. Please contact support with the request ID.",
                    "request_id": req_id,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={"X-Request-ID": req_id} if req_id else None,
        )

    # --- Mount API v1 routes ---
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(model_info.router, prefix="/api/v1")
    app.include_router(decisions.router, prefix="/api/v1")
    app.include_router(actions.router, prefix="/api/v1")
    app.include_router(outcomes.router, prefix="/api/v1")
    app.include_router(summary.router, prefix="/api/v1")
    app.include_router(analytics.router, prefix="/api/v1")
    app.include_router(observability.router, prefix="/api/v1")
    app.include_router(agent.router, prefix="/api/v1")
    app.include_router(webhooks.router, prefix="/api/v1")
    app.include_router(provider_sync.router, prefix="/api/v1")
    app.include_router(subscriptions.router, prefix="/api/v1")
    app.include_router(dashboard.router, prefix="/api/v1")

    # Top-level health and ready convenience aliases
    app.include_router(health.router, prefix="")
    app.include_router(observability.router, prefix="")

    # Root redirect to Command Center dashboard
    @app.get("/", include_in_schema=False)
    async def root_redirect():
        return RedirectResponse(url="/dashboard", status_code=307)

    # Static assets for Merchant Recovery Command Center UI
    static_dir = Path("static")
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/dashboard", StaticFiles(directory=str(static_dir), html=True), name="dashboard_static")

    return app


app = create_app()
