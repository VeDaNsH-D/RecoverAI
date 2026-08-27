"""
FastAPI Application Entry Point for RecoverAI Revenue Recovery API.
"""

from contextlib import asynccontextmanager
import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import settings
from api.routes import health, model_info, decisions, actions, outcomes, summary
from api.services.recovery_service import recovery_service

logger = logging.getLogger("recoverai.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager: loads champion model on startup.
    """
    model_path = Path(settings.model_path)
    logger.info(f"Initializing RecoverAI API. Attempting to load model from: {model_path}")

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

    # Configure CORS for future dashboard integration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API v1 routes
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(model_info.router, prefix="/api/v1")
    app.include_router(decisions.router, prefix="/api/v1")
    app.include_router(actions.router, prefix="/api/v1")
    app.include_router(outcomes.router, prefix="/api/v1")
    app.include_router(summary.router, prefix="/api/v1")

    # Top-level health check convenience alias
    app.include_router(health.router, prefix="")

    return app


app = create_app()
