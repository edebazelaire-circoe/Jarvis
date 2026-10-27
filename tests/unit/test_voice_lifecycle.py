"""Cycle de vie produit de la voix : Off / Sleep / Active (`docs/voice-lifecycle.md`, Slice 05 presentation-edition-v1-2).

Ce que ce fichier épingle, sans micro ni haut-parleur réels (doubles de processus, d'arbre et de sonde) :

- une seule préférence persistée (`voice_lifecycle` dans `control-center-settings.json`), défaut ``sleep`` ; un bloc
  abîmé n'est jamais lu comme ``off`` ;
- matrice de démarrage du lanceur : profil vierge → Voice démarrée ; ``off`` persisté → Voice jamais démarrée ;
  clé du fournisseur absente → Voice tenue (`voice_provider_key_missing`), aucune boucle de plantages ;
- bascule à chaud : ``off`` arrête Voice par la demande d'arrêt propre, ``sleep`` la redémarre (et redonne sa chance
  à une Voix abandonnée) ;
- « Quitter JARVIS » : Core, Control Center et Voice reçoivent la demande d'arrêt, chaque Job est fermé ;
- Voice elle-même : ``off`` au démarrage → sortie 0 sans rien ouvrir ; ``off`` en cours → rend la main ;
- la projection affichée (`project`) et la route `/api/voice/lifecycle` du Control Center ; `/api/status` la porte ;
- la page « Mot d'éveil » reçoit l'état réel du moteur (`engine`) ; la ligne « Voix » de la préparation.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from jarvis.domain.product_readiness import ActionId, Probe, ReadinessState
from jarvis.runtime import product_launcher as L
from jarvis.runtime import voice_lifecycle as V
from jarvis.runtime.control_center import SETTINGS_ERROR_CODE_HEADER, ControlCenter
from jarvis.runtime.journal import read_jsonl_tail
from tests.unit.test_product_launcher import CleanProcess, FakeTree, events, launcher
from tests.unit.test_product_readiness import by_id, facts

KEY_ENV = ("OPENAI_API_KEY", "PORCUPINE_ACCESS_KEY", "JARVIS_VOICE_ARCH", "GEMINI_API_KEY", "GOOGLE_API_KEY")


@pytest.fixture
def no_env_keys(monkeypatch):
    for name in KEY_ENV:
        monkeypatch.delenv(name, raising=False)
    # Le `.env` du poste ne doit pas fournir une clé à ces tests.
    monkeypatch.setattr("jarvis.environment.load_project_environment", lambda: None)


def write_settings(runtime: Path, settings: dict) -> None:
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / V.SETTINGS_FILE).write_text(json.dumps(settings), encoding="utf-8")


# ---------------------------------------------------------------------- préférence


@pytest.mark.parametrize("settings, expected, problem", [
    ({}, "sleep", None),
    ({"voice_lifecycle": {"schema_version": 1, "preference": "off"}}, "off", None),
    ({"voice_lifecycle": {"preference": "off"}}, "off", None),
    ({"voice_lifecycle": "off"}, "unreadable", "voice_lifecycle_block_malformed"),
    ({"voice_lifecycle": {"schema_version": 9, "preference": "off"}}, "unreadable",
     "voice_lifecycle_stored_version_unreadable"),
    ({"voice_lifecycle": {"preference": "Off"}}, "unreadable", "voice_lifecycle_preference_invalid"),
])
def test_absent_block_is_sleep_and_a_present_but_unreadable_block_never_lets_voice_run(settings, expected, problem):
    """Reprise QA m1 : bloc absent -> veille ; bloc présent mais illisible -> Voice tenue (jamais de micro)."""

    assert V.inspect_preference(settings) == (expected, problem)
    assert V.voice_allowed(expected) is (expected == "sleep")


@pytest.mark.parametrize("payload, code", [
    (None, "voice_lifecycle_bad_payload"), ({"preference": "off", "x": 1}, "voice_lifecycle_bad_payload"),
    ({"preference": "active"}, "voice_lifecycle_preference_invalid"), ({"preference": True}, "voice_lifecycle_preference_invalid"),
])
def test_writing_the_preference_is_strict(payload, code):
    settings = {"other": 1}
    with pytest.raises(V.VoiceLifecycleError) as caught:
        V.apply_preference(settings, payload)
    assert caught.value.code == code and settings == {"other": 1}


def test_the_switch_rewrites_an_unreadable_block_with_a_valid_choice():
    """Reprise QA m1 : l'interrupteur doit permettre de sortir d'un bloc illisible (autre version, valeur inconnue)."""

    for stored in ({"schema_version": 2, "preference": "off", "extra": True}, {"preference": "Off"}, "off"):
        settings = {"voice_lifecycle": stored, "other": 1}
        assert V.apply_preference(settings, {"preference": "sleep"}) == "sleep"
        assert settings == {"voice_lifecycle": {"schema_version": 1, "preference": "sleep"}, "other": 1}
        assert V.inspect_preference(settings) == ("sleep", None)
    assert V.apply_preference({}, {"preference": "off"}) == "off"


# ---------------------------------------------------------------------- décision du lanceur


def test_launch_decision_matrix(no_env_keys, monkeypatch):
    assert V.launch_decision({}) == V.LaunchDecision(False, "voice_provider_key_missing")
    assert V.launch_decision({}, check_key=False) == V.LaunchDecision(True, None)
    off = {"voice_lifecycle": {"schema_version": 1, "preference": "off"}}
    assert V.launch_decision(off) == V.LaunchDecision(False, "voice_off", stop_running=True)
    bad = {"voice_lifecycle": {"preference": "Off"}}
    assert V.launch_decision(bad) == V.LaunchDecision(False, "voice_preference_unreadable", stop_running=True)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert V.launch_decision(bad) == V.LaunchDecision(False, "voice_preference_unreadable", stop_running=True)
    assert V.launch_decision({}) == V.LaunchDecision(True, None)
    assert V.launch_decision(off) == V.LaunchDecision(False, "voice_off", stop_running=True)


def test_provider_key_follows_the_voice_path_without_saying_the_value(no_env_keys, monkeypatch):
    missing = V.provider_key({})
    assert (missing.present, missing.code, missing.provider) == (False, "voice_provider_key_missing", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value")
    present = V.provider_key({})
    assert present.present and present.code is None and "sk-secret" not in json.dumps(present.to_payload())


# ---------------------------------------------------------------------- lanceur : matrice de démarrage


def gate_from(runtime: Path):
    return lambda running: L.default_voice_gate(runtime, running=running)


def roles_of(spawned) -> list[str]:
    return [p.argv[-1] for p in spawned]


def test_fresh_profile_with_a_key_starts_voice_in_sleep(tmp_path, no_env_keys, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    instance, spawned, notices, _ = launcher(tmp_path, stop_after=3.0, gate=gate_from(tmp_path / "runtime"))
    assert instance.run() == 0 and notices == []
    assert roles_of(spawned) == ["core", "control-center", "voice"]


def test_persisted_off_never_starts_voice_and_survives_a_restart(tmp_path, no_env_keys, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    write_settings(tmp_path / "runtime", {"voice_lifecycle": {"schema_version": 1, "preference": "off"}})
    states = []
    for _ in range(2):  # deux lancements : la préférence n'est jamais réécrite par un redémarrage
        instance, spawned, notices, _ = launcher(tmp_path, stop_after=3.0, gate=gate_from(tmp_path / "runtime"))
        original = instance.write_state

        def capture(original=original):
            original()
            states.append(json.loads((tmp_path / "runtime" / L.STATE_FILE).read_text(encoding="utf-8")))

        instance.write_state = capture
        assert instance.run() == 0 and notices == []
        assert roles_of(spawned) == ["core", "control-center"]
    assert states[-1]["roles"]["voice"] == {"pid": None, "abandoned": False, "last_exit": None, "held": "voice_off",
                                            "running": False}
    assert V.read_preference(tmp_path / "runtime") == "off"
    assert [row["data"]["code"] for row in events(tmp_path) if row["kind"] == "voice_held"] == ["voice_off", "voice_off"]


def test_a_missing_provider_key_holds_voice_visibly_instead_of_a_crash_loop(tmp_path, no_env_keys):
    instance, spawned, notices, _ = launcher(tmp_path, stop_after=8.0, gate=gate_from(tmp_path / "runtime"),
                                             behaviours={"voice": [{"exit_after_polls": 0}] * 10})
    assert instance.run() == 0 and notices == []
    assert roles_of(spawned) == ["core", "control-center"]
    rows = events(tmp_path)
    assert not [row for row in rows if row["kind"] in ("child_abandoned", "child_exited")]
    held = [row for row in rows if row["kind"] == "voice_held"]
    assert len(held) == 1 and held[0]["data"]["code"] == "voice_provider_key_missing" and held[0]["level"] == "warning"


# ---------------------------------------------------------------------- lanceur : bascule à chaud


class Switchboard:
    """Une préférence que le test change pendant la veille du lanceur, et la clé présente."""

    def __init__(self) -> None:
        self.preference = "sleep"
        self.calls: list[bool] = []

    def __call__(self, running: bool):
        self.calls.append(running)
        settings = {"voice_lifecycle": {"schema_version": 1, "preference": self.preference}}
        return V.launch_decision(settings, key=lambda _s: V.ProviderKey(True, "openai", "OpenAI"))


def test_hot_toggle_off_stops_voice_cleanly_and_sleep_starts_it_again(tmp_path):
    board = Switchboard()
    instance, spawned, notices, _ = launcher(tmp_path, gate=board)
    original_spawn = instance.spawn

    def spawn(argv, **kwargs):
        process = original_spawn(argv, **kwargs)
        process.__class__ = CleanProcess  # chaque rôle lit sa demande d'arrêt propre
        return process

    instance.spawn = spawn
    original_sleep = instance.sleep

    def sleep(seconds):
        original_sleep(seconds)
        now = instance.clock()
        if 3.0 <= now < 6.0:
            board.preference = "off"
        elif 6.0 <= now < 9.0:
            board.preference = "sleep"
        elif now >= 9.0:
            (instance.plan.runtime_root / L.STOP_FILE).write_text("now", encoding="utf-8")

    instance.sleep = sleep
    assert instance.run() == 0 and notices == []
    voices = [p for p in spawned if p.argv[-1] == "voice"]
    assert len(voices) == 2, "coupée puis rallumée : une seconde incarnation"
    assert not voices[0].terminated and voices[0].returncode == 0, "arrêt propre, pas de terminate"
    kinds = [row["kind"] for row in events(tmp_path)]
    assert kinds.index("voice_stopping") < kinds.index("voice_released")
    assert not [k for k in kinds if k in ("child_abandoned", "voice_exited_held")]
    assert False in board.calls and True in board.calls, "la clé n'est relue que quand Voice ne tourne pas"


def test_switching_voice_back_on_gives_an_abandoned_voice_a_new_chance(tmp_path):
    board = Switchboard()
    crash = {"exit_after_polls": 0}
    instance, spawned, _notices, _ = launcher(tmp_path, gate=board, behaviours={"voice": [crash] * 4 + [None] * 3})
    original_sleep = instance.sleep

    def sleep(seconds):
        original_sleep(seconds)
        now = instance.clock()
        if 20.0 <= now < 22.0:
            board.preference = "off"
        elif 22.0 <= now < 25.0:
            board.preference = "sleep"
        elif now >= 25.0:
            (instance.plan.runtime_root / L.STOP_FILE).write_text("now", encoding="utf-8")

    instance.sleep = sleep
    assert instance.run() == 0
    kinds = [row["kind"] for row in events(tmp_path)]
    assert "child_abandoned" in kinds
    assert len([p for p in spawned if p.argv[-1] == "voice"]) == 1 + L.MAX_RESTARTS + 1


def test_quit_stops_core_control_center_and_voice_through_their_stop_request(tmp_path):
    instance, spawned, notices, _ = launcher(tmp_path, stop_after=2.0)
    original_spawn = instance.spawn

    def spawn(argv, **kwargs):
        process = original_spawn(argv, **kwargs)
        process.__class__ = CleanProcess
        return process

    instance.spawn = spawn
    assert instance.run() == 0 and notices == []
    assert all(p.returncode == 0 and not p.terminated for p in spawned)
    clean = [row["data"]["role"] for row in events(tmp_path) if row["kind"] == "child_stopped_cleanly"]
    assert clean == ["ui", "voice", "core"]
    assert all(tree.terminated for tree in FakeTree.made), "chaque Job fermé : Remotion et aides avec"
    assert not list((tmp_path / "runtime").glob("stop-*.request"))


# ---------------------------------------------------------------------- Voice elle-même


def test_voice_with_off_persisted_exits_zero_before_opening_anything(tmp_path, monkeypatch):
    runtime = tmp_path / "rt"
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("JARVIS_DATA_ROOT", str(tmp_path / "data"))
    write_settings(runtime, {"voice_lifecycle": {"schema_version": 1, "preference": "off"}})
    from jarvis import app

    def boom(*_args, **_kwargs):  # pragma: no cover - would mean Voice went past the gate
        raise AssertionError("Voice composed its stack despite voice off")

    monkeypatch.setattr("jarvis.runtime.voice_composition.resolve_voice_composition", boom)
    assert asyncio.run(app._run_voice_v2()) == 0
    rows = read_jsonl_tail(runtime / "trace.jsonl", limit=50)
    refused = [row for row in rows if row["kind"] == "voice.lifecycle.start_refused_off"]
    assert refused and refused[0]["data"] == {"code": "voice_off", "problem": None}


@pytest.mark.parametrize("trigger, expected", [("off", V.RELEASED_OFF), ("stop", V.STOP_REQUESTED), (None, None)])
def test_voice_main_loop_is_released_by_off_or_the_stop_request(tmp_path, trigger, expected):
    stop_file = tmp_path / "stop-voice.request"
    cancelled = []

    async def main():
        try:
            if trigger is None:
                return "done"
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    async def scenario():
        task = asyncio.ensure_future(V.run_until_released(main(), stop_file=stop_file, runtime_root=tmp_path,
                                                          poll_s=0.01))
        await asyncio.sleep(0.05)
        if trigger == "off":
            write_settings(tmp_path, {"voice_lifecycle": {"schema_version": 1, "preference": "off"}})
        elif trigger == "stop":
            stop_file.write_text("now", encoding="utf-8")
        return await asyncio.wait_for(task, 5)

    assert asyncio.run(scenario()) == expected
    assert bool(cancelled) is (trigger is not None), "la boucle de Voice est annulée puis fermée par son finally"


# ---------------------------------------------------------------------- projection


KEY = V.ProviderKey(True, "openai", "OpenAI")
NO_WAKE = {"configured": False, "available": False, "code": None, "message": "x"}


def view(**kw):
    base = {"preference": "sleep", "voice_online": False, "runtime_state": None, "launcher": None, "key": KEY,
            "wake": NO_WAKE, "manual_key": "f9"}
    return V.project(**{**base, **kw})


@pytest.mark.parametrize("kw, state, code", [
    ({"voice_online": True, "runtime_state": "background"}, "sleep", None),
    ({"voice_online": True, "runtime_state": "active"}, "active", None),
    ({"voice_online": True, "runtime_state": "connecting"}, "active", None),
    ({"voice_online": True, "runtime_state": "error"}, "degraded", "voice_runtime_error"),
    ({"preference": "off"}, "off", "voice_off"),
    ({"preference": "off", "voice_online": True, "runtime_state": "background"}, "stopping", "voice_stopping"),
    ({"launcher": {"managed": True, "voice": {"held": None, "abandoned": False}}}, "starting", "voice_starting"),
    ({"launcher": {"managed": True, "voice": {"held": "voice_provider_key_missing"}}}, "degraded",
     "voice_provider_key_missing"),
    ({"launcher": {"managed": True, "voice": {"abandoned": True}}}, "degraded", "voice_crash_loop"),
    ({"launcher": {"managed": True, "voice": {"held": "voice_preference_unreadable"}}}, "starting", "voice_starting"),
    ({"launcher": {"managed": True, "voice": {"held": "voice_off"}}}, "starting", "voice_starting"),
    ({"launcher": {"managed": True, "voice": None}}, "degraded", "voice_not_launched"),
    ({"key": V.ProviderKey(False, "openai", "OpenAI", "voice_provider_key_missing")}, "degraded",
     "voice_provider_key_missing"),
    ({}, "not_running", "voice_not_running"),
    ({"preference": "unreadable"}, "degraded", "voice_preference_unreadable"),
    ({"preference": "unreadable", "voice_online": True, "runtime_state": "background"}, "stopping", "voice_stopping"),
])
def test_projection_matrix(kw, state, code):
    got = view(**kw)
    assert (got["state"], got["code"]) == (state, code)
    assert got["message"] == V.MESSAGES.get(code or "", "")


def test_the_wake_is_armed_only_in_sleep_and_the_voice_word_only_with_its_engine():
    ready = {"configured": True, "available": True, "code": None, "keyword": "hey_jarvis"}
    missing = {"configured": True, "available": False, "code": "wake_package_missing"}
    sleep = view(voice_online=True, runtime_state="background", wake=ready)["wake"]
    assert sleep["manual_key"] == "F9" and sleep["manual_armed"] and sleep["voice_word"]["armed"]
    assert not view(voice_online=True, runtime_state="background", wake=missing)["wake"]["voice_word"]["armed"]
    off = view(preference="off", wake=ready)["wake"]
    assert not off["manual_armed"] and not off["voice_word"]["armed"]


def test_wake_engine_says_what_is_missing(no_env_keys, monkeypatch):
    from jarvis.runtime import wake_word_install

    oww = {"wake_word": {"schema_version": 1, "enabled": True, "provider": "openwakeword"}}
    monkeypatch.setattr(wake_word_install, "package_installed", lambda: False)
    assert V.wake_engine(oww)["code"] == "wake_package_missing"
    monkeypatch.setattr(wake_word_install, "package_installed", lambda: True)
    monkeypatch.setattr(wake_word_install, "read_states", lambda: [type("S", (), {"state": "missing"})()])
    got = V.wake_engine(oww)
    assert (got["available"], got["code"]) == (False, "wake_model_missing") and "F9" in got["message"]
    monkeypatch.setattr(wake_word_install, "read_states", lambda: [type("S", (), {"state": "verified"})()])
    assert V.wake_engine(oww)["available"] is True
    porcupine = {"wake_word": {"schema_version": 1, "enabled": True, "provider": "porcupine"}}
    assert V.wake_engine(porcupine)["code"] == "wake_porcupine_key_missing"
    assert V.wake_engine({})["configured"] is False


# ---------------------------------------------------------------------- Control Center


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


@pytest.fixture
def control(tmp_path, no_env_keys):
    return ControlCenter(runtime_root=tmp_path, project_root=tmp_path)


def test_routes_are_registered(control):
    routes = {(r.method, r.resource.canonical) for r in control._app.router.routes()}
    assert ("GET", "/api/voice/lifecycle") in routes and ("POST", "/api/voice/lifecycle") in routes


async def test_fresh_profile_without_key_reads_degraded_and_off_is_saved_and_projected(control, tmp_path):
    first = json.loads((await control.get_voice_lifecycle(None)).text)
    assert (first["preference"], first["state"], first["code"]) == ("sleep", "degraded", "voice_provider_key_missing")
    assert not control.settings_path.exists(), "lire n'écrit rien"
    control.settings_path.write_text(json.dumps({"keep": {"a": 1}}), encoding="utf-8")
    saved = json.loads((await control.save_voice_lifecycle(JsonRequest({"preference": "off"}))).text)
    assert (saved["preference"], saved["state"], saved["code"]) == ("off", "off", "voice_off")
    stored = json.loads(control.settings_path.read_text(encoding="utf-8"))
    assert stored["voice_lifecycle"] == {"schema_version": 1, "preference": "off"} and stored["keep"] == {"a": 1}
    rows = read_jsonl_tail(tmp_path / "trace.jsonl", limit=50)
    saved_rows = [row for row in rows if row["kind"] == "voice.lifecycle.preference_saved"]
    assert saved_rows[-1]["data"] == {"before": "sleep", "after": "off", "managed": False}
    states = [row["data"] for row in rows if row["kind"] == "voice.lifecycle.state"]
    assert {"state": "off", "code": "voice_off", "preference": "off", "problem": None} in states


async def test_voice_online_in_background_reads_sleep_and_a_bad_payload_is_a_coded_400(control, tmp_path):
    import time
    from aiohttp import web

    (tmp_path / ".voice_heartbeat").write_text(f"{time.time()}\n", encoding="utf-8")
    (tmp_path / ".voice_runtime").write_text(json.dumps({"runtime_state": "background"}), encoding="utf-8")
    got = json.loads((await control.get_voice_lifecycle(None)).text)
    assert (got["state"], got["wake"]["manual_armed"]) == ("sleep", True)
    with pytest.raises(web.HTTPBadRequest) as refused:
        await control.save_voice_lifecycle(JsonRequest({"preference": "maybe"}))
    assert refused.value.headers[SETTINGS_ERROR_CODE_HEADER] == "voice_lifecycle_preference_invalid"
    assert not control.settings_path.exists()


async def test_status_beat_carries_the_projection(control):
    status = json.loads((await control.status(None)).text)
    assert status["voice_lifecycle"]["state"] == "degraded" and status["voice_lifecycle"]["preference"] == "sleep"


async def test_wake_word_page_receives_the_real_engine_state(control, monkeypatch):
    from jarvis.runtime import wake_word_install

    monkeypatch.setattr(wake_word_install, "package_installed", lambda: False)
    control.settings_path.write_text(json.dumps(
        {"wake_word": {"schema_version": 1, "enabled": True, "provider": "openwakeword"}}), encoding="utf-8")
    described = json.loads((await control.get_wake_word(None)).text)
    assert described["enabled"] is True
    assert described["engine"]["available"] is False and described["engine"]["code"] == "wake_package_missing"


# ---------------------------------------------------------------------- préparation


def lifecycle(**kw):
    return Probe(value=view(**kw))


def test_readiness_voice_line():
    missing = by_id(facts(voice=lifecycle(key=V.ProviderKey(False, "openai", "OpenAI", "voice_provider_key_missing"))))
    line = missing["voice"]
    assert line.state is ReadinessState.ACTION_NEEDED and not line.required and line.detail == "voice_provider_key_missing"
    assert [a.action_id for a in line.actions] == [ActionId.OPEN_CONNECTIONS]
    off = by_id(facts(voice=lifecycle(preference="off")))["voice"]
    assert off.state is ReadinessState.OPTIONAL and "coupée" in off.summary and "Clé OpenAI présente" in off.summary
    sleep = by_id(facts(voice=lifecycle(voice_online=True, runtime_state="background")))["voice"]
    assert sleep.state is ReadinessState.READY and "F9 la réveille" in sleep.summary
    unread = by_id(facts())["voice"]
    assert unread.state is ReadinessState.UNAVAILABLE and unread.detail == "voice_lifecycle_unavailable"


def test_a_hold_that_changes_is_published_in_launcher_json(tmp_path):
    """Bac à sable du 2026-10-27 : clé absente puis « voix coupée » laissait `held` à l'ancienne raison."""

    preference = {"value": "sleep"}

    def gate(running):
        settings = {"voice_lifecycle": {"schema_version": 1, "preference": preference["value"]}}
        return V.launch_decision(settings, key=lambda _s: V.ProviderKey(False, "openai", "OpenAI",
                                                                         "voice_provider_key_missing"))

    instance, spawned, _notices, _ = launcher(tmp_path, gate=gate)
    seen = []
    original_sleep = instance.sleep

    def sleep(seconds):
        original_sleep(seconds)
        state = tmp_path / "runtime" / L.STATE_FILE
        if state.exists():
            seen.append(json.loads(state.read_text(encoding="utf-8"))["roles"]["voice"]["held"])
        if instance.clock() >= 2.0:
            preference["value"] = "off"
        if instance.clock() >= 5.0:
            (instance.plan.runtime_root / L.STOP_FILE).write_text("now", encoding="utf-8")

    instance.sleep = sleep
    assert instance.run() == 0 and roles_of(spawned) == ["core", "control-center"]
    assert seen[0] == "voice_provider_key_missing" and seen[-1] == "voice_off"


async def test_quit_is_not_held_by_an_open_request_of_the_page(tmp_path, no_env_keys):
    """Bac à sable du 2026-10-27 : une requête encore ouverte (long-poll de la page) faisait attendre l'arrêt du Control
    Center 60 s (aiohttp), au-delà des 15 s de grâce du lanceur : « Quitter JARVIS » finissait en arrêt forcé."""

    import socket
    import time

    import aiohttp
    from aiohttp import web

    from jarvis.runtime import control_center as cc

    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    entered = asyncio.Event()

    async def hang(_request):
        entered.set()
        await asyncio.sleep(120)
        return web.Response(text="late")

    control._app.router.add_get("/__test_hang", hang)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    await control.start(port=port)
    session = aiohttp.ClientSession()
    pending = asyncio.ensure_future(session.get(f"http://127.0.0.1:{port}/__test_hang"))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        started = time.monotonic()
        await control.stop()
        assert time.monotonic() - started < cc.HTTP_SHUTDOWN_TIMEOUT_S + 5
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await session.close()


# ---------------------------------------------------------------------- reprise QA


def test_an_unreadable_block_holds_voice_at_start_and_stops_a_running_voice(tmp_path, no_env_keys, monkeypatch):
    """Reprise QA m1 : avec une clé, un bloc illisible ne démarre pas Voice ; écrit pendant qu'elle tourne, il l'arrête."""

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    runtime = tmp_path / "runtime"
    write_settings(runtime, {"voice_lifecycle": {"preference": "Off"}})
    instance, spawned, notices, _ = launcher(tmp_path, stop_after=3.0, gate=gate_from(runtime))
    assert instance.run() == 0 and notices == [] and roles_of(spawned) == ["core", "control-center"]
    held = [row for row in events(tmp_path) if row["kind"] == "voice_held"]
    assert held[-1]["data"]["code"] == "voice_preference_unreadable" and held[-1]["level"] == "warning"

    write_settings(runtime, {})
    instance, spawned, _notices, _ = launcher(tmp_path, gate=gate_from(runtime))
    original_spawn, original_sleep = instance.spawn, instance.sleep

    def spawn(argv, **kwargs):
        process = original_spawn(argv, **kwargs)
        process.__class__ = CleanProcess
        return process

    def sleep(seconds):
        original_sleep(seconds)
        if instance.clock() >= 3.0:
            write_settings(runtime, {"voice_lifecycle": {"schema_version": 7, "preference": "sleep"}})
        if instance.clock() >= 6.0:
            (runtime / L.STOP_FILE).write_text("now", encoding="utf-8")

    instance.spawn, instance.sleep = spawn, sleep
    assert instance.run() == 0
    voices = [p for p in spawned if p.argv[-1] == "voice"]
    assert len(voices) == 1 and voices[0].returncode == 0 and not voices[0].terminated
    assert "voice_stopping" in [row["kind"] for row in events(tmp_path)]


def test_voice_with_an_unreadable_block_exits_zero_and_says_why(tmp_path, monkeypatch):
    runtime = tmp_path / "rt"
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("JARVIS_DATA_ROOT", str(tmp_path / "data"))
    write_settings(runtime, {"voice_lifecycle": {"schema_version": 1, "preference": "OFF"}})
    from jarvis import app

    def boom(*_args, **_kwargs):  # pragma: no cover - would mean Voice went past the gate
        raise AssertionError("Voice composed its stack despite an unreadable block")

    monkeypatch.setattr("jarvis.runtime.voice_composition.resolve_voice_composition", boom)
    assert asyncio.run(app._run_voice_v2()) == 0
    rows = [row for row in read_jsonl_tail(runtime / "trace.jsonl", limit=50)
            if row["kind"] == "voice.lifecycle.start_refused_off"]
    assert rows[0]["level"] == "warning"
    assert rows[0]["data"] == {"code": "voice_preference_unreadable", "problem": "voice_lifecycle_preference_invalid"}


async def test_an_unreadable_block_is_visible_journaled_and_rewritten_by_the_switch(control, tmp_path):
    control.settings_path.write_text(json.dumps({"voice_lifecycle": {"preference": "Off"}}), encoding="utf-8")
    view = json.loads((await control.get_voice_lifecycle(None)).text)
    assert (view["preference"], view["state"], view["code"], view["problem"]) == (
        "unreadable", "degraded", "voice_preference_unreadable", "voice_lifecycle_preference_invalid")
    assert "illisible" in view["message"]
    rows = [row for row in read_jsonl_tail(tmp_path / "trace.jsonl", limit=50) if row["kind"] == "voice.lifecycle.state"]
    assert rows[-1]["level"] == "warning" and rows[-1]["data"]["problem"] == "voice_lifecycle_preference_invalid"
    saved = json.loads((await control.save_voice_lifecycle(JsonRequest({"preference": "sleep"}))).text)
    assert saved["preference"] == "sleep" and saved["problem"] is None
    assert json.loads(control.settings_path.read_text(encoding="utf-8"))["voice_lifecycle"] == {
        "schema_version": 1, "preference": "sleep"}


class ShortOffVoice(CleanProcess):
    """Voice qui a vu une « voix coupée » trop brève pour le lanceur (bascules de 0,25 s, harnais QA) : elle se libère
    (code 0) à l'instant `exit_at`, alors que la préférence est déjà revenue à « veille »."""

    exit_at: float = 0.0
    clock = None

    def poll(self):
        if self.returncode is None and self.clock() >= self.exit_at:
            self.returncode = 0
        return super().poll()


def test_fast_off_sleep_toggles_never_count_as_crashes_and_voice_follows_the_current_preference(tmp_path):
    """Reprise QA m2 : cinq Off -> Sleep plus brefs que la relecture du lanceur ; aucun plantage compté, jamais
    d'abandon, Voice relancée chaque fois parce que la préférence courante est « veille »."""

    board = Switchboard()  # « veille » à chaque lecture du lanceur : il ne voit jamais les Off brefs
    instance, spawned, notices, _ = launcher(tmp_path, gate=board)
    original_spawn, original_sleep = instance.spawn, instance.sleep
    exits = iter([2.5, 6.5, 10.5, 14.5, 18.5])

    def spawn(argv, **kwargs):
        process = original_spawn(argv, **kwargs)
        process.__class__ = ShortOffVoice if argv[-1] == "voice" else CleanProcess
        if argv[-1] == "voice":
            process.clock, process.exit_at = instance.clock, next(exits, 1e9)
        return process

    def sleep(seconds):
        original_sleep(seconds)
        if instance.clock() >= 25.0:
            (instance.plan.runtime_root / L.STOP_FILE).write_text("now", encoding="utf-8")

    instance.spawn, instance.sleep = spawn, sleep
    assert instance.run() == 0 and notices == []
    kinds = [row["kind"] for row in events(tmp_path)]
    assert kinds.count("voice_exited_clean") == 5
    assert "child_abandoned" not in kinds and "child_exited" not in kinds
    voices = [p for p in spawned if p.argv[-1] == "voice"]
    assert len(voices) == 6 and voices[-1].returncode == 0, "la dernière incarnation tournait jusqu'à Quitter"
    assert instance.plan.roles[2].restarts == [], "aucun redémarrage de plantage consommé"


def test_a_voice_that_keeps_exiting_zero_is_still_abandoned_eventually(tmp_path):
    instance, spawned, _notices, _ = launcher(tmp_path, gate=Switchboard(),
                                              behaviours={"voice": [{"exit_after_polls": 0, "code": 0}] * 40},
                                              stop_after=40.0)
    assert instance.run() == 0
    kinds = [row["kind"] for row in events(tmp_path)]
    assert "child_abandoned" in kinds
    assert len([p for p in spawned if p.argv[-1] == "voice"]) == L.VOICE_CLEAN_EXITS_MAX + 1
