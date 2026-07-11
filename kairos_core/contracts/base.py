"""Envelope base class for every message that travels on the bus."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0"
SUPPORTED_SCHEMA_MAJOR = 1


def utcnow() -> datetime:
    """Timezone-aware UTC now (never use naive datetimes on the wire)."""
    return datetime.now(timezone.utc)


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
    causation_id: str | None = Field(
        default=None, description="message_id of the immediate upstream event."
    )
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
