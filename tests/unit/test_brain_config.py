"""Configuration des cerveaux (Slice 02) : descripteurs, écritures révisées chez chaque propriétaire, routes.

Contrat : docs/brain-config.md. Les fixtures de la fenêtre du cerveau (`tests/fixtures/brain_config_{core,voice}.json`,
Slice 05) sont produites par le service : `JARVIS_WRITE_BRAIN_CONFIG_FIXTURES=1 pytest tests/unit/test_brain_config.py`
les réécrit, sinon ce test vérifie qu'elles sont à jour.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.domain.brain_config import BrainConfigError, DelegationTendency
from jarvis.runtime.architecture_graph import ArchitectureGraphService, FileSettingsStore, RuntimeObservations
from jarvis.runtime.brain_config import BrainConfigService
from jarvis.runtime.brain_config_http import BrainConfigRoutes
from jarvis.runtime.brain_config_store import BrainConfigStore
from jarvis.runtime.tool_brain_decider import tool_brain_model_name
from jarvis.runtime.tool_brain_ownership import JARVIS_DEFAULT

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _selection(config: dict) -> dict:
    return {"voice_architecture": {"schema_version": 1, "config": config, "compatibility": None}}


DUPLEX = _selection({"architecture": "duplex", "conversation_model": {"provider_id": "openai", "model_id": "gpt-live-1"}})
FRONT = _selection({"architecture": "front_brain", "reflex_model": {"provider_id": "openai", "model_id": "gpt-realtime-2.1"},
                    "analysis_model": {"provider_id": "openai", "model_id": "gpt-5.6-luna"}})
SIMPLE = _selection({"architecture": "simple", "conversation_model": {"provider_id": "openai", "model_id": "gpt-realtime-2.1"}})


def _item(surface: str, provider: str, model: str, *, agent: str | None = None, selectable: bool = True,
          reason: str = "") -> dict:
    """Une ligne de `CatalogView.to_dict()["items"]`, réduite à ce que lit le service."""

    state = "usable" if selectable else "unavailable"
    return {"key": f"k-{surface}-{agent}-{model}", "kind": "subagent_model" if surface == "subagents" else "voice_model",
            "identity": {"agent_id": agent, "provider_id": provider, "model_id": model},
            "label": f"{agent or provider} · {model or 'défaut'}",
            "availability": {"state": state, "selectable": selectable, "reason_code": "" if selectable else "catalog_x",
                             "reason": reason or ("" if selectable else "Non listé par le fournisseur.")}}


CATALOG = {
    ("subagents", "text"): [
        _item("subagents", "anthropic", "", agent="claude"),
        _item("subagents", "anthropic", "claude-opus-5-5", agent="claude"),
        _item("subagents", "anthropic", "claude-haiku-5", agent="claude"),
        _item("subagents", "anthropic", "claude-retired-1", agent="claude", selectable=False,
              reason="Modèle retiré par le fournisseur."),
        _item("subagents", "openai", "", agent="codex", selectable=False, reason="CLI Codex introuvable."),
    ],
    ("voice", "duplex"): [_item("voice", "openai", "gpt-live-1"), _item("voice", "openai", "gpt-live-2")],
    ("voice", "realtime"): [_item("voice", "openai", "gpt-realtime-2.1"), _item("voice", "openai", "gpt-realtime-2.1-mini")],
    ("voice", "analysis"): [_item("voice", "openai", "gpt-5.6-luna"), _item("voice", "openai", "gpt-5.7-luna")],
}


async def fake_catalog(surface: str, role: str) -> dict:
    return {"schema_version": 1, "surface": surface, "role": role, "items": CATALOG.get((surface, role), [])}


async def broken_catalog(surface: str, role: str) -> dict:
    raise TimeoutError("provider timeout")


class Journal:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        self.events.append((kind, level, data or {}))


def _service(tmp_path: Path, settings: dict, *, environ: dict | None = None, catalog=fake_catalog,
             switch=None, after=None):
    store = FileSettingsStore(tmp_path)
    store.write(settings)
    switches: list = []

    def requester(previous, updated, observed):
        switches.append(updated)
        return {"request_id": "switch-1"}

    journal = Journal()
    graph = ArchitectureGraphService(tmp_path, store=store, environ=environ or {},
                                     observe=lambda: RuntimeObservations(None, JARVIS_DEFAULT, True),
                                     voice_switch=switch or requester, journal=journal)
    service = BrainConfigService(graph, catalog=catalog, environ=environ or {}, journal=journal,
                                 after_settings_write=after)
    return service, store, switches, journal


# ------------------------------------------------------------------ descripteurs


async def test_core_exposes_provider_model_instructions_delegation_and_a_read_only_mission(tmp_path):
    service, *_ = _service(tmp_path, {**DUPLEX, "agent_cli": "claude",
                                      "agent_cli_settings": {"claude": {"model": "claude-opus-5-5", "command": "C:/x"}}})
    config = await service.describe("core")
    fields = config["fields"]
    assert set(fields) == {"provider", "model", "instructions", "delegation", "mission", "activation"}
    assert fields["model"]["value"] == "claude-opus-5-5" and fields["model"]["owner"] == "agent_cli_settings.claude.model"
    assert fields["provider"]["value"] == "claude" and fields["provider"]["applies"] == "core_restart"
    assert [c["value"] for c in fields["model"]["choices"]] == ["", "claude-opus-5-5", "claude-haiku-5", "claude-retired-1"]
    retired = fields["model"]["choices"][-1]
    assert retired["available"] is False and retired["reason"] == "Modèle retiré par le fournisseur."
    assert fields["delegation"]["value"] == "standard" and fields["delegation"]["editable"] is True
    assert [c["value"] for c in fields["delegation"]["choices"]] == ["never", "rare", "standard", "proactive", "exploratory"]
    assert {item["mechanism"]: item["applies"] for item in fields["delegation"]["enforcement"]} == {
        "routing_hook": "live", "cli_disallowed_tools": "core_restart", "brain_prompt": "core_restart"}
    assert fields["instructions"]["prompt_id"] == "backend.system.addition" and fields["instructions"]["editable"]
    assert fields["mission"]["editable"] is False and fields["mission"]["value"]
    assert fields["activation"]["editable"] is False and fields["activation"]["reason"]
    assert "command" not in json.dumps(fields) and "permission_mode" not in json.dumps(fields)  # CLI technique hors contrat
    assert "voice.persona" not in json.dumps(config)  # aucune personnalité ici
    out = {c["id"] for c in config["connections"]["outgoing"]}
    assert "core.agents->subagents.spawn" in out and config["connections"]["edit_on"] == "graph"


async def test_voice_luna_and_tool_brain_declare_delegation_not_applicable_with_a_reason(tmp_path):
    service, *_ = _service(tmp_path, FRONT)
    for brain in ("voice", "luna", "tool_brain"):
        field = (await service.describe(brain))["fields"]["delegation"]
        assert field["value"] == "not_applicable" and field["editable"] is False and field["reason"]
    voice = (await service.describe("voice"))["fields"]
    assert voice["model"]["owner"] == "voice_architecture.config.reflex_model" and voice["model"]["applies"] == "voice_restart"
    assert voice["instructions"]["prompt_id"] == "voice.conversation.addition"
    luna = (await service.describe("luna"))["fields"]
    assert luna["model"]["value"] == "gpt-5.6-luna" and luna["instructions"]["prompt_id"] == "front_brain.analysis.addition"
    tool = (await service.describe("tool_brain"))["fields"]
    assert tool["instructions"]["editable"] is False and "catalogue des prompts" in tool["instructions"]["reason"]
    assert tool["activation"]["value"] == "off" and tool["activation"]["editable"] is True


async def test_luna_is_absent_outside_front_brain_and_an_unknown_brain_is_refused(tmp_path):
    service, *_ = _service(tmp_path, DUPLEX)
    with pytest.raises(BrainConfigError) as absent:
        await service.describe("luna")
    assert absent.value.code == "brain_config_brain_absent" and absent.value.status == 409
    with pytest.raises(BrainConfigError) as unknown:
        await service.describe("subagents")
    assert unknown.value.code == "brain_config_unknown_brain" and unknown.value.status == 404
    assert (await service.describe("voice"))["fields"]["instructions"]["prompt_id"] == "live.duplex.addition"


async def test_a_compatibility_architecture_shows_the_voice_model_read_only(tmp_path):
    service, *_ = _service(tmp_path, {})  # aucun réglage : architecture legacy projetée
    model = (await service.describe("voice"))["fields"]["model"]
    assert model["editable"] is False and model["owner"] == "voice_stack" and "Avancé" in model["reason"]


# ------------------------------------------------------------------ délégation


async def test_writing_never_persists_the_level_and_the_governed_graph_link_follows(tmp_path):
    service, *_ = _service(tmp_path, DUPLEX)
    before = await service.describe("core")
    link = next(c for c in before["connections"]["outgoing"] if c["id"] == "core.agents->subagents.spawn")
    assert link["enabled"] is True and link["mutability"] == "governed"
    result = await service.patch("core", {"base_revision": before["revision"], "delegation": "never"})
    assert result["changed"] is True and result["applies"] == "core_restart"
    after = result["config"]
    assert after["fields"]["delegation"]["value"] == "never" and after["revision"] != before["revision"]
    link = next(c for c in after["connections"]["outgoing"] if c["id"] == "core.agents->subagents.spawn")
    assert link["enabled"] is False
    snapshot = service.graph.snapshot()
    assert snapshot.connection("core.agents->subagents.spawn").enabled is False
    again = await service.patch("core", {"base_revision": after["revision"], "delegation": "standard"})
    assert service.graph.snapshot().connection("core.agents->subagents.spawn").enabled is True
    assert again["config"]["fields"]["delegation"]["value"] == "standard"


async def test_the_graph_revision_is_unchanged_by_the_default_and_changes_with_never(tmp_path):
    service, *_ = _service(tmp_path, DUPLEX)
    default = service.graph.snapshot().revision
    store = BrainConfigStore(tmp_path)
    store.set_delegation("core", DelegationTendency.STANDARD, base_revision="bc-0")
    assert service.graph.snapshot().revision == default  # standard = révision d'avant le réglage
    store.set_delegation("core", DelegationTendency.NEVER, base_revision="bc-1")
    assert service.graph.snapshot().revision != default


async def test_delegation_is_refused_on_a_brain_that_does_not_delegate(tmp_path):
    service, *_ = _service(tmp_path, DUPLEX)
    config = await service.describe("voice")
    with pytest.raises(BrainConfigError) as caught:
        await service.patch("voice", {"base_revision": config["revision"], "delegation": "never"})
    assert caught.value.code == "brain_config_field_unsupported" and "Core" in caught.value.reason


async def test_a_stale_revision_is_refused_and_nothing_is_written(tmp_path):
    service, store, *_ = _service(tmp_path, DUPLEX)
    config = await service.describe("core")
    BrainConfigStore(tmp_path).set_delegation("core", DelegationTendency.RARE, base_revision="bc-0")
    with pytest.raises(BrainConfigError) as caught:
        await service.patch("core", {"base_revision": config["revision"], "delegation": "never"})
    assert caught.value.code == "brain_config_revision_stale" and caught.value.status == 409
    assert (await service.describe("core"))["fields"]["delegation"]["value"] == "rare"
    # Une écriture d'une autre page dans les réglages (même fichier que /api/settings) périme aussi le modèle.
    config = await service.describe("core")
    store.write({**store.read(), "agent_cli_settings": {"claude": {"model": "claude-haiku-5"}}})
    with pytest.raises(BrainConfigError) as model_stale:
        await service.patch("core", {"base_revision": config["revision"], "model": "claude-opus-5-5"})
    assert model_stale.value.code == "brain_config_revision_stale"
    assert store.read()["agent_cli_settings"]["claude"]["model"] == "claude-haiku-5"


async def test_requests_are_validated_with_stable_codes(tmp_path):
    service, *_ = _service(tmp_path, DUPLEX)
    revision = (await service.describe("core"))["revision"]
    cases = [
        ({"base_revision": revision}, "brain_config_request_invalid"),
        ({"base_revision": revision, "delegation": "sometimes"}, "brain_config_delegation_invalid"),
        ({"base_revision": revision, "delegation": "never", "model": ""}, "brain_config_request_invalid"),
        ({"base_revision": revision, "persona": "drôle"}, "brain_config_request_invalid"),
        ({"base_revision": revision, "activation": "active"}, "brain_config_field_unsupported"),
        ({"base_revision": revision, "mission": "Autre"}, "brain_config_field_unsupported"),
    ]
    for body, code in cases:
        with pytest.raises(BrainConfigError) as caught:
            await service.patch("core", body)
        assert caught.value.code == code, body


# ------------------------------------------------------------------ modèles et catalogue


async def test_the_core_model_is_written_to_its_existing_owner_and_cli_fields_are_untouched(tmp_path):
    applied: list = []
    service, store, *_ = _service(tmp_path, {**DUPLEX, "agent_cli_settings": {"claude": {
        "model": "", "command": "C:/bin/claude.exe", "permission_mode": "acceptEdits"}}}, after=applied.append)
    config = await service.describe("core")
    result = await service.patch("core", {"base_revision": config["revision"], "model": "claude-opus-5-5"})
    assert result["changed"] is True
    saved = store.read()["agent_cli_settings"]["claude"]
    assert saved == {"model": "claude-opus-5-5", "command": "C:/bin/claude.exe", "permission_mode": "acceptEdits"}
    assert store.read()["agent_cli"] == "claude" and len(applied) == 1
    assert "brain_config" not in store.read()  # aucune copie dans les réglages


async def test_an_unavailable_or_unlisted_model_is_refused_with_its_reason(tmp_path):
    service, store, *_ = _service(tmp_path, DUPLEX)
    revision = (await service.describe("core"))["revision"]
    with pytest.raises(BrainConfigError) as retired:
        await service.patch("core", {"base_revision": revision, "model": "claude-retired-1"})
    assert retired.value.code == "brain_config_model_unavailable" and "retiré" in retired.value.reason
    with pytest.raises(BrainConfigError) as invented:
        await service.patch("core", {"base_revision": revision, "model": "gpt-4o"})
    assert invented.value.code == "brain_config_model_unavailable"
    with pytest.raises(BrainConfigError) as cli:
        await service.patch("core", {"base_revision": revision, "provider": "codex"})
    assert cli.value.code == "brain_config_model_unavailable" and "Codex" in cli.value.reason
    assert "agent_cli_settings" not in store.read()


async def test_a_saved_model_missing_from_the_catalog_stays_visible_and_a_down_catalog_refuses_writes(tmp_path):
    settings = {**DUPLEX, "agent_cli_settings": {"claude": {"model": "claude-old-0"}}}
    service, *_ = _service(tmp_path, settings)
    choices = (await service.describe("core"))["fields"]["model"]["choices"]
    assert choices[-1]["value"] == "claude-old-0" and choices[-1]["available"] is False and choices[-1]["reason"]
    down, *_ = _service(tmp_path / "down", settings, catalog=broken_catalog)
    config = await down.describe("core")
    assert config["catalog"]["status"] == "unavailable" and "TimeoutError" in config["catalog"]["reason"]
    assert config["fields"]["model"]["value"] == "claude-old-0"  # lisible sans catalogue
    with pytest.raises(BrainConfigError) as caught:
        await down.patch("core", {"base_revision": config["revision"], "model": "claude-opus-5-5"})
    assert caught.value.code == "brain_config_catalog_unavailable" and caught.value.status == 503
    # La valeur en place, même absente du catalogue, se renvoie sans refus ni écriture.
    same = await down.patch("core", {"base_revision": config["revision"], "model": "claude-old-0"})
    assert same["changed"] is False
    # Revenir au défaut du CLI reste possible : ce choix ne dépend d'aucun fournisseur.
    assert (await down.patch("core", {"base_revision": config["revision"], "model": ""}))["changed"] is True


async def test_the_voice_model_write_validates_the_composition_and_requests_a_voice_switch(tmp_path):
    service, store, switches, _ = _service(tmp_path, SIMPLE)
    config = await service.describe("voice")
    result = await service.patch("voice", {"base_revision": config["revision"], "model": "gpt-realtime-2.1-mini"})
    assert result["changed"] is True and result["applies"] == "voice_restart"
    saved = store.read()["voice_architecture"]["config"]["conversation_model"]
    assert saved == {"provider_id": "openai", "model_id": "gpt-realtime-2.1-mini"} and len(switches) == 1


async def test_a_catalog_model_the_voice_runtime_cannot_run_is_refused_before_any_write(tmp_path):
    service, store, switches, _ = _service(tmp_path, DUPLEX)
    config = await service.describe("voice")
    with pytest.raises(BrainConfigError) as caught:  # listé par le fournisseur, mais aucun adaptateur Duplex
        await service.patch("voice", {"base_revision": config["revision"], "model": "gpt-live-2"})
    assert caught.value.code == "brain_config_model_unavailable" and "rien n'a été écrit" in caught.value.reason
    assert store.read()["voice_architecture"] == DUPLEX["voice_architecture"] and switches == []


async def test_a_failed_voice_switch_restores_the_previous_model(tmp_path):
    def failing(previous, updated, observed):
        raise OSError("switch bus unwritable")

    service, store, *_ = _service(tmp_path, FRONT, switch=failing)
    config = await service.describe("voice")
    with pytest.raises(BrainConfigError) as caught:
        await service.patch("voice", {"base_revision": config["revision"], "model": "gpt-realtime-2.1-mini"})
    assert caught.value.code == "brain_config_write_failed" and "rétabli" in caught.value.reason
    assert store.read()["voice_architecture"]["config"]["reflex_model"]["model_id"] == "gpt-realtime-2.1"


# ------------------------------------------------------------------ Tool Brain


async def test_the_tool_brain_model_is_a_persistent_setting_read_by_the_decider(tmp_path):
    service, store, *_ = _service(tmp_path, DUPLEX)
    config = await service.describe("tool_brain")
    assert config["fields"]["model"]["value"] == "haiku" and config["fields"]["model"]["source"] == "default"
    await service.patch("tool_brain", {"base_revision": config["revision"], "model": "claude-haiku-5"})
    assert store.read()["tool_brain"] == {"model": "claude-haiku-5"}
    assert tool_brain_model_name({}, store.read()) == "claude-haiku-5"
    config = await service.describe("tool_brain")
    await service.patch("tool_brain", {"base_revision": config["revision"], "model": ""})
    assert store.read()["tool_brain"] == {} and tool_brain_model_name({}, store.read()) == "haiku"


async def test_an_environment_tool_brain_model_wins_and_locks_the_field(tmp_path):
    env = {"JARVIS_TOOL_BRAIN_MODEL": "opus"}
    service, store, *_ = _service(tmp_path, {**DUPLEX, "tool_brain": {"model": "claude-haiku-5"}}, environ=env)
    config = await service.describe("tool_brain")
    model = config["fields"]["model"]
    assert (model["value"], model["source"], model["editable"]) == ("opus", "env", False)
    assert "JARVIS_TOOL_BRAIN_MODEL=opus" in model["reason"]
    with pytest.raises(BrainConfigError) as caught:
        await service.patch("tool_brain", {"base_revision": config["revision"], "model": "claude-opus-5-5"})
    assert caught.value.code == "brain_config_field_locked" and caught.value.status == 423
    assert tool_brain_model_name(env, store.read()) == "opus"


async def test_tool_brain_activation_goes_through_the_graph_writer(tmp_path):
    service, store, _, journal = _service(tmp_path, DUPLEX)
    config = await service.describe("tool_brain")
    result = await service.patch("tool_brain", {"base_revision": config["revision"], "activation": "active"})
    assert result["changed"] is True and result["applies"] == "core_restart"
    assert store.read()["tool_brain"]["mode"] == "active"
    assert any(kind == "architecture.tool_brain.updated" for kind, _, _ in journal.events)
    assert service.graph.snapshot().connection("core.events->tool_brain.wake").pending is not None
    locked, *_ = _service(tmp_path / "env", DUPLEX, environ={"JARVIS_TOOL_BRAIN": "shadow"})
    config = await locked.describe("tool_brain")
    assert config["fields"]["activation"]["editable"] is False
    with pytest.raises(BrainConfigError) as caught:
        await locked.patch("tool_brain", {"base_revision": config["revision"], "activation": "off"})
    assert caught.value.code == "brain_config_field_locked"


# ------------------------------------------------------------------ instructions


async def test_instructions_use_the_prompt_override_mechanism_and_its_revisions(tmp_path):
    service, store, *_ = _service(tmp_path, DUPLEX)
    config = await service.describe("core")
    field = config["fields"]["instructions"]
    result = await service.patch("core", {"base_revision": config["revision"], "instructions": {
        "text": "Toujours citer la source.", "effective_revision": field["effective_revision"]}})
    assert result["changed"] is True
    saved = store.read()["prompt_overrides"]["overrides"]["backend.system.addition"]
    assert saved["text"] == "Toujours citer la source."
    assert result["config"]["fields"]["instructions"]["value"] == "Toujours citer la source."
    with pytest.raises(BrainConfigError) as stale:  # révision d'avant : modifiée depuis
        await service.patch("core", {"base_revision": result["config"]["revision"], "instructions": {
            "text": "Autre.", "effective_revision": field["effective_revision"]}})
    assert stale.value.code == "prompt_override_concurrent" and stale.value.status == 409
    with pytest.raises(BrainConfigError) as missing:
        await service.patch("core", {"base_revision": result["config"]["revision"], "instructions": {"text": "x"}})
    assert missing.value.code == "brain_config_request_invalid"


# ------------------------------------------------------------------ routes


async def test_routes_serve_the_descriptor_and_coded_refusals(tmp_path):
    service, _, _, journal = _service(tmp_path, DUPLEX)
    app = web.Application()
    app.add_routes(BrainConfigRoutes(service, journal=journal).routes())
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/api/brains/core/config")
        assert response.status == 200
        config = await response.json()
        assert config["brain_id"] == "core"
        ok = await client.patch("/api/brains/core/config",
                                json={"base_revision": config["revision"], "delegation": "proactive"})
        body = await ok.json()
        assert ok.status == 200 and body["ok"] is True and body["config"]["fields"]["delegation"]["value"] == "proactive"
        stale = await client.patch("/api/brains/core/config", json={"base_revision": config["revision"],
                                                                    "delegation": "never"})
        refused = await stale.json()
        assert stale.status == 409 and refused["code"] == "brain_config_revision_stale" and refused["config"]
        assert (await client.get("/api/brains/nope/config")).status == 404
        absent = await client.get("/api/brains/luna/config")
        assert absent.status == 409 and (await absent.json())["code"] == "brain_config_brain_absent"
        garbled = await client.patch("/api/brains/core/config", data=b"{oops", headers={"Content-Type": "application/json"})
        assert garbled.status == 400 and (await garbled.json())["code"] == "brain_config_request_invalid"
    kinds = [kind for kind, _, _ in journal.events]
    assert "brain_config.read" in kinds and "brain_config.saved" in kinds and "brain_config.rejected" in kinds


# ------------------------------------------------------------------ fixtures (Slice 05)


@pytest.mark.parametrize(("name", "brain", "settings"), [
    ("brain_config_core.json", "core", {**DUPLEX, "agent_cli": "claude",
                                        "agent_cli_settings": {"claude": {"model": "claude-opus-5-5"}}}),
    ("brain_config_voice.json", "voice", DUPLEX),
])
async def test_ui_fixtures_are_the_service_output(tmp_path, name, brain, settings):
    service, *_ = _service(tmp_path, settings)
    config = await service.describe(brain)
    # Les révisions d'un prompt du catalogue incluent le chemin absolu de son module (`prompt_catalog._path`) : elles
    # diffèrent d'une copie du dépôt à l'autre. La fixture les remplace par un jeton ; le contrat est leur présence.
    instructions = config["fields"]["instructions"]
    for key in ("effective_revision", "default_revision"):
        assert isinstance(instructions[key], str) and instructions[key]
        instructions[key] = f"<{key}>"
    produced = json.dumps(config, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    path = FIXTURES / name
    if os.environ.get("JARVIS_WRITE_BRAIN_CONFIG_FIXTURES") == "1":
        path.write_text(produced, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == produced, f"{name} est périmée : régénérez-la (voir le docstring)"
