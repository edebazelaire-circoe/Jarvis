from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from jarvis.domain.catalog import (
    CatalogContractError,
    CatalogFreshness,
    CatalogIdentity,
    CatalogProvenance,
    CatalogSourceKind,
    CatalogSurface,
    SourcedValue,
)
from jarvis.domain.routing import CandidateRef
from jarvis.domain.voice_architecture import (
    ModelAvailability,
    VoiceAdapterStatus,
    VoiceModelRef,
)
from jarvis.runtime.catalog_metadata import (
    CatalogMetadataEntry,
    CatalogMetadataRegistry,
    timed_pricing_value,
    token_pricing_value,
)
from jarvis.runtime.catalog_view import CatalogViewService, ProviderCatalogSnapshot
from jarvis.runtime import cli_catalog
from jarvis.runtime.voice_capabilities import VoiceCapabilityRegistry, default_voice_registry


NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def provider(*models: dict, source: str = "live", at: datetime = NOW) -> dict:
    return {"source": source, "fetched_at": at.timestamp(), "models": list(models)}


def agent(agent_id: str, provider_id: str, *, available: bool = True) -> dict:
    return {
        "id": agent_id,
        "label": agent_id.title(),
        "description": f"{agent_id} runtime",
        "model_provider": provider_id,
        "available": available,
        "capabilities": ["semantic", "code"],
    }


def by_model(view) -> dict[str, dict]:
    return {item["identity"]["model_id"]: item for item in view.to_dict()["items"]}


def test_catalog_keys_are_deterministic_opaque_and_delimiter_safe():
    first = CatalogIdentity(CatalogSurface.SUBAGENTS, "provider:a/b", "model:x/y", "agent:z")
    same = CatalogIdentity(CatalogSurface.SUBAGENTS, "provider:a/b", "model:x/y", "agent:z")
    different = CatalogIdentity(CatalogSurface.SUBAGENTS, "provider", "a/b:model:x/y", "agent:z")

    assert first.key == same.key
    assert first.key != different.key
    assert first.key.startswith("catalog_v1_") and "model:x/y" not in first.key


def test_subagent_matrix_keeps_cli_default_unverified_and_requires_fresh_model_evidence():
    service = CatalogViewService()
    view = service.subagents(
        agents=[agent("claude", "anthropic"), agent("codex", "openai", available=False)],
        catalogs={
            "anthropic": provider({"id": "m1", "label": "M1", "roles": ["text"]}),
            "openai": provider({"id": "m2", "label": "M2", "roles": ["text"]}),
        },
        saved=[CandidateRef("claude", "removed")],
        now=NOW,
    )
    payload = view.to_dict()
    claude = {
        item["identity"]["model_id"]: item
        for item in payload["items"]
        if item["identity"]["agent_id"] == "claude"
    }
    codex = {
        item["identity"]["model_id"]: item
        for item in payload["items"]
        if item["identity"]["agent_id"] == "codex"
    }

    assert claude[""]["availability"]["state"] == "configured_unverified"
    assert claude["m1"]["availability"]["state"] == "usable"
    assert claude["m1"]["availability"]["selectable"] is True
    assert claude["removed"]["availability"]["state"] == "unavailable"
    assert claude["removed"]["availability"]["reason_code"] == "catalog_model_not_listed"
    assert codex["m2"]["availability"]["state"] == "available_not_configured"
    assert codex["m2"]["availability"]["selectable"] is False
    assert all(item["actions"] == [] for item in payload["items"])
    assert all(item["pricing"] is None for item in payload["items"])
    assert "key_hint" not in json.dumps(payload)


def test_stale_catalog_proves_neither_usability_nor_removal():
    view = CatalogViewService().subagents(
        agents=[agent("claude", "anthropic")],
        catalogs={
            "anthropic": provider(
                {"id": "old-known", "roles": ["text"]},
                source="stale",
                at=NOW - timedelta(days=2),
            )
        },
        saved=[CandidateRef("claude", "saved-but-not-in-stale-list")],
        now=NOW,
    )
    items = by_model(view)

    assert items["old-known"]["availability"]["state"] == "configured_unverified"
    assert items["saved-but-not-in-stale-list"]["availability"]["state"] == "configured_unverified"
    assert all(not item["availability"]["selectable"] for item in items.values())
    assert view.sources[0].freshness is CatalogFreshness.STALE


def test_missing_credentials_or_catalog_keep_saved_candidate_unknown_not_removed():
    view = CatalogViewService().subagents(
        agents=[agent("claude", "anthropic")],
        catalogs={"anthropic": {"source": "catalog_no_key", "models": []}},
        saved=[CandidateRef("claude", "saved")],
        now=NOW,
    )

    saved = by_model(view)["saved"]
    assert saved["availability"]["state"] == "configured_unverified"
    assert saved["availability"]["reason_code"] == "catalog_no_key"
    assert view.sources[0].freshness is CatalogFreshness.UNKNOWN
    assert view.to_dict()["sources"][0]["status_code"] == "catalog_no_key"
    assert view.to_dict()["sources"][0]["kind"] == "provider_failure"


def test_auto_only_selects_candidates_enforceable_by_the_active_cli_host():
    agents = [
        cli_catalog.describe(
            spec,
            command=spec.default_command,
            detection={"available": True, "path": spec.default_command, "version": "test", "error": ""},
        )
        for spec in cli_catalog.AGENT_CLIS
    ]
    catalogs = {
        "anthropic": provider({"id": "claude-model", "roles": ["text"]}),
        "openai": provider({"id": "codex-model", "roles": ["text"]}),
    }

    claude_host = by_model(CatalogViewService().subagents(
        agents=agents,
        catalogs=catalogs,
        routing_enabled=True,
        active_agent="claude",
        now=NOW,
    ))
    codex_host = by_model(CatalogViewService().subagents(
        agents=agents,
        catalogs=catalogs,
        routing_enabled=True,
        active_agent="codex",
        now=NOW,
    ))

    assert claude_host["claude-model"]["availability"]["state"] == "usable"
    assert claude_host["codex-model"]["availability"]["selectable"] is False
    assert claude_host["codex-model"]["availability"]["reason_code"] == "catalog_subagent_not_active_host"
    assert codex_host["codex-model"]["availability"]["selectable"] is False
    assert codex_host["codex-model"]["availability"]["reason_code"] == "catalog_subagent_delegation_unsupported"


@pytest.mark.parametrize("malformed", [1, 0, "true", "false", None, [], {}])
def test_cli_availability_requires_an_exact_boolean(malformed):
    broken = agent("claude", "anthropic")
    broken["available"] = malformed
    items = by_model(CatalogViewService().subagents(
        agents=[broken],
        catalogs={"anthropic": provider({"id": "m1", "roles": ["text"]})},
        now=NOW,
    ))

    assert {item["availability"]["state"] for item in items.values()} == {"unknown"}
    assert all(item["availability"]["reason_code"] == "catalog_cli_probe_invalid" for item in items.values())
    assert all(item["availability"]["selectable"] is False for item in items.values())


def test_provider_cache_freshness_requires_a_plausible_bounded_timestamp():
    service = CatalogViewService(ttl_s=600)
    fresh = ProviderCatalogSnapshot.from_payload(
        "openai", provider(source="cache", at=NOW - timedelta(seconds=599)), now=NOW, ttl_s=600,
    )
    stale = ProviderCatalogSnapshot.from_payload(
        "openai", provider(source="cache", at=NOW - timedelta(seconds=601)), now=NOW, ttl_s=600,
    )
    future = ProviderCatalogSnapshot.from_payload(
        "openai", provider(source="live", at=NOW + timedelta(hours=1)), now=NOW, ttl_s=600,
    )
    corrupt = ProviderCatalogSnapshot.from_payload(
        "openai", {"source": "live", "fetched_at": float("nan"), "models": [{"private": "secret"}]},
        now=NOW,
        ttl_s=600,
    )
    hostile = ProviderCatalogSnapshot.from_payload(
        "openai", {"source": "private key value!", "models": []}, now=NOW, ttl_s=600,
    )
    failed_stale = ProviderCatalogSnapshot.from_payload(
        "openai",
        {"source": "stale", "status_code": "catalog_unreachable", "fetched_at": (NOW - timedelta(days=1)).timestamp()},
        now=NOW,
        ttl_s=600,
    )

    assert service.ttl_s == 600
    assert fresh.authoritative and fresh.provenance.freshness is CatalogFreshness.FRESH
    assert not stale.authoritative and stale.provenance.freshness is CatalogFreshness.STALE
    assert not future.authoritative and future.provenance.freshness is CatalogFreshness.UNKNOWN
    assert not corrupt.authoritative and corrupt.models == ()
    assert hostile.status_code == "unknown" and "private" not in json.dumps(hostile.provenance.to_dict())
    assert failed_stale.status_code == "catalog_unreachable"
    assert failed_stale.provenance.kind is CatalogSourceKind.PROVIDER_CACHE


def test_voice_matrix_combines_provider_and_adapter_evidence_without_guessing():
    original = default_voice_registry()
    base = original.descriptors()[0]
    ready = replace(base, ref=VoiceModelRef("example", "ready"), availability=ModelAvailability.UNKNOWN)
    planned = replace(base, ref=VoiceModelRef("example", "planned"), adapter_status=VoiceAdapterStatus.PLANNED)
    removed = replace(base, ref=VoiceModelRef("example", "removed"))
    denied = replace(base, ref=VoiceModelRef("example", "denied"), availability=ModelAvailability.UNAVAILABLE)
    registry = VoiceCapabilityRegistry((ready, planned, removed, denied))

    view = CatalogViewService().voice(
        registry=registry,
        catalogs={"example": provider(
            {"id": "ready", "roles": ["realtime"]},
            {"id": "planned", "roles": ["realtime"]},
            {"id": "raw-provider-model", "roles": ["realtime"]},
            {"id": "denied", "roles": ["realtime"]},
        )},
        role="realtime",
        now=NOW,
    )
    states = {model: item["availability"]["state"] for model, item in by_model(view).items()}

    assert states == {
        "denied": "unavailable",
        "planned": "available_not_configured",
        "raw-provider-model": "available_not_configured",
        "ready": "usable",
        "removed": "unavailable",
    }
    assert by_model(view)["ready"]["capabilities"]["provenance"]["kind"] == "runtime_registry"


def test_stale_voice_evidence_does_not_promote_ready_or_planned_models():
    original = default_voice_registry()
    base = original.descriptors()[0]
    ready = replace(base, ref=VoiceModelRef("example", "ready"))
    planned = replace(base, ref=VoiceModelRef("example", "planned"), adapter_status=VoiceAdapterStatus.PLANNED)
    view = CatalogViewService().voice(
        registry=VoiceCapabilityRegistry((ready, planned)),
        catalogs={"example": provider(
            {"id": "ready", "roles": ["realtime"]},
            {"id": "planned", "roles": ["realtime"]},
            source="stale",
            at=NOW - timedelta(days=1),
        )},
        now=NOW,
    )

    assert by_model(view)["ready"]["availability"]["state"] == "configured_unverified"
    assert by_model(view)["planned"]["availability"]["state"] == "unknown"


def test_metadata_claims_are_sourced_and_cannot_override_availability():
    identity = CatalogIdentity(CatalogSurface.SUBAGENTS, "anthropic", "m1", "claude")
    provenance = CatalogProvenance(
        "reviewed-pricing",
        CatalogSourceKind.CURATED,
        "https://example.invalid/reviewed-source",
        NOW.isoformat(),
        CatalogFreshness.FRESH,
        updated_at=NOW.isoformat(),
    )
    price = token_pricing_value({
        "schema_version": 1,
        "model_id": "m1",
        "currency": "USD",
        "input_price_per_million_tokens": 1.0,
        "output_price_per_million_tokens": 2.0,
        "source": "https://example.invalid/pricing",
        "effective_at": NOW.isoformat(),
    }, model_id="m1")
    registry = CatalogMetadataRegistry((CatalogMetadataEntry(
        identity,
        tags=SourcedValue(("reviewed",), provenance),
        pricing=SourcedValue(price, provenance),
    ),))
    price["input"] = 999
    view = CatalogViewService(metadata=registry).subagents(
        agents=[agent("claude", "anthropic")],
        catalogs={"anthropic": provider({"id": "m1", "roles": ["text"]})},
        now=NOW,
    )
    item = by_model(view)["m1"]

    assert item["availability"]["state"] == "usable"
    assert item["tags"]["provenance"]["freshness"] == "fresh"
    assert item["pricing"]["value"]["unit"] == "million_tokens"
    assert item["pricing"]["value"]["input"] == 1.0
    assert item["pricing"]["value"]["source"] == "https://example.invalid/pricing"
    item["pricing"]["value"]["input"] = 777
    assert by_model(view)["m1"]["pricing"]["value"]["input"] == 1.0


def test_sourced_values_own_a_deeply_immutable_copy():
    provenance = CatalogProvenance(
        "source", CatalogSourceKind.CURATED, "reference", NOW.isoformat(), CatalogFreshness.FRESH,
    )
    original = {"nested": [{"value": 1}]}
    claim = SourcedValue(original, provenance)
    original["nested"][0]["value"] = 9

    assert claim.to_dict()["value"] == {"nested": [{"value": 1}]}
    with pytest.raises(TypeError):
        claim.value["nested"] = ()  # type: ignore[index]
    response = claim.to_dict()
    response["value"]["nested"][0]["value"] = 7
    assert claim.to_dict()["value"] == {"nested": [{"value": 1}]}


def test_invalid_or_unsourced_pricing_is_unknown():
    assert token_pricing_value({"model_id": "m1", "input_price_per_million_tokens": 1}, model_id="m1") is None
    assert timed_pricing_value({
        "schema_version": 1,
        "model_id": "wrong",
        "currency": "USD",
        "price_per_minute": 1,
        "source": "source",
        "effective_at": NOW.isoformat(),
    }, model_id="m1") is None
    with pytest.raises(CatalogContractError) as failure:
        CatalogMetadataEntry(
            CatalogIdentity(CatalogSurface.VOICE, "openai", "m1"),
            pricing={"amount": 1},  # type: ignore[arg-type]
        )
    assert failure.value.code == "catalog_metadata_unsourced"
    with pytest.raises(CatalogContractError) as malformed:
        CatalogMetadataEntry(
            CatalogIdentity(CatalogSurface.VOICE, "openai", "m1"),
            pricing=SourcedValue({"amount": 1}, CatalogProvenance(
                "source", CatalogSourceKind.CURATED, "reference", NOW.isoformat(), CatalogFreshness.FRESH,
            )),
        )
    assert malformed.value.code == "catalog_pricing_invalid"


def test_role_filter_and_surface_are_explicit():
    subagents = CatalogViewService().subagents(
        agents=[agent("claude", "anthropic")],
        catalogs={"anthropic": provider({"id": "m1", "roles": ["text"]})},
        role="text",
        now=NOW,
    ).to_dict()
    voices = CatalogViewService().voice(
        registry=VoiceCapabilityRegistry(),
        catalogs={"openai": provider(
            {"id": "t", "roles": ["transcription"]},
            {"id": "r", "roles": ["realtime"]},
        )},
        role="transcription",
        now=NOW,
    ).to_dict()

    assert subagents["surface"] == "subagents" and subagents["role"] == "text"
    assert [item["identity"]["model_id"] for item in voices["items"]] == ["t"]
    assert voices["surface"] == "voice" and voices["role"] == "transcription"


def test_long_untrusted_labels_fall_back_without_breaking_catalog():
    cli = agent("claude", "anthropic")
    cli["label"] = "a" * 600
    model = {"id": "safe-model", "label": "m" * 600, "roles": ["text", "realtime"]}
    subagent_item = by_model(CatalogViewService().subagents(
        agents=[cli], catalogs={"anthropic": provider(model)}, now=NOW,
    ))["safe-model"]
    voice_item = by_model(CatalogViewService().voice(
        registry=VoiceCapabilityRegistry(), catalogs={"anthropic": provider(model)}, now=NOW,
    ))["safe-model"]

    assert subagent_item["label"] == "claude · safe-model"
    assert voice_item["label"] == "safe-model"
    assert len(subagent_item["label"]) <= 500 and len(voice_item["label"]) <= 500


def test_roles_are_attributed_to_classifier_or_registry_not_provider_availability():
    subagents = CatalogViewService().subagents(
        agents=[agent("claude", "anthropic")],
        catalogs={"anthropic": provider({"id": "m1", "roles": ["text"]})},
        now=NOW,
    ).to_dict()["items"]
    explicit = next(item for item in subagents if item["identity"]["model_id"] == "m1")
    default = next(item for item in subagents if item["identity"]["model_id"] == "")
    voice = CatalogViewService().voice(
        registry=VoiceCapabilityRegistry(),
        catalogs={"openai": provider({"id": "r1", "roles": ["realtime"]})},
        now=NOW,
    ).to_dict()["items"][0]

    assert explicit["roles"]["provenance"]["kind"] == "role_classifier"
    assert voice["roles"]["provenance"]["kind"] == "role_classifier"
    assert default["roles"]["provenance"]["kind"] == "runtime_registry"


def test_saved_absent_and_voice_union_roles_keep_exact_per_value_provenance():
    saved = by_model(CatalogViewService().subagents(
        agents=[agent("claude", "anthropic")],
        catalogs={"anthropic": provider({"id": "present", "roles": ["text"]})},
        saved=[CandidateRef("claude", "saved-absent")],
        now=NOW,
    ))["saved-absent"]
    voice = by_model(CatalogViewService().voice(
        registry=default_voice_registry(),
        catalogs={"openai": provider({"id": "gpt-live-1", "roles": ["realtime", "duplex"]})},
        now=NOW,
    ))["gpt-live-1"]

    assert saved["roles"]["value"] == ["subagent", "text"]
    assert saved["roles"]["provenance"]["source_id"] == "routing_settings:claude"
    assert {
        role: [source["kind"] for source in sources]
        for role, sources in saved["roles"]["provenance_by_value"].items()
    } == {
        "subagent": ["runtime_registry"],
        "text": ["runtime_registry"],
    }
    voice_sources = voice["roles"]["provenance_by_value"]
    assert [source["kind"] for source in voice_sources["realtime"]] == [
        "role_classifier", "runtime_registry",
    ]
    assert [source["kind"] for source in voice_sources["duplex"]] == [
        "role_classifier", "runtime_registry",
    ]
    assert [source["kind"] for source in voice_sources["conversation"]] == ["runtime_registry"]
