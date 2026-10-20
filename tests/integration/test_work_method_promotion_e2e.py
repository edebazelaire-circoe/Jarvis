"""Work Methods de bout en bout : vrai Core (`JarvisCoreApplication`), vraie route sous jeton, vrai client (Slice 12).

L'historique est écrit dans la base temporaire de ce Core par l'adaptateur réel ; les candidats sont lus et la
promotion faite par `LocalCoreClient` à travers `LocalProtocolServer`, puis Core est redémarré sur la même
racine : la version promue survit, le candidat reste promu. Jamais une base réelle.
"""

from __future__ import annotations

import socket

import pytest

from jarvis.adapters.sqlite_mission_history import SQLiteMissionHistoryRepository
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from tests.fakes.work_methods import record_mission

TOKEN = "w" * 48


async def _up(root):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    core = JarvisCoreApplication(data_root=root)
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    return core, server, LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)


async def _down(core, server, client):
    await client.close()
    await server.stop()
    await core.stop()


async def test_candidates_are_promoted_once_by_a_person_and_survive_a_restart(tmp_path):
    core, server, client = await _up(tmp_path)
    try:
        store = SQLiteMissionHistoryRepository(core.state)
        for n, minute in enumerate((0, 10, 20)):
            await record_mission(store, f"m{n}", minute=minute)
        body = await client.work_method_candidates()
        [candidate] = [c for c in body["candidates"] if c["status"] == "candidate"]
        assert candidate["uses"] == 3 and candidate["draft"]["version"] == 2
        with pytest.raises(CoreProtocolError) as refused:
            await client.promote_work_method({"candidate_id": candidate["candidate_id"], "expected_version": 1,
                                              "promoted_by": "research-lead", "method": candidate["draft"]})
        assert (refused.value.status, refused.value.code) == (403, "work_method_promoter_not_human")
        promoted = await client.promote_work_method({"candidate_id": candidate["candidate_id"], "expected_version": 1,
                                                     "promoted_by": "user", "method": candidate["draft"]})
        assert promoted["method"]["provenance"]["origin"] == "promoted"
    finally:
        await _down(core, server, client)

    core, server, client = await _up(tmp_path)
    try:
        catalogue = await client.work_methods()
        assert catalogue["latest"]["deep-research"] == "deep-research@2"
        body = await client.work_method_candidates()
        [again] = [c for c in body["candidates"] if c["candidate_id"] == candidate["candidate_id"]]
        assert again["status"] == "promoted" and again["promoted_keys"] == ["deep-research@2"]
    finally:
        await _down(core, server, client)
