"""Canal du plein écran de surface, de l'agent à la page, sur un vrai Control Center (studio de présentation, Slice 03).

Chaîne réelle : requête HTTP de l'agent → `FullscreenCommandBroker` → long-poll → reçu → rapports d'état.
Seule la page est remplacée par un client qui appelle exactement les routes que la vraie page appelle.

Ce que ce fichier épingle :

- **une demande d'entrée ARME, elle n'entre pas** : le reçu dit `needs_gesture` et l'état tenu aussi, jusqu'à ce que
  la page rapporte `entered` (clic) ; l'agent lit l'état par `GET /api/fullscreen/state` ;
- **aucune page = refus codé** (504 `fullscreen_no_visible_page`), jamais un 200 optimiste ; une page qui prend la
  commande et se tait = `fullscreen_command_expired` (deux causes, deux codes) ;
- **une commande en vol à la fois, remise exclusive, identifiant à usage unique** ;
- **un reçu mal formé solde la commande tout de suite avec sa cause**, il ne la laisse pas échoir ;
- **le serveur tient l'état et refuse l'incohérent** (409) ; un rapport périmé n'écrit rien ; Échap (sortie sans
  identifiant) et l'entrée locale (clic sans commande) passent ;
- **l'armement ne dure pas indéfiniment même si la page meurt** (échéance revérifiée à la lecture) ;
- **garde d'origine** : un cadre de prefab (`Origin: null`) ou un site étranger ne peut ni consommer ni dicter.
"""

from __future__ import annotations

import asyncio
import socket

import aiohttp
import pytest

from jarvis.domain import surface_fullscreen as fs
from jarvis.runtime.control_center import (
    FULLSCREEN_ROUTE_PREFIX,
    FULLSCREEN_SCRIPT_MARKER,
    READ_GUARDED_ROUTES,
    SETTINGS_ERROR_CODE_HEADER,
    ControlCenter,
)
from jarvis.runtime.fullscreen_commands import ARM_GRACE_S, FullscreenCommandBroker
from jarvis.runtime.journal import read_jsonl_tail


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class RunningCenter:
    def __init__(self, control: ControlCenter, port: int) -> None:
        self.control = control
        self.base = f"http://127.0.0.1:{port}"

    async def ask(self, session, body, *, headers=None) -> tuple[int, dict, str]:
        async with session.post(f"{self.base}/api/fullscreen/commands", json=body, headers=headers) as response:
            return response.status, await response.json(), response.headers.get(SETTINGS_ERROR_CODE_HEADER, "")

    async def poll(self, session, wait_s: float = 5) -> dict:
        async with session.get(f"{self.base}/api/fullscreen/commands?wait_s={wait_s}") as response:
            assert response.status == 200, await response.text()
            return await response.json()

    async def receipt(self, session, command_id, body) -> tuple[int, dict, str]:
        async with session.post(f"{self.base}/api/fullscreen/commands/{command_id}", json=body) as response:
            return response.status, await response.json(), response.headers.get(SETTINGS_ERROR_CODE_HEADER, "")

    async def report(self, session, body) -> tuple[int, dict, str]:
        async with session.post(f"{self.base}/api/fullscreen/state", json=body) as response:
            return response.status, await response.json(), response.headers.get(SETTINGS_ERROR_CODE_HEADER, "")

    async def state(self, session) -> dict:
        async with session.get(f"{self.base}/api/fullscreen/state") as response:
            assert response.status == 200
            return await response.json()

    async def armed(self, session, body=None) -> tuple[asyncio.Task, str]:
        """Lance une demande `enter`, joue la page qui l'arme, et rend (tâche de la demande, id court)."""

        task = asyncio.create_task(self.ask(session, body or {"action": "enter", "object_id": "obj_1"}))
        command = (await self.poll(session))["command"]
        assert command is not None
        status, _, _ = await self.receipt(session, command["id"], {"state": "needs_gesture", "object_id": "obj_1"})
        assert status == 200
        return task, command["id"][:8]


@pytest.fixture
async def running(tmp_path):
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
        control.fullscreen.close()
        await runner.cleanup()


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as client:
        yield client


def kinds(control: ControlCenter) -> list[str]:
    return [line["kind"] for line in read_jsonl_tail(control.journal.trace_path, limit=300)]


def lines(control: ControlCenter, kind: str) -> list[dict]:
    return [line for line in read_jsonl_tail(control.journal.trace_path, limit=300) if line["kind"] == kind]


# ------------------------------------------------------------------ armer, pas entrer


async def test_an_enter_request_arms_and_only_the_page_report_enters(running, session):
    task, short = await running.armed(session)
    status, answer, _ = await task
    assert status == 200
    assert answer["state"] == "needs_gesture" and answer["armed_for_s"] == fs.ARM_DEFAULT_S
    assert answer["snapshot"]["state"] == "needs_gesture" and answer["snapshot"]["id"] == short
    assert answer["deliveries"] == 1 and "clic" in answer["explanation"]
    # Rien n'est « entered » tant que le navigateur ne l'a pas dit.
    assert (await running.state(session))["state"] == "needs_gesture"
    status, snap, _ = await running.report(session, {"state": "entered", "id": short, "object_id": "obj_1",
                                                    "display_selection": "denied"})
    assert status == 200 and snap["state"] == "entered" and snap["object_id"] == "obj_1"
    assert snap["display_selection"] == "denied" and snap["id"] is None
    # Échap : le navigateur sort, sans identifiant.
    status, snap, _ = await running.report(session, {"state": "exited", "object_id": "obj_1"})
    assert status == 200 and snap["state"] == "exited" and snap["object_id"] is None
    assert {"fullscreen.command_requested", "fullscreen.command_delivered", "fullscreen.command_answered",
            "fullscreen.state_changed"} <= set(kinds(running.control))


async def test_the_wire_command_carries_the_validated_fields_and_nothing_else(running, session):
    task = asyncio.create_task(running.ask(session, {"action": "enter", "object_id": "obj_9", "display": "primary",
                                                    "keys": "none", "arm_s": 12}))
    command = (await running.poll(session))["command"]
    assert set(command) == {"id", "remaining_ms", "action", "object_id", "display", "keys", "arm_s"}
    assert (command["action"], command["object_id"], command["display"], command["keys"], command["arm_s"]) == (
        "enter", "obj_9", "primary", "none", 12.0)
    assert len(command["id"]) >= 32 and 0 < command["remaining_ms"] <= 3000
    await running.receipt(session, command["id"], {"state": "unsupported", "code": fs.UNSUPPORTED, "reason": "non"})
    status, answer, _ = await task
    assert status == 200 and answer["state"] == "unsupported" and answer["snapshot"]["state"] == "unsupported"
    assert answer["snapshot"]["code"] == fs.UNSUPPORTED


async def test_an_exit_request_while_armed_cancels_and_the_state_follows_the_page(running, session):
    armed, _ = await running.armed(session)
    await armed
    task = asyncio.create_task(running.ask(session, {"action": "exit"}))
    command = (await running.poll(session))["command"]
    assert command == {"id": command["id"], "remaining_ms": command["remaining_ms"], "action": "exit"}
    await running.receipt(session, command["id"], {"state": "exited", "code": fs.CANCELLED})
    status, answer, _ = await task
    assert status == 200 and answer["state"] == "exited" and answer["snapshot"]["state"] == "exited"


async def test_a_page_receipt_that_refuses_for_a_missing_target_is_a_named_refusal_not_a_success(running, session):
    task = asyncio.create_task(running.ask(session, {"action": "enter", "object_id": "gone"}))
    command = (await running.poll(session))["command"]
    await running.receipt(session, command["id"], {"state": "refused", "code": fs.TARGET_MISSING, "reason": "absent"})
    status, answer, _ = await task
    assert status == 200 and answer["state"] == "refused" and answer["code"] == fs.TARGET_MISSING
    assert answer["snapshot"]["state"] == "refused"
    assert any(line["level"] == "warning" for line in lines(running.control, "fullscreen.command_answered"))


# ------------------------------------------------------------------ pas de page, page muette


async def test_without_a_page_the_request_is_a_coded_504_and_the_state_is_untouched(running, session):
    running.control.fullscreen.deadline_s = 0.3
    status, body, header = await running.ask(session, {"action": "enter"})
    assert status == 504 and header == fs.NO_VISIBLE_PAGE and body["error"]["code"] == fs.NO_VISIBLE_PAGE
    assert (await running.state(session))["state"] == "exited"
    assert lines(running.control, "fullscreen.command_expired")[0]["data"]["deliveries"] == 0


async def test_a_page_that_takes_the_command_and_stays_silent_is_expired_not_absent(running, session):
    running.control.fullscreen.deadline_s = 0.4
    task = asyncio.create_task(running.ask(session, {"action": "enter"}))
    command = (await running.poll(session))["command"]
    assert command is not None
    status, body, header = await task
    assert status == 504 and header == fs.COMMAND_EXPIRED
    assert "n'a pas répondu" in body["error"]["message"]
    status, late, header = await running.receipt(session, command["id"], {"state": "needs_gesture"})
    assert status == 404 and header == fs.UNKNOWN_COMMAND_ID   # le reçu tardif n'est pas appliqué
    assert (await running.state(session))["state"] == "exited"


async def test_one_command_in_flight_and_exclusive_delivery(running, session):
    first = asyncio.create_task(running.ask(session, {"action": "enter"}))
    await asyncio.sleep(0.05)
    status, body, header = await running.ask(session, {"action": "exit"})
    assert status == 409 and header == fs.COMMAND_BUSY
    got, other = await asyncio.gather(running.poll(session, 1), running.poll(session, 1))
    assert sorted([got["command"] is None, other["command"] is None]) == [False, True]   # une page, une seule fois
    command = got["command"] or other["command"]
    await running.receipt(session, command["id"], {"state": "needs_gesture"})
    assert (await first)[0] == 200


async def test_a_receipt_is_single_use_and_a_malformed_id_leaves_a_trace(running, session):
    task = asyncio.create_task(running.ask(session, {"action": "enter"}))
    command = (await running.poll(session))["command"]
    assert (await running.receipt(session, command["id"], {"state": "needs_gesture"}))[0] == 200
    await task
    status, _, header = await running.receipt(session, command["id"], {"state": "needs_gesture"})
    assert status == 404 and header == fs.UNKNOWN_COMMAND_ID
    status, _, header = await running.receipt(session, "court", {"state": "needs_gesture"})
    assert status == 404 and header == fs.UNKNOWN_COMMAND_ID
    refused = lines(running.control, "fullscreen.receipt_refused")
    assert len(refused) == 2 and refused[-1]["data"]["id_chars"] == 5   # jamais l'identifiant reçu lui-même


async def test_a_malformed_receipt_settles_the_command_at_once_with_its_cause(running, session):
    running.control.fullscreen.deadline_s = 5
    task = asyncio.create_task(running.ask(session, {"action": "enter"}))
    command = (await running.poll(session))["command"]
    status, _, header = await running.receipt(session, command["id"], {"state": "refused"})   # refus sans code
    assert status == 400 and header == fs.BAD_RECEIPT
    started = asyncio.get_running_loop().time()
    status, body, header = await task
    assert asyncio.get_running_loop().time() - started < 1.0          # pas d'attente jusqu'à l'échéance
    assert status == 502 and header == fs.RECEIPT_INVALID and "peut-être agi" in body["error"]["message"]
    assert lines(running.control, "fullscreen.receipt_rejected")


async def test_an_oversized_receipt_is_refused_by_size_and_named(running, session):
    running.control.fullscreen.deadline_s = 5
    task = asyncio.create_task(running.ask(session, {"action": "enter"}))
    command = (await running.poll(session))["command"]
    status, _, header = await running.receipt(session, command["id"], {"state": "needs_gesture", "reason": "x" * 5000})
    assert status == 413 and header == fs.BAD_RECEIPT
    status, _, header = await task
    assert status == 502 and header == fs.RECEIPT_TOO_LARGE


# ------------------------------------------------------------------ l'état tenu par le serveur


async def test_the_server_refuses_incoherent_reports_and_a_stale_report_writes_nothing(running, session):
    # `expired` hors armement : transition impossible, et rien ne change.
    status, body, header = await running.report(session, {"state": "expired", "code": fs.ARM_EXPIRED})
    assert status == 409 and header == fs.INVALID_TRANSITION
    assert (await running.state(session))["state"] == "exited"
    task, short = await running.armed(session)
    await task
    status, _, header = await running.report(session, {"state": "entered", "id": "ZZZZZZZZ"})
    assert status == 409 and header == fs.STALE_REPORT
    assert (await running.state(session))["state"] == "needs_gesture"
    # La page retire elle-même son invite : expiration constatée, avec sa cause.
    status, snap, _ = await running.report(session, {"state": "expired", "id": short, "code": fs.ARM_EXPIRED,
                                                    "reason": "30 s sans clic"})
    assert status == 200 and snap["state"] == "expired" and snap["code"] == fs.ARM_EXPIRED
    # Idempotent : la page répète ce qui est déjà vrai.
    assert (await running.report(session, {"state": "expired", "code": fs.ARM_EXPIRED}))[0] == 200


async def test_a_local_user_click_enters_without_any_command_and_escape_leaves(running, session):
    status, snap, _ = await running.report(session, {"state": "entered", "object_id": "obj_2"})
    assert status == 200 and snap["state"] == "entered" and snap["object_id"] == "obj_2"
    status, snap, _ = await running.report(session, {"state": "exited", "object_id": "obj_2"})
    assert status == 200 and snap["state"] == "exited"


async def test_a_denied_browser_request_is_recorded_with_the_browsers_words(running, session):
    task, short = await running.armed(session)
    await task
    status, snap, _ = await running.report(session, {"state": "refused", "id": short, "code": fs.DENIED,
                                                    "reason": "TypeError: Disallowed by permissions policy"})
    assert status == 200 and snap["state"] == "refused" and "permissions policy" in snap["reason"]
    state_lines = lines(running.control, "fullscreen.state_changed")
    assert state_lines[-1]["level"] == "warning" and state_lines[-1]["data"]["code"] == fs.DENIED


# ------------------------------------------------------------------ échéance d'armement côté serveur


async def test_an_armed_request_expires_on_the_server_even_if_the_page_died():
    now = [100.0]
    broker = FullscreenCommandBroker(clock=lambda: now[0], deadline_s=2)
    request = fs.parse_request({"action": "enter", "object_id": "obj_1", "arm_s": 10})
    task = asyncio.create_task(broker.request(request))
    await asyncio.sleep(0)
    command = broker.deliver()
    assert command is not None and command["arm_s"] == 10.0
    broker.complete(command["id"], fs.parse_receipt("enter", {"state": "needs_gesture", "object_id": "obj_1"}))
    answer = await task
    assert answer["snapshot"]["state"] == "needs_gesture"
    now[0] += 10 + ARM_GRACE_S - 0.1
    assert broker.snapshot()["state"] == "needs_gesture"            # dans la marge : la page garde la main
    now[0] += 0.2
    snap = broker.snapshot()                                        # la page est muette : le serveur tranche
    assert snap["state"] == "expired" and snap["code"] == fs.ARM_EXPIRED and snap["id"] is None
    # Un rapport tardif de la page se juge sur l'état réel, sans rien casser.
    late = fs.parse_state_report({"state": "expired", "code": fs.ARM_EXPIRED})
    assert broker.report(late)["state"] == "expired"


async def test_closing_the_center_releases_a_waiting_request_with_its_cause():
    broker = FullscreenCommandBroker(deadline_s=30)
    task = asyncio.create_task(broker.request(fs.parse_request({"action": "enter"})))
    await asyncio.sleep(0)
    broker.close()
    with pytest.raises(fs.SurfaceFullscreenError) as caught:
        await task
    assert caught.value.code == fs.COMMAND_CANCELLED and caught.value.status == 503
    with pytest.raises(fs.SurfaceFullscreenError):
        await broker.request(fs.parse_request({"action": "exit"}))


# ------------------------------------------------------------------ demandes invalides, garde d'origine


@pytest.mark.parametrize("body", [{"action": "maximize"}, {"action": "enter", "force": 1}, {"action": "enter", "display": "left"},
                                  {"action": "enter", "arm_s": 0}, [], None])
async def test_invalid_requests_are_refused_before_reaching_the_page(running, session, body):
    status, payload, header = await running.ask(session, body)
    assert status == 400 and header == fs.BAD_REQUEST and payload["error"]["code"] == fs.BAD_REQUEST


async def test_the_poll_and_routes_reject_bad_parameters_and_oversized_bodies(running, session):
    for url in ("/api/fullscreen/commands?wait_s=abc", "/api/fullscreen/commands?wait_s=99",
                "/api/fullscreen/commands?x=1", "/api/fullscreen/state?x=1"):
        async with session.get(running.base + url) as response:
            assert response.status == 400 and response.headers[SETTINGS_ERROR_CODE_HEADER] == fs.BAD_REQUEST
    async with session.post(running.base + "/api/fullscreen/commands", data=b"{" + b" " * 3000 + b"}",
                            headers={"Content-Type": "application/json"}) as response:
        assert response.status == 413
    async with session.post(running.base + "/api/fullscreen/state", data=b"{not json",
                            headers={"Content-Type": "application/json"}) as response:
        assert response.status == 400 and response.headers[SETTINGS_ERROR_CODE_HEADER] == fs.BAD_RECEIPT


async def test_a_prefab_frame_or_a_foreign_site_can_neither_consume_nor_dictate(running, session):
    """`Origin: null` est l'origine d'un cadre sandboxé de prefab ; un GET étranger consommerait la commande."""

    assert FULLSCREEN_ROUTE_PREFIX in READ_GUARDED_ROUTES
    task = asyncio.create_task(running.ask(session, {"action": "enter"}))
    await asyncio.sleep(0.05)
    for origin in ("null", "https://evil.example"):
        async with session.get(running.base + "/api/fullscreen/commands?wait_s=0", headers={"Origin": origin}) as response:
            assert response.status == 403 and response.headers[SETTINGS_ERROR_CODE_HEADER] == fs.FORBIDDEN_ORIGIN
        async with session.get(running.base + "/api/fullscreen/state", headers={"Origin": origin}) as response:
            assert response.status == 403
        async with session.post(running.base + "/api/fullscreen/state", json={"state": "entered"},
                                headers={"Origin": origin}) as response:
            assert response.status == 403 and response.headers[SETTINGS_ERROR_CODE_HEADER] == fs.FORBIDDEN_ORIGIN
        async with session.post(running.base + "/api/fullscreen/commands", json={"action": "exit"},
                                headers={"Origin": origin}) as response:
            assert response.status == 403
    async with session.get(running.base + "/api/fullscreen/commands?wait_s=0",
                           headers={"Sec-Fetch-Site": "cross-site"}) as response:
        assert response.status == 403
    # La commande n'a été consommée par aucun des refus : la vraie page la reçoit encore.
    command = (await running.poll(session))["command"]
    assert command is not None and command["action"] == "enter"
    await running.receipt(session, command["id"], {"state": "needs_gesture"})
    assert (await task)[0] == 200
    assert (await running.state(session))["state"] == "needs_gesture"


def test_the_page_splice_marker_is_in_the_served_html():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center.html").read_text(encoding="utf-8")
    assert html.count(FULLSCREEN_SCRIPT_MARKER) == 1
    # Après la page de scène (éléments lus à la demande), avant les bibliothèques plein écran du dock.
    assert html.index("/*__CONTROL_CENTER_SCENE_PAGE_JS__*/") < html.index(FULLSCREEN_SCRIPT_MARKER)


# ------------------------------------------------------------------ rework QA-1


async def test_a_refused_enter_while_another_surface_is_fullscreen_leaves_the_real_state_untouched(running, session):
    task, short = await running.armed(session)
    await task
    await running.report(session, {"state": "entered", "id": short, "object_id": "obj_1"})
    ask = asyncio.create_task(running.ask(session, {"action": "enter", "object_id": "obj_plain"}))
    command = (await running.poll(session))["command"]
    await running.receipt(session, command["id"], {"state": "refused", "code": fs.OTHER_ENTERED,
                                                   "reason": "Une autre surface est déjà plein écran",
                                                   "object_id": "obj_plain"})
    status, answer, _ = await ask
    # La page a bien refusé, avec sa cause, mais l'état tenu décrit ce que fait le navigateur.
    assert status == 200 and answer["state"] == "refused" and answer["code"] == fs.OTHER_ENTERED
    for snap in (answer["snapshot"], await running.state(session)):
        assert snap["state"] == "entered" and snap["object_id"] == "obj_1" and snap["code"] is None
        assert snap["reason"] is None
    kept = lines(running.control, "fullscreen.request_refused_while_entered")
    assert kept and kept[0]["data"]["object_id"] == "obj_1" and kept[0]["data"]["requested_object_id"] == "obj_plain"


async def test_a_page_that_said_it_is_hidden_never_takes_the_command_even_with_a_poll_still_open(running, session):
    running.control.fullscreen.deadline_s = 1.2
    base = running.base + "/api/fullscreen/commands"
    held = asyncio.create_task(session.get(f"{base}?wait_s=3&page=HIDDENPAGE1&visible=1"))
    await asyncio.sleep(0.1)
    async with session.get(f"{base}?wait_s=0&page=HIDDENPAGE1&visible=0") as response:
        assert (await response.json())["command"] is None             # l'avis de visibilité répond tout de suite
    ask = asyncio.create_task(running.ask(session, {"action": "enter"}))
    await asyncio.sleep(0.2)
    # La commande n'a pas été prise par le poll resté ouvert de la page cachée : une page visible la reçoit.
    async with session.get(f"{base}?wait_s=1&page=VISIBLEPAGE1&visible=1") as response:
        command = (await response.json())["command"]
    assert command is not None and command["action"] == "enter"
    await running.receipt(session, command["id"], {"state": "needs_gesture"})
    assert (await ask)[0] == 200
    held.cancel()
    assert lines(running.control, "fullscreen.page_hidden")[0]["data"]["page"] == "HIDDENPA"


async def test_with_only_hidden_pages_the_request_is_the_coded_no_visible_page_refusal(running, session):
    running.control.fullscreen.deadline_s = 0.4
    async with session.get(running.base + "/api/fullscreen/commands?wait_s=0&page=HIDDENPAGE2&visible=0") as response:
        assert response.status == 200
    ask = asyncio.create_task(running.ask(session, {"action": "enter"}))
    async with session.get(running.base + "/api/fullscreen/commands?wait_s=0.6&page=HIDDENPAGE2&visible=1") as response:
        assert (await response.json())["command"] is not None          # la page se remontre : elle peut la prendre
    status, _, header = await ask
    assert status == 504 and header == fs.COMMAND_EXPIRED              # prise mais jamais répondue (pas de reçu)
    # Cachée de nouveau et sans autre page : personne ne prend rien.
    async with session.get(running.base + "/api/fullscreen/commands?wait_s=0&page=HIDDENPAGE2&visible=0") as response:
        assert response.status == 200
    status, _, header = await running.ask(session, {"action": "enter"})
    assert status == 504 and header == fs.NO_VISIBLE_PAGE


async def test_a_page_holding_a_stale_prompt_is_told_at_once_and_an_exit_elsewhere_wakes_the_other_pages(running, session):
    base = running.base + "/api/fullscreen/commands"
    task, short = await running.armed(session)
    await task
    # Une page qui croit tenir un autre armement l'apprend tout de suite (retour d'un onglet caché).
    started = asyncio.get_running_loop().time()
    async with session.get(f"{base}?wait_s=5&page=STALEPAGE01&armed=ZZZZZZZZ") as response:
        body = await response.json()
    assert body == {"command": None, "armed": short}
    assert asyncio.get_running_loop().time() - started < 1.0
    # Une page qui tient le bon armement attend ; quand l'armement s'efface (annulation reçue par un autre
    # onglet), son poll rend la main aussitôt avec `armed: null`.
    waiting = asyncio.create_task(session.get(f"{base}?wait_s=10&page=STALEPAGE01&armed={short}"))
    await asyncio.sleep(0.2)
    started = asyncio.get_running_loop().time()
    await running.report(session, {"state": "exited", "id": short, "code": fs.CANCELLED})
    response = await asyncio.wait_for(waiting, 3)
    assert await response.json() == {"command": None, "armed": None}
    assert asyncio.get_running_loop().time() - started < 2.0


async def test_a_poll_whose_client_left_does_not_swallow_the_next_command(running, session):
    base = running.base + "/api/fullscreen/commands"
    gone = asyncio.create_task(session.get(f"{base}?wait_s=10&page=GONEPAGE001&visible=1"))
    await asyncio.sleep(0.2)
    gone.cancel()                                                      # le client coupe : le serveur le voit fermé
    await asyncio.sleep(0.2)
    ask = asyncio.create_task(running.ask(session, {"action": "enter"}))
    command = (await running.poll(session))["command"]
    assert command is not None                                         # pas avalée par le poll mort
    await running.receipt(session, command["id"], {"state": "needs_gesture"})
    assert (await ask)[0] == 200


@pytest.mark.parametrize("query", ["page=short", "page=bad%20page%21%21", "visible=2", "visible=", "armed=toolongarmedid",
                                   "armed=%2F%2F%2F%2F%2F%2F%2F%2F"])
async def test_the_poll_validates_its_visibility_and_armed_parameters(running, session, query):
    async with session.get(f"{running.base}/api/fullscreen/commands?wait_s=0&{query}") as response:
        assert response.status == 400 and response.headers[SETTINGS_ERROR_CODE_HEADER] == fs.BAD_REQUEST


def test_keys_default_to_none_on_the_wire():
    assert fs.parse_request({"action": "enter"}).to_wire()["keys"] == "none"
