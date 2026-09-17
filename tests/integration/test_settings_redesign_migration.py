from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.domain import routing
from jarvis.domain.routing import CandidateRef, ModelCandidate
from jarvis.runtime import agent_routing, routing_hook
from jarvis.runtime.catalog_view import CatalogViewService
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.voice_capabilities import default_voice_registry


ROOT = Path(__file__).parents[2]
PAGE = ROOT / "jarvis" / "runtime" / "control_center.html"
IA_CONTRACT = (
    ROOT
    / "tasks"
    / "jarvis-settings-model-catalog-ux"
    / "docs"
    / "settings-ia-contract.json"
)
FIXTURE = (
    ROOT
    / "tasks"
    / "jarvis-settings-model-catalog-ux"
    / "slices"
    / "07-e2e-migration-docs"
    / "fixtures"
    / "pre-redesign-settings.json"
)
NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


def fixture_data() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def case_ids() -> list[str]:
    return [case["id"] for case in fixture_data()["settings_cases"]]


def case_by_id(identifier: str) -> dict:
    return next(case for case in fixture_data()["settings_cases"] if case["id"] == identifier)


def control_for(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: dict) -> ControlCenter:
    for name in (
        "JARVIS_VOICE_ARCH", "JARVIS_VOICE_STACK", "JARVIS_AGENT_CLI",
        "OPENAI_REALTIME_MODEL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    runtime_root = tmp_path / case["id"]
    runtime_root.mkdir(parents=True)
    (runtime_root / "control-center-settings.json").write_text(
        json.dumps(case["saved"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return ControlCenter(runtime_root=runtime_root, project_root=tmp_path)


def run_node(tmp_path: Path, data: object, source: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    data_path = tmp_path / "settings-migration-data.json"
    script_path = tmp_path / "settings-migration.cjs"
    data_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    script_path.write_text(
        "const data=JSON.parse(require('node:fs').readFileSync(process.argv[2],'utf8'));" + source,
        encoding="utf-8",
    )
    result = subprocess.run(
        [node, str(script_path), str(data_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def ui_draft(tmp_path: Path, data: dict) -> dict:
    page = PAGE.read_text(encoding="utf-8")
    source = page[page.index("function draftFrom(data)") : page.index("async function openSettings()")]
    return run_node(
        tmp_path,
        data,
        "const SET={architectureDirty:true};"
        + source
        + "const draft=draftFrom(data);process.stdout.write(JSON.stringify({draft,architectureDirty:SET.architectureDirty}));",
    )


def stored(control: ControlCenter) -> dict:
    return json.loads(control.settings_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case_id", case_ids())
async def test_pre_redesign_get_agent_save_reload_is_non_mutating_and_lossless(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_id: str,
):
    case = case_by_id(case_id)
    control = control_for(tmp_path, monkeypatch, case)
    disk_before_get = control.settings_path.read_bytes()

    canonical = json.loads((await control.get_settings(None)).text)

    assert control.settings_path.read_bytes() == disk_before_get
    assert canonical["cli"]["delegation_mode"] == case["expected_mode"]
    assert canonical["voice"]["effective_stack"] == case["expected_effective_stack"]
    migration = ui_draft(tmp_path, canonical)
    assert migration["architectureDirty"] is False
    draft = migration["draft"]
    target_mode = "duplicate" if case["expected_mode"] == "auto" else "auto"
    draft["cli"]["delegation_mode"] = target_mode
    draft["cli"]["behavior"] = {
        "response_verbosity": "detailed",
        "politeness_formality": "formal",
    }

    await control.save_settings(JsonRequest(draft))
    reloaded_control = ControlCenter(runtime_root=control.runtime_root, project_root=tmp_path)
    reloaded = json.loads((await reloaded_control.get_settings(None)).text)
    saved = stored(reloaded_control)

    assert reloaded["cli"]["delegation_mode"] == target_mode
    assert reloaded["cli"]["behavior"]["values"] == draft["cli"]["behavior"]
    assert saved["future_extension"] == case["saved"]["future_extension"]
    assert saved.get("voice_architecture") == case["saved"].get("voice_architecture")
    for stack_id, values in case["saved"].get("voice_stack_settings", {}).items():
        for key, value in values.items():
            assert saved["voice_stack_settings"][stack_id][key] == value
    for profile, values in case["saved"].get("agent_routing", {}).get("profiles", {}).items():
        assert saved["agent_routing"]["profiles"][profile]["candidates"] == values["candidates"]
    original_cli = case["saved"].get("agent_cli_settings", {}).get("claude", {})
    if "future_cli" in original_cli:
        assert saved["agent_cli_settings"]["claude"]["future_cli"] == original_cli["future_cli"]


async def test_all_seven_voice_categories_round_trip_and_keep_inactive_stack_extensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    case = case_by_id("legacy-auto-openai")
    control = control_for(tmp_path, monkeypatch, case)
    canonical = json.loads((await control.get_settings(None)).text)
    assert [category["id"] for category in canonical["voice"]["categories"]] == [
        "architecture", "conversation", "turn_taking", "models", "audio", "advanced", "diagnostic",
    ]
    diagnostics = [
        item for item in canonical["voice"]["option_metadata"] if item["category"] == "diagnostic"
    ]
    assert diagnostics and all(item["readonly"] for item in diagnostics)

    draft = ui_draft(tmp_path, canonical)["draft"]
    duplex = next(
        profile for profile in canonical["voice"]["architecture"]["architectures"]
        if profile["id"] == "duplex"
    )
    draft["voice"]["architecture"] = duplex["defaults"]
    draft["voice"]["arch"] = "legacy"
    draft["voice"]["settings"]["openai_realtime"].update({
        "model": "saved-after-redesign",
        "voice": "sage",
        "transcription_language": "en",
        "noise_reduction": "near_field",
        "vad_threshold": 0.65,
        "ack_delay_ms": 500,
    })
    draft["voice"]["authorization"] = {
        "conversation_mode": "open_room",
        "speaker_verification": "off",
        "owner_buffer_ms": 2800,
        "owner_threshold": 0.6,
        "owner_evidence_ms": 1700,
        "owner_short_evidence_ms": 700,
        "owner_short_margin": 0.12,
    }
    draft["audio"] = {"input_device": "4", "output_device": "8", "active_timeout_s": "75"}

    await control.save_settings(JsonRequest(draft))
    await control.save_shortcuts(JsonRequest({"shortcuts": {"wake_toggle": "f11"}}))
    reloaded = ControlCenter(runtime_root=control.runtime_root, project_root=tmp_path)
    projected = json.loads((await reloaded.get_settings(None)).text)
    saved = stored(reloaded)

    assert projected["voice"]["architecture"]["selection"]["config"] == duplex["defaults"]
    assert projected["voice"]["effective_stack"] == "openai_realtime"
    openai = projected["voice"]["settings"]["openai_realtime"]
    assert {key: openai[key] for key in (
        "model", "voice", "transcription_language", "noise_reduction", "vad_threshold", "ack_delay_ms",
    )} == {
        "model": "saved-after-redesign", "voice": "sage", "transcription_language": "en",
        "noise_reduction": "near_field", "vad_threshold": 0.65, "ack_delay_ms": 500,
    }
    assert projected["audio"] == {"input_device": "4", "output_device": "8", "active_timeout_s": "75"}
    assert projected["shortcuts"]["values"]["wake_toggle"] == "f11"
    assert saved["owner_threshold"] == 0.6 and saved["owner_buffer_ms"] == 2800
    assert saved["voice_stack_settings"]["gemini_live"]["voice"] == "Kore"
    assert saved["voice_stack_settings"]["gemini_live"]["future_transport"] == {"keep": "inactive-gemini"}
    assert saved["voice_stack_settings"]["openai_realtime"]["future_transport"] == {"keep": "openai-nested"}
    assert not ({item["id"] for item in diagnostics} - {"owner_profile_path"}) & set(saved)


async def test_production_save_draft_only_sends_architecture_after_user_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    control = control_for(tmp_path, monkeypatch, case_by_id("legacy-duplicate-gemini"))
    data = json.loads((await control.get_settings(None)).text)
    page = PAGE.read_text(encoding="utf-8")
    draft_source = page[page.index("function draftFrom(data)") : page.index("async function openSettings()")]
    save_source = page[page.index("async function saveDraft(options)") : page.index("modalSave.addEventListener")]
    result = run_node(
        tmp_path,
        data,
        r"""
        const calls=[];const modalSave={disabled:false};const SET={architectureDirty:false,shortcuts:data.shortcuts};
        const say=()=>{},renderTab=async()=>{};
        const api=async(_path,options)=>{calls.push(JSON.parse(options.body));return data};
        """
        + draft_source
        + save_source
        + r"""
        (async()=>{
          SET.draft=draftFrom(data);await saveDraft({silent:true});
          SET.draft=draftFrom(data);SET.draft.voice.architecture=data.voice.architecture.architectures.find(item=>item.id==='duplex').defaults;SET.architectureDirty=true;
          await saveDraft({silent:true});process.stdout.write(JSON.stringify(calls));
        })().catch(error=>{console.error(error);process.exitCode=1});
        """,
    )

    assert "architecture" not in result[0]["voice"]
    assert result[1]["voice"]["architecture"]["architecture"] == "duplex"


def test_auto_and_duplicate_smoke_keep_one_host_agent_call_and_never_fan_out():
    saved = case_by_id("legacy-auto-openai")["saved"]
    policy = agent_routing.load_policy(saved)
    candidates = [
        ModelCandidate("claude", "available", "Claude available", "anthropic", frozenset({routing.CODE}), True),
        ModelCandidate("claude", "disappeared", "Claude missing", "anthropic", frozenset({routing.CODE}), False, "missing"),
        ModelCandidate("codex", "unknown", "Codex unknown", "openai", frozenset({routing.CODE}), True),
    ]
    event = {
        "tool_name": "Agent",
        "tool_use_id": "toolu-migration-1",
        "tool_input": {"description": "[code] migration smoke", "prompt": "one task", "model": "caller-choice"},
    }

    output, decision = routing_hook.decide(event, policy, candidates)

    assert decision is not None and (decision.agent, decision.model) == ("claude", "available")
    assert output["hookSpecificOutput"]["updatedInput"] == {"model": "available"}
    assert "codex" not in json.dumps(output)
    duplicate_settings = json.loads(json.dumps(saved))
    agent_routing.apply_delegation_mode(duplicate_settings, "duplicate")
    duplicate_output, duplicate_decision = routing_hook.decide(
        event, agent_routing.load_policy(duplicate_settings), candidates,
    )
    assert duplicate_output == {}
    assert duplicate_decision is not None and duplicate_decision.reason == routing.REASON_COMPATIBILITY
    assert event["tool_input"]["model"] == "caller-choice"


async def test_behavior_survives_reload_and_runtime_evidence_contains_identity_not_prompt_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    control = control_for(tmp_path, monkeypatch, case_by_id("legacy-duplicate-gemini"))
    await control.save_settings(JsonRequest({"cli": {"behavior": {
        "response_verbosity": "concise", "politeness_formality": "formal",
    }}}))
    reloaded = ControlCenter(runtime_root=control.runtime_root, project_root=tmp_path)
    messages: list[str] = []
    evidence: list[dict] = []

    async def send(
        text: str, *, prompt_evidence: dict | None = None, input_text: str | None = None,
    ) -> dict:
        messages.append(text)
        if prompt_evidence is not None:
            evidence.append(prompt_evidence)
        assert input_text == "migration secret sentence"
        return {"ok": True}

    reloaded.agent.send = send  # type: ignore[assignment]
    await reloaded.agent_send(JsonRequest({"text": "migration secret sentence"}))

    assert reloaded._settings()["agent_behavior"] == {
        "response_verbosity": "concise", "politeness_formality": "formal",
    }
    assert "Réponds de façon concise" in messages[0] and "Adopte un ton formel" in messages[0]
    assert len(evidence) == 1
    assert {
        "program_id", "prompt_ids", "layer_revisions", "static_fingerprint",
        "render_fingerprint", "channel", "application",
    } <= set(evidence[0])
    serialized = json.dumps(evidence[0], ensure_ascii=False)
    assert "migration secret sentence" not in serialized
    assert "Réponds de façon concise" not in serialized


@pytest.mark.parametrize("case", fixture_data()["catalog_cases"], ids=lambda case: case["id"])
def test_catalog_migration_truth_states_are_source_backed_and_offer_no_fake_actions(case: dict):
    view = CatalogViewService().subagents(
        agents=[case["agent"]],
        catalogs={"anthropic": case["catalog"]},
        saved=[CandidateRef("claude", case["saved_model"])],
        now=NOW,
    ).to_dict()
    item = next(entry for entry in view["items"] if entry["identity"]["model_id"] == case["saved_model"])

    assert item["availability"]["state"] == case["expected_state"]
    assert item["availability"]["evidence"]
    assert all(entry["actions"] == [] for entry in view["items"])
    assert "requestable" not in json.dumps(view).lower()


def test_voice_catalog_unknown_credentials_never_promotes_or_offers_request_actions():
    view = CatalogViewService().voice(
        registry=default_voice_registry(),
        catalogs={
            "openai": {"source": "catalog_no_key", "status_code": "catalog_no_key", "models": []},
            "google": {"source": "unknown", "status_code": "catalog_unreachable", "models": []},
        },
        now=NOW,
    ).to_dict()

    assert {item["availability"]["state"] for item in view["items"]} <= {"configured_unverified", "unknown"}
    assert all(not item["availability"]["selectable"] and item["actions"] == [] for item in view["items"])
    assert "requestable" not in json.dumps(view).lower()


async def test_assembled_primary_navigation_has_six_tabs_and_no_legacy_navigation(tmp_path: Path):
    served = (await ControlCenter(runtime_root=tmp_path, project_root=tmp_path).index(None)).text
    scripts = "\n".join(re.findall(r"<script>(.*?)</script>", served, re.S))
    tabs = scripts[scripts.index("const TABS=") : scripts.index("const SET=")]
    install = scripts[scripts.index("  function installSettingsTab()") : scripts.index("  function bridgeStatusApi()")]
    rendered = run_node(
        tmp_path,
        {},
        tabs
        + r"""
        const SET={tab:'voice'},modalSave={style:{}},modalSub={textContent:''},modalContent={innerHTML:''};
        const cleanupSettingsSurface=()=>{},appearanceHtml=()=>'',bindAppearance=()=>{},say=()=>{};
        let renderTab=async()=>{};
        """
        + install
        + "installSettingsTab();process.stdout.write(JSON.stringify(TABS.map(({id,label})=>({id,label}))));",
    )

    assert rendered == [
        {"id": "voice", "label": "Voix"},
        {"id": "prompts", "label": "Prompts"},
        {"id": "cli", "label": "Agent / CLI"},
        {"id": "keys", "label": "API Keys"},
        {"id": "shortcuts", "label": "Raccourcis"},
        {"id": "appearance", "label": "Apparence"},
    ]
    contract_navigation = json.loads(IA_CONTRACT.read_text(encoding="utf-8"))["navigation"]
    assert [item["label"] for item in contract_navigation] == [item["label"] for item in rendered]
    assert [item["id"] for item in contract_navigation] == [
        "voice", "prompts", "agent_cli", "credentials", "shortcuts", "appearance",
    ]
    assert "Aiguillage" not in served
    assert "id:'routing'" not in tabs and "id:'config'" not in tabs
    assert "function tabConfig" not in served
