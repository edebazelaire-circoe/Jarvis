"""Optional sourced comparison metadata for catalog projections.

There is intentionally no bundled price or recommendation table.  Callers may
inject reviewed entries; malformed/unsourced claims cannot enter the registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from collections.abc import Mapping
from typing import Iterable

from jarvis.domain.catalog import CatalogContractError, CatalogIdentity, SourcedValue
from jarvis.runtime.pricing import PricingMetadata, TokenPricingMetadata


@dataclass(frozen=True, slots=True)
class CatalogMetadataEntry:
    identity: CatalogIdentity
    description: SourcedValue | None = None
    tags: SourcedValue | None = None
    recommended_uses: SourcedValue | None = None
    pricing: SourcedValue | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CatalogIdentity):
            raise CatalogContractError("catalog_metadata_invalid", "Metadata identity is required")
        for claim in (self.description, self.tags, self.recommended_uses, self.pricing):
            if claim is not None and not isinstance(claim, SourcedValue):
                raise CatalogContractError("catalog_metadata_unsourced", "Metadata claim requires provenance")
        if self.pricing is not None and not _valid_pricing_value(self.pricing.value, self.identity.model_id):
            raise CatalogContractError(
                "catalog_pricing_invalid",
                "Pricing must use the strict sourced token or minute schema for this model",
            )
        if self.description is not None and (
            not isinstance(self.description.value, str) or not self.description.value.strip()
        ):
            raise CatalogContractError("catalog_metadata_invalid", "Description must be non-empty text")
        for name, claim in (("tags", self.tags), ("recommended_uses", self.recommended_uses)):
            if claim is not None and (
                not isinstance(claim.value, tuple)
                or any(not isinstance(item, str) or not item.strip() for item in claim.value)
            ):
                raise CatalogContractError("catalog_metadata_invalid", f"{name} must be a tuple of non-empty text")


class CatalogMetadataRegistry:
    def __init__(self, entries: Iterable[CatalogMetadataEntry] = ()) -> None:
        self._entries: dict[str, CatalogMetadataEntry] = {}
        for entry in entries:
            key = entry.identity.key
            if key in self._entries:
                raise CatalogContractError("catalog_metadata_duplicate", "Duplicate catalog metadata identity")
            self._entries[key] = entry

    def find(self, identity: CatalogIdentity) -> CatalogMetadataEntry | None:
        return self._entries.get(identity.key)


def _valid_pricing_value(value: object, model_id: str) -> bool:
    if not isinstance(value, Mapping):
        return False
    common = {"schema_version", "model_id", "currency", "unit", "source", "effective_at"}
    unit = value.get("unit")
    if unit not in {"million_tokens", "minute"}:
        return False
    expected = common | ({"input", "output"} if unit == "million_tokens" else {"amount"} if unit == "minute" else set())
    if set(value) != expected:
        return False
    if (value.get("schema_version") != 1 or value.get("model_id") != model_id
            or not isinstance(value.get("currency"), str) or not value["currency"]
            or not isinstance(value.get("source"), str) or not value["source"]
            or not isinstance(value.get("effective_at"), str)):
        return False
    numbers = (value.get("input"), value.get("output")) if unit == "million_tokens" else (value.get("amount"),)
    if any(isinstance(number, bool) or not isinstance(number, (int, float))
           or not math.isfinite(float(number)) or float(number) < 0 for number in numbers):
        return False
    try:
        effective = datetime.fromisoformat(value["effective_at"])
    except ValueError:
        return False
    return effective.tzinfo is not None and effective.utcoffset() is not None


def token_pricing_value(value: object, *, model_id: str) -> dict[str, object] | None:
    """Normalize existing strict token pricing; invalid/unsourced means unknown."""
    parsed = TokenPricingMetadata.parse(value, model_id=model_id)
    if parsed is None:
        return None
    return {
        "schema_version": parsed.schema_version,
        "model_id": parsed.model_id,
        "currency": parsed.currency,
        "unit": "million_tokens",
        "input": parsed.input_price_per_million_tokens,
        "output": parsed.output_price_per_million_tokens,
        "source": parsed.source,
        "effective_at": parsed.effective_at,
    }


def timed_pricing_value(value: object, *, model_id: str) -> dict[str, object] | None:
    """Normalize existing strict time pricing; invalid/unsourced means unknown."""
    parsed = PricingMetadata.parse(value, model_id=model_id)
    if parsed is None:
        return None
    return {
        "schema_version": parsed.schema_version,
        "model_id": parsed.model_id,
        "currency": parsed.currency,
        "unit": "minute",
        "amount": parsed.price_per_minute,
        "source": parsed.source,
        "effective_at": parsed.effective_at,
    }
