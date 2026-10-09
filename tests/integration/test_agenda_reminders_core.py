"""Chaîne réelle de Core : agenda -> boucle de rappel -> tour système du cerveau -> accusé.

Seuls l'agenda (plugin MCP) et le backend du cerveau sont factices ; l'horloge
est simulée. Aucun tour utilisateur ne déclenche le rappel.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import socket
from zoneinfo import ZoneInfo

import pytest

from jarvis.core.brain_service import BRAIN_WOKEN_KIND
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.agenda_reminders import AgendaSettings, parse_events
from jarvis.domain.v2 import BrainTurnResult
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer

PARIS = ZoneInfo("Europe/Paris")
TOKEN = "c" * 48


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Backend:
    def __init__(self):
        self.turns = []

    async def run_turn(self, turn, state, emit):
        self.turns.append((turn.source.value, turn.text))
        return BrainTurnResult(correlation_id=turn.correlation_id)


class Sink:
    def __init__(self):
        self.events = []

    def emit(self, kind, message, *, level="info", data=None):
        self.events.append((kind, dict(data or {})))


async def test_core_opens_a_system_turn_for_the_appointment_then_stays_quiet_once_acknowledged(tmp_path):
    clock = {"now": datetime(2026, 10, 7, 8, 50, tzinfo=PARIS)}
    backend, sink, port = Backend(), Sink(), free_port()
    core = JarvisCoreApplication(data_root=tmp_path / "data", brain_backend=backend, diagnostics=sink,
                                 agenda_settings=AgendaSettings, agenda_tick_s=3600.0, agenda_clock=lambda: clock["now"])

    async def fetch(start, end):
        return parse_events([{"id": "9", "summary": "Rendez-vous Quentin", "start": "2026-10-07T09:00:00+02:00",
                              "end": "2026-10-07T10:00:00+02:00", "allDay": False}])

    core.agenda_reminders._fetch = fetch
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    try:
        conversation = (await client.current_session())["binding"]["conversation_id"]
        # La boucle réelle a déjà tourné une fois au démarrage (8 h 50 : « dans 10 min »).
        async with asyncio.timeout(5):
            while not backend.turns:
                await asyncio.sleep(.01)
        source, text = backend.turns[0]
        assert source == "system" and "Rendez-vous Quentin" in text and "dans 10 min" in text
        assert [d["origin"] for k, d in sink.events if k == BRAIN_WOKEN_KIND] == ["agenda"]

        # L'utilisateur répond : accusé. Le rappel « manqué » se tait.
        await client.submit_brain_turn(conversation, content="Oui, j'y vais", correlation_id="ack-1")
        async with asyncio.timeout(5):
            while len(backend.turns) < 2:
                await asyncio.sleep(.01)
        await asyncio.sleep(.2)
        clock["now"] = datetime(2026, 10, 7, 9, 6, tzinfo=PARIS)
        assert await core.agenda_reminders.tick() == 0
        assert len(backend.turns) == 2
    finally:
        await client.close()
        await server.stop()
        await core.stop()
