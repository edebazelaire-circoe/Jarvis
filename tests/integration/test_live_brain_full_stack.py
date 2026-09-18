"""Mode `continuous_brain` de bout en bout, contre les vrais fournisseurs, **opt-in**.

Sauté tant que `JARVIS_LIVE_OPENAI=1` **et** `JARVIS_LIVE_CLAUDE=1` ne sont pas
posés. La clé OpenAI est lue (lecture seule) dans les réglages réels du Control
Center ; tout le reste vit dans `tmp_path` et sur des ports libres.

Ce qu'aucun faux ne prouve, et qui manquait le 17/09 quand Voice tournait en
`simple` : la parole atteint réellement le cerveau (l'agent Claude Code local
du Control Center), le cerveau répond et Voice le dit, le cerveau peut lancer
un sous-agent, chaque tour — pas seulement le premier — obtient sa réponse, et
la console ouverte pendant que l'agent tourne reprend sa session en la
dupliquant (`--resume <id> --fork-session`).

Composition, comme en production :
Voice (`app._run_voice_v2`, pile OpenAI Realtime, micro TTS, faux haut-parleur)
  → Core (`JarvisCoreApplication` + `LocalProtocolServer`)
  → `ControlCenterBrainBackend` → Control Center (`/api/agent/ask`)
  → `ClaudeLocalAgent` (vrai CLI `claude`).

Lancer :
    JARVIS_LIVE_OPENAI=1 JARVIS_LIVE_CLAUDE=1 .venv/Scripts/python.exe -m pytest \
        tests/integration/test_live_brain_full_stack.py -s -q
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import time
from pathlib import Path

import aiohttp
from aiohttp.test_utils import TestServer
import pytest

from jarvis import app
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime import realtime_audio
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import V2Settings, VoiceArchitecture
from tests.fakes.audio_device import BufferedOutputStream
from tests.integration.test_live_openai_multi_turn import synthesize_pcm24
from tests.integration.test_voice_production_composition import ControlledWake

ROOT = Path(__file__).resolve().parents[2]
live_only = pytest.mark.skipif(
    os.getenv("JARVIS_LIVE_OPENAI") != "1" or os.getenv("JARVIS_LIVE_CLAUDE") != "1",
    reason="requires JARVIS_LIVE_OPENAI=1 and JARVIS_LIVE_CLAUDE=1",
)

MATH = "Jarvis, combien font deux plus deux ?"
SUBAGENT = ("Jarvis, lance un sous-agent pour compter les fichiers du dossier docs "
            "et dis-moi le résultat.")
CAPITAL = "Jarvis, quelle est la capitale de l'Italie ?"

#: Réglages de l'agent recopiés des réglages réels : aucun secret.
AGENT_SETTING_KEYS = ("agent_cli", "claude_cli", "claude_permission_mode", "agent_cli_settings",
                      "agent_routing", "agent_behavior")

#: Ce qui raconte un tour, dans l'ordre où la trace l'écrit.
STORY_KINDS = (
    "voice.brain_turn_submitted", "voice.brain_turn_rejected", "voice.reflex.started",
    "agent.input", "agent.subagent.started", "agent.subagent.finished", "agent.ask",
    "agent.ask_timeout", "agent.unsolicited_result", "agent.console_open",
    "core.brain.backend_task_result", "core.brain.notice_relayed", "core.brain.turn_failed",
    "voice.speech.dispatched", "voice.speech.started", "voice.latency.first_brain_audio",
    "voice.speech.completed", "voice.speech.interrupted", "voice.speech.superseded",
    "voice.speech.expired", "voice.speech.error_withheld",
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def trace(runtime_root: Path) -> list[dict]:
    path = runtime_root / "trace.jsonl"
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def brain_speech(entry: dict, kind: str) -> bool:
    """Une parole du cerveau, pas l'accusé de réception de la surface."""
    data = entry.get("data") or {}
    return entry["kind"] == kind and str(data.get("work_id") or "").startswith("brain-turn:")


def brief(entry: dict) -> str:
    data = entry.get("data") or {}
    extra = {key: data[key] for key in ("kind", "work_id", "status", "subagent_type", "description", "forked")
             if key in data and data[key] not in (None, "")}
    message = str(entry.get("message") or "").replace("\n", " ")[:110]
    return f"{entry['ts'][11:23]} {entry['kind']:<34} {message}" + (f" {extra}" if extra else "")


@live_only
async def test_continuous_brain_reaches_real_claude_speaks_every_turn_and_forks_console(tmp_path, monkeypatch):
    from jarvis.adapters import wakeword_keyboard
    from jarvis.adapters.control_center_brain import ControlCenterBrainBackend
    from jarvis.runtime import claude_local, credentials
    from jarvis.runtime.control_center import ControlCenter
    from jarvis.runtime.conversation_event_forwarder import (
        ConversationEventForwarder, CoreConversationEventTransport,
    )
    from jarvis.runtime.work_ingress import CoreWorkTransport, WorkIngressForwarder

    real_settings = app._control_settings(ROOT / "runtime")
    key = credentials.secret_for(real_settings, "openai")
    assert key, "aucune clé OpenAI dans les réglages ni l'environnement"

    # --- Voice : continuous_brain explicite, jamais la compatibilité `simple`.
    overrides = {k: v for k, v in real_settings.items() if k != "voice_architecture"}
    stack = dict((overrides.get("voice_stack_settings") or {}).get("openai_realtime") or {})
    overrides.update({
        "voice_arch": "continuous_brain",
        "voice_stack": "openai_realtime",
        # Délai d'activité désactivé : un tour cerveau dure des minutes, et le
        # réveil est piloté par le test, pas par un mot-clé.
        "active_timeout_s": 0,
        "voice_stack_settings": {**(overrides.get("voice_stack_settings") or {}),
                                 "openai_realtime": {**stack, "turn_mode": "auto", "echo_cancellation": False}},
    })

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    token = "b" * 32
    token_file = runtime_root / "core.token"
    token_file.write_text(token, encoding="utf-8")
    (runtime_root / "control-center-settings.json").write_text(
        json.dumps({k: real_settings[k] for k in AGENT_SETTING_KEYS if k in real_settings}), encoding="utf-8")
    ui_port = free_port()
    monkeypatch.setenv("JARVIS_UI_PORT", str(ui_port))
    journal = RuntimeJournal(runtime_root)

    # --- Core, relié au cerveau du Control Center comme `_run_core_v2`.
    brain_backend = ControlCenterBrainBackend(base_url=app._control_center_url(), timeout_s=600.0)
    core = JarvisCoreApplication(data_root=tmp_path / "data", brain_backend=brain_backend,
                                 diagnostics=journal, **app._brain_availability_from_env())
    await core.start()
    protocol = LocalProtocolServer(core, host="127.0.0.1", port=0, token=token)
    server = TestServer(protocol._app())
    await server.start_server()
    journal.emit("brain.backend", "Cerveau relié à l'agent du Control Center", data={"url": brain_backend.base_url})

    # --- Control Center et vrai agent Claude, sur la racine temporaire.
    control = ControlCenter(
        runtime_root=runtime_root,
        project_root=ROOT,
        work_ingress=WorkIngressForwarder(
            source="claude", journal=journal,
            transport=CoreWorkTransport(host="127.0.0.1", port=server.port, token_file=token_file)),
        conversation_events=ConversationEventForwarder(
            journal=journal,
            transport=CoreConversationEventTransport(host="127.0.0.1", port=server.port, token_file=token_file)),
    )
    await control.start(port=ui_port)

    settings = V2Settings(tmp_path / "data", runtime_root, "127.0.0.1", server.port, "Europe/Paris",
                          token_file, 12, 0, "unused", "cedar", True, VoiceArchitecture.CONTINUOUS_BRAIN)
    monkeypatch.setattr(V2Settings, "load", classmethod(lambda cls: settings))
    monkeypatch.setattr(app, "_control_settings", lambda root: overrides)
    monkeypatch.setattr(app, "_speaker_verifier", lambda *args: None)
    monkeypatch.setattr(wakeword_keyboard, "KeyboardWakeWordBackend", ControlledWake)

    audios = []

    class Audio(realtime_audio.SoundDeviceRealtimeAudio):
        async def start(self):
            self._loop = asyncio.get_running_loop()
            self._output = self.device = BufferedOutputStream()
            self.device_wait_s = 1
            self._output_latency_ms = self._stream_latency_ms()
            audios.append(self)

    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", Audio)

    speech = {text: await synthesize_pcm24(key, text) for text in (MATH, SUBAGENT, CAPITAL)}
    chunk = 2400  # 50 ms à 24 kHz
    marks: list[tuple[str, int]] = []
    captured_console: list[list[str]] = []
    durations: dict[str, float] = {}

    def count(predicate) -> int:
        return sum(1 for entry in trace(runtime_root) if predicate(entry))

    def kind_is(kind):
        return lambda entry: entry["kind"] == kind

    async def wait_until(predicate, minimum: int, timeout: float, what: str) -> None:
        try:
            async with asyncio.timeout(timeout):
                while count(predicate) < minimum:
                    await asyncio.sleep(.25)
        except TimeoutError:
            raise AssertionError(f"délai dépassé ({timeout:.0f} s) en attendant : {what}") from None

    async def say(audio, pcm: bytes, trailing_silence_s: float) -> None:
        payload = pcm + b"\0\0" * int(24000 * trailing_silence_s)
        for start in range(0, len(payload), chunk * 2):
            audio._enqueue(payload[start:start + chunk * 2])
            await asyncio.sleep(chunk / 24000)

    async def drain_speakers():
        while True:
            for audio in audios:
                audio.device.consume()
            await asyncio.sleep(.05)

    async def spoken_turn(label: str, text: str, *, answer_timeout: float) -> None:
        """Dire une phrase, prouver que le cerveau l'a reçue et que sa réponse est dite."""
        submitted = count(kind_is("voice.brain_turn_submitted"))
        inputs = count(kind_is("agent.input"))
        asks = count(kind_is("agent.ask"))
        completed = count(lambda e: brain_speech(e, "voice.speech.completed"))
        marks.append((label, len(trace(runtime_root))))
        began = time.monotonic()
        await say(audios[0], speech[text], 1.8)
        await wait_until(kind_is("voice.brain_turn_submitted"), submitted + 1, 45, f"{label}: tour soumis à Core")
        await wait_until(kind_is("agent.input"), inputs + 1, 60, f"{label}: tour reçu par l'agent Claude")
        await wait_until(kind_is("agent.ask"), asks + 1, answer_timeout, f"{label}: réponse de l'agent Claude")
        await wait_until(lambda e: brain_speech(e, "voice.speech.completed"), completed + 1, 90,
                         f"{label}: réponse du cerveau prononcée")
        durations[label] = time.monotonic() - began

    async def open_console_captured() -> dict:
        """La vraie route `/api/agent/console/open`, sans ouvrir de fenêtre."""
        real_popen = subprocess.Popen

        class FakeConsole:
            pid = 424242

            def poll(self):
                return None

            def terminate(self):
                pass

            def wait(self, timeout=None):
                return 0

            def kill(self):
                pass

        def fake_popen(command, *args, **kwargs):
            if isinstance(command, (list, tuple)) and "--chrome" in command and "-p" not in command:
                captured_console.append([str(part) for part in command])
                return FakeConsole()
            return real_popen(command, *args, **kwargs)

        monkeypatch.setattr(claude_local.subprocess, "Popen", fake_popen)
        try:
            async with aiohttp.ClientSession() as http:
                async with http.post(f"http://127.0.0.1:{ui_port}/api/agent/console/open") as response:
                    assert response.status == 200, await response.text()
                    return await response.json()
        finally:
            monkeypatch.setattr(claude_local.subprocess, "Popen", real_popen)

    console_result: dict = {}

    async def drive(runtime):
        drainer = asyncio.create_task(drain_speakers())
        try:
            await runtime.activate()
            async with asyncio.timeout(20):
                while not audios:
                    await asyncio.sleep(.05)
            assert runtime.voice_arch is VoiceArchitecture.CONTINUOUS_BRAIN

            # Tour 1 : question simple, le cerveau répond et Voice le dit.
            await spoken_turn("tour 1 (2+2)", MATH, answer_timeout=240)
            agent = control.agent
            assert agent.state == "running" and agent.session_id, "l'agent doit tourner avec une session"

            # Tour 2 : sous-agent. La réponse peut arriver dans le tour ou par
            # un relais spontané une fois le sous-agent fini.
            subagents = count(kind_is("agent.subagent.started"))
            inputs = count(kind_is("agent.input"))
            completed_before = count(lambda e: brain_speech(e, "voice.speech.completed"))
            marks.append(("tour 2 (sous-agent)", len(trace(runtime_root))))
            began = time.monotonic()
            await say(audios[0], speech[SUBAGENT], 1.8)
            await wait_until(kind_is("agent.input"), inputs + 1, 90,
                             "tour 2: tour reçu par l'agent Claude")
            await wait_until(kind_is("agent.subagent.started"), subagents + 1, 240, "tour 2: sous-agent lancé")

            # Console ouverte pendant que l'agent vocal tourne : copie de session.
            console_result.update(await open_console_captured())

            await wait_until(kind_is("agent.subagent.finished"), 1, 300, "tour 2: sous-agent terminé")
            await wait_until(lambda e: brain_speech(e, "voice.speech.completed") or
                             (e["kind"] == "voice.speech.completed" and
                              str((e.get("data") or {}).get("kind") or "") not in ("", "reflex")),
                             completed_before + 1, 300, "tour 2: réponse prononcée")
            # Laisser se dire un éventuel relais de fin de sous-agent avant le tour 3.
            async with asyncio.timeout(240):
                while (count(kind_is("agent.unsolicited_result")) > count(kind_is("core.brain.notice_relayed"))
                       or agent._pending_result is not None):
                    await asyncio.sleep(.5)
            await asyncio.sleep(8)
            durations["tour 2 (sous-agent)"] = time.monotonic() - began

            # Tour 3 : le tour d'après doit lui aussi obtenir sa réponse.
            await spoken_turn("tour 3 (capitale)", CAPITAL, answer_timeout=240)
            await runtime.mute()
        finally:
            drainer.cancel()
            await asyncio.gather(drainer, return_exceptions=True)

    monkeypatch.setattr(PersistentVoiceRuntime, "run", drive)
    started = time.monotonic()
    failure: BaseException | None = None
    try:
        assert await asyncio.wait_for(app._run_voice_v2(), 1500) == 0
    except BaseException as exc:  # noqa: BLE001 - rapport complet, puis on relève
        failure = exc
    finally:
        entries = trace(runtime_root)
        print(f"\n=== durée totale : {time.monotonic() - started:.1f} s ; durées : "
              + ", ".join(f"{k}={v:.1f}s" for k, v in durations.items()))
        bounds = [index for _, index in marks] + [len(entries)]
        for (label, begin), end in zip(marks, bounds[1:]):
            print(f"--- {label}")
            for entry in entries[begin:end]:
                if entry["kind"] in STORY_KINDS:
                    print("   ", brief(entry))
        print("--- console capturée :", captured_console, console_result)
        errors = [e for e in entries if e.get("level") == "error"]
        print(f"--- erreurs tracées : {len(errors)}")
        for entry in errors[:40]:
            print("   ", brief(entry))
        for audio in audios:
            audio.device.consume()
        await control.stop()
        await server.close()
        await core.stop()
        await brain_backend.close()
    if failure is not None:
        raise failure

    kinds = [entry["kind"] for entry in entries]
    assert kinds.count("voice.brain_turn_submitted") >= 3
    assert kinds.count("agent.input") >= 3
    assert kinds.count("agent.subagent.started") >= 1
    assert sum(1 for e in entries if brain_speech(e, "voice.speech.completed")) >= 3
    assert kinds.count("voice.latency.first_brain_audio") >= 3
    # Le résultat du sous-agent est lui aussi dit : relais spontané, puis parole
    # effectivement terminée après la fin du sous-agent.
    finished_at = kinds.index("agent.subagent.finished")
    after = kinds[finished_at:]
    if "agent.unsolicited_result" in after:
        relayed_at = finished_at + after.index("core.brain.notice_relayed")
        assert "voice.speech.completed" in kinds[relayed_at:]
    else:  # sous-agent attendu dans le tour : sa réponse est celle du tour
        assert "voice.speech.completed" in after

    assert len(captured_console) == 1
    command = captured_console[0]
    session_id = console_result.get("session_id")
    assert session_id
    assert command[command.index("--resume") + 1] == session_id
    assert "--fork-session" in command
    assert console_result.get("forked") is True
