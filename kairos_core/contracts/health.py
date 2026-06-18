"""Health signal for a single LLM call.

Emitted by every layer that owns an ``LLMGateway`` so the Risk Manager's
per-model circuit breakers can react to 5xx / timeouts automatically — closing
the loop between an unstable model API and the system's degraded modes
(``TEXT_LOCAL_FILTER`` / ``CONFLICT_SAFE`` / ``LOCAL_QUANT_MODE``).
"""
from __future__ import annotations

from .base import KairosMessage


class LLMHealthEvent(KairosMessage):
    provider: str               # "deepseek" | "openai"
    model: str                  # e.g. "deepseek-v4-flash", "deepseek-v4-pro", "gpt-5.5"
    ok: bool                    # True on success; False on a failed call
    kind: str = "ok"            # "ok" | "5xx" | "timeout" | "error"
    latency_s: float = 0.0
    detail: str = ""

    @property
    def is_outage(self) -> bool:
        """Whether this signal should trip a per-model breaker.

        Only API-level instability counts (5xx / timeout); a bad-output or 4xx
        means the API answered, so it must not detach the model.
        """
        return (not self.ok) and self.kind in ("5xx", "timeout")
