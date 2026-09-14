from __future__ import annotations

import json
from pathlib import Path

from jarvis.runtime import agent_routing, cli_catalog, voice_stack
from jarvis.runtime.voice_capabilities import default_voice_registry


CONTRACT_PATH = (
    Path(__file__).parents[2]
    / "tasks"
    / "jarvis-settings-model-catalog-ux"
    / "docs"
    / "settings-ia-contract.json"
)
MIGRATION_FIXTURE_PATH = CONTRACT_PATH.parents[1] / "slices" / "01-settings-ia-contract" / "fixtures" / "aiguillage-migration.json"


def contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_every_option_has_rendering_and_runtime_metadata() -> None:
    data = contract()
    required = set(data["option_metadata_contract"]["required"])
    options = [data["agent_cli"]["delegation_mode"], *data["agent_cli"]["settings"], *data["voice"]["settings"]]

    assert all(required <= set(option) for option in options)
    assert len({option["id"] for option in data["agent_cli"]["settings"]}) == len(data["agent_cli"]["settings"])
    assert len({option["id"] for option in data["voice"]["settings"]}) == len(data["voice"]["settings"])
    assert all("Aiguillage" not in option["destination"] for option in options)

    for option in options:
        if option["type"] == "enum":
            identifiers = [entry["id"] if isinstance(entry, dict) else entry for entry in option["options"]]
            if option["default"] is None:
                assert option.get("placeholder")
            else:
                assert option["default"] in identifiers
        if option["type"].startswith("number"):
            assert "minimum" in option and "maximum" in option

    voice = {item["id"]: item for item in data["voice"]["settings"]}
    assert voice["owner_threshold"]["exclusive_minimum"] == 0.0


def test_live_agent_cli_inventory_is_complete_and_behavior_controls_are_not_placebos() -> None:
    data = contract()
    settings = {item["id"]: item for item in data["agent_cli"]["settings"]}

    assert set(data["agent_cli"]["profiles"]) == {"desktop", "code", "fast", "general"}
    assert {spec.id for spec in cli_catalog.AGENT_CLIS} == set(settings["agent_cli"]["options"])
    assert {"command", "model", "permission_mode"} <= set(settings)
    assert settings["response_verbosity"]["runtime_status"] == "live"
    assert settings["politeness_formality"]["runtime_status"] == "live"
    assert settings["response_verbosity"]["default"] == settings["politeness_formality"]["default"] == "inherit"


def test_live_voice_stack_and_architecture_fields_are_mapped_once() -> None:
    data = contract()
    persisted = [item["persistence"] for item in data["voice"]["settings"]]

    for spec in voice_stack.VOICE_STACKS:
        expected = {f"voice_stack_settings.{spec.id}.{field.key}" for field in spec.fields}
        actual = {item for item in persisted if item.startswith(f"voice_stack_settings.{spec.id}.")}
        assert actual == expected

    architecture = default_voice_registry().settings_architectures()
    expected_architecture = {
        f"voice_architecture.config.{field['key']}"
        for profile in architecture
        for field in profile["fields"]
    } | {"voice_architecture.config.architecture"}
    actual_architecture = {item for item in persisted if item.startswith("voice_architecture.config.")}
    assert actual_architecture == expected_architecture

    external = {
        item for item in persisted
        if not item.startswith("voice_stack_settings.") and not item.startswith("voice_architecture.config.")
    }
    assert external == {
        "voice_stack", "voice_arch", "conversation_mode", "speaker_verification", "owner_buffer_ms",
        "owner_threshold", "owner_evidence_ms", "owner_short_evidence_ms", "owner_short_margin",
        "owner_profile_path", "audio_input_device", "audio_output_device", "active_timeout_s",
        "shortcuts.wake_toggle",
    }

    writable = [item for item in data["voice"]["settings"] if not item.get("readonly")]
    assert len({item["persistence"] for item in writable}) == len(writable)


def test_delegation_projection_preserves_compatibility_and_single_winner_contract() -> None:
    mode = contract()["agent_cli"]["delegation_mode"]

    assert mode["mapping"] == {"auto": True, "duplicate": False}
    assert mode["default"] == "duplicate"
    assert mode["host_agent_scope"] == "active_cli_only"
    assert mode["cross_cli_policy"] == "self_development_only"
    assert mode["max_subagent_calls_per_tool_call"] == 1


def test_migration_has_no_read_write_and_removes_old_navigation_vocabulary() -> None:
    data = contract()
    rules = data["migration"]["rules"]

    assert all(rule["write"] == "none on read" for rule in rules[:2])
    agent_navigation = next(item for item in data["navigation"] if item["id"] == "agent_cli")
    assert "routing" in agent_navigation["replaces"]
    assert all(item["label"] != "Aiguillage" for item in data["navigation"])


def test_aiguillage_migration_fixture_is_a_non_mutating_projection() -> None:
    cases = json.loads(MIGRATION_FIXTURE_PATH.read_text(encoding="utf-8"))["cases"]

    for case in cases:
        before = json.loads(json.dumps(case["saved"]))
        projected = agent_routing.delegation_mode(case["saved"])

        assert projected == case["expected_delegation_mode"]
        assert case["saved"] == before


def test_behavior_bound_has_stable_settings_and_prompt_rejection_contracts() -> None:
    events = {item["event"]: item for item in contract()["observability_test_contract"]["future_expected_events"]}
    code = "agent_settings_behavior_prompt_too_large"

    assert code in events["settings.agent.rejected"]["slice_02_stable_codes"]
    assert events["prompt.override.rejected"]["slice_02_stable_codes"] == [code]
    assert "AgentBehaviorError" in events["settings.agent.rejected"]["code_scope"]
    identity = {
        "program_id", "prompt_ids", "layer_revisions", "static_fingerprint",
        "render_fingerprint", "channel", "application",
    }
    assert set(events["agent.prompt"]["required_data"]) == identity
    assert set(events["job.agent.prompt"]["required_data"]) == identity | {"job_id"}
