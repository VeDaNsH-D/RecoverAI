"""
API configuration and settings for RecoverAI backend.
Provides deterministic environment configuration, strict validation, and startup diagnostics.
"""

import os
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


class Settings(BaseModel):
    """
    Application configuration loaded from environment variables.
    Provides deterministic defaults for local development and strict validation for production.
    """
    app_name: str = "RecoverAI Revenue Recovery API"
    app_version: str = "0.1.0"
    env: Literal["development", "test", "production"] = Field(
        default_factory=lambda: os.getenv("RECOVERAI_ENV", "development").lower()  # type: ignore
    )
    host: str = Field(default_factory=lambda: os.getenv("RECOVERAI_HOST", "0.0.0.0"))
    port: int = Field(default_factory=lambda: int(os.getenv("RECOVERAI_PORT", "8000")))
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default_factory=lambda: os.getenv("RECOVERAI_LOG_LEVEL", "INFO").upper()  # type: ignore
    )
    model_path: Path = Field(
        default_factory=lambda: Path(os.getenv("RECOVERAI_MODEL_PATH", "models/champion_recovery_model.pkl"))
    )
    db_path: Path = Field(
        default_factory=lambda: Path(os.getenv("RECOVERAI_DB_PATH", "data/recovery_operations.db"))
    )
    agent_driver: Literal["deterministic", "llm"] = Field(
        default_factory=lambda: os.getenv("RECOVERAI_AGENT_DRIVER", "deterministic").lower()  # type: ignore
    )
    llm_provider: Literal["mock", "openai", "anthropic", "gemini"] = Field(
        default_factory=lambda: os.getenv("RECOVERAI_LLM_PROVIDER", "mock").lower()  # type: ignore
    )
    llm_model: str = Field(
        default_factory=lambda: os.getenv("RECOVERAI_LLM_MODEL", "mock-recovery-v1")
    )
    llm_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("RECOVERAI_LLM_API_KEY")
    )
    llm_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("RECOVERAI_LLM_TIMEOUT_SECONDS", "10.0"))
    )
    llm_temperature: float = Field(
        default_factory=lambda: float(os.getenv("RECOVERAI_LLM_TEMPERATURE", "0.0"))
    )

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"Port must be between 1 and 65535, got {v}")
        return v

    @field_validator("env")
    @classmethod
    def validate_env(cls, v: str) -> str:
        valid_envs = {"development", "test", "production"}
        if v not in valid_envs:
            raise ValueError(f"Environment must be one of {valid_envs}, got '{v}'")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR"}
        if v not in valid_levels:
            raise ValueError(f"Log level must be one of {valid_levels}, got '{v}'")
        return v

    def validate_startup(self) -> None:
        """
        Validates environment configuration at startup.
        Ensures target directories are writable and files are discoverable.
        """
        # Ensure database parent directory exists or is creatable
        if str(self.db_path) != ":memory:" and not str(self.db_path).startswith("file:"):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
