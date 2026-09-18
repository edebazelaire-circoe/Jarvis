"""L'abandon d'un tour traverse vraiment le protocole (19/09/2026).

Un barge-in pendant la réflexion ne vaut que si la surface peut réellement
atteindre Core : la corrélation d'un tour Realtime
(`realtime:{conversation}:{item}`) contient des deux-points, et voyage donc
dans le corps de la requête, pas dans le chemin. Ce test fait l'aller-retour
complet, contre un vrai serveur de protocole et un vrai orchestrateur.
"""

from __future__ import annotations

import asyncio

from tests.unit.test_v2_brain_orchestrator import SlowBackend, wait_idle


async def test_the_protocol_round_trip_carries_the_abandon(tmp_path):
    """Client et serveur parlent bien du même abandon, corrélation comprise.

    La corrélation voyage dans le corps : `realtime:{conversation}:{item}`
    contient des deux-points, et n'a pas à traverser une URL.
    """

    from aiohttp.test_utils import TestServer
    from jarvis.protocol.client import LocalCoreClient
    from jarvis.protocol.server import LocalProtocolServer
    from jarvis.core.v2_app import JarvisCoreApplication

    backend = SlowBackend()
    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    core.brain._backend = backend
    token = "t" * 32
    protocol = LocalProtocolServer(core, host="127.0.0.1", port=0, token=token)
    server = TestServer(protocol._app())
    await server.start_server()
    try:
        client = LocalCoreClient(host="127.0.0.1", port=server.port, token=token)
        conversation = await client.create_conversation()
        correlation = f"realtime:{conversation['id']}:item-1"
        await client.submit_brain_turn(conversation["id"], content="Jarvis, prépare le rapport",
                                       correlation_id=correlation)
        await asyncio.wait_for(backend.started.wait(), timeout=5)

        result = await client.cancel_brain_turn(conversation["id"], correlation_id=correlation)

        assert result["cancelled"] is True and result["correlation_id"] == correlation
        await wait_idle(core.brain)
        assert backend.cancelled == [correlation]
        await client.close()
    finally:
        await server.close()
        await core.stop()
