"""Pure assembly service for shared sub-agent and voice catalog views.

This module consumes already measured provider/CLI/adapter evidence.  It does
not fetch, persist, route, install, or create model requests.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
from typing import Any, Iterable, Mapping, Sequence

from jarvis.domain.catalog import (
    CatalogAvailability,
    CatalogAvailabilityState,
    CatalogFreshness,
    CatalogIdentity,
    CatalogItem,
    CatalogProvenance,
    CatalogSourceKind,
    CatalogSurface,
    CatalogView,
    SourcedValue,
)
from jarvis.domain.routing import CandidateRef
from jarvis.domain.voice_architecture import (
    ModelAvailability,
    VoiceAdapterStatus,
    VoiceModelDescriptor,
)
from jarvis.runtime.catalog_metadata import CatalogMetadataRegistry
from jarvis.runtime.model_catalog import CACHE_TTL_S
from jarvis.runtime.voice_capabilities import VoiceCapabilityRegistry


VOICE_ROLES = frozenset({"text", "realtime", "duplex", "transcription", "speech", "analysis", "conversation"})
SUBAGENT_ROLES = frozenset({"subagent", "text"})


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Catalog clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()


def _catalog_time(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _safe_models(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        model_id = raw.get("id")
        if not isinstance(model_id, str) or not model_id or model_id != model_id.strip() or len(model_id) > 500:
            continue
        if model_id in seen:
            continue
        roles_raw = raw.get("roles")
        roles = tuple(dict.fromkeys(
            role for role in roles_raw
            if isinstance(role, str) and role and role == role.strip() and len(role) <= 100
        )) if isinstance(roles_raw, (list, tuple)) else ()
        label = raw.get("label")
        result.append({
            "id": model_id,
            "label": (
                label.strip()
                if isinstance(label, str) and label.strip() and len(label.strip()) <= 500
                else model_id
            ),
            "roles": roles,
        })
        seen.add(model_id)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class ProviderCatalogSnapshot:
    provider_id: str
    models: tuple[dict[str, object], ...]
    provenance: CatalogProvenance
    authoritative: bool
    status_code: str

    @classmethod
    def from_payload(
        cls,
        provider_id: str,
        payload: Mapping[str, object] | None,
        *,
        now: datetime,
        ttl_s: float = CACHE_TTL_S,
    ) -> "ProviderCatalogSnapshot":
        current = _utc(now)
        values = payload if isinstance(payload, Mapping) else {}
        source = str(values.get("source") or "unknown")
        if (len(source) > 100 or not source
                or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in source)):
            source = "unknown"
        status = str(values.get("status_code") or ("ok" if source in {"live", "cache"} else source))
        if (len(status) > 100 or not status
                or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in status)):
            status = "catalog_provider_failure"
        fetched = _catalog_time(values.get("fetched_at"))
        age = (current - fetched).total_seconds() if fetched is not None else None
        plausible = age is not None and age >= -60
        if source == "live" and plausible and age < ttl_s:
            freshness = CatalogFreshness.LIVE
        elif source == "cache" and plausible and age < ttl_s:
            freshness = CatalogFreshness.FRESH
        elif source in {"live", "cache", "stale"} and fetched is not None and plausible:
            freshness = CatalogFreshness.STALE
        else:
            freshness = CatalogFreshness.UNKNOWN
        kind = (
            CatalogSourceKind.PROVIDER_CACHE
            if source in {"cache", "stale"}
            else CatalogSourceKind.PROVIDER_LIVE
            if source == "live"
            else CatalogSourceKind.PROVIDER_FAILURE
        )
        observed = fetched if fetched is not None and plausible else current
        provenance = CatalogProvenance(
            source_id=f"provider_catalog:{provider_id}",
            kind=kind,
            reference=f"jarvis.runtime.model_catalog:{provider_id}",
            observed_at=_iso(observed),
            updated_at=_iso(fetched) if fetched is not None and plausible else None,
            freshness=freshness,
            status_code=status,
        )
        return cls(
            provider_id=provider_id,
            models=_safe_models(values.get("models")),
            provenance=provenance,
            authoritative=freshness in {CatalogFreshness.LIVE, CatalogFreshness.FRESH},
            status_code=status,
        )

    def find(self, model_id: str) -> dict[str, object] | None:
        return next((item for item in self.models if item["id"] == model_id), None)

    def current_models(self, role: str) -> tuple[dict[str, object], ...]:
        """Models eligible for current decisions; stale/unknown never qualify."""
        if not self.authoritative:
            return ()
        return tuple(model for model in self.models if role in model["roles"])


def _runtime_provenance(
    source_id: str,
    reference: str,
    now: datetime,
    *,
    probe: bool = False,
    status_code: str = "ok",
) -> CatalogProvenance:
    return CatalogProvenance(
        source_id=source_id,
        kind=CatalogSourceKind.RUNTIME_PROBE if probe else CatalogSourceKind.RUNTIME_REGISTRY,
        reference=reference,
        observed_at=_iso(now),
        freshness=CatalogFreshness.LIVE if probe else CatalogFreshness.FRESH,
        status_code=status_code,
    )


def _role_provenance(provider: str, snapshot: ProviderCatalogSnapshot, now: datetime) -> CatalogProvenance:
    return CatalogProvenance(
        source_id=f"model_roles:{provider}",
        kind=CatalogSourceKind.ROLE_CLASSIFIER,
        reference="jarvis.runtime.model_catalog role classification",
        observed_at=_iso(now),
        updated_at=snapshot.provenance.updated_at,
        freshness=snapshot.provenance.freshness,
        status_code=snapshot.provenance.status_code,
    )


def _availability(
    state: CatalogAvailabilityState,
    code: str,
    reason: str,
    *evidence: CatalogProvenance,
) -> CatalogAvailability:
    return CatalogAvailability(state, state is CatalogAvailabilityState.USABLE, code, reason, tuple(evidence))


def _display_label(value: object, fallback: str) -> str:
    if isinstance(value, str):
        clean = value.strip()
        if clean and len(clean) <= 500:
            return clean
    return fallback


def _metadata(registry: CatalogMetadataRegistry, identity: CatalogIdentity) -> dict[str, SourcedValue | None]:
    entry = registry.find(identity)
    return {
        "description": entry.description if entry else None,
        "tags": entry.tags if entry else None,
        "recommended_uses": entry.recommended_uses if entry else None,
        "pricing": entry.pricing if entry else None,
    }


def _role_claim(
    sources_by_role: Mapping[str, Sequence[CatalogProvenance]],
    *,
    fallback: CatalogProvenance | None = None,
    primary: CatalogProvenance | None = None,
) -> SourcedValue:
    """Build one role list while retaining every source for every role."""
    normalized = {
        role: tuple(dict.fromkeys(sources))
        for role, sources in sources_by_role.items()
        if role and sources
    }
    provenances = tuple(source for sources in normalized.values() for source in sources)
    if not provenances and fallback is None:
        raise ValueError("Catalog role claim requires provenance")
    return SourcedValue(
        tuple(normalized),
        primary or (provenances[0] if provenances else fallback),
        provenance_by_value=normalized,
    )


def _subagent_availability(
    *,
    cli_available: bool | None,
    model_id: str,
    model_found: bool,
    snapshot: ProviderCatalogSnapshot,
    cli_evidence: CatalogProvenance,
    delegation_code: str | None = None,
    delegation_reason: str = "",
) -> CatalogAvailability:
    if cli_available is None:
        return _availability(
            CatalogAvailabilityState.UNKNOWN,
            "catalog_cli_probe_invalid",
            "Agent CLI availability probe returned an invalid state.",
            cli_evidence,
        )
    if delegation_code is not None:
        state = (
            CatalogAvailabilityState.AVAILABLE_NOT_CONFIGURED
            if snapshot.authoritative and model_found
            else CatalogAvailabilityState.UNAVAILABLE
        )
        return _availability(
            state,
            delegation_code,
            delegation_reason,
            cli_evidence,
            snapshot.provenance,
        )
    if not model_id:
        if cli_available:
            return _availability(
                CatalogAvailabilityState.CONFIGURED_UNVERIFIED,
                "catalog_cli_default_unverified",
                "CLI detected; its default model and authentication were not invoked.",
                cli_evidence,
            )
        return _availability(
            CatalogAvailabilityState.UNAVAILABLE,
            "catalog_cli_unavailable",
            "Agent CLI is not available on this machine.",
            cli_evidence,
        )
    if snapshot.authoritative and model_found:
        if cli_available:
            return _availability(
                CatalogAvailabilityState.USABLE,
                "catalog_model_usable",
                "Agent CLI is detected and the configured account currently lists this model.",
                cli_evidence,
                snapshot.provenance,
            )
        return _availability(
            CatalogAvailabilityState.AVAILABLE_NOT_CONFIGURED,
            "catalog_cli_not_configured",
            "Configured account lists this model, but the required Agent CLI is unavailable.",
            snapshot.provenance,
            cli_evidence,
        )
    if snapshot.authoritative:
        return _availability(
            CatalogAvailabilityState.UNAVAILABLE,
            "catalog_model_not_listed",
            "A fresh provider catalog does not list this saved model.",
            snapshot.provenance,
            cli_evidence,
        )
    if cli_available:
        code = (
            snapshot.status_code
            if snapshot.status_code not in {"unknown", "stale", "live", "cache"}
            else "catalog_provider_stale" if snapshot.provenance.freshness is CatalogFreshness.STALE
            else "catalog_provider_unverified"
        )
        return _availability(
            CatalogAvailabilityState.CONFIGURED_UNVERIFIED,
            code,
            "Agent CLI is detected, but provider availability is stale or unknown.",
            cli_evidence,
            snapshot.provenance,
        )
    return _availability(
        CatalogAvailabilityState.UNAVAILABLE,
        "catalog_cli_unavailable",
        "Agent CLI is unavailable and provider availability is not current.",
        cli_evidence,
        snapshot.provenance,
    )


def _voice_roles(descriptor: VoiceModelDescriptor) -> tuple[str, ...]:
    capabilities = descriptor.capabilities
    roles: list[str] = []
    if capabilities.supports_text_output:
        roles.append("text")
    if capabilities.supports_structured_output:
        roles.append("analysis")
    if capabilities.supports_realtime_conversation:
        roles.extend(("realtime", "conversation"))
    if capabilities.supports_full_duplex:
        roles.append("duplex")
    return tuple(dict.fromkeys(roles))


def _voice_availability(
    *,
    descriptor: VoiceModelDescriptor | None,
    model_found: bool,
    snapshot: ProviderCatalogSnapshot,
    registry_evidence: CatalogProvenance | None,
) -> CatalogAvailability:
    evidence = tuple(item for item in (snapshot.provenance, registry_evidence) if item is not None)
    if descriptor is not None and descriptor.availability is ModelAvailability.UNAVAILABLE:
        return _availability(
            CatalogAvailabilityState.UNAVAILABLE,
            "catalog_voice_account_unavailable",
            "Voice registry reports this model unavailable for the configured account.",
            *evidence,
        )
    if snapshot.authoritative and not model_found:
        return _availability(
            CatalogAvailabilityState.UNAVAILABLE,
            "catalog_model_not_listed",
            "A fresh provider catalog does not list this registered model.",
            *evidence,
        )
    if snapshot.authoritative and model_found:
        if descriptor is not None and descriptor.adapter_status is VoiceAdapterStatus.READY:
            return _availability(
                CatalogAvailabilityState.USABLE,
                "catalog_voice_usable",
                "Provider availability and a ready runtime adapter are both verified.",
                *evidence,
            )
        return _availability(
            CatalogAvailabilityState.AVAILABLE_NOT_CONFIGURED,
            "catalog_voice_adapter_not_ready",
            "Provider lists this model, but no ready canonical voice adapter is registered.",
            *evidence,
        )
    if descriptor is not None and descriptor.adapter_status is VoiceAdapterStatus.READY:
        code = (
            snapshot.status_code
            if snapshot.status_code not in {"unknown", "stale", "live", "cache"}
            else "catalog_provider_stale" if snapshot.provenance.freshness is CatalogFreshness.STALE
            else "catalog_voice_provider_unverified"
        )
        return _availability(
            CatalogAvailabilityState.CONFIGURED_UNVERIFIED,
            code,
            "Runtime adapter is ready, but account availability is stale or unknown.",
            *evidence,
        )
    return _availability(
        CatalogAvailabilityState.UNKNOWN,
        "catalog_voice_unverified",
        "Neither current provider availability nor a ready runtime adapter is established.",
        *evidence,
    )


class CatalogViewService:
    """Build versioned views from dependency-injected measurements."""

    def __init__(
        self,
        *,
        metadata: CatalogMetadataRegistry | None = None,
        ttl_s: float = CACHE_TTL_S,
    ) -> None:
        self.metadata = metadata or CatalogMetadataRegistry()
        self.ttl_s = ttl_s

    def _snapshots(
        self,
        catalogs: Mapping[str, Mapping[str, object]],
        providers: Iterable[str],
        now: datetime,
    ) -> dict[str, ProviderCatalogSnapshot]:
        return {
            provider: ProviderCatalogSnapshot.from_payload(
                provider,
                catalogs.get(provider),
                now=now,
                ttl_s=self.ttl_s,
            )
            for provider in sorted(set(providers))
        }

    def subagents(
        self,
        *,
        agents: Sequence[Mapping[str, object]],
        catalogs: Mapping[str, Mapping[str, object]],
        saved: Iterable[CandidateRef] = (),
        role: str = "subagent",
        active_agent: str | None = None,
        routing_enabled: bool = False,
        now: datetime | None = None,
    ) -> CatalogView:
        generated = _utc(now or datetime.now(timezone.utc))
        providers = [str(agent.get("model_provider") or "unknown") for agent in agents]
        snapshots = self._snapshots(catalogs, providers, generated)
        saved_set = {(ref.agent, ref.model) for ref in saved}
        items: list[CatalogItem] = []
        for agent in agents:
            agent_id = str(agent.get("id") or "").strip()
            if not agent_id:
                continue
            provider = str(agent.get("model_provider") or "unknown").strip() or "unknown"
            snapshot = snapshots[provider]
            available_raw = agent.get("available")
            cli_available = available_raw if type(available_raw) is bool else None
            cli_provenance = _runtime_provenance(
                f"cli_probe:{agent_id}",
                f"jarvis.runtime.cli_catalog:{agent_id}",
                generated,
                probe=True,
                status_code="ok" if cli_available is not None else "catalog_cli_probe_invalid",
            )
            registry_provenance = _runtime_provenance(
                f"cli_registry:{agent_id}",
                "jarvis.runtime.cli_catalog.AGENT_CLIS",
                generated,
            )
            saved_provenance = _runtime_provenance(
                f"routing_settings:{agent_id}",
                "agent_routing profile CandidateRef",
                generated,
            )
            known: dict[str, dict[str, object] | None] = {"": None}
            for model in snapshot.models:
                if "text" in model["roles"]:
                    known[str(model["id"])] = model
            for saved_agent, saved_model in saved_set:
                if saved_agent == agent_id:
                    known.setdefault(saved_model, None)
            for model_id, model in known.items():
                role_sources: dict[str, list[CatalogProvenance]] = {}
                role_primary = None
                subagent_source = saved_provenance if model_id and model is None else registry_provenance
                role_sources["subagent"] = [subagent_source]
                if not model_id:
                    role_sources["text"] = [registry_provenance]
                elif model is not None:
                    role_primary = _role_provenance(provider, snapshot, generated)
                    for model_role in model["roles"]:
                        role_sources.setdefault(str(model_role), []).append(role_primary)
                else:
                    # The saved candidate remains text-routable by contract,
                    # but that claim comes only from settings—not a live provider.
                    role_sources["text"] = [saved_provenance]
                roles = tuple(role_sources)
                if role and role not in roles:
                    continue
                identity = CatalogIdentity(CatalogSurface.SUBAGENTS, provider, model_id, agent_id)
                label = _display_label(agent.get("label"), agent_id)
                if model_id:
                    model_label = _display_label(model.get("label") if model else None, model_id)
                    combined = label + " · " + model_label
                    label = combined if len(combined) <= 500 else model_label
                else:
                    combined = label + " · Default CLI model"
                    label = combined if len(combined) <= 500 else "Default CLI model"
                metadata = _metadata(self.metadata, identity)
                description = metadata["description"]
                if description is None and isinstance(agent.get("description"), str) and agent["description"].strip():
                    description = SourcedValue(agent["description"].strip(), registry_provenance)
                capabilities_raw = agent.get("capabilities")
                capabilities = (
                    SourcedValue(tuple(sorted({str(value) for value in capabilities_raw if str(value)})), registry_provenance)
                    if isinstance(capabilities_raw, (list, tuple)) else None
                )
                delegation_code = None
                delegation_reason = ""
                capabilities_set = {
                    str(value)
                    for value in capabilities_raw
                    if str(value)
                } if isinstance(capabilities_raw, (list, tuple)) else set()
                if routing_enabled and agent_id != active_agent:
                    delegation_code = "catalog_subagent_not_active_host"
                    delegation_reason = (
                        "Auto can enforce one model only inside the active Agent CLI; "
                        "switch the primary CLI before using this candidate."
                    )
                elif routing_enabled and "background" not in capabilities_set:
                    delegation_code = "catalog_subagent_delegation_unsupported"
                    delegation_reason = (
                        "The active Agent CLI exposes no verified background sub-agent boundary; "
                        "Auto cannot enforce this candidate."
                    )
                items.append(CatalogItem(
                    identity=identity,
                    label=label,
                    roles=_role_claim(role_sources, primary=role_primary),
                    availability=_subagent_availability(
                        cli_available=cli_available,
                        model_id=model_id,
                        model_found=model is not None,
                        snapshot=snapshot,
                        cli_evidence=cli_provenance,
                        delegation_code=delegation_code,
                        delegation_reason=delegation_reason,
                    ),
                    capabilities=capabilities,
                    description=description,
                    tags=metadata["tags"],
                    recommended_uses=metadata["recommended_uses"],
                    pricing=metadata["pricing"],
                ))
        items.sort(key=lambda item: (item.identity.agent_id or "", item.identity.model_id))
        return CatalogView(
            CatalogSurface.SUBAGENTS,
            role,
            _iso(generated),
            tuple(items),
            tuple(snapshot.provenance for snapshot in snapshots.values()),
        )

    def voice(
        self,
        *,
        registry: VoiceCapabilityRegistry,
        catalogs: Mapping[str, Mapping[str, object]],
        role: str = "",
        now: datetime | None = None,
    ) -> CatalogView:
        generated = _utc(now or datetime.now(timezone.utc))
        descriptors = {(item.ref.provider_id, item.ref.model_id): item for item in registry.descriptors()}
        providers = set(catalogs) | {provider for provider, _model in descriptors}
        snapshots = self._snapshots(catalogs, providers, generated)
        identities: set[tuple[str, str]] = set(descriptors)
        for provider, snapshot in snapshots.items():
            identities.update(
                (provider, str(model["id"]))
                for model in snapshot.models
                if set(model["roles"]) & VOICE_ROLES
            )
        items: list[CatalogItem] = []
        for provider, model_id in sorted(identities):
            snapshot = snapshots[provider]
            model = snapshot.find(model_id)
            descriptor = descriptors.get((provider, model_id))
            registry_provenance = (
                _runtime_provenance(
                    f"voice_registry:{provider}:{model_id}",
                    descriptor.evidence,
                    generated,
                ) if descriptor is not None else None
            )
            role_sources: dict[str, list[CatalogProvenance]] = {}
            if model is not None:
                classifier = _role_provenance(provider, snapshot, generated)
                for model_role in model["roles"]:
                    role_sources.setdefault(str(model_role), []).append(classifier)
            if descriptor is not None and registry_provenance is not None:
                for descriptor_role in _voice_roles(descriptor):
                    role_sources.setdefault(descriptor_role, []).append(registry_provenance)
            roles = tuple(role_sources)
            if role and role not in roles:
                continue
            identity = CatalogIdentity(CatalogSurface.VOICE, provider, model_id)
            metadata = _metadata(self.metadata, identity)
            capabilities = None
            if descriptor is not None and registry_provenance is not None:
                enabled = tuple(sorted(
                    name.removeprefix("supports_")
                    for name, value in asdict(descriptor.capabilities).items()
                    if value
                ))
                capabilities = SourcedValue(enabled, registry_provenance)
            items.append(CatalogItem(
                identity=identity,
                label=_display_label(model.get("label") if model else None, model_id),
                roles=_role_claim(role_sources, fallback=snapshot.provenance),
                availability=_voice_availability(
                    descriptor=descriptor,
                    model_found=model is not None,
                    snapshot=snapshot,
                    registry_evidence=registry_provenance,
                ),
                capabilities=capabilities,
                description=metadata["description"],
                tags=metadata["tags"],
                recommended_uses=metadata["recommended_uses"],
                pricing=metadata["pricing"],
            ))
        return CatalogView(
            CatalogSurface.VOICE,
            role,
            _iso(generated),
            tuple(items),
            tuple(snapshot.provenance for snapshot in snapshots.values()),
        )
