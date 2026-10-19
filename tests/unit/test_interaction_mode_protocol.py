"""`/v1/interaction-mode` de bout en bout : route, authentification, codec, évènement.

Les tests de la Slice 02 qui n'utilisent pas le réseau prouvent la logique ;
celui-ci prouve le **transport**. Depuis la Slice 01b de
`jarvis-board-ui-wheel-dossier-refactor`, `POST /v1/interaction-mode` refuse
**toute** demande (409 `interaction_mode_derived`) : le mode suit le type du
Board actif, et le Studio l'appelle en processus. Un refus dont le code stable
se perdrait entre Core et le client serait un échec silencieux.
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from jarvis.core.interaction_mode import INTERACTION_MODE_CHANGED
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.interaction_mode import INTERACTION_MODE_DERIVED, INTERACTION_MODE_DERIVED_MESSAGE
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer


@pytest.fixture
async def stack(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token="t" * 48)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token="t" * 48)
    try:
        yield core, server, client
    finally:
        await client.close()
        await server.stop()
        await core.stop()


async def test_core_rend_le_mode_effectif_sa_revision_et_les_modes_annonces(stack):
    _core, _server, client = stack

    snapshot = await client.interaction_mode()

    assert snapshot["mode"] == "assistant"
    assert snapshot["label"] == "SIMPLE"
    assert snapshot["revision"] == 0
    assert [entry["value"] for entry in snapshot["modes"]] == ["assistant", "presentation", "meeting"]
    assert [entry["implemented"] for entry in snapshot["modes"]] == [True, True, False]


async def _post(client, body) -> tuple[int, dict]:
    session = await client._http()
    async with session.post(client.base_url + "/v1/interaction-mode", headers=client.headers,
                            json=body) as response:
        return response.status, await response.json()


@pytest.mark.parametrize("body", [
    {"mode": "presentation", "source": "control_center"},
    {"mode": "presentation", "source": "presentation_studio_run"},
    {"mode": "assistant"},
    {"mode": "meeting"},
    {"mode": "fromage", "source": "x" * 500},
    {"mode": "presentation", "restart": True},
    {},
    ["presentation"],
])
async def test_toute_demande_de_mode_par_le_protocole_est_refusee_en_409(stack, body):
    """Aucune origine n'est admise, `presentation_studio_run` comprise : le Studio appelle le service en processus."""

    core, _server, client = stack

    status, payload = await _post(client, body)

    assert status == 409
    assert payload["error"] == {"code": INTERACTION_MODE_DERIVED, "message": INTERACTION_MODE_DERIVED_MESSAGE}
    assert (await client.interaction_mode())["revision"] == 0
    assert core.interaction_mode.mode.value == "assistant"


def test_le_client_n_a_plus_de_methode_d_ecriture_du_mode():
    assert not hasattr(LocalCoreClient, "set_interaction_mode")


async def test_un_changement_de_mode_arrive_sur_le_flux_d_evenements(stack):
    """Le fil par lequel Voice apprend le mode sans redémarrer (Décision D15)."""

    _core, _server, client = stack
    subscribed = asyncio.Event()
    received: list[dict] = []

    async def listen() -> None:
        async for envelope in client.events(on_connected=subscribed.set):
            if envelope.message_type == INTERACTION_MODE_CHANGED:
                received.append(envelope.payload)
                return

    task = asyncio.create_task(listen())
    try:
        await asyncio.wait_for(subscribed.wait(), timeout=5)
        # Le seul chemin d'un changement : en processus (bascule de Board, lecture du Studio).
        await _core.interaction_mode.request("presentation", source="board_switch")
        await asyncio.wait_for(task, timeout=5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert received[0]["mode"] == "presentation"
    assert received[0]["label"] == "PRESENTATION"
    assert received[0]["revision"] == 1
    assert received[0]["source"] == "board_switch"
    # L'époque voyage avec la révision : sans elle, un Voice qui survit au
    # redémarrage de Core prendrait les révisions neuves pour des vieilles.
    assert received[0]["epoch"] == _core.interaction_mode.epoch
    # …et le catalogue des modes ne voyage pas : l'instantané le porte déjà.
    assert "modes" not in received[0]


async def test_l_instantane_et_l_evenement_portent_la_meme_vie_de_core(stack):
    core, _server, client = stack

    snapshot = await client.interaction_mode()

    assert snapshot["epoch"] == core.interaction_mode.epoch
    assert snapshot["epoch"]
    # Deux services distincts ne partagent jamais une époque, sinon leurs
    # révisions se compareraient entre elles.
    from jarvis.core.interaction_mode import InteractionModeService

    class _Bus:
        async def publish(self, envelope):
            return None

    assert InteractionModeService(events=_Bus()).epoch != core.interaction_mode.epoch


async def test_la_lecture_et_l_ecriture_exigent_le_jeton_de_session(stack):
    _core, _server, client = stack
    intrus = LocalCoreClient(host=client.host, port=client.port, token="x" * 48)
    try:
        with pytest.raises(CoreProtocolError) as lecture:
            await intrus.interaction_mode()
        assert lecture.value.status == 401
        session = await intrus._http()
        async with session.post(intrus.base_url + "/v1/interaction-mode", headers=intrus.headers,
                                json={"mode": "presentation"}) as response:
            assert response.status == 401
    finally:
        await intrus.close()
