from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, Mock

import pytest

import jarvis.app as app
import jarvis.environment as environment
from jarvis.domain.errors import ConfigurationError
from jarvis.runtime.control_center import ControlCenter
from jarvis.v2_config import V2Settings


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(environment, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(os, "environ", {})


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_loads_literal_credentials_and_windows_paths(tmp_path, encoding):
    (tmp_path / ".env").write_text(
        '# Local configuration\n'
        'export OPENAI_API_KEY = "test-key=#${LITERAL}" # comment\n'
        "PORCUPINE_ACCESS_KEY='wake # key'\n"
        'JARVIS_RUNTIME_DIR=C:\\Jarvis\\runtime\n'
        'JARVIS_CORE_PORT=18653 # local port\n',
        encoding=encoding,
    )

    environment.load_project_environment()

    assert os.environ["OPENAI_API_KEY"] == "test-key=#${LITERAL}"
    assert os.environ["PORCUPINE_ACCESS_KEY"] == "wake # key"
    assert os.environ["JARVIS_RUNTIME_DIR"] == r"C:\Jarvis\runtime"
    assert V2Settings.load().core_port == 18653


@pytest.mark.parametrize("existing", ["environment-key", ""])
def test_existing_process_values_take_priority(tmp_path, existing):
    os.environ["OPENAI_API_KEY"] = existing
    (tmp_path / ".env").write_text("OPENAI_API_KEY=file-key\n", encoding="utf-8")

    environment.load_project_environment()

    assert os.environ["OPENAI_API_KEY"] == existing


def test_uses_project_file_independently_of_working_directory(tmp_path, monkeypatch):
    other = tmp_path / "unrelated"
    other.mkdir()
    (other / ".env").write_text("OPENAI_API_KEY=wrong-key\n", encoding="utf-8")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=project-key\n", encoding="utf-8")
    monkeypatch.chdir(other)

    environment.load_project_environment()

    assert os.environ["OPENAI_API_KEY"] == "project-key"


def test_missing_project_file_does_not_search_other_directories(tmp_path, monkeypatch):
    other = tmp_path / "unrelated"
    other.mkdir()
    (other / ".env").write_text("OPENAI_API_KEY=wrong-key\n", encoding="utf-8")
    monkeypatch.chdir(other)

    environment.load_project_environment()

    assert "OPENAI_API_KEY" not in os.environ


@pytest.mark.parametrize("bad", ["private-value", "INVALID NAME=private-value", 'OPENAI_API_KEY="private-value', 'OPENAI_API_KEY="private-value" extra'])
def test_invalid_file_fails_without_partial_loading_or_secret_disclosure(tmp_path, bad):
    (tmp_path / ".env").write_text(f"FIRST=one\n{bad}\n", encoding="utf-8")

    with pytest.raises(ConfigurationError) as error:
        environment.load_project_environment()

    assert "ligne 2" in str(error.value)
    assert "private-value" not in str(error.value)
    assert "FIRST" not in os.environ


@pytest.mark.asyncio
async def test_voice_cli_passes_dotenv_key_to_realtime_and_hides_it_in_ui(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from jarvis.adapters.openai_realtime import OpenAIRealtimeSession
    from jarvis.domain.v2 import ProtocolEnvelope
    from jarvis.protocol.client import LocalCoreClient
    from jarvis.runtime.voice_v2 import PersistentVoiceRuntime

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    (runtime_root / "core.token").write_text("local-token", encoding="utf-8")
    (tmp_path / ".env").write_text(
        f'OPENAI_API_KEY="file-test-key"\nJARVIS_RUNTIME_DIR="{runtime_root}"\n',
        encoding="utf-8-sig",
    )
    monkeypatch.setattr(LocalCoreClient, "health", AsyncMock(return_value={"ready": True}))
    async def connected_session(**kwargs):
        closed = asyncio.Event()
        async def events():
            yield ProtocolEnvelope(message_type="realtime.session_updated", payload={
                "session_id": "test-provider-session", "instructions": kwargs["instructions_override"],
            })
            await closed.wait()
        async def close():
            closed.set()
        return SimpleNamespace(events=events, close=close, active_output_id=None)

    connect = AsyncMock(side_effect=connected_session)
    monkeypatch.setattr(OpenAIRealtimeSession, "connect", connect)

    async def run_once(voice):
        session = await voice.realtime_factory({})
        try:
            from jarvis.domain.voice_frontend import FrontendState
            assert session.frontend.state is FrontendState.ACTIVE
        finally:
            await session.close()

    monkeypatch.setattr(PersistentVoiceRuntime, "run", run_once)

    assert await app._amain(["voice"]) == 0
    assert connect.await_args.kwargs["api_key"] == "file-test-key"
    control = ControlCenter(runtime_root=runtime_root, project_root=tmp_path)
    response = await control.get_settings(None)
    assert json.loads(response.text)["openai_api_key_set"] is True
    assert "file-test-key" not in response.text


@pytest.mark.asyncio
async def test_voice_missing_key_explains_how_to_configure_it(tmp_path):
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    (runtime_root / "core.token").write_text("local-token", encoding="utf-8")
    os.environ["JARVIS_RUNTIME_DIR"] = str(runtime_root)

    with pytest.raises(RuntimeError, match=r"API Keys.*OPENAI_API_KEY.*\.env"):
        await app._amain(["voice"])


@pytest.mark.asyncio
async def test_supervisor_loads_dotenv_before_spawning_children(tmp_path, monkeypatch):
    import scripts.supervisor_v2 as supervisor_module

    # JARVIS_RUNTIME_DIR garde le journal et les logs de crash du superviseur
    # dans le tmp_path du test plutôt que dans le runtime/ réel du projet.
    (tmp_path / ".env").write_text(
        f"OPENAI_API_KEY=supervisor-key\nJARVIS_CORE_PORT=18653\nJARVIS_RUNTIME_DIR={tmp_path / 'runtime'}\n",
        encoding="utf-8",
    )
    process = Mock()
    process.returncode = 0
    process.wait = AsyncMock(return_value=0)
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(supervisor_module.asyncio, "create_subprocess_exec", spawn)

    async def run_once(supervisor):
        assert V2Settings.load().core_port == 18653
        await supervisor.spawn("voice", "voice")
        return 0

    monkeypatch.setattr(supervisor_module.Supervisor, "run", run_once)
    monkeypatch.setattr(supervisor_module.asyncio.get_running_loop(), "add_signal_handler", Mock())

    assert await supervisor_module.main() == 0
    assert spawn.await_args.kwargs["env"]["OPENAI_API_KEY"] == "supervisor-key"


def test_legacy_launcher_loads_dotenv_before_reading_configuration(tmp_path, monkeypatch):
    import scripts.dev_start as launcher

    (tmp_path / ".env").write_text("OPENAI_API_KEY=launcher-key\n", encoding="utf-8")
    monkeypatch.setattr(launcher.sys, "argv", ["dev_start.py"])

    def read_config(path):
        assert os.environ["OPENAI_API_KEY"] == "launcher-key"
        raise ConfigurationError("Stop before spawning UI/audio processes")

    monkeypatch.setattr(app.AppConfig, "load", read_config)
    with pytest.raises(SystemExit, match="Stop before spawning"):
        launcher.main()
