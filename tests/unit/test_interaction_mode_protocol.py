"""`/v1/interaction-mode` de bout en bout : route, authentification, codec, évènement.

Les tests de la Slice 02 qui n'utilisent pas le réseau prouvent la logique ;
celui-ci prouve le **transport**. Un refus dont le code stable se perdrait entre
Core et le client rendrait `interaction_mode_not_implemented` inutile, et c'est
précisément le code sur lequel l'écran de la Slice 03 doit s'appuyer.
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from jarvis.core.interaction_mode import INTERACTION_MODE_CHANGED
from jarvis.core.v2_app import JarvisCoreApplication
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


async def test_une_demande_applique_le_mode_et_fait_monter_la_revision_une_seule_fois(stack):
    _core, _server, client = stack

    applied = await client.set_interaction_mode("presentation", source="control_center")
    assert applied["disposition"] == "applied"
    assert applied["mode"] == "presentation"
    assert applied["revision"] == 1

    again = await client.set_interaction_mode("presentation", source="control_center")
    assert again["disposition"] == "unchanged"
    assert again["revision"] == 1
    assert (await client.interaction_mode())["revision"] == 1


async def test_le_mode_reunion_est_refuse_en_409_avec_son_code_stable(stack):
    _core, _server, client = stack

    with pytest.raises(CoreProtocolError) as refus:
        await client.set_interaction_mode("meeting")

    assert refus.value.status == 409
    assert refus.value.code == "interaction_mode_not_implemented"
    assert (await client.interaction_mode())["mode"] == "assistant"


@pytest.mark.parametrize("payload", ["simple", "continuous_brain", "SIMPLE", "", "fromage"])
async def test_une_valeur_qui_n_est_pas_un_mode_est_refusee_en_400(stack, payload):
    _core, _server, client = stack

    with pytest.raises(CoreProtocolError) as refus:
        await client.set_interaction_mode(payload)

    assert refus.value.status == 400
    assert refus.value.code == "interaction_mode_unknown"


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
        await client.set_interaction_mode("presentation", source="control_center")
        await asyncio.wait_for(task, timeout=5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert received[0]["mode"] == "presentation"
    assert received[0]["label"] == "PRESENTATION"
    assert received[0]["revision"] == 1
    assert received[0]["source"] == "control_center"


async def test_la_route_refuse_un_champ_qu_elle_ne_connait_pas(stack):
    _core, _server, client = stack
    session = await client._http()

    async with session.post(
        client.base_url + "/v1/interaction-mode", headers=client.headers,
        json={"mode": "presentation", "restart": True},
    ) as response:
        body = await response.json()

    assert response.status == 400
    assert body["error"]["code"] == "invalid_request"
    assert (await client.interaction_mode())["revision"] == 0


async def test_la_lecture_et_l_ecriture_exigent_le_jeton_de_session(stack):
    _core, _server, client = stack
    intrus = LocalCoreClient(host=client.host, port=client.port, token="x" * 48)
    try:
        with pytest.raises(CoreProtocolError) as lecture:
            await intrus.interaction_mode()
        assert lecture.value.status == 401
        with pytest.raises(CoreProtocolError) as ecriture:
            await intrus.set_interaction_mode("presentation")
        assert ecriture.value.status == 401
    finally:
        await intrus.close()
