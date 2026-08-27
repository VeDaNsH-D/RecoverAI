"""
API configuration and settings for RecoverAI backend.
"""

import os
from pathlib import Path
from pydantic import BaseModel, Field


class Settings(BaseModel):
    """Application configuration loaded from environment variables."""
    app_name: str = "RecoverAI Revenue Recovery API"
    app_version: str = "0.1.0"
    env: str = Field(default_factory=lambda: os.getenv("RECOVERAI_ENV", "production"))
    host: str = Field(default_factory=lambda: os.getenv("RECOVERAI_HOST", "0.0.0.0"))
    port: int = Field(default_factory=lambda: int(os.getenv("RECOVERAI_PORT", "8000")))
    log_level: str = Field(default_factory=lambda: os.getenv("RECOVERAI_LOG_LEVEL", "INFO"))
    model_path: Path = Field(
        default_factory=lambda: Path(os.getenv("RECOVERAI_MODEL_PATH", "models/champion_recovery_model.pkl"))
    )


settings = Settings()
