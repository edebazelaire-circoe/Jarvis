"""Canal de commandes Bare Hands, du cerveau à la page (Slice 12).

Chaîne réelle exercée ici : outils MCP `jarvis-barehands` →
`BarehandsCommandTools` → **vrai** `ControlCenter` servi en HTTP →
`BarehandsCommandBroker` → long-poll → reçu. Rien n'est simulé entre les deux
bouts sauf la page, parce que c'est elle qui manque ; et le test qui en a
besoin la remplace par un client qui appelle exactement les deux routes que la
vraie page appelle.

Ce que ce fichier épingle :

- **le vocabulaire est fermé** et chaque refus porte un code stable, dans le
  corps *et* dans `X-Jarvis-Error-Code` ;
- **une commande expire** : sans page visible, le cerveau reçoit
  `barehands_no_visible_page` après l'échéance, jamais un 200 optimiste, et un
  reçu arrivé trop tard est refusé plutôt qu'appliqué ;
- **l'identifiant est à usage unique** : le second reçu est refusé ;
- **la porte** : Bare Hands éteint, la route refuse, `/api/status` le dit, et
  l'agent ne reçoit **ni** serveur MCP **ni** consigne ;
- **aucun faux succès** : un refus de la page devient une erreur d'outil, pas
  un résultat.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import socket

import aiohttp
import pytest

from jarvis.domain import barehands_command as vocab
from jarvis.domain.barehands_command import BarehandsCommandError
from jarvis.runtime import barehands_test_mode as barehands
from jarvis.runtime.barehands_commands import BarehandsCommandBroker
from jarvis.runtime.barehands_mcp import (
    CONFIG_FILE_NAME,
    SERVER_NAME,
    TOOL_COMMANDS,
    TOOL_NAMES,
    BarehandsCommandTools,
    BarehandsConfigError,
    BarehandsMcpTarget,
    BarehandsToolError,
    build_server,
    mcp_config,
)
from jarvis.runtime.claude_local import BRAIN_BAREHANDS_PROMPT, BRAIN_SYSTEM_PROMPT, ClaudeLocalAgent
from jarvis.runtime.control_center import (
    BAREHANDS_COMMANDS_SCRIPT_MARKER,
    BAREHANDS_SCRIPT_MARKER,
    SCENE_PAGE_SCRIPT_MARKER,
    SETTINGS_ERROR_CODE_HEADER,
    ControlCenter,
)
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.prompt_catalog import default_prompt_registry


# ------------------------------------------------------------------ fixtures


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class JsonRequest:
    """Même double que `test_barehands_test_mode` : seul `save_barehands` le prend."""

    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


class RunningCenter:
    """Un vrai Control Center, servi en HTTP sur la boucle locale."""

    def __init__(self, control: ControlCenter, port: int) -> None:
        self.control = control
        self.port = port
        self.base = f"http://127.0.0.1:{port}"

    async def enable(self, value: bool = True) -> None:
        await self.control.save_barehands(JsonRequest({"enabled": value}))

    async def poll(self, session: aiohttp.ClientSession, wait_s: float = 5) -> dict:
        async with session.get(f"{self.base}/api/barehands/commands?wait_s={wait_s}") as response:
            assert response.status == 200, await response.text()
            return await response.json()

    async def receipt(self, session: aiohttp.ClientSession, command_id: str, body: dict) -> tuple[int, dict, str]:
        async with session.post(f"{self.base}/api/barehands/commands/{command_id}", json=body) as response:
            return response.status, await response.json(), response.headers.get(SETTINGS_ERROR_CODE_HEADER, "")

    async def ask(self, session: aiohttp.ClientSession, command: str) -> tuple[int, dict, str]:
        async with session.post(f"{self.base}/api/barehands/commands", json={"command": command}) as response:
            return response.status, await response.json(), response.headers.get(SETTINGS_ERROR_CODE_HEADER, "")


@pytest.fixture
async def running(tmp_path, monkeypatch):
    """Control Center démarré pour de vrai : routes, garde d'origine, journal."""

    monkeypatch.delenv(barehands.VENDOR_ENV, raising=False)
    # Le cerveau n'est pas lancé par ce test : `start()` le tenterait.
    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path,
                            barehands_vendor_root=tmp_path / "vendor")
    port = free_port()
    from aiohttp import web

    runner = web.AppRunner(control._app)  # noqa: SLF001 - démarrage sans l'agent, volontaire
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    try:
        yield RunningCenter(control, port)
    finally:
        control.barehands_commands.close()
        await runner.cleanup()


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as client:
        yield client


def trace(control: ControlCenter, limit: int = 200) -> list[dict]:
    return read_jsonl_tail(control.journal.trace_path, limit=limit)


def kinds(control: ControlCenter) -> list[str]:
    return [line["kind"] for line in trace(control)]


# ------------------------------------------------------- le vocabulaire (pur)


def test_the_vocabulary_is_closed_and_every_refusal_has_its_own_code():
    """Une commande inconnue ne devient pas `activate`, et un reçu ne peut pas
    inventer son code : les deux tables sont fermées, et c'est ce qui permet au
    journal et à l'erreur d'outil de vouloir dire quelque chose."""

    assert vocab.COMMANDS == ("activate", "deactivate", "calibrate", "tutorial", "exit_overlay")
    for name in vocab.COMMANDS:
        assert vocab.check_command(name) == name
    for bad in ("", "ACTIVATE", "activate ", "enable", None, 3, ["activate"]):
        with pytest.raises(BarehandsCommandError) as caught:
            vocab.check_command(bad)
        assert caught.value.code == vocab.COMMAND_UNKNOWN and caught.value.status == 400
    # La demande : un champ, exactement, et aucun défaut silencieux.
    assert vocab.parse_request({"command": "activate"}) == "activate"
    for bad, code in (
        (None, vocab.BAD_REQUEST), ([], vocab.BAD_REQUEST), ({}, vocab.BAD_REQUEST),
        ({"command": "activate", "force": True}, vocab.BAD_REQUEST),
        ({"commande": "activate"}, vocab.BAD_REQUEST),
        ({"command": "danser"}, vocab.COMMAND_UNKNOWN),
    ):
        with pytest.raises(BarehandsCommandError) as caught:
            vocab.parse_request(bad)
        assert caught.value.code == code, bad


def test_a_receipt_cannot_invent_a_refusal_code_or_a_lifecycle():
    """Le reçu est la seule chose que la page raconte d'elle-même. S'il pouvait
    porter n'importe quelle chaîne, le code stable du journal ne vaudrait que
    ce que vaut la page qui l'a écrit — et un refus muet remonterait au cerveau
    comme une panne de transport."""

    ok = vocab.parse_receipt({"outcome": "applied", "lifecycle": "active"})
    assert ok == {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None}
    refused = vocab.parse_receipt(
        {"outcome": "refused", "lifecycle": "error", "code": vocab.LIFECYCLE_REFUSED, "reason": "x" * 999}
    )
    assert refused["code"] == vocab.LIFECYCLE_REFUSED and len(refused["reason"]) == vocab.MAX_REASON_CHARS
    for bad in (
        None, "applied", {"outcome": "applied"}, {"lifecycle": "active"},
        {"outcome": "done", "lifecycle": "active"},
        {"outcome": "applied", "lifecycle": "asleep"},
        {"outcome": "refused", "lifecycle": "off"},                              # refus sans code
        {"outcome": "refused", "lifecycle": "off", "code": "barehands_je_sais_pas"},
        {"outcome": "applied", "lifecycle": "active", "code": vocab.FLOW_ABSENT},  # code sans refus
        {"outcome": "applied", "lifecycle": "active", "reason": 7},
        {"outcome": "applied", "lifecycle": "active", "extra": 1},
    ):
        with pytest.raises(BarehandsCommandError) as caught:
            vocab.parse_receipt(bad)
        assert caught.value.code == vocab.BAD_RECEIPT, bad
    # Les trois codes de page ont chacun une phrase écrite pour le cerveau : un
    # code sans phrase se lirait « échec » et n'apprendrait rien à l'utilisateur.
    assert set(vocab.PAGE_CODES) == set(vocab.PAGE_CODE_EXPLANATIONS)


def test_the_command_id_is_unguessable_and_checked_like_a_capture():
    for bad in (None, "", "court", "a" * 31, "a" * 65, "avec/une/barre" + "a" * 20, 42):
        with pytest.raises(BarehandsCommandError) as caught:
            vocab.check_command_id(bad)
        assert caught.value.code == vocab.UNKNOWN_COMMAND_ID and caught.value.status == 404
    assert vocab.check_command_id("A" * 32) == "A" * 32
    assert vocab.short_id("B" * 40) == "B" * 8


def test_the_deadline_is_bounded_and_shorter_than_a_scene_capture():
    """3 s, et c'est un arbitrage, pas une valeur ronde : la capture (5 s) doit
    dessiner et téléverser une image, une commande n'a qu'à traverser un
    long-poll ouvert. En face, le cerveau **bloque** pendant que la
    conversation vocale attend."""

    from jarvis.domain.scene_capture import CAPTURE_DEADLINE_S

    assert 0 < vocab.COMMAND_DEADLINE_S < CAPTURE_DEADLINE_S
    assert vocab.COMMAND_REDELIVER_S < vocab.COMMAND_DEADLINE_S
    assert vocab.COMMAND_DEADLINE_S < vocab.MAX_POLL_WAIT_S


# ------------------------------------------------------------------ courtier


async def test_a_command_with_nobody_listening_expires_instead_of_succeeding(tmp_path):
    """Le cœur de la Slice : personne n'écoute, donc **rien n'a eu lieu**, et
    c'est ce que le cerveau apprend. Un 200 optimiste ici ferait dire à JARVIS
    « c'est activé » devant une fenêtre fermée."""

    from jarvis.runtime.journal import RuntimeJournal

    journal = RuntimeJournal(tmp_path)
    broker = BarehandsCommandBroker(journal=journal, deadline_s=0.05)
    with pytest.raises(BarehandsCommandError) as caught:
        await broker.request("activate")
    assert caught.value.code == vocab.NO_VISIBLE_PAGE and caught.value.status == 504
    # La place est rendue : une commande échue n'occupe pas le canal.
    assert broker.delivery_due() is None
    lines = {line["kind"]: line for line in read_jsonl_tail(journal.trace_path, limit=20)}
    assert set(lines) == {"barehands.command_requested", "barehands.command_expired"}
    expired = lines["barehands.command_expired"]
    assert expired["level"] == "warning"
    assert expired["data"]["code"] == vocab.NO_VISIBLE_PAGE
    assert expired["data"]["command"] == "activate" and expired["data"]["deliveries"] == 0
    assert expired["data"]["waited_ms"] >= 0


async def test_a_pending_command_is_redelivered_at_most_once_per_window(tmp_path):
    """Deux fenêtres ouvertes ne se disputent pas la commande en boucle serrée :
    la redistribution est bornée, exactement comme celle d'une capture."""

    from jarvis.runtime.journal import RuntimeJournal

    broker = BarehandsCommandBroker(journal=RuntimeJournal(tmp_path), deadline_s=5.0, redeliver_s=5.0)
    task = asyncio.ensure_future(broker.request("deactivate"))
    await asyncio.sleep(0)
    first = broker.deliver()
    assert first is not None and first["name"] == "deactivate" and first["remaining_ms"] > 0
    # Aussitôt après, rien : la fenêtre de redistribution n'est pas écoulée.
    assert broker.deliver() is None
    assert broker.delivery_due() > 0
    broker.complete(first["id"], {"outcome": "applied", "lifecycle": "sleep", "code": None, "reason": None})
    answer = await task
    assert answer["outcome"] == "applied" and answer["deliveries"] == 1 and answer["command"] == "deactivate"
    # Consommée : plus rien à remettre, même à la fenêtre suivante.
    assert broker.deliver() is None and broker.delivery_due() is None


async def test_one_command_at_a_time_and_one_receipt_per_command(tmp_path):
    from jarvis.runtime.journal import RuntimeJournal

    broker = BarehandsCommandBroker(journal=RuntimeJournal(tmp_path), deadline_s=5.0)
    task = asyncio.ensure_future(broker.request("activate"))
    await asyncio.sleep(0)
    with pytest.raises(BarehandsCommandError) as busy:
        await broker.request("deactivate")
    assert busy.value.code == vocab.COMMAND_BUSY and busy.value.status == 409
    command = broker.deliver()
    receipt = {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None}
    broker.complete(command["id"], receipt)
    assert (await task)["outcome"] == "applied"
    # Le même identifiant une seconde fois : refusé, jamais rejoué.
    with pytest.raises(BarehandsCommandError) as again:
        broker.complete(command["id"], receipt)
    assert again.value.code == vocab.UNKNOWN_COMMAND_ID and again.value.status == 404


async def test_a_receipt_after_the_deadline_is_refused_not_applied(tmp_path):
    """Une commande périmée ne doit pas se déclencher après coup : l'utilisateur
    est passé à autre chose."""

    from jarvis.runtime.journal import RuntimeJournal

    journal = RuntimeJournal(tmp_path)
    broker = BarehandsCommandBroker(journal=journal, deadline_s=0.05)
    task = asyncio.ensure_future(broker.request("activate"))
    await asyncio.sleep(0)
    command = broker.deliver()
    with pytest.raises(BarehandsCommandError) as caught:
        await task
    assert caught.value.code == vocab.NO_VISIBLE_PAGE
    with pytest.raises(BarehandsCommandError) as late:
        broker.complete(command["id"], {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None})
    # La commande a quitté la place à son échéance : le reçu tardif est inconnu.
    assert late.value.code == vocab.UNKNOWN_COMMAND_ID
    assert any(line["data"].get("code") == vocab.UNKNOWN_COMMAND_ID
               for line in read_jsonl_tail(journal.trace_path, limit=20)
               if line["kind"] == "barehands.receipt_refused")


async def test_a_command_already_answered_is_never_handed_out_again(tmp_path):
    """`consumed` n'est pas la même garde que « la réponse est posée ».

    Entre le reçu de la page et la reprise de l'appel du cerveau, la commande
    est encore en place : un second onglet qui sonde dans cet intervalle la
    recevrait une deuxième fois et l'appliquerait deux fois. La fenêtre de
    redistribution est **forcée à échéance** ici, sinon c'est elle qui rendrait
    `None` et l'assertion ne dirait rien de `consumed`."""

    from jarvis.runtime.journal import RuntimeJournal

    broker = BarehandsCommandBroker(journal=RuntimeJournal(tmp_path), deadline_s=30.0, redeliver_s=1.0)
    task = asyncio.ensure_future(broker.request("activate"))
    await asyncio.sleep(0)
    command = broker.deliver()
    assert command is not None
    broker.complete(command["id"], {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None})
    # La commande n'a pas encore quitté la place : l'appel du cerveau n'a pas
    # repris. La fenêtre, elle, est écoulée.
    broker._pending.last_delivered = float("-inf")  # noqa: SLF001 - la fenêtre, rendue non pertinente
    assert broker._pending is not None  # noqa: SLF001
    assert broker.deliver() is None, "une commande déjà rendue ne se redonne pas"
    assert broker.delivery_due() is None
    assert (await task)["deliveries"] == 1


async def test_a_receipt_that_races_the_deadline_is_refused_by_its_own_code(tmp_path):
    """La course que `complete` doit tenir : le reçu arrive **pendant** que la
    commande est encore en place, mais après son échéance. L'échéance est
    forcée plutôt qu'attendue — sans quoi la branche ne serait atteinte qu'au
    hasard de l'ordonnancement, c'est-à-dire jamais dans un test, et elle
    pourrait disparaître sans rien faire tomber."""

    from jarvis.runtime.journal import RuntimeJournal

    journal = RuntimeJournal(tmp_path)
    broker = BarehandsCommandBroker(journal=journal, deadline_s=30.0)
    task = asyncio.ensure_future(broker.request("activate"))
    await asyncio.sleep(0)
    command = broker.deliver()
    broker._pending.deadline = asyncio.get_running_loop().time() - 1  # noqa: SLF001 - la course, rendue déterministe
    with pytest.raises(BarehandsCommandError) as caught:
        broker.complete(command["id"], {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None})
    assert caught.value.code == vocab.COMMAND_EXPIRED and caught.value.status == 410
    refused = [line for line in read_jsonl_tail(journal.trace_path, limit=20)
               if line["kind"] == "barehands.receipt_refused"]
    assert refused[-1]["data"]["code"] == vocab.COMMAND_EXPIRED
    assert refused[-1]["data"]["command"] == "activate"
    broker.close()
    with pytest.raises(BarehandsCommandError):
        await task


async def test_the_gate_refuses_before_waiting_rather_than_after(tmp_path):
    """Éteint, la page ne poste aucun long-poll : attendre trois secondes pour
    conclure « personne » mentirait sur la cause. Le refus est immédiat et dit
    ce que l'utilisateur doit faire."""

    from jarvis.runtime.journal import RuntimeJournal

    journal = RuntimeJournal(tmp_path)
    broker = BarehandsCommandBroker(journal=journal, gate=lambda: False, deadline_s=30.0)
    started = asyncio.get_running_loop().time()
    with pytest.raises(BarehandsCommandError) as caught:
        await broker.request("activate")
    assert caught.value.code == vocab.COMMAND_DISABLED and caught.value.status == 409
    assert "Expérimental" in str(caught.value)
    assert asyncio.get_running_loop().time() - started < 1.0, "refus immédiat, pas après l'échéance"
    assert kinds_of(journal) == ["barehands.command_refused"]


async def test_shutdown_hands_a_waiting_brain_its_cause_instead_of_a_timeout(tmp_path):
    from jarvis.runtime.journal import RuntimeJournal

    broker = BarehandsCommandBroker(journal=RuntimeJournal(tmp_path), deadline_s=30.0)
    task = asyncio.ensure_future(broker.request("activate"))
    await asyncio.sleep(0)
    broker.close()
    with pytest.raises(BarehandsCommandError) as caught:
        await task
    assert caught.value.code == vocab.COMMAND_CANCELLED and caught.value.status == 503


def kinds_of(journal) -> list[str]:  # noqa: ANN001 - RuntimeJournal
    return [line["kind"] for line in read_jsonl_tail(journal.trace_path, limit=50)]


# --------------------------------------------------- les vraies routes en HTTP


async def test_the_page_receives_a_command_on_its_long_poll_and_answers_it(running, session):
    """Bout en bout sur le **vrai** serveur : le cerveau demande, le long-poll
    déjà ouvert reçoit, la page répond, le cerveau lit ce qu'elle a constaté."""

    await running.enable()
    polling = asyncio.ensure_future(running.poll(session, wait_s=10))
    await asyncio.sleep(0.05)
    asking = asyncio.ensure_future(running.ask(session, "activate"))
    delivered = await asyncio.wait_for(polling, timeout=10)
    command = delivered["command"]
    assert command["name"] == "activate" and 0 < command["remaining_ms"] <= vocab.COMMAND_DEADLINE_S * 1000
    status, body, _ = await running.receipt(session, command["id"],
                                            {"outcome": "applied", "lifecycle": "active"})
    assert status == 200 and body == {"command": "activate", "id": command["id"]}
    status, answer, _ = await asyncio.wait_for(asking, timeout=10)
    assert status == 200
    assert answer["outcome"] == "applied" and answer["lifecycle"] == "active"
    assert answer["command"] == "activate" and answer["deliveries"] == 1 and answer["duration_ms"] >= 0
    # Le journal raconte la commande entière, reliée par son identifiant court.
    lines = [line for line in trace(running.control) if line["kind"].startswith("barehands.command")]
    assert [line["kind"] for line in lines] == [
        "barehands.command_requested", "barehands.command_delivered", "barehands.command_applied",
    ]
    assert len({line["data"]["id"] for line in lines}) == 1
    assert all(line["data"]["command"] == "activate" for line in lines)


async def test_an_empty_long_poll_returns_nothing_rather_than_hanging(running, session):
    await running.enable()
    assert await running.poll(session, wait_s=0) == {"command": None}


async def test_every_http_refusal_mirrors_its_code_in_the_header(running, session):
    """Le corps porte la phrase que la page affiche, l'en-tête porte le code que
    le serveur MCP lit : aucun des deux ne doit analyser l'autre."""

    # Éteint : la demande est refusée, code dans le corps et dans l'en-tête.
    status, body, header = await running.ask(session, "activate")
    assert (status, header) == (409, vocab.COMMAND_DISABLED)
    assert body["error"]["code"] == vocab.COMMAND_DISABLED and body["error"]["message"]
    await running.enable()
    # Commande inconnue.
    status, body, header = await running.ask(session, "danser")
    assert (status, header, body["error"]["code"]) == (400, vocab.COMMAND_UNKNOWN, vocab.COMMAND_UNKNOWN)
    # Reçu pour un identifiant qui n'a pas la forme d'une commande.
    status, body, header = await running.receipt(session, "trop-court", {"outcome": "applied", "lifecycle": "active"})
    assert (status, header) == (404, vocab.UNKNOWN_COMMAND_ID)
    # Reçu mal formé : refusé avant d'atteindre le courtier.
    status, body, header = await running.receipt(session, "A" * 32, {"outcome": "peut-etre", "lifecycle": "active"})
    assert (status, header) == (400, vocab.BAD_RECEIPT)
    # Paramètre inconnu sur le long-poll.
    async with session.get(f"{running.base}/api/barehands/commands?wait_s=1&tab=2") as response:
        assert response.status == 400
        assert response.headers[SETTINGS_ERROR_CODE_HEADER] == vocab.BAD_REQUEST
    # `wait_s` hors bornes : refusé plutôt que rogné en silence.
    async with session.get(f"{running.base}/api/barehands/commands?wait_s=600") as response:
        assert response.status == 400 and response.headers[SETTINGS_ERROR_CODE_HEADER] == vocab.BAD_REQUEST


async def test_the_switch_travels_through_the_real_settings_file(running, session):
    """Aller-retour réel : la route écrit le fichier, `/api/status` le relit, et
    c'est ce booléen que la page lit pour ouvrir ou fermer son canal — pas une
    valeur gardée en mémoire à côté."""

    async with session.get(f"{running.base}/api/status") as response:
        assert (await response.json())["barehands"] == {"enabled": False}
    await running.enable(True)
    stored = json.loads((running.control.runtime_root / "control-center-settings.json").read_text(encoding="utf-8"))
    assert stored[barehands.SETTING_KEY]["enabled"] is True
    async with session.get(f"{running.base}/api/status") as response:
        assert (await response.json())["barehands"] == {"enabled": True}
    await running.enable(False)
    async with session.get(f"{running.base}/api/status") as response:
        assert (await response.json())["barehands"] == {"enabled": False}
    # Et la porte du courtier suit le fichier, pas un souvenir.
    assert running.control.barehands_commands.enabled() is False


# ------------------------------------------------------------- outils du cerveau


async def test_the_catalog_is_exactly_the_five_commands_with_no_switch():
    """Le cerveau ne peut pas **éteindre** Bare Hands : l'interrupteur
    appartient à l'utilisateur, et aucun outil ne le touche."""

    server = build_server(BarehandsMcpTarget("127.0.0.1", 1))
    listed = await server.list_tools()
    assert tuple(tool.name for tool in listed) == TOOL_NAMES
    assert tuple(TOOL_COMMANDS.values()) == vocab.COMMANDS
    for tool in listed:
        # Aucun argument : ces outils n'en prennent pas, et le schéma le dit.
        assert tool.inputSchema.get("properties", {}) == {}
        assert tool.inputSchema["additionalProperties"] is False
        assert tool.description, tool.name
    names = " ".join(tool.name for tool in listed)
    for forbidden in ("enable", "disable", "settings", "tool", "camera"):
        assert forbidden not in names


async def test_a_refused_command_crosses_the_mcp_protocol_as_an_error_not_a_result(running, session):
    """Aucun faux succès, sur la chaîne entière : la page refuse, le cerveau
    reçoit une **erreur d'outil** portant le code et la phrase — jamais un
    résultat qu'il pourrait lire comme « c'est fait »."""

    from mcp.shared.memory import create_connected_server_and_client_session

    await running.enable()
    tools = BarehandsCommandTools(BarehandsMcpTarget("127.0.0.1", running.port, running.control.runtime_root),
                                  journal=running.control.journal)

    async def page(outcome: dict) -> None:
        delivered = await running.poll(session, wait_s=10)
        await running.receipt(session, delivered["command"]["id"], outcome)

    try:
        async with create_connected_server_and_client_session(build_server(tools=tools)) as client:
            # 1. La page refuse : erreur d'outil, avec la phrase du code.
            answering = asyncio.ensure_future(page(
                {"outcome": "refused", "lifecycle": "error", "code": vocab.LIFECYCLE_REFUSED,
                 "reason": "camera_unsupported"}))
            result = await asyncio.wait_for(client.call_tool("barehands_activate", {}), timeout=20)
            await answering
            assert result.isError is True
            text = result.content[0].text
            assert "camera_unsupported" in text and "Traceback" not in text
            assert vocab.PAGE_CODE_EXPLANATIONS[vocab.LIFECYCLE_REFUSED][:40] in text
            # 2. La page applique : résultat, et il dit l'état **constaté**.
            answering = asyncio.ensure_future(page({"outcome": "applied", "lifecycle": "active"}))
            ok = await asyncio.wait_for(client.call_tool("barehands_activate", {}), timeout=20)
            await answering
            assert ok.isError is False
            assert json.loads(ok.content[0].text)["lifecycle"] == "active"
            # 3. Un argument inventé ne passe pas pour appliqué.
            bad = await client.call_tool("barehands_activate", {"force": True})
            assert bad.isError is True and "rien n'a été envoyé" in bad.content[0].text
    finally:
        await tools.close()


async def test_the_three_unbuilt_flows_refuse_with_one_honest_code(running, session):
    """Ce qu'un cerveau voit **aujourd'hui** pour la calibration, le tutoriel et
    la sortie d'un panneau : un refus `barehands_flow_absent` et une phrase qui
    dit de ne pas prétendre l'avoir lancé. Le transport, lui, est complet."""

    await running.enable()
    tools = BarehandsCommandTools(BarehandsMcpTarget("127.0.0.1", running.port, running.control.runtime_root),
                                  journal=running.control.journal)
    try:
        for tool_name in ("barehands_calibrate", "barehands_tutorial", "barehands_exit_overlay"):
            async def page() -> None:
                delivered = await running.poll(session, wait_s=10)
                await running.receipt(session, delivered["command"]["id"], {
                    "outcome": "refused", "lifecycle": "sleep", "code": vocab.FLOW_ABSENT,
                    "reason": "JarvisBarehands.calibrate n'existe pas dans cette version"})

            answering = asyncio.ensure_future(page())
            with pytest.raises(BarehandsToolError) as caught:
                await tools.send(tool_name, TOOL_COMMANDS[tool_name])
            await answering
            assert caught.value.code == vocab.FLOW_ABSENT
            assert "ne prétends pas l'avoir lancé" in str(caught.value)
    finally:
        await tools.close()


async def test_an_unreachable_control_center_is_a_tool_error_not_a_silence(tmp_path):
    """Fenêtre fermée, serveur arrêté : le cerveau doit pouvoir le **dire**."""

    from jarvis.runtime.journal import RuntimeJournal

    journal = RuntimeJournal(tmp_path)
    tools = BarehandsCommandTools(BarehandsMcpTarget("127.0.0.1", free_port(), tmp_path), journal=journal)
    try:
        with pytest.raises(BarehandsToolError) as caught:
            await tools.send("barehands_activate", "activate")
    finally:
        await tools.close()
    assert caught.value.code == vocab.CHANNEL_UNREACHABLE
    assert "Control Center" in str(caught.value)
    failed = [line for line in read_jsonl_tail(journal.trace_path, limit=20)
              if line["kind"] == "barehands.tool_failed"]
    assert failed and failed[-1]["level"] == "error"
    assert failed[-1]["data"]["code"] == vocab.CHANNEL_UNREACHABLE
    assert failed[-1]["data"]["tool"] == "barehands_activate"


async def test_the_brain_waiting_for_a_page_gives_up_on_the_deadline_it_was_told(running):
    """L'outil n'invente pas son propre délai plus court que celui du serveur :
    il doit lire la **vraie** cause (`barehands_no_visible_page`), pas la
    masquer derrière un délai de client."""

    from jarvis.runtime.barehands_mcp import READ_TIMEOUT_S

    assert READ_TIMEOUT_S > vocab.COMMAND_DEADLINE_S
    await running.enable()
    tools = BarehandsCommandTools(BarehandsMcpTarget("127.0.0.1", running.port, running.control.runtime_root),
                                  journal=running.control.journal)
    try:
        with pytest.raises(BarehandsToolError) as caught:
            await tools.send("barehands_activate", "activate")
    finally:
        await tools.close()
    assert caught.value.code == vocab.NO_VISIBLE_PAGE
    assert "visible" in str(caught.value)


def test_the_server_environment_is_read_strictly():
    target = BarehandsMcpTarget.from_env({"JARVIS_CONTROL_CENTER_HOST": "127.0.0.1",
                                          "JARVIS_CONTROL_CENTER_PORT": "4242",
                                          "JARVIS_RUNTIME_DIR": "C:/a b/runtime"})
    assert (target.host, target.port, target.base_url) == ("127.0.0.1", 4242, "http://127.0.0.1:4242")
    for bad in ({"JARVIS_CONTROL_CENTER_PORT": "abc"}, {"JARVIS_CONTROL_CENTER_PORT": "0"},
                {"JARVIS_CONTROL_CENTER_PORT": "70000"}, {"JARVIS_CONTROL_CENTER_HOST": "8.8.8.8"}):
        with pytest.raises(BarehandsConfigError):
            BarehandsMcpTarget.from_env(bad)
    # Le document `--mcp-config` ne porte ni jeton ni secret : un hôte et un port.
    document = mcp_config(BarehandsMcpTarget("127.0.0.1", 17654, Path("C:/a b/runtime")))
    assert set(document["mcpServers"]) == {SERVER_NAME}
    assert document["mcpServers"][SERVER_NAME]["args"] == ["-m", "jarvis", "barehands-mcp"]


# ------------------------------------------------------------------- la porte


async def test_the_brain_gets_neither_the_server_nor_the_prompt_when_hands_are_off(tmp_path, monkeypatch):
    """La surface est **absente**, pas grisée : un outil qu'on ne voit pas ne se
    promet pas. Même règle que `display_mcp` sur `scene.enabled`, et le rappel
    par `save_barehands` est ce qui la rend effective sans redémarrage complet."""

    monkeypatch.delenv(barehands.VENDOR_ENV, raising=False)
    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path,
                            barehands_vendor_root=tmp_path / "vendor",
                            barehands_mcp=BarehandsMcpTarget("127.0.0.1", 17654, tmp_path / "runtime"))
    agent = control.agent
    assert isinstance(agent, ClaudeLocalAgent)
    # Défaut : éteint, donc rien.
    assert agent.barehands_mcp is None
    assert agent._barehands_mcp_args() == []  # noqa: SLF001 - le chemin exact du lancement
    await control.save_barehands(JsonRequest({"enabled": True}))
    assert agent.barehands_mcp is not None
    args = agent._barehands_mcp_args()  # noqa: SLF001
    assert args[0] == "--mcp-config" and Path(args[1]) == (tmp_path / "runtime" / CONFIG_FILE_NAME).resolve()
    assert json.loads(Path(args[1]).read_text(encoding="utf-8"))["mcpServers"][SERVER_NAME]["type"] == "stdio"
    await control.save_barehands(JsonRequest({"enabled": False}))
    assert agent.barehands_mcp is None and agent._barehands_mcp_args() == []  # noqa: SLF001


async def test_the_launched_brain_gets_the_server_and_the_prompt_together(monkeypatch, tmp_path):
    """Le fil qui relie les deux : le **vrai** argv du lancement.

    Tester le registre de prompts seul laisse passer la seule ligne qui compte
    — celle qui compose le nom du programme à partir des capacités réellement
    déclarées. Un serveur MCP sans sa consigne, c'est un outil que le cerveau
    ne sait pas qu'il a ; une consigne sans son serveur, c'est une promesse
    qu'il ne peut pas tenir. Les quatre combinaisons sont lancées pour de vrai
    (le processus seul est un double) et lues dans l'argv."""

    from test_display_mcp import _launch, _prompt  # noqa: E402 - le harnais de lancement, réutilisé
    from jarvis.runtime.claude_local import BRAIN_DISPLAY_PROMPT
    from jarvis.runtime.display_mcp import DisplayMcpTarget

    runtime = tmp_path / "dossier avec espaces" / "runtime"
    token = tmp_path / "dossier avec espaces" / "core.token"
    token.parent.mkdir(parents=True)
    token.write_text("secret-" * 8, encoding="utf-8")
    screen = DisplayMcpTarget("127.0.0.1", 17999, token, runtime)
    hands = BarehandsMcpTarget("127.0.0.1", 17654, runtime)

    async def argv(**kwargs) -> list[str]:
        return await _launch(monkeypatch, ClaudeLocalAgent(runtime_root=runtime, cwd=tmp_path, **kwargs))

    off = await argv()
    assert "--mcp-config" not in off
    assert BRAIN_BAREHANDS_PROMPT not in _prompt(off, "--append-system-prompt")

    only_hands = await argv(barehands_mcp=hands)
    prompt = _prompt(only_hands, "--append-system-prompt")
    assert BRAIN_BAREHANDS_PROMPT in prompt and BRAIN_DISPLAY_PROMPT not in prompt
    path = Path(only_hands[only_hands.index("--mcp-config") + 1])
    assert path == (runtime / CONFIG_FILE_NAME).resolve() and " " in str(path)
    # Option variadique du CLI : l'argument suivant est une autre option, jamais
    # un second chemin — un chemin Windows avec une espace s'y scinderait.
    assert only_hands[only_hands.index("--mcp-config") + 2].startswith("--")

    only_screen = await argv(display_mcp=screen)
    assert BRAIN_BAREHANDS_PROMPT not in _prompt(only_screen, "--append-system-prompt")

    both = await argv(display_mcp=screen, barehands_mcp=hands)
    prompt = _prompt(both, "--append-system-prompt")
    assert BRAIN_BAREHANDS_PROMPT in prompt and BRAIN_DISPLAY_PROMPT in prompt
    # Deux drapeaux, deux fichiers : chacun indépendamment absent de son côté.
    assert both.count("--mcp-config") == 2
    files = [Path(both[i + 1]) for i, flag in enumerate(both) if flag == "--mcp-config"]
    assert sorted(path.name for path in files) == sorted(["display-mcp.json", CONFIG_FILE_NAME])
    # Chaque fichier ne déclare que son serveur : aucun ne réécrit l'autre.
    servers = [list(json.loads(path.read_text(encoding="utf-8"))["mcpServers"]) for path in files]
    assert sorted(sum(servers, [])) == sorted(["jarvis-display", SERVER_NAME])


def test_the_prompt_says_the_capability_only_where_the_tools_are_declared():
    """Quatre compositions pour deux interrupteurs indépendants. Une consigne
    qui décrirait des outils absents est la façon la plus sûre de faire
    promettre au cerveau ce qu'il ne peut pas tenir."""

    from jarvis.domain.prompt_registry import PromptTarget
    from jarvis.runtime.prompt_runtime import prompt_channel, resolve_prompt

    def prompt(invocation: str) -> str:
        return prompt_channel(
            resolve_prompt(PromptTarget("backend", None, "claude", None, None, invocation)),
            "cli.append_system_prompt",
        )

    registry = default_prompt_registry()
    assert registry.require("backend.claude.conversation.barehands").default_text == BRAIN_BAREHANDS_PROMPT
    plain = prompt("conversation_session")
    hands = prompt("conversation_barehands_session")
    both = prompt("conversation_display_barehands_session")
    display = prompt("conversation_display_session")
    assert BRAIN_BAREHANDS_PROMPT not in plain and BRAIN_BAREHANDS_PROMPT not in display
    assert BRAIN_BAREHANDS_PROMPT in hands and BRAIN_BAREHANDS_PROMPT in both
    # La consigne d'affichage n'a pas bougé de place, et n'a pas suivi les mains.
    assert "LA SCÈNE CONSTELLATION" in display and "LA SCÈNE CONSTELLATION" in both
    assert "LA SCÈNE CONSTELLATION" not in hands
    # Le socle est le même partout : les mains s'ajoutent, elles ne remplacent rien.
    for text in (plain, display, hands, both):
        assert text.startswith(BRAIN_SYSTEM_PROMPT)
    # Et la consigne dit que l'interrupteur n'est pas au cerveau.
    assert "l'interrupteur est à lui" in BRAIN_BAREHANDS_PROMPT


# ------------------------------------------------------------- insertion en page


async def test_the_page_serves_the_command_channel_after_the_surface_it_drives(tmp_path):
    """Constat F3 : l'ordre d'insertion est porteur. Le canal lit
    `window.JarvisBarehands` **au chargement** et refuse de s'installer sans
    lui : servi trop tôt, la page casse à l'insertion, pas à l'usage."""

    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    page = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center.html"
    raw = page.read_text(encoding="utf-8")
    html = (await control.index(None)).text
    assert BAREHANDS_COMMANDS_SCRIPT_MARKER in raw
    assert raw.index(BAREHANDS_SCRIPT_MARKER) < raw.index(BAREHANDS_COMMANDS_SCRIPT_MARKER) \
        < raw.index(SCENE_PAGE_SCRIPT_MARKER)
    assert BAREHANDS_COMMANDS_SCRIPT_MARKER not in html, "le repère n'a pas été remplacé"
    assert "window.JarvisBarehandsCommands" not in raw, "la page ne le définit pas elle-même"
    assert "root.JarvisBarehandsCommands=api" in html
    assert (
        html.index("function installJarvisBarehands()")
        < html.index("root.JarvisBarehandsCommands=api")
        < html.index("function installJarvisScene")
    )
    # La porte passe par le seul battement déjà permanent de la page.
    assert "JarvisBarehandsCommandChannel.gate(s.barehands)" in html
    assert "JarvisBarehandsCommandChannel.statusLost()" in html
    # Et aucune minuterie n'a été ajoutée pour ce canal.
    assert "setInterval" not in Path(page.parent / "control_center_barehands_commands.js").read_text(encoding="utf-8")
