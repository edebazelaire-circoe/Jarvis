"""Provider-neutral comparison catalog contract.

Catalog entries are projections of evidence.  They never authorize routing and
never turn curated metadata into runtime availability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
import json
import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any


class CatalogContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CatalogSurface(StrEnum):
    SUBAGENTS = "subagents"
    VOICE = "voice"


class CatalogAvailabilityState(StrEnum):
    USABLE = "usable"
    CONFIGURED_UNVERIFIED = "configured_unverified"
    AVAILABLE_NOT_CONFIGURED = "available_not_configured"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class CatalogFreshness(StrEnum):
    LIVE = "live"
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class CatalogSourceKind(StrEnum):
    PROVIDER_LIVE = "provider_live"
    PROVIDER_CACHE = "provider_cache"
    PROVIDER_FAILURE = "provider_failure"
    RUNTIME_PROBE = "runtime_probe"
    RUNTIME_REGISTRY = "runtime_registry"
    ROLE_CLASSIFIER = "role_classifier"
    CURATED = "curated"


def _timestamp(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise CatalogContractError("catalog_provenance_invalid", f"{name} must be a bounded timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CatalogContractError("catalog_provenance_invalid", f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CatalogContractError("catalog_provenance_invalid", f"{name} must include a timezone")
    return parsed.isoformat()


def _text(value: str, name: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str) or value != value.strip() or not value or len(value) > maximum:
        raise CatalogContractError("catalog_contract_invalid", f"{name} must be trimmed and bounded")
    return value


def _freeze_json(value: object) -> object:
    """Own an immutable JSON-like copy so caller mutation cannot rewrite claims."""
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise CatalogContractError("catalog_value_invalid", "Catalog object keys must be text")
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or type(value) in {str, bool, int}:
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise CatalogContractError("catalog_value_invalid", "Catalog claims must contain finite JSON values")


def _thaw_json(value: object) -> object:
    """Return a detached JSON value; mutating a response never mutates the claim."""
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class CatalogProvenance:
    source_id: str
    kind: CatalogSourceKind
    reference: str
    observed_at: str
    freshness: CatalogFreshness
    updated_at: str | None = None
    status_code: str = "ok"

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id", maximum=200))
        if not isinstance(self.kind, CatalogSourceKind) or not isinstance(self.freshness, CatalogFreshness):
            raise CatalogContractError("catalog_provenance_invalid", "Unknown provenance kind or freshness")
        object.__setattr__(self, "reference", _text(self.reference, "reference", maximum=1000))
        object.__setattr__(self, "observed_at", _timestamp(self.observed_at, "observed_at"))
        if self.updated_at is not None:
            object.__setattr__(self, "updated_at", _timestamp(self.updated_at, "updated_at"))
        object.__setattr__(self, "status_code", _text(self.status_code, "status_code", maximum=100))

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "kind": self.kind.value,
            "reference": self.reference,
            "observed_at": self.observed_at,
            "updated_at": self.updated_at,
            "freshness": self.freshness.value,
            "status_code": self.status_code,
        }


@dataclass(frozen=True, slots=True)
class SourcedValue:
    value: object
    provenance: CatalogProvenance
    provenance_by_value: Mapping[str, tuple[CatalogProvenance, ...]] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, CatalogProvenance):
            raise CatalogContractError("catalog_metadata_unsourced", "Catalog claims require provenance")
        object.__setattr__(self, "value", _freeze_json(self.value))
        if self.provenance_by_value is not None:
            if not isinstance(self.provenance_by_value, Mapping):
                raise CatalogContractError("catalog_metadata_unsourced", "Per-value provenance must be an object")
            available = set(self.value) if isinstance(self.value, tuple) else set()
            normalized: dict[str, tuple[CatalogProvenance, ...]] = {}
            for key, sources in self.provenance_by_value.items():
                if not isinstance(key, str) or key not in available:
                    raise CatalogContractError("catalog_metadata_unsourced", "Per-value provenance key is invalid")
                if (not isinstance(sources, tuple) or not sources
                        or any(not isinstance(source, CatalogProvenance) for source in sources)):
                    raise CatalogContractError("catalog_metadata_unsourced", "Per-value provenance sources are invalid")
                normalized[key] = tuple(dict.fromkeys(sources))
            if set(normalized) != available:
                raise CatalogContractError("catalog_metadata_unsourced", "Every claim value requires exact provenance")
            object.__setattr__(self, "provenance_by_value", MappingProxyType(normalized))

    def to_dict(self) -> dict[str, object]:
        result = {"value": _thaw_json(self.value), "provenance": self.provenance.to_dict()}
        if self.provenance_by_value is not None:
            result["provenance_by_value"] = {
                key: [source.to_dict() for source in sources]
                for key, sources in self.provenance_by_value.items()
            }
        return result


@dataclass(frozen=True, slots=True)
class CatalogIdentity:
    surface: CatalogSurface
    provider_id: str
    model_id: str
    agent_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.surface, CatalogSurface):
            raise CatalogContractError("catalog_identity_invalid", "Unknown catalog surface")
        object.__setattr__(self, "provider_id", _text(self.provider_id, "provider_id", maximum=100))
        if not isinstance(self.model_id, str) or self.model_id != self.model_id.strip() or len(self.model_id) > 500:
            raise CatalogContractError("catalog_identity_invalid", "model_id must be trimmed and bounded")
        if self.surface is CatalogSurface.SUBAGENTS:
            object.__setattr__(self, "agent_id", _text(self.agent_id or "", "agent_id", maximum=100))
        elif self.agent_id is not None:
            raise CatalogContractError("catalog_identity_invalid", "Voice identities cannot carry an agent_id")

    @property
    def key(self) -> str:
        # Hash canonical structured identity. Consumers must treat this as opaque;
        # provider IDs may themselves contain every common delimiter.
        encoded = json.dumps(
            [self.surface.value, self.agent_id, self.provider_id, self.model_id],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return "catalog_v1_" + sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
        }


@dataclass(frozen=True, slots=True)
class CatalogAvailability:
    state: CatalogAvailabilityState
    selectable: bool
    reason_code: str
    reason: str
    evidence: tuple[CatalogProvenance, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.state, CatalogAvailabilityState) or type(self.selectable) is not bool:
            raise CatalogContractError("catalog_availability_invalid", "Invalid catalog availability")
        object.__setattr__(self, "reason_code", _text(self.reason_code, "reason_code", maximum=100))
        object.__setattr__(self, "reason", _text(self.reason, "reason", maximum=1000))
        if self.selectable and self.state is not CatalogAvailabilityState.USABLE:
            raise CatalogContractError("catalog_availability_invalid", "Only verified usable items are selectable")
        if any(not isinstance(item, CatalogProvenance) for item in self.evidence):
            raise CatalogContractError("catalog_availability_invalid", "Availability evidence is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "selectable": self.selectable,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class CatalogItem:
    identity: CatalogIdentity
    label: str
    roles: SourcedValue
    availability: CatalogAvailability
    capabilities: SourcedValue | None = None
    description: SourcedValue | None = None
    tags: SourcedValue | None = None
    recommended_uses: SourcedValue | None = None
    pricing: SourcedValue | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CatalogIdentity) or not isinstance(self.roles, SourcedValue):
            raise CatalogContractError("catalog_item_invalid", "Catalog item identity and roles are required")
        object.__setattr__(self, "label", _text(self.label, "label", maximum=500))
        roles = self.roles.value
        if not isinstance(roles, tuple) or any(not isinstance(role, str) or not role for role in roles):
            raise CatalogContractError("catalog_item_invalid", "roles must be a tuple of identifiers")
        for claim in (self.capabilities, self.description, self.tags, self.recommended_uses, self.pricing):
            if claim is not None and not isinstance(claim, SourcedValue):
                raise CatalogContractError("catalog_metadata_unsourced", "Comparison metadata requires provenance")

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.identity.key,
            "kind": "subagent_model" if self.identity.surface is CatalogSurface.SUBAGENTS else "voice_model",
            "identity": self.identity.to_dict(),
            "label": self.label,
            "roles": self.roles.to_dict(),
            "availability": self.availability.to_dict(),
            "capabilities": self.capabilities.to_dict() if self.capabilities else None,
            "description": self.description.to_dict() if self.description else None,
            "tags": self.tags.to_dict() if self.tags else None,
            "recommended_uses": self.recommended_uses.to_dict() if self.recommended_uses else None,
            "pricing": self.pricing.to_dict() if self.pricing else None,
            # No request/add sink exists. Advertising an action would be a
            # product lie; future actions require a real injected boundary.
            "actions": [],
        }


@dataclass(frozen=True, slots=True)
class CatalogView:
    surface: CatalogSurface
    role: str
    generated_at: str
    items: tuple[CatalogItem, ...]
    sources: tuple[CatalogProvenance, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not isinstance(self.surface, CatalogSurface):
            raise CatalogContractError("catalog_schema_invalid", "Catalog view schema_version must be 1")
        if not isinstance(self.role, str) or self.role != self.role.strip() or len(self.role) > 100:
            raise CatalogContractError("catalog_schema_invalid", "Catalog role must be trimmed")
        object.__setattr__(self, "generated_at", _timestamp(self.generated_at, "generated_at"))
        if any(item.identity.surface is not self.surface for item in self.items):
            raise CatalogContractError("catalog_schema_invalid", "Item belongs to another surface")
        keys = [item.identity.key for item in self.items]
        if len(keys) != len(set(keys)):
            raise CatalogContractError("catalog_duplicate_item", "Catalog item keys must be unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "surface": self.surface.value,
            "role": self.role,
            "sources": [source.to_dict() for source in self.sources],
            "items": [item.to_dict() for item in self.items],
        }
