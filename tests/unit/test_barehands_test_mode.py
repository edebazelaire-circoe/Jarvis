"""Barehands en mode test : réglage persistant et assets servis à la page.

Le serveur ne suit aucune main : il garde l'interrupteur (éteint par défaut,
rangé dans le fichier de réglages commun, refusé en HTTP 400 avec un code
stable s'il est mal formé) et ne sert à la page que la liste blanche des
fichiers MediaPipe vendorisés.
"""

from __future__ import annotations

import json
from pathlib import Path

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
    assert barehands.load({}) == {"enabled": False}
    assert barehands.load({"barehands_test_mode": {"enabled": "true"}}) == {"enabled": False}
    assert barehands.load({"barehands_test_mode": True}) == {"enabled": False}
    assert barehands.load({"barehands_test_mode": {"enabled": True}}) == {"enabled": True}


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (None, "barehands_bad_payload"),
        ([True], "barehands_bad_payload"),
        ({}, "barehands_enabled_missing"),
        ({"enabled": "yes"}, "barehands_enabled_not_boolean"),
        ({"enabled": 1}, "barehands_enabled_not_boolean"),
        ({"enabled": True, "camera": "front"}, "barehands_unknown_field"),
    ],
)
def test_apply_rejects_malformed_payloads_with_a_stable_code(payload, code):
    settings: dict = {"barehands_test_mode": {"enabled": True}}
    with pytest.raises(barehands.BarehandsSettingsError) as caught:
        barehands.apply(settings, payload)
    assert caught.value.code == code
    assert settings == {"barehands_test_mode": {"enabled": True}}


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
    assert stored["barehands_test_mode"] == {"enabled": True}
    assert stored["agent_cli"] == "codex" and stored["manual_wake_key"] == "f8"

    restarted = ControlCenter(runtime_root=control.runtime_root, project_root=tmp_path, barehands_vendor_root=vendor)
    assert (await state_of(restarted))["enabled"] is True

    await restarted.save_barehands(JsonRequest({"enabled": False}))
    assert (await state_of(control))["enabled"] is False
    assert json.loads(control.settings_path.read_text(encoding="utf-8"))["barehands_test_mode"] == {"enabled": False}

    events = [event for event in read_jsonl_tail(control.journal.trace_path, limit=50)
              if event.get("kind") == "settings.barehands"]
    assert [event["data"]["enabled"] for event in events] == [True, False]


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
