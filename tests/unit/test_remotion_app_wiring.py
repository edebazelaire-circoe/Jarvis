"""La composition de production câble le moteur Remotion (Slice 10) : `jarvis/app.py` passe le bac à sable à Core, Core en tire la porte
du moteur, et un Core composé sans Remotion garde le comportement d'avant. Aucun processus, aucun socket.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import jarvis.app as app
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain import remotion_sandbox as sb
from jarvis.domain.presentation_studio_engine import Engine
from jarvis.adapters.file_local_capability_store import FileLocalCapabilityStore
from jarvis.adapters.node_capability_runner import default_remotion_runner
from jarvis.runtime.remotion_composition import remotion_factory
from jarvis.runtime.remotion_sandbox_server import DEFAULT_HOST, DEFAULT_PORT, RemotionSandboxSettings


def test_the_production_composition_hands_core_the_sandbox_settings():
    source = inspect.getsource(app._run_core_v2)
    assert "remotion=_remotion_factory()" in source and "local_capability_store=" in source
    assert "local_capability_runner=_local_capability_runner()" in source


def test_the_settings_are_another_address_and_port_than_core_and_the_control_center(monkeypatch):
    for name in ("JARVIS_REMOTION_SANDBOX_HOST", "JARVIS_REMOTION_SANDBOX_PORT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JARVIS_UI_PORT", "18654")
    settings = app._remotion_sandbox_settings()
    assert (settings.host, settings.port) == (DEFAULT_HOST, DEFAULT_PORT) == ("127.77.0.2", 17655)
    assert settings.embedder_origin == "http://127.0.0.1:18654" and settings.origin == "http://127.77.0.2:17655"
    sb.assert_distinct_origins("http://127.77.0.1:17653", settings.origin)   # Core
    sb.assert_distinct_origins(settings.embedder_origin, settings.origin)    # Control Center
    monkeypatch.setenv("JARVIS_REMOTION_SANDBOX_PORT", "19000")
    assert app._remotion_sandbox_settings().port == 19000


def test_a_sandbox_on_the_host_of_the_control_center_is_refused_at_composition(monkeypatch):
    monkeypatch.setenv("JARVIS_REMOTION_SANDBOX_HOST", "127.0.0.1")
    with pytest.raises(sb.SandboxContractError):
        app._remotion_sandbox_settings()


async def test_a_composed_core_has_the_gate_and_reports_remotion_unavailable_until_the_capability_is_installed(tmp_path: Path):
    core = JarvisCoreApplication(
        data_root=tmp_path, local_capability_store=FileLocalCapabilityStore(tmp_path), local_capability_runner=default_remotion_runner(),
        remotion=remotion_factory(RemotionSandboxSettings("127.77.0.2", 17655, "http://127.0.0.1:17654")))
    try:
        assert core.studio_engine_gate is not None and core.remotion_sandbox is not None
        state = core.remotion_player.availability()
        assert not state.ready and "not_installed" in state.reason, "nothing is installed: the engine says so, with its repair"
        assert core.remotion_sandbox.origin is None, "no port is opened by the composition"
        view = await core.presentation_studio.create({"title": "Remotion"})
        assert view.presentation.engine is Engine.REMOTION
    finally:
        await core.state.close()


async def test_a_core_composed_without_remotion_has_no_gate_and_no_listener(tmp_path: Path):
    core = JarvisCoreApplication(data_root=tmp_path)
    try:
        assert core.studio_engine_gate is None and core.remotion_sandbox is None
        assert not core.remotion_player.availability().ready
        view = await core.presentation_studio.create({"title": "Headless"})
        assert await core.presentation_studio.require_engine(view.presentation.presentation_id, "play") is None
    finally:
        await core.state.close()
