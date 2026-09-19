"""Barehands en mode test : réglage persistant et assets servis à la page.

Le serveur ne suit aucune main : il garde l'interrupteur (éteint par défaut,
rangé dans le fichier de réglages commun, refusé en HTTP 400 avec un code
stable s'il est mal formé) et ne sert à la page que la liste blanche des
fichiers MediaPipe vendorisés.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from aiohttp import web
import pytest

from jarvis.runtime import barehands_test_mode as barehands
from jarvis.runtime.control_center import BAREHANDS_SCRIPT_MARKER, SETTINGS_ERROR_CODE_HEADER, ControlCenter
from jarvis.runtime.journal import read_jsonl_tail


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class AssetRequest:
    def __init__(self, asset: str) -> None:
        self.match_info = {"asset": asset}


def install_assets(root: Path, names=barehands.REQUIRED_ASSETS) -> None:
    for name in names:
        relative, _ = barehands.ASSETS[name]
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"asset:" + name.encode())


@pytest.fixture
def vendor(tmp_path) -> Path:
    return tmp_path / "vendor"


@pytest.fixture
def control(tmp_path, vendor, monkeypatch):
    monkeypatch.delenv(barehands.VENDOR_ENV, raising=False)
    runtime = tmp_path / "runtime"
    return ControlCenter(runtime_root=runtime, project_root=tmp_path, barehands_vendor_root=vendor)


async def state_of(control: ControlCenter) -> dict:
    return json.loads((await control.get_barehands(None)).text)


# ------------------------------------------------------------------ réglage


def test_the_setting_is_off_by_default_and_any_doubtful_value_reads_as_off():
    assert barehands.load({}) == barehands.SETTINGS_DEFAULTS
    assert barehands.load({"barehands_test_mode": {"enabled": "true"}})["enabled"] is False
    assert barehands.load({"barehands_test_mode": True})["enabled"] is False
    assert barehands.load({"barehands_test_mode": {"enabled": True}})["enabled"] is True


def test_a_version_one_block_is_migrated_and_a_foreign_one_is_not_acted_upon():
    """La couture de migration, côté serveur.

    Un bloc v1 ne portait que `enabled` : le convertir, c'est donner leur
    défaut aux huit clés qu'il n'avait pas. Une version **étrangère**, elle,
    ne se devine pas — on n'en garde rien plutôt que d'agir sur des réglages
    qu'on ne sait pas lire, et le refus codé arrive à l'écriture.
    """

    migrated = barehands.load({"barehands_test_mode": {"enabled": True}})
    assert migrated["enabled"] is True
    assert migrated["tool"] == "pointer" and migrated["sleep_timeout_ms"] == 30000
    assert set(migrated) == set(barehands.SETTINGS_DEFAULTS)

    stranger = barehands.load({"barehands_test_mode": {"schema_version": 99, "enabled": True, "tool": "pan"}})
    assert stranger == barehands.SETTINGS_DEFAULTS
    assert stranger["enabled"] is False, "on n'allume pas Bare Hands sur des réglages illisibles"

    settings = {"barehands_test_mode": {"schema_version": 99, "enabled": True}}
    with pytest.raises(barehands.BarehandsSettingsError) as caught:
        barehands.apply(settings, {"enabled": True, "schema_version": 99})
    assert caught.value.code == "barehands_schema_version_unsupported"


def test_a_stored_value_out_of_range_or_of_the_wrong_type_falls_back_to_its_default():
    """Lecture **tolérante** : un fichier abîmé ne rend pas Bare Hands
    injoignable. C'est l'écriture qui refuse, pas la lecture."""

    loaded = barehands.load({"barehands_test_mode": {
        "schema_version": 2, "enabled": True, "sleep_timeout_ms": "beaucoup",
        "assistance": 9, "sensitivity": -4, "tool": "draw", "diagnostics": "oui",
    }})
    assert loaded["enabled"] is True
    assert loaded["sleep_timeout_ms"] == 30000, "un nombre illisible vaut le défaut"
    assert loaded["assistance"] == 1.0 and loaded["sensitivity"] == 0.25, "hors bornes : borné"
    assert loaded["tool"] == "pointer", "un outil sans moteur ne se relit pas comme actif"
    assert loaded["diagnostics"] is False


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (None, "barehands_bad_payload"),
        ([True], "barehands_bad_payload"),
        ({}, "barehands_enabled_missing"),
        ({"enabled": "yes"}, "barehands_enabled_not_boolean"),
        ({"enabled": 1}, "barehands_enabled_not_boolean"),
        ({"enabled": True, "camera": "front"}, "barehands_unknown_field"),
        ({"enabled": True, "target_preview": "non"}, "barehands_setting_not_boolean"),
        ({"enabled": True, "diagnostics": 1}, "barehands_setting_not_boolean"),
        ({"enabled": True, "sleep_timeout_ms": "30s"}, "barehands_setting_not_a_number"),
        ({"enabled": True, "sleep_timeout_ms": True}, "barehands_setting_not_a_number"),
        ({"enabled": True, "sleep_timeout_ms": 4999}, "barehands_setting_out_of_range"),
        ({"enabled": True, "sleep_timeout_ms": 600001}, "barehands_setting_out_of_range"),
        ({"enabled": True, "assistance": 1.5}, "barehands_setting_out_of_range"),
        ({"enabled": True, "sensitivity": 0.1}, "barehands_setting_out_of_range"),
        ({"enabled": True, "tool": "gomme"}, "barehands_tool_unknown"),
        # Déclaré au contrat, sans moteur : refusé **par son nom**, jamais
        # accepté en silence — un outil sans effet serait indiscernable d'un
        # outil appliqué.
        ({"enabled": True, "tool": "highlighter"}, "barehands_tool_not_installed"),
        ({"enabled": True, "tool": "draw"}, "barehands_tool_not_installed"),
    ],
)
def test_apply_rejects_malformed_payloads_with_a_stable_code(payload, code):
    stored = {"schema_version": barehands.SCHEMA_VERSION, **barehands.SETTINGS_DEFAULTS, "enabled": True}
    settings: dict = {"barehands_test_mode": dict(stored)}
    with pytest.raises(barehands.BarehandsSettingsError) as caught:
        barehands.apply(settings, payload)
    assert caught.value.code == code
    assert settings == {"barehands_test_mode": stored}, "un refus n'écrit rien"


def test_the_whole_widened_payload_is_accepted_and_an_absent_key_keeps_what_is_stored():
    """La route reste utilisable avec le seul interrupteur (constat F5) : elle
    s'applique à chaud et ne doit dépendre de rien d'autre."""

    settings: dict = {}
    barehands.apply(settings, {
        "schema_version": barehands.SCHEMA_VERSION, "enabled": True, "target_preview": False,
        "sleep_timeout_ms": 45000, "tool": "pan", "assistance": 0.25, "sensitivity": 2,
        "tutorial_seen": True, "calibration_enabled": False, "diagnostics": True,
    })
    assert settings["barehands_test_mode"]["schema_version"] == barehands.SCHEMA_VERSION
    assert settings["barehands_test_mode"]["tool"] == "pan"

    # L'interrupteur seul : il éteint, et ne réinitialise pas les huit autres.
    value = barehands.apply(settings, {"enabled": False})
    assert value["enabled"] is False
    assert value["tool"] == "pan" and value["sleep_timeout_ms"] == 45000
    assert value["assistance"] == 0.25 and value["diagnostics"] is True


def test_the_tool_table_matches_the_contract_the_page_draws_from(tmp_path):
    """Le serveur refuse sur sa table, la palette dessine sur celle du contrat.
    Deux tables qui divergent, c'est un outil grisé à l'écran et accepté par la
    route, ou l'inverse. La parité est **exécutée**, pas supposée."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    contracts = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center_barehands_contracts.js"
    script = tmp_path / "tools.cjs"
    script.write_text(
        f"const C=require({json.dumps(str(contracts))});\n"
        "process.stdout.write(JSON.stringify({tools:C.TOOLS,installed:C.INSTALLED_TOOLS,"
        "version:C.SETTINGS_SCHEMA_VERSION,defaults:C.SETTINGS_DEFAULTS,"
        "bounds:C.SETTINGS_BOUNDS,wire:C.SETTINGS_WIRE_KEYS}));",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8",
                          timeout=30, check=False)
    assert done.returncode == 0, done.stderr
    contract = json.loads(done.stdout)

    assert contract["tools"] == list(barehands.TOOLS)
    assert contract["installed"] == list(barehands.INSTALLED_TOOLS)
    assert contract["version"] == barehands.SCHEMA_VERSION
    # Les neuf clés, les mêmes des deux côtés, avec les mêmes défauts.
    assert set(contract["wire"].values()) == set(barehands.SETTINGS_DEFAULTS)
    for js_key, wire_key in contract["wire"].items():
        assert contract["defaults"][js_key] == barehands.SETTINGS_DEFAULTS[wire_key], wire_key
    for js_key, bound in contract["bounds"].items():
        low, high = barehands.SETTINGS_BOUNDS[contract["wire"][js_key]]
        assert (bound["min"], bound["max"]) == (low, high), js_key


async def test_default_state_is_off_and_reports_missing_assets(control):
    state = await state_of(control)

    assert state["enabled"] is False
    assert state["status"] == "experimental"
    assert state["assets"]["installed"] is False
    assert state["assets"]["missing"] == list(barehands.REQUIRED_ASSETS)
    assert state["assets"]["install_hint"] == "python scripts/bootstrap_third_party.py"


async def test_toggle_is_persisted_in_the_shared_settings_file_and_survives_a_restart(control, tmp_path, vendor):
    control.settings_path.parent.mkdir(parents=True, exist_ok=True)
    control.settings_path.write_text(json.dumps({"agent_cli": "codex", "manual_wake_key": "f8"}), encoding="utf-8")

    response = await control.save_barehands(JsonRequest({"enabled": True}))

    assert json.loads(response.text)["enabled"] is True
    stored = json.loads(control.settings_path.read_text(encoding="utf-8"))
    assert stored["barehands_test_mode"] == {
        "schema_version": barehands.SCHEMA_VERSION, **barehands.SETTINGS_DEFAULTS, "enabled": True,
    }
    assert stored["agent_cli"] == "codex" and stored["manual_wake_key"] == "f8"

    restarted = ControlCenter(runtime_root=control.runtime_root, project_root=tmp_path, barehands_vendor_root=vendor)
    assert (await state_of(restarted))["enabled"] is True

    await restarted.save_barehands(JsonRequest({"enabled": False}))
    assert (await state_of(control))["enabled"] is False
    assert json.loads(control.settings_path.read_text(encoding="utf-8"))["barehands_test_mode"]["enabled"] is False

    events = [event for event in read_jsonl_tail(control.journal.trace_path, limit=50)
              if event.get("kind") == "settings.barehands"]
    assert [event["data"]["enabled"] for event in events] == [True, False]


async def test_the_journal_names_the_settings_that_changed_not_only_the_switch(control):
    """Le journal durable est la seule trace qui survit à la session : il doit
    dire **ce qui a changé**.

    La route porte les neuf réglages depuis la Slice 07, et le message n'avait
    pas suivi : trois déplacements du curseur de sensibilité écrivaient trois
    lignes identiques disant « Barehands (mode test) activé », et aucun des
    huit autres réglages n'apparaissait nulle part. Un journal qui dit la même
    chose quoi qu'il arrive ne dit rien."""

    await control.save_barehands(JsonRequest({"enabled": True}))
    await control.save_barehands(JsonRequest({"enabled": True, "sensitivity": 2}))
    await control.save_barehands(JsonRequest({"enabled": True, "sensitivity": 3}))
    await control.save_barehands(JsonRequest({"enabled": True, "tool": "select", "diagnostics": True}))
    # Une écriture qui ne change rien arrive pour de bon, et se dit telle quelle.
    await control.save_barehands(JsonRequest({"enabled": True}))
    await control.save_barehands(JsonRequest({"enabled": False}))

    events = [event for event in read_jsonl_tail(control.journal.trace_path, limit=50)
              if event.get("kind") == "settings.barehands"]
    messages = [event["message"] for event in events]

    assert messages == [
        "Bare Hands activé (mode test)",
        "Réglages Bare Hands : sensitivity=2",
        "Réglages Bare Hands : sensitivity=3",
        "Réglages Bare Hands : diagnostics=True, tool=select",
        "Réglages Bare Hands réécrits sans changement",
        "Bare Hands désactivé (mode test)",
    ], messages
    # Et la donnée porte le détail, relisible par une machine.
    assert [event["data"]["changed"] for event in events] == [
        {"enabled": True}, {"sensitivity": 2}, {"sensitivity": 3},
        {"tool": "select", "diagnostics": True}, {}, {"enabled": False},
    ]
    # L'interrupteur reste lisible où il l'a toujours été.
    assert [event["data"]["enabled"] for event in events] == [True] * 5 + [False]


async def test_rejected_toggle_writes_nothing_and_answers_400_with_its_code(control):
    await control.save_barehands(JsonRequest({"enabled": True}))
    before = control.settings_path.read_text(encoding="utf-8")

    for payload in ({"enabled": "on"}, ValueError("not json")):
        with pytest.raises(web.HTTPBadRequest) as caught:
            await control.save_barehands(JsonRequest(payload))
        assert caught.value.headers[SETTINGS_ERROR_CODE_HEADER].startswith("barehands_")

    assert control.settings_path.read_text(encoding="utf-8") == before


def test_routes_are_registered(control):
    paths = {resource.get_info().get("path") or resource.get_info().get("formatter")
             for resource in control._app.router.resources()}
    assert {"/api/barehands", "/barehands/assets/{asset}"} <= paths


# ------------------------------------------------------------------- assets


def test_vendor_root_defaults_to_the_bootstrap_install_and_can_be_overridden(tmp_path):
    assert barehands.vendor_root(tmp_path, {}) == tmp_path / "third_party" / "barehands" / "vendor"
    assert barehands.vendor_root(tmp_path, {barehands.VENDOR_ENV: str(tmp_path / "elsewhere")}) == tmp_path / "elsewhere"


async def test_installed_assets_are_served_with_their_type_and_nothing_else(control, vendor, tmp_path):
    install_assets(vendor)
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")

    assert (await state_of(control))["assets"] == {
        "installed": True, "missing": [], "base_url": "/barehands/assets",
        "install_hint": "python scripts/bootstrap_third_party.py",
    }

    wasm = await control.barehands_asset(AssetRequest("wasm/vision_wasm_internal.wasm"))
    assert isinstance(wasm, web.FileResponse)
    assert wasm.headers["Content-Type"] == "application/wasm"
    module = await control.barehands_asset(AssetRequest("vision_bundle.mjs"))
    assert module.headers["Content-Type"] == "text/javascript"

    for name in ("../../secret.txt", "mediapipe/vision_bundle.mjs", "wasm/vision_wasm_nosimd_internal.wasm", ""):
        with pytest.raises(web.HTTPNotFound):
            await control.barehands_asset(AssetRequest(name))


def test_the_page_receives_the_pointer_script_in_place_of_its_marker(control):
    import asyncio

    served = asyncio.run(control.index(None)).text
    assert BAREHANDS_SCRIPT_MARKER not in served
    assert "const JarvisBarehandsCore=" in served
    assert "window.JarvisBarehands=" in served
