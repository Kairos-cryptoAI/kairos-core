"""Envelope base class for every message that travels on the bus."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"


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
    produced_at: datetime = Field(default_factory=utcnow)
    source: str = Field(..., description="Service that produced this message, e.g. 'quant-scouts'.")

    def to_json(self) -> str:
        return self.model_dump_json()

    def to_payload(self) -> dict:
        """JSON-safe dict suitable for bus transport."""
        return self.model_dump(mode="json")

    @classmethod
    def from_json(cls, raw: str | bytes):
        return cls.model_validate_json(raw)
