"""Envelope base class for every message that travels on the bus."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import orjson
from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0"
SUPPORTED_SCHEMA_MAJOR = 1


def utcnow() -> datetime:
    """Timezone-aware UTC now (never use naive datetimes on the wire)."""
    return datetime.now(UTC)


class KairosMessage(BaseModel):
    """Common envelope.

    ``extra="ignore"`` makes consumers tolerant to producers that add new
    fields in a later schema version — combined with ``schema_version`` this
    gives us forward/backward compatibility across independently deployed
    services.
    """

    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        ser_json_timedelta="iso8601",
        validate_assignment=True,
    )

    schema_version: str = Field(default=SCHEMA_VERSION)
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    correlation_id: str | None = Field(
        default=None, description="Stable ID linking all messages in one decision/execution trace."
    )
    causation_id: str | None = Field(default=None, description="message_id of the immediate upstream event.")
    produced_at: datetime = Field(default_factory=utcnow)
    source: str = Field(..., description="Service that produced this message, e.g. 'quant-scouts'.")

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        """Reject malformed or future-major messages; minor additions remain compatible."""
        try:
            major_text, minor_text = value.split(".", maxsplit=1)
            major, minor = int(major_text), int(minor_text)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("schema_version must be '<major>.<minor>'") from exc
        if major < 1 or minor < 0:
            raise ValueError("schema_version components must be non-negative and major >= 1")
        if major > SUPPORTED_SCHEMA_MAJOR:
            raise ValueError(
                f"unsupported schema major {major}; this service supports <= {SUPPORTED_SCHEMA_MAJOR}"
            )
        return value

    def to_json(self) -> str:
        return self.model_dump_json()

    def to_payload(self) -> dict:
        """JSON-safe dict suitable for bus transport."""
        return self.model_dump(mode="json")

    @classmethod
    def from_json(cls, raw: str | bytes):
        return cls.model_validate_json(raw)


class StrictKairosMessage(KairosMessage):
    """Immutable envelope for the strategy-parity and PAPER pipeline.

    Legacy messages deliberately remain forward-compatible with unknown minor
    fields.  Safety-critical PAPER contracts use the opposite rule: every byte
    must be understood by the consumer, so unknown fields are rejected.
    ``contract_version`` versions the concrete payload while the inherited
    ``schema_version`` continues to version the common bus envelope.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        ser_json_timedelta="iso8601",
        allow_inf_nan=False,
    )

    contract_version: str = Field(..., min_length=3, max_length=64)


class StrictValueModel(BaseModel):
    """Immutable, closed-world value object nested in strict messages."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def canonical_json_bytes(value: BaseModel | Mapping[str, Any]) -> bytes:
    """Return deterministic UTF-8 JSON suitable for cross-platform hashing.

    The canonical representation sorts every object key, emits no whitespace,
    and normalises negative zero.  Contract validation rejects non-finite
    numbers before this function is called; the explicit check also makes the
    helper safe for plain mappings used by fixtures and fingerprint tooling.
    """

    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    normalized = _canonical_value(payload)
    return orjson.dumps(normalized, option=orjson.OPT_SORT_KEYS)


def canonical_sha256(value: BaseModel | Mapping[str, Any]) -> str:
    """SHA-256 of :func:`canonical_json_bytes`, encoded as lowercase hex."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _canonical_value(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON cannot contain a non-finite number")
        return 0.0 if value == 0 else value
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


def datetime_from_unix_ms(timestamp_ms: int) -> datetime:
    """Convert an integer Unix millisecond timestamp to timezone-aware UTC."""

    return datetime.fromtimestamp(timestamp_ms / 1_000, tz=UTC)
