"""Plusieurs onglets du Control Center, Chat ouvert : aucun ne s'affame (Slice 06, reprise QA bloquante).

Chrome partage six connexions HTTP/1.1 par origine entre TOUS ses onglets. La
page tient déjà des attentes longues (commandes plein écran, explorateur,
Bare Hands, chronologie) ; la première version du Chat y ajoutait un long-poll
de 25 s par onglet et, à deux onglets, `/api/status` et `/api/chat/state`
dépassaient 9 s (QA S06). Décision agent 0 : le Chat ne tient AUCUNE requête
en attente — lectures courtes par le seul meneur Web Locks, partagées par
`BroadcastChannel`.

Ici un vrai serveur HTTP (aiohttp, port éphémère) sert la page composée et
TIENT vraiment toute attente longue demandée (`wait_s`, `wait_ms`), comme le
Control Center. Deux onglets Chat ouverts : `/api/status` répond en moins
d'une seconde, un seul onglet lit les événements, un envoi depuis le suiveur
aboutit et se voit dans l'autre. Trois onglets plus la chronologie : le Chat
ne demande aucune attente longue de plus que la page Chat fermé (cette page-là
affame déjà Chrome à elle seule, hors du Chat). Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil

from aiohttp import web
import pytest

from tests.unit.test_boards_card_browser import _chrome, _served_page

HARNESS = Path(__file__).parent / "_chat_tabs_browser.mjs"
MAX_HOLD_S = 25.0


class FakeControlCenter:
    """Page servie + `/api/status`, routes du Chat et attentes longues réelles."""

    def __init__(self, page: Path) -> None:
        self.page = page.read_text(encoding="utf-8")
        self.rows: list[dict] = []
        self.appended = asyncio.Event()
        self.posted: list[dict] = []
        self.event_reads = 0
        self.state = {"schema_version": 1, "jarvis_session_id": "jsess_1", "board_id": "default",
                      "conversation_id": "conv-a",
                      "voice": {"state": "background", "epoch": "e", "revision": 1, "report_age_ms": 200, "request": None},
                      "chat_writable": True, "locked_reason": None}
        self._add("user.transcript.accepted", "voice:1", "Bonjour Jarvis")
        self._add("brain.message.published", "voice:1", "Bonjour.", {"kind": "turn_result", "status": "completed"})

    def _add(self, kind: str, correlation: str, text: str, attributes: dict | None = None) -> None:
        sequence = len(self.rows) + 1
        self.rows.append({"sequence": sequence, "recorded_at": "2026-10-14T09:00:00.000Z", "event": {
            "schema_version": 1, "event_id": f"cev-{sequence}", "event_type": kind,
            "actor": "user" if kind.startswith("user") else "brain", "conversation_id": "conv-a", "producer": "fake",
            "visibility": "public", "occurred_at": "2026-10-14T09:00:00.000Z", "started_at": None, "ended_at": None,
            "span_id": None, "session_id": "voice-1", "turn_id": None, "correlation_id": correlation,
            "parent_event_id": None, "task_id": None, "work_id": None, "speech_id": None, "outcome_id": None,
            "trace_ref": None, "content": text, "attributes": attributes or {"source": "text", "addressing": "addressed"}}})
        self.appended.set()
        self.appended = asyncio.Event()

    @staticmethod
    def _hold_s(request: web.Request) -> float:
        query = request.query
        if "wait_ms" in query:
            return min(int(query["wait_ms"]) / 1000, MAX_HOLD_S)
        for name in ("wait_s", "wait"):
            if name in query:
                return min(float(query[name]), MAX_HOLD_S)
        return 0.0

    async def index(self, _request: web.Request) -> web.Response:
        return web.Response(text=self.page, content_type="text/html")

    async def status(self, _request: web.Request) -> web.Response:
        return web.json_response({"voice_state": "idle", "voice_online": False, "agent": {"name": "claude", "state": "running"},
                                  "agent_cli": "claude", "error_count": 0, "background": None,
                                  "boards": {"available": True, "active": {"board_id": "default", "title": "Jarvis"},
                                             "jarvis_session_id": "jsess_1", "error": None,
                                             "bindings": [{"board_id": "default", "lifecycle": "foreground",
                                                           "agent_cli": "claude", "closed": False}]}})

    async def chat_state(self, _request: web.Request) -> web.Response:
        return web.json_response(self.state)

    async def events(self, request: web.Request) -> web.Response:
        if request.query.get("projection") == "chat":
            self.event_reads += 1
        after = int(request.query.get("after_sequence", "0"))
        hold = self._hold_s(request)
        page = [row for row in self.rows if row["sequence"] > after]
        if not page and hold:
            try:
                await asyncio.wait_for(self.appended.wait(), hold)
            except asyncio.TimeoutError:
                pass
            page = [row for row in self.rows if row["sequence"] > after]
        cursor = page[-1]["sequence"] if page else max(after, len(self.rows))
        return web.json_response({"schema_version": 1, "events": page, "next_cursor": cursor, "has_more": False,
                                  "skipped_rows": 0})

    async def conversations(self, _request: web.Request) -> web.Response:
        return web.json_response({"schema_version": 1, "summaries": [{
            "conversation_id": "conv-a", "session_id": "voice-1", "event_count": len(self.rows), "first_sequence": 1,
            "last_sequence": len(self.rows), "first_occurred_at": "2026-10-14T09:00:00.000Z",
            "last_occurred_at": "2026-10-14T09:00:00.000Z", "last_recorded_at": "2026-10-14T09:00:00.000Z"}],
            "next_cursor": None, "has_more": False, "skipped_summaries": 0})

    async def turns(self, request: web.Request) -> web.Response:
        body = await request.json()
        self.posted.append(body)
        correlation = "chat:" + body["client_request_id"]
        self._add("user.transcript.accepted", correlation, body["content"])
        return web.json_response({"ok": True, "correlation_id": correlation, "turn_id": "t-" + correlation,
                                  "duplicate": False}, status=202)

    async def other(self, request: web.Request) -> web.Response:
        hold = self._hold_s(request)
        if hold:
            await asyncio.sleep(hold)  # the real Control Center holds its long-polls this long
            return web.json_response({"ok": True, "commands": [], "items": []})
        return web.json_response({"ok": False, "code": "http_error", "error": "not stubbed"}, status=404)

    def app(self) -> web.Application:
        app = web.Application()
        app.add_routes([web.get("/", self.index), web.get("/api/status", self.status),
                        web.get("/api/chat/state", self.chat_state), web.get("/api/conversations/events", self.events),
                        web.get("/api/conversations", self.conversations), web.post("/api/chat/turns", self.turns),
                        web.route("*", "/{tail:.*}", self.other)])
        return app


async def _run(tmp_path: Path, plan: dict) -> tuple[dict, FakeControlCenter]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    tmp_path.mkdir(parents=True, exist_ok=True)
    fake = FakeControlCenter(_served_page(tmp_path))
    runner = web.AppRunner(fake.app(), shutdown_timeout=0.5)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        proc = await asyncio.create_subprocess_exec(node, str(HARNESS), f"http://127.0.0.1:{port}", chrome, json.dumps(plan),
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=180)
    finally:
        await runner.cleanup()
    assert proc.returncode == 0, err.decode("utf-8", "replace")
    return json.loads(out.decode("utf-8")), fake


def _no_chat_wait(seen: dict) -> None:
    asks = [url for urls in seen["chatAsks"] for url in urls]
    assert asks, "the Chat did read"
    assert not any("wait_ms" in url for url in asks), [url for url in asks if "wait_ms" in url]


async def test_two_visible_chat_tabs_stay_responsive_and_a_follower_send_succeeds(tmp_path):
    """QA S06 : à deux onglets Chat ouverts, `/api/status` dépassait 9 s et l'envoi de l'onglet 2 n'aboutissait pas."""

    seen, fake = await _run(tmp_path, {"chatTabs": 2, "timelineTab": False, "settleMs": 6000, "sendFrom": 1,
                                       "text": "depuis l’onglet deux"})
    assert all(ms < 1000 for ms in seen["latency"]), seen["latency"]
    assert sorted(seen["roles"]) == ["follower", "leader"], seen["roles"]
    assert seen["send"]["sender"] is True and seen["send"]["sendError"] is None, seen["send"]
    assert all(seen["send"]["others"]), "the leader shares what it reads with every tab"
    assert [turn["content"] for turn in fake.posted] == ["depuis l’onglet deux"]
    # Only the leader reads events; the follower never asks for them.
    assert sum(1 for reads in seen["eventsRequests"] if reads) == 1, seen["eventsRequests"]
    _no_chat_wait(seen)
    assert seen["errors"] == [[], []], seen["errors"]


async def test_the_chat_adds_no_held_connection_with_three_tabs_and_a_timeline(tmp_path):
    """Trois onglets Chat ouverts et un onglet chronologie, comparés aux MÊMES onglets Chat fermé.

    Mesuré (rapport S6 rework) : Chat FERMÉ, ces quatre onglets visibles affament déjà `/api/status`
    (> 9 s) — les attentes longues de la page (plein écran, explorateur, chronologie) dépassent à elles seules
    les six connexions de Chrome ; c'est hors du Chat. Ce que le Chat doit prouver ici : il ne demande
    AUCUNE attente longue de plus (mêmes attentes, route par route) et un seul onglet lit les événements.
    """

    plan = {"chatTabs": 3, "timelineTab": True, "settleMs": 6000, "sendFrom": 2, "text": "x"}
    closed, _ = await _run(tmp_path / "closed", {**plan, "chatOpen": False})
    opened, _ = await _run(tmp_path / "open", plan)
    assert sorted(opened["roles"][:3]) == ["follower", "follower", "leader"], opened["roles"]
    held = lambda seen: sorted({url for urls in seen["held"] for url in urls})  # noqa: E731
    assert held(opened) == held(closed), (held(opened), held(closed))
    assert not any("/api/chat/" in url or "/api/conversations/events" in url for url in held(opened) if url not in held(closed))
    _no_chat_wait(opened)
