"""Écran du réglage `scene.enabled` (handoff jarvis-constellation-scene-runtime, Slice 11).

- aller-retour des réglages : `GET/POST /api/settings` décrivent, écrivent et
  relisent le bloc `scene` (`enabled`, `source`, `stored`, `env`), et
  `/api/status` suit ;
- variable d'environnement : lecture seule côté page, écriture refusée côté
  serveur (`scene_env_override`), fichier inchangé ;
- l'état réel du brain en cours (`agent.display_tools`), que l'écran compare au
  réglage pour proposer un redémarrage ;
- la logique pure de la section (`control_center_scene_settings.js`) exécutée
  avec node, et les garanties statiques du bloc navigateur (onglet
  Expérimental, confirmation en page, pas de `confirm()`, pas d'`innerHTML`).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from aiohttp import web
import pytest

from jarvis.runtime import claude_local
from jarvis.runtime.claude_local import ClaudeLocalAgent
from jarvis.runtime.control_center import (
    BAREHANDS_SCRIPT_MARKER,
    SCENE_PAGE_SCRIPT_MARKER,
    SCENE_SETTINGS_SCRIPT_MARKER,
    SETTINGS_ERROR_CODE_HEADER,
    TIMELINE_SCRIPT_MARKER,
    ControlCenter,
)
from jarvis.runtime.display_mcp import DisplayMcpTarget
from jarvis.runtime.journal import read_jsonl_tail

RUNTIME = Path(__file__).resolve().parents[2] / "jarvis" / "runtime"
SETTINGS_JS = RUNTIME / "control_center_scene_settings.js"
BAREHANDS_JS = RUNTIME / "control_center_barehands.js"
PAGE_HTML = RUNTIME / "control_center.html"
_NODE = shutil.which("node")


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch):
    monkeypatch.delenv("JARVIS_SCENE_ENABLED", raising=False)


def _target(tmp_path: Path) -> DisplayMcpTarget:
    return DisplayMcpTarget("127.0.0.1", 17999, tmp_path / "core.token", tmp_path)


def _settings_file(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))


def _node(expression: str) -> Any:
    if _NODE is None:
        pytest.skip("node absent")
    script = f"const L=require({json.dumps(str(SETTINGS_JS))});console.log(JSON.stringify({expression}))"
    result = subprocess.run([_NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def describe(scene: Any, status: Any) -> dict[str, Any]:
    return _node(f"L.describe({json.dumps(scene)},{json.dumps(status)})")


def status_view(payload: Any) -> Any:
    """La projection du statut que le bloc navigateur garde (pure, donc testée)."""

    return _node(f"L.statusView({json.dumps(payload)})")


# ------------------------------------------------------------------ serveur


async def test_the_settings_round_trip_describes_writes_and_rereads_the_gate(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, display_mcp=_target(tmp_path))
    described = json.loads((await control.get_settings(None)).text)
    assert described["scene"] == {"enabled": False, "source": "settings", "stored": False, "env": None}
    assert json.loads((await control.status(None)).text)["scene"] == {"enabled": False, "source": "settings"}

    saved = json.loads((await control.save_settings(JsonRequest({"scene": {"enabled": True}}))).text)
    assert saved["scene"] == {"enabled": True, "source": "settings", "stored": True, "env": None}
    assert _settings_file(tmp_path)["scene"] == {"enabled": True}
    reread = json.loads((await control.get_settings(None)).text)
    assert reread["scene"] == saved["scene"]
    # Le rendu lit le même interrupteur dans le statut, relu chaque seconde par la page.
    assert json.loads((await control.status(None)).text)["scene"] == {"enabled": True, "source": "settings"}
    assert control.agent.display_mcp == _target(tmp_path)

    off = json.loads((await control.save_settings(JsonRequest({"scene": {"enabled": False}}))).text)
    assert off["scene"]["enabled"] is False and _settings_file(tmp_path)["scene"] == {"enabled": False}
    assert control.agent.display_mcp is None


async def test_an_environment_override_is_described_and_refused_without_touching_the_file(tmp_path, monkeypatch):
    (tmp_path / "control-center-settings.json").write_text(json.dumps({"scene": {"enabled": False}, "other": 1}), encoding="utf-8")
    monkeypatch.setenv("JARVIS_SCENE_ENABLED", "on")
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, display_mcp=_target(tmp_path))
    described = json.loads((await control.get_settings(None)).text)
    assert described["scene"] == {"enabled": True, "source": "env", "stored": False, "env": "JARVIS_SCENE_ENABLED"}
    before = (tmp_path / "control-center-settings.json").read_bytes()
    for enabled in (True, False):
        with pytest.raises(web.HTTPBadRequest) as refused:
            await control.save_settings(JsonRequest({"scene": {"enabled": enabled}}))
        assert refused.value.headers[SETTINGS_ERROR_CODE_HEADER] == "scene_env_override"
        assert "JARVIS_SCENE_ENABLED" in refused.value.text and "relancez le Control Center" in refused.value.text
    assert (tmp_path / "control-center-settings.json").read_bytes() == before
    # Rien d'autre n'est bloqué : un enregistrement sans bloc scene passe.
    await control.save_settings(JsonRequest({"active_timeout_s": "0"}))
    assert _settings_file(tmp_path)["scene"] == {"enabled": False}


class _Stream:
    async def readline(self) -> bytes:
        return b""

    async def read(self, n: int = -1) -> bytes:  # noqa: ARG002
        return b""


class _LiveProcess:
    pid = 4343

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.stdin = None
        self.stdout = _Stream()
        self.stderr = _Stream()

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


async def _running(monkeypatch, agent: ClaudeLocalAgent) -> None:
    async def fake_exec(*args, **kwargs):  # noqa: ANN002, ANN003
        return _LiveProcess()  # un processus neuf à chaque lancement, comme le vrai CLI

    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", fake_exec)
    if agent._process_tree is not None:
        monkeypatch.setattr(agent._process_tree, "attach_and_resume", lambda pid: None)
    await agent.start()


async def test_the_brain_snapshot_says_whether_the_running_process_has_the_display_tools(monkeypatch, tmp_path):
    agent = ClaudeLocalAgent(runtime_root=tmp_path / "runtime", cwd=tmp_path)
    assert agent.snapshot()["display_tools"] is False
    await _running(monkeypatch, agent)
    assert agent.snapshot()["state"] == "running" and agent.snapshot()["display_tools"] is False
    # Le réglage change pendant que le brain tourne : le processus en cours, lui, ne change pas.
    agent.display_mcp = _target(tmp_path)
    assert agent.snapshot()["display_tools"] is False
    await agent.stop()
    await _running(monkeypatch, agent)
    assert agent.snapshot()["display_tools"] is True
    agent.display_mcp = None
    assert agent.snapshot()["display_tools"] is True
    await agent.stop()
    assert agent.snapshot()["display_tools"] is False
    # Réglage allumé mais configuration MCP impossible à écrire : le brain démarre sans outils, et l'écran le dit.
    agent.display_mcp = _target(tmp_path)

    def refuse(*args, **kwargs):  # noqa: ANN002, ANN003
        raise OSError("disque plein")

    monkeypatch.setattr("jarvis.runtime.display_mcp.write_mcp_config", refuse)
    await _running(monkeypatch, agent)
    assert agent.snapshot()["display_tools"] is False
    await agent.stop()


class _RestartRequest:
    def __init__(self, body: bytes | None) -> None:
        self.body = body
        self.content_length = None if body is None else len(body)
        self.can_read_body = body is not None
        self.content = self

    async def iter_chunked(self, size: int):  # noqa: ARG002
        yield self.body


class _RestartSpy:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def restart(self, *, resume: bool = True) -> dict:
        self.calls.append({"resume": resume})
        return {"state": "running"}


async def test_the_restart_route_opens_a_new_conversation_only_when_asked(tmp_path, monkeypatch):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    spy = _RestartSpy()
    monkeypatch.setattr(type(control), "agent", property(lambda self: spy))
    for body, resume in ((None, True), (b"", True), (b"{}", True), (b'{"new_conversation": false}', True), (b'{"new_conversation": true}', False)):
        await control.agent_restart(_RestartRequest(body))
        assert spy.calls[-1] == {"resume": resume}, body
    for bad in (b"[]", b'{"new_conversation": "oui"}', b'{"fresh": true}', b"{", b'{"new_conversation": true, "new_conversation": false}'):
        with pytest.raises(web.HTTPBadRequest):
            await control.agent_restart(_RestartRequest(bad))
    with pytest.raises(web.HTTPRequestEntityTooLarge):
        await control.agent_restart(_RestartRequest(b" " * 300))
    assert len(spy.calls) == 5
    journaled = [e["data"] for e in read_jsonl_tail(tmp_path / "trace.jsonl", limit=50) if e["kind"] == "agent.restart"]
    assert journaled == [{"new_conversation": False}] * 4 + [{"new_conversation": True}]


async def test_a_restart_without_resume_starts_the_cli_without_resume(monkeypatch, tmp_path):
    started: list[list[str]] = []

    async def fake_exec(*args, **kwargs):  # noqa: ANN002, ANN003
        started.append([str(a) for a in args])
        return _LiveProcess()

    agent = ClaudeLocalAgent(runtime_root=tmp_path / "runtime", cwd=tmp_path)
    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", fake_exec)
    if agent._process_tree is not None:
        monkeypatch.setattr(agent._process_tree, "attach_and_resume", lambda pid: None)
    agent.session_id = "conversation-1"
    await agent.restart()
    assert "--resume" in started[-1] and started[-1][started[-1].index("--resume") + 1] == "conversation-1"
    await agent.restart(resume=False)
    assert "--resume" not in started[-1]
    await agent.stop()


async def test_the_display_prompt_follows_new_conversations_only(monkeypatch, tmp_path):
    agent = ClaudeLocalAgent(runtime_root=tmp_path / "runtime", cwd=tmp_path)
    await _running(monkeypatch, agent)
    agent.session_id = "conversation-flag-off"
    assert (agent.snapshot()["display_tools"], agent.snapshot()["display_prompt"]) == (False, False)
    agent.display_mcp = _target(tmp_path)
    await agent.restart()  # reprise : outils oui, consigne figée de la conversation
    assert (agent.snapshot()["display_tools"], agent.snapshot()["display_prompt"]) == (True, False)
    await agent.restart(resume=False)  # conversation neuve : la consigne suit
    assert (agent.snapshot()["display_tools"], agent.snapshot()["display_prompt"]) == (True, True)
    agent.session_id = "conversation-flag-on"
    agent.display_mcp = None
    await agent.restart()
    assert (agent.snapshot()["display_tools"], agent.snapshot()["display_prompt"]) == (False, True)
    await agent.stop()
    assert (agent.snapshot()["display_tools"], agent.snapshot()["display_prompt"]) == (False, False)


# ------------------------------------------------------------------ logique pure (node)


def test_the_toggle_is_read_only_and_explained_when_the_environment_imposes_it():
    model = describe({"enabled": True, "source": "env", "stored": False, "env": "JARVIS_SCENE_ENABLED"}, None)
    assert model["checked"] is True and model["readOnly"] is True
    assert "JARVIS_SCENE_ENABLED" in model["source"]["title"]
    detail = model["source"]["detail"]
    assert "lecture seule" in detail and "relancez le Control Center" in detail and "ignoré tant qu'elle existe : désactivée" in detail

    free = describe({"enabled": False, "source": "settings", "stored": False, "env": None}, None)
    assert free["readOnly"] is False and free["source"] is None and free["checked"] is False
    # Réglages illisibles : jamais un interrupteur actif sur une valeur inventée.
    for broken in (None, {}, {"enabled": "true", "source": "settings"}):
        unknown = describe(broken, None)
        assert unknown["known"] is False and unknown["readOnly"] is True and unknown["checked"] is False


def test_the_effects_say_render_now_brain_tools_at_next_start_and_core_keeps_projecting():
    effects = {e["term"]: e["text"] for e in describe({"enabled": False, "source": "settings"}, None)["effects"]}
    assert list(effects) == ["Affichage", "Outils du brain", "Core"]
    assert "sans recharger" in effects["Affichage"] and "Immédiat" in effects["Affichage"]
    assert effects["Outils du brain"].startswith("Au prochain démarrage du brain sur une nouvelle conversation") and "Jamais archiver" in effects["Outils du brain"]
    assert "même éteinte" in effects["Core"]


def _status(state: str = "running", tools: bool = False, active: int = 0, cli: str = "claude", prompt: bool | None = None) -> dict[str, Any]:
    agent = {"name": "Claude" if cli == "claude" else "Codex", "state": state, "display_tools": tools}
    if prompt is not None:
        agent["display_prompt"] = prompt
    return {"agent_cli": cli, "agent": agent,
            "subagents": {"active": active, "running_shell": 0}}


ON = {"enabled": True, "source": "settings", "stored": True, "env": None}
OFF = {"enabled": False, "source": "settings", "stored": False, "env": None}


def test_the_brain_state_is_compared_with_the_choice_and_a_restart_is_offered_only_on_mismatch():
    assert describe(ON, _status(tools=True))["brain"] == {
        "tone": "ok", "title": "Brain en cours : outils d'affichage présents",
        "detail": "Il peut lire, composer et capturer la scène.", "restart": False}
    assert describe(OFF, _status(tools=False))["brain"]["restart"] is False

    enable = describe(ON, _status(tools=False, active=2))["brain"]
    assert enable["tone"] == "warn" and enable["restart"] is True
    assert "pas encore d'outils d'affichage" in enable["title"]
    assert enable["confirm"] == {
        "title": "Redémarrer le brain ?",
        "lines": ["Il repart sur une nouvelle conversation, avec les outils et la consigne d'affichage.",
                  "La conversation en cours n'est pas reprise : une conversation reprise garderait son ancienne consigne.",
                  "Cela interrompra 2 sous-agents en cours."],
        "confirmLabel": "Redémarrer le brain", "danger": True}

    disable = describe(OFF, _status(tools=True))["brain"]
    assert disable["restart"] is True and "garde ses outils" in disable["title"]
    assert disable["confirm"]["lines"][0] == "Il repart sur une nouvelle conversation, sans les outils ni la consigne d'affichage."
    assert disable["confirm"]["lines"][2] == "Aucun sous-agent n'est en cours."
    assert disable["confirm"]["danger"] is False


def test_the_status_projection_keeps_everything_brain_view_reads():
    """Sans `display_prompt`, l'écran retombait sur le repli « agent plus ancien » et ne montrait jamais l'écart."""

    payload = {"agent_cli": "claude", "voice_state": "idle", "scene": {"enabled": True},
               "agent": {"name": "Claude", "state": "running", "display_tools": True, "display_prompt": False, "pid": 42, "events": [1, 2]},
               "subagents": {"active": 2, "running_shell": 1}}
    kept = status_view(payload)
    assert kept == {"agent_cli": "claude", "agent": {"name": "Claude", "state": "running", "display_tools": True, "display_prompt": False},
                    "subagents": {"active": 2, "running_shell": 1}}
    # La vue du brain, construite sur cette projection, voit bien l'écart (scénario D de la QA).
    assert describe(ON, kept)["brain"]["title"] == "Conversation reprise : outils présents, consigne d'affichage absente"
    for broken in (None, "", {"agent_cli": "claude"}):
        assert (status_view(broken) or {}).get("agent") is None


def test_a_resumed_conversation_with_the_old_prompt_is_a_mismatch_even_with_the_tools():
    """Constaté en E2E (Slice 11) : reprise = outils présents, consigne d'affichage absente, aucun artefact."""

    resumed_on = describe(ON, _status(tools=True, prompt=False))["brain"]
    assert resumed_on["restart"] is True and resumed_on["title"] == "Conversation reprise : outils présents, consigne d'affichage absente"
    resumed_off = describe(OFF, _status(tools=False, prompt=True))["brain"]
    assert resumed_off["restart"] is True and "sans ses outils" in resumed_off["title"]
    assert describe(ON, _status(tools=True, prompt=True))["brain"]["restart"] is False
    assert describe(OFF, _status(tools=False, prompt=False))["brain"]["restart"] is False


def test_a_stopped_brain_another_cli_or_an_unread_status_never_offer_a_restart():
    stopped = describe(ON, _status(state="stopped"))["brain"]
    assert stopped == {"tone": "info", "title": "Brain arrêté", "detail": "Il recevra les outils d'affichage à son prochain démarrage.", "restart": False}
    assert describe(OFF, _status(state="exited"))["brain"]["detail"] == "Il démarrera sans outils d'affichage."
    codex = describe(ON, _status(cli="codex"))["brain"]
    assert codex["restart"] is False and "Seul le brain Claude" in codex["detail"]
    for status in (None, {}, {"agent": None}):
        assert describe(ON, status)["brain"] == {
            "tone": "info", "title": "État du brain inconnu",
            "detail": "Le statut du Control Center n'a pas pu être lu. Il est relu à chaque seconde.", "restart": False}


# ------------------------------------------------------------------ page (statique)


async def test_the_section_is_injected_after_barehands_into_the_experimental_tab(tmp_path):
    html = PAGE_HTML.read_text(encoding="utf-8")
    assert html.index(BAREHANDS_SCRIPT_MARKER) < html.index(SCENE_PAGE_SCRIPT_MARKER) < html.index(SCENE_SETTINGS_SCRIPT_MARKER) < html.index(TIMELINE_SCRIPT_MARKER)
    served = (await ControlCenter(runtime_root=tmp_path, project_root=tmp_path).index(None)).text
    source = SETTINGS_JS.read_text(encoding="utf-8")
    assert SCENE_SETTINGS_SCRIPT_MARKER not in served and source in served
    # Barehands crée l'onglet ; la section s'y ajoute ensuite (installations dans l'ordre d'insertion).
    assert served.index(BAREHANDS_JS.read_text(encoding="utf-8")) < served.index(source)
    assert "TABS.push({id:TAB_ID,label:'Expérimental',save:false})" in BAREHANDS_JS.read_text(encoding="utf-8")
    assert "const TAB_ID='experimental';" in source


def test_the_browser_block_saves_through_settings_confirms_in_page_and_stays_accessible():
    source = SETTINGS_JS.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    pure, browser = code.split("installJarvisSceneSettings")
    for forbidden in ("document.", "window.", "fetch(", "setInterval", "addEventListener", "innerHTML", "localStorage"):
        assert forbidden not in pure, forbidden
    # Écriture par le bloc scene de /api/settings, jamais de fetch à la main (api() vérifie le statut HTTP).
    assert "body:JSON.stringify({scene:{enabled}})" in browser and "fetch(" not in browser
    assert "await confirmDialog(" in browser and "body:JSON.stringify(Logic.RESTART_BODY)" in browser
    assert "const RESTART_BODY=Object.freeze({new_conversation:true});" in pure
    for forbidden in ("confirm(", "alert(", "prompt(", "innerHTML"):
        assert re.search(r"(?<![\w.])" + re.escape(forbidden), browser.replace("confirmDialog(", "")) is None, forbidden
    # Accessibilité : case étiquetée, décrite, focus rendu au contrôle après chaque redessin.
    assert "type:'checkbox',id:'f_scene'" in browser and "node('label',{for:'f_scene'}" in browser
    assert "'aria-describedby':describedBy" in browser
    # Le statut gardé par la page passe par la fonction pure (MAJOR-1 : un champ oublié rendait l'écran aveugle).
    assert "view.status=Logic.statusView(value)" in browser and "display_prompt" not in browser.split("function statusView")[-1].split("}")[0]
    # Une seule région vivante, hors de la section redessinée, dont seul le texte change.
    assert "liveEl.setAttribute('role','status')" in browser and "liveEl.setAttribute('aria-live','polite')" in browser
    assert "id:'sceneBrain'}" in browser or "id:'sceneBrain'," in browser
    assert "role:'status'" not in browser.split("const brain=node(")[1].split(");")[0]
    assert "announce(Logic.brainSentence(" in browser and "if(!text||text===lastSpoken)return;" in browser
    # Un redémarrage refusé laisse un bandeau, pas seulement une notification.
    assert "view.error=`Redémarrage du brain impossible" in browser
    assert "focus({preventScroll:true})" in browser and ":focus-visible" in browser
    # Échec visible (bandeau + notification), journalisé en console, main rendue dans finally.
    assert "scene.setting_failed" in browser and "scene.brain_restart_failed" in browser
    assert browser.count("finally{") >= 2 and "RESTART_DEADLINE_MS" in browser
    # Rendu appliqué tout de suite : le statut est relu après l'écriture.
    assert "refreshStatus()" in browser
