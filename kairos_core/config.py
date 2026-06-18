"""Environment-driven settings shared by every service.

Each service subclasses :class:`CoreSettings` to add its own keys. All keys are
read from the environment with the ``KAIROS_`` prefix (and an optional .env).
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class CoreSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KAIROS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "dev"          # dev | staging | prod
    service_name: str = "kairos-service"
    log_level: str = "INFO"
    log_json: bool = True

    # bus
    bus_backend: str = "redis"        # redis | memory
    redis_url: str = "redis://localhost:6379/0"
