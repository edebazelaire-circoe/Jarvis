"""Strict versioned pricing metadata shared by status and benchmark reports."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math


PRICING_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class PricingMetadata:
    model_id: str
    currency: str
    price_per_minute: float
    source: str
    effective_at: str
    schema_version: int = PRICING_SCHEMA_VERSION

    @classmethod
    def parse(cls, value: object, *, model_id: str | None) -> "PricingMetadata | None":
        fields = {"schema_version", "model_id", "currency", "price_per_minute", "source", "effective_at"}
        if not isinstance(value, dict) or set(value) != fields or model_id is None:
            return None
        if (type(value.get("schema_version")) is not int
                or value.get("schema_version") != PRICING_SCHEMA_VERSION
                or value.get("model_id") != model_id):
            return None
        currency, source = value.get("currency"), value.get("source")
        effective_at, price = value.get("effective_at"), value.get("price_per_minute")
        if (not isinstance(currency, str) or not 1 <= len(currency.strip()) <= 8
                or not isinstance(source, str) or not 1 <= len(source.strip()) <= 200
                or not isinstance(effective_at, str) or len(effective_at) > 64
                or isinstance(price, bool) or not isinstance(price, (int, float))
                or not math.isfinite(float(price)) or float(price) < 0):
            return None
        try:
            effective = datetime.fromisoformat(effective_at)
        except ValueError:
            return None
        if effective.tzinfo is None or effective.utcoffset() is None:
            return None
        return cls(model_id, currency.strip().upper(), float(price), source.strip(), effective.isoformat())

    def estimate(self, seconds: float, *, basis: str) -> dict[str, object]:
        return {
            "estimated": True,
            "amount": self.price_per_minute * seconds / 60.0,
            "currency": self.currency,
            "basis": basis,
            "pricing_schema_version": self.schema_version,
            "pricing_source": self.source,
            "pricing_effective_at": self.effective_at,
            "model_id": self.model_id,
        }


@dataclass(frozen=True, slots=True)
class TokenPricingMetadata:
    model_id: str
    currency: str
    input_price_per_million_tokens: float
    output_price_per_million_tokens: float
    source: str
    effective_at: str
    schema_version: int = PRICING_SCHEMA_VERSION

    @classmethod
    def parse(cls, value: object, *, model_id: str | None) -> "TokenPricingMetadata | None":
        fields = {"schema_version", "model_id", "currency", "input_price_per_million_tokens",
                  "output_price_per_million_tokens", "source", "effective_at"}
        if not isinstance(value, dict) or set(value) != fields or model_id is None:
            return None
        if (type(value.get("schema_version")) is not int
                or value.get("schema_version") != PRICING_SCHEMA_VERSION
                or value.get("model_id") != model_id):
            return None
        currency, source, effective_at = value.get("currency"), value.get("source"), value.get("effective_at")
        prices = (value.get("input_price_per_million_tokens"), value.get("output_price_per_million_tokens"))
        if (not isinstance(currency, str) or not 1 <= len(currency.strip()) <= 8
                or not isinstance(source, str) or not 1 <= len(source.strip()) <= 200
                or not isinstance(effective_at, str) or len(effective_at) > 64
                or any(isinstance(price, bool) or not isinstance(price, (int, float))
                       or not math.isfinite(float(price)) or float(price) < 0 for price in prices)):
            return None
        try:
            effective = datetime.fromisoformat(effective_at)
        except ValueError:
            return None
        if effective.tzinfo is None or effective.utcoffset() is None:
            return None
        return cls(model_id, currency.strip().upper(), float(prices[0]), float(prices[1]),
                   source.strip(), effective.isoformat())

    def estimate(self, *, input_tokens: int, output_tokens: int) -> dict[str, object]:
        amount = (self.input_price_per_million_tokens * input_tokens
                  + self.output_price_per_million_tokens * output_tokens) / 1_000_000
        return {
            "estimated": True,
            "amount": amount,
            "currency": self.currency,
            "basis": "provider_tokens",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "pricing_schema_version": self.schema_version,
            "pricing_source": self.source,
            "pricing_effective_at": self.effective_at,
            "model_id": self.model_id,
        }
