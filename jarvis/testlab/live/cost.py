"""Cost and usage of a `live` run: what the provider was actually asked for, and what it costs.

Binding contract: `docs/testlab.md` ("Cost and budget"). Three separate things,
kept separate on purpose:

- **Usage** is measured. It comes from the `voice.realtime.usage` journal lines
  the Realtime session already emits (`input_tokens`, `output_tokens`,
  `duration_seconds`, `source`); nothing here invents a number.
- **Price** is configuration. The repository has no built-in price table and this
  module does not add one: prices change, and a hard-coded table that has gone
  stale is worse than none because it reads as authority. A price comes from
  `jarvis.runtime.pricing` (`TokenPricingMetadata` / `PricingMetadata`, the same
  documents the Control Center's Live pricing setting carries), supplied to the
  run.
- **Budget** is the declared `CostBounds.max_cost_usd` of the profile, already
  compared to the caller's `ResourceGrant` before the run is queued
  (`check_profile_permission`). `CostBudget` is the mid-run half: the estimate is
  recomputed on every usage update and the run aborts the moment it crosses.

**Without a price, the money bound is the time bound.** An unpriced model yields
`cost_usd = None`, the metadata says `cost_basis: "unpriced"`, and the only thing
bounding spend is the profile's `max_duration_s`, which the supervisor enforces
by killing the worker. That is stated in the docs rather than papered over.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from jarvis.testlab.runners import CostBudgetExceeded
from jarvis.testlab.validation import check_number, fail

COST_BUDGET_EXCEEDED = "testlab_cost_budget_exceeded"

#: The journal kind the Realtime session emits on every usage update.
USAGE_KIND = "voice.realtime.usage"
#: Terminal usage source: the provider's own final accounting.
PROVIDER_FINAL_SOURCE = "provider_final"


#: Re-exported from the runner seam: the typed exception the worker recognises, so a
#: budget abort has its own failure code instead of reading as an unforeseen crash.
__all__ = ["COST_BUDGET_EXCEEDED", "CostBudget", "CostBudgetExceeded", "CostModel", "USAGE_KIND", "UsageTotals"]


@dataclass(frozen=True, slots=True)
class UsageTotals:
    """Folded `voice.realtime.usage` lines. Counts and seconds only; never a transcript."""

    input_tokens: int = 0
    output_tokens: int = 0
    duration_seconds: float = 0.0
    updates: int = 0
    #: True once a `provider_final` line has been seen: the numbers are the provider's own.
    final: bool = False

    def fold(self, payload: object) -> UsageTotals:
        """Absorb one usage payload. A malformed or partial payload contributes what it can.

        The provider reports CUMULATIVE totals for the session, so each update
        replaces the counters rather than adding to them; adding would multiply the
        bill by the number of updates and abort every run on its third line.
        """
        if not isinstance(payload, dict):
            return self
        return replace(
            self,
            input_tokens=_count(payload.get("input_tokens"), self.input_tokens),
            output_tokens=_count(payload.get("output_tokens"), self.output_tokens),
            duration_seconds=_seconds(payload.get("duration_seconds"), self.duration_seconds),
            updates=self.updates + 1,
            final=self.final or payload.get("source") == PROVIDER_FINAL_SOURCE,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "duration_seconds": round(self.duration_seconds, 3), "updates": self.updates,
                "final": self.final}


def _count(value: object, previous: int) -> int:
    """A token count the provider reported, or the previous one. Never a decrease to noise."""
    if type(value) is int and value >= 0:
        return max(previous, value)
    return previous


def _seconds(value: object, previous: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return max(previous, float(value))
    return previous


@dataclass(frozen=True, slots=True)
class CostModel:
    """How usage becomes money, for one model. Supplied, never assumed.

    `token_pricing` and `minute_pricing` are `jarvis.runtime.pricing` documents, so a
    Test Lab estimate uses exactly the arithmetic and the provenance fields (source,
    effective date, schema version) the Live status surface already uses.
    """

    model_id: str
    token_pricing: Any = None
    minute_pricing: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise fail("cost_model.model_id must be a non-empty string")

    @property
    def priced(self) -> bool:
        return self.token_pricing is not None or self.minute_pricing is not None

    @property
    def basis(self) -> str:
        if self.token_pricing is not None:
            return "provider_tokens"
        if self.minute_pricing is not None:
            return "duration"
        return "unpriced"

    def estimate(self, usage: UsageTotals) -> dict[str, Any] | None:
        """USD estimate of `usage`, or `None` when this model has no price.

        Tokens win over minutes when both are configured: the token document is the
        finer measure, and the usage payload carries the counts.
        """
        if self.token_pricing is not None:
            return dict(self.token_pricing.estimate(input_tokens=usage.input_tokens,
                                                    output_tokens=usage.output_tokens))
        if self.minute_pricing is not None:
            return dict(self.minute_pricing.estimate(usage.duration_seconds, basis="duration"))
        return None

    @classmethod
    def from_settings(cls, model_id: str, pricing: object) -> CostModel:
        """Build from the Control Center `live_pricing` shape: `{model_id: {...}}`.

        Anything that does not parse leaves the model UNPRICED rather than guessing:
        an estimate built from a document we did not understand is a wrong number
        with a currency symbol on it.
        """
        from jarvis.runtime.pricing import PricingMetadata, TokenPricingMetadata

        if not isinstance(pricing, dict):
            return cls(model_id)
        entry = pricing.get(model_id)
        if not isinstance(entry, dict):
            return cls(model_id)
        # `parse` returns None (never raises) on any mismatch, and the two documents
        # have disjoint field sets, so at most one of them recognises an entry.
        return cls(model_id, token_pricing=TokenPricingMetadata.parse(entry, model_id=model_id),
                   minute_pricing=PricingMetadata.parse(entry, model_id=model_id))


@dataclass(slots=True)
class CostBudget:
    """Mechanical mid-run budget: recompute on every usage update, abort on the first crossing."""

    max_cost_usd: float
    model: CostModel
    usage: UsageTotals = field(default_factory=UsageTotals)
    #: Last estimate, kept so the metadata records what the run believed it spent.
    estimate: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        check_number(self.max_cost_usd, "budget.max_cost_usd", minimum=0)
        if not isinstance(self.model, CostModel):
            raise fail("budget.model must be a CostModel")

    @property
    def cost_usd(self) -> float | None:
        if self.estimate is None:
            return None
        amount = self.estimate.get("amount")
        return float(amount) if isinstance(amount, (int, float)) and not isinstance(amount, bool) else None

    def observe(self, payload: object) -> None:
        """Fold one usage payload and raise `CostBudgetExceeded` when the estimate crosses.

        A model with no price never raises here — there is nothing to compare — which
        is exactly why the duration bound is the real guard on an unpriced model.
        """
        self.usage = self.usage.fold(payload)
        self.estimate = self.model.estimate(self.usage)
        spent = self.cost_usd
        if spent is None:
            return
        if spent > self.max_cost_usd:
            raise CostBudgetExceeded(
                COST_BUDGET_EXCEEDED,
                f"the run's estimated provider spend reached {spent:.4f} USD, over its "
                f"{self.max_cost_usd:.4f} USD budget; the session was stopped")

    def to_dict(self) -> dict[str, Any]:
        return {"max_cost_usd": self.max_cost_usd, "cost_usd": self.cost_usd, "cost_basis": self.model.basis,
                "model_id": self.model.model_id, "usage": self.usage.to_dict(), "estimate": self.estimate}
