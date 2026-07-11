"""Environment-driven settings shared by every service.

Each service subclasses :class:`CoreSettings` to add its own keys. All keys are
read from the environment with the ``KAIROS_`` prefix (and an optional .env).
"""
from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_TRADING_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]


def normalize_symbols(symbols: list[str]) -> list[str]:
    """Normalize and de-duplicate a configured trading universe."""
    normalized = list(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))
    if not normalized:
        raise ValueError("trading_symbols cannot be empty")
    if any(not symbol.endswith("USDT") for symbol in normalized):
        raise ValueError("every trading symbol must be a USDT perpetual pair")
    return normalized


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
    trading_symbols: list[str] = DEFAULT_TRADING_SYMBOLS.copy()

    @field_validator("trading_symbols")
    @classmethod
    def validate_trading_symbols(cls, value: list[str]) -> list[str]:
        return normalize_symbols(value)

    def symbol_allowed(self, symbol: str) -> bool:
        return symbol.strip().upper() in self.trading_symbols

    # bus
    bus_backend: str = "redis"        # redis | memory
    redis_url: str = "redis://localhost:6379/0"
