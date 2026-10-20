"""Outils MCP de relation et relais du Control Center (Slice 06).

- serveur `jarvis-workspace` réel en mémoire contre un faux Control Center : l'identité apposée par le hook est
  retirée de l'entrée, transmise, jamais montrée dans le schéma ; sans elle, refus actionnable ;
- `RelationRelay` contre les vraies routes de Core (service, base temporaire) : agentId du CLI → identités de
  travail, `self`, agent inconnu, refus de Core rendus tels quels, billet de relais déposé.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.domain.relation_runtime import CALLER_STAMP_KEY
from jarvis.runtime import agent_handoffs
from jarvis.runtime.relation_relay import RelationRelay, RelationRelayError
from jarvis.runtime.workspace_mcp import build_server
from tests.fakes.mission_history import SOURCE
from tests.unit.test_relations_runtime_service import core, member, owner, packet, run  # noqa: F401 - fixture
from tests.unit.test_workspace_mcp import fake_cc  # noqa: F401 - fixture réutilisée

STAMP = {"stamped": True, "agent_id": "a1b2c3d4e5f6a7b8c", "agent_type": "general-purpose"}


# ------------------------------------------------------------------ outils MCP


async def test_the_server_strips_the_stamp_passes_the_caller_and_hides_it_from_the_schema(fake_cc):  # noqa: F811
    from mcp.shared.memory import create_connected_server_and_client_session

    fake, ws = fake_cc
    fake.answer("POST", "/api/missions/relations", 200, {"ok": True, "relation": {
        "relation_id": "rel_1", "kind": "qa", "mission_id": "mis_A", "purpose": "Relire", "status": "open",
        "participants": [{"instance_id": "ainst_q", "position": "reviewer"},
                         {"instance_id": "ainst_b", "position": "reviewed"}]},
        "agents": {"ainst_q": STAMP["agent_id"], "ainst_b": "bbbbbbbbbbbbbbbbb"}})
    async with create_connected_server_and_client_session(build_server(tools=ws)) as session:
        listed = {tool.name: tool for tool in (await session.list_tools()).tools}
        assert CALLER_STAMP_KEY not in listed["relation_open"].inputSchema["properties"]
        result = await session.call_tool("relation_open", {
            "kind": "qa", "purpose": "Relire", "reviewer": "self", "reviewed": "bbbbbbbbbbbbbbbbb",
            CALLER_STAMP_KEY: STAMP})
        assert not result.isError, result.content
        assert result.structuredContent["participants"][0] == {"agent_id": STAMP["agent_id"],
                                                               "instance_id": "ainst_q", "position": "reviewer"}
        unstamped = await session.call_tool("relation_post", {"relation_id": "rel_1", "text": "Bonjour"})
        assert unstamped.isError
        assert "relancer JARVIS" in unstamped.content[0].text
        wrong = await session.call_tool("relation_open", {"kind": "adversary", "purpose": "Un seul",
                                                          "producers": ["self"], CALLER_STAMP_KEY: STAMP})
        assert wrong.isError and "au moins deux producers" in wrong.content[0].text
    [(method, path, _query, body)] = [request for request in fake.requests if request[1] == "/api/missions/relations"]
    assert body["caller_agent_id"] == STAMP["agent_id"]
    assert body["participants"] == [{"agent": "self", "position": "reviewer"},
                                    {"agent": "bbbbbbbbbbbbbbbbb", "position": "reviewed"}]


async def test_a_core_refusal_reaches_the_agent_with_what_to_fix(fake_cc):  # noqa: F811
    from mcp.shared.memory import create_connected_server_and_client_session

    fake, ws = fake_cc
    fake.answer("POST", "/api/missions/relations/rel_1/messages", 409, {
        "ok": False, "code": "relation_private_content",
        "error": "text: private reasoning. À faire : publiez le message explicite destiné aux autres, jamais votre "
                 "raisonnement."})
    async with create_connected_server_and_client_session(build_server(tools=ws)) as session:
        result = await session.call_tool("relation_post", {"relation_id": "rel_1", "text": "x",
                                                           CALLER_STAMP_KEY: STAMP})
    assert result.isError and "relation_private_content" in result.content[0].text
    assert "jamais votre raisonnement" in result.content[0].text


# ------------------------------------------------------------------ relais du Control Center vers Core


class Tracker:
    def __init__(self, tasks):
        self._tasks = tasks

    def find(self, key):
        return next((task for task in self._tasks if key in (task.task_id, task.work_key)), None)


class Declarations:
    """Le suivi des tâches vu par le relais : agentId (task_id) → work_key."""

    def __init__(self, mapping):
        tasks = [SimpleNamespace(task_id=agent, work_key=key) for agent, key in mapping.items()]
        self._trackers = {1: Tracker(tasks)}
        self.settled = 0

    def task_for_agent(self, agent_id):
        task = self._trackers[1].find(agent_id)
        return (SOURCE, task) if task is not None and task.task_id == agent_id else None

    async def settle(self):
        self.settled += 1
        return True


class CoreHttp:
    """`CoreMissionTransport` branché sur les vraies routes de Core (sans jeton)."""

    def __init__(self, client):
        self.client = client

    async def _json(self, response):
        from jarvis.protocol.client import CoreProtocolError

        body = await response.json()
        if response.status >= 400:
            raise CoreProtocolError(response.status, body["error"]["code"], body["error"]["message"])
        return body

    async def open_relation(self, body):
        return await self._json(await self.client.post("/v1/missions/relations", json=body))

    async def read_relation(self, relation_id, *, after=0, limit=100):
        return await self._json(await self.client.get(f"/v1/missions/relations/{relation_id}",
                                                      params={"after": after, "limit": limit}))

    async def post_relation_message(self, relation_id, body):
        return await self._json(await self.client.post(f"/v1/missions/relations/{relation_id}/messages", json=body))

    async def close_relation(self, relation_id, body):
        return await self._json(await self.client.post(f"/v1/missions/relations/{relation_id}/close", json=body))

    async def prepare_handoff(self, body):
        return await self._json(await self.client.post("/v1/missions/handoffs", json=body))

    async def close(self):
        return None


AGENTS = {"agentA": "A", "agentB": "B", "agentC": "C", "agentQ": "Q"}


@pytest.fixture
async def relay(core, tmp_path):  # noqa: F811
    await owner(core, "A")
    for key, role in (("B", "coder"), ("C", "coder"), ("Q", "qa")):
        await run(core, key)
        await member(core, key, "A", role)
    declarations = Declarations(AGENTS)
    return SimpleNamespace(relay=RelationRelay(declarations=declarations, transport=CoreHttp(core.client),
                                               runtime_root=tmp_path / "runtime"),
                           core=core, declarations=declarations, runtime=tmp_path / "runtime")


async def test_the_relay_resolves_agent_ids_and_self_then_core_records_the_relation(relay):
    opened = await relay.relay.open(caller="agentQ", kind="qa", participants=[("self", "reviewer"),
                                                                              ("agentB", "reviewed")],
                                    purpose="Relire B", target_refs=[])
    assert relay.declarations.settled == 1  # les déclarations en attente partent d'abord
    relation = opened["relation"]
    assert set(opened["agents"].values()) == {"agentQ", "agentB"}
    posted = await relay.relay.post(caller="agentQ", relation_id=relation["relation_id"], type="critique",
                                    text="Le test du cas vide manque.", audience=["agentB"], artifact_refs=[],
                                    reply_to_message_id=None)
    assert posted["seq"] >= 1
    read = await relay.relay.read(relation_id=relation["relation_id"], after=0, limit=10)
    assert [item["text"] for item in read["messages"]] == ["Le test du cas vide manque."]
    assert set(read["agents"].values()) == {"agentQ", "agentB"}
    closed = await relay.relay.close(caller="agentQ", relation_id=relation["relation_id"], outcome="findings",
                                     summary="Un test manque.", winner=None)
    assert closed["relation"]["outcome"] == "findings"


async def test_the_relay_names_an_unknown_agent_and_relays_core_refusals(relay):
    with pytest.raises(RelationRelayError) as refused:
        await relay.relay.open(caller="agentA", kind="adversary", participants=[("agentB", "producer"),
                                                                                ("ghost123", "producer")],
                               purpose="Duel", target_refs=[])
    assert (refused.value.status, refused.value.code) == (404, "relation_agent_unknown")
    assert "agentId exact" in refused.value.message
    with pytest.raises(RelationRelayError) as refused:
        await relay.relay.open(caller="agentB", kind="adversary", participants=[("self", "producer"),
                                                                                ("agentC", "producer")],
                               purpose="Duel sans autorité", target_refs=[])
    assert (refused.value.status, refused.value.code) == (403, "relation_not_owner")
    with pytest.raises(RelationRelayError) as refused:
        await relay.relay.open(caller=None, kind="communication", participants=[("self", "member"),
                                                                               ("agentC", "member")],
                               purpose="Le cerveau", target_refs=[])
    assert refused.value.code == "relation_caller_not_instance"


async def test_a_prepared_handoff_leaves_a_ticket_the_hook_can_claim(relay):
    result = await relay.relay.handoff(caller="agentA", purpose="Contexte neuf", packet=packet().to_payload())
    handoff_id = result["handoff"]["handoff_id"]
    # L'horloge du Core de test est figée (2026-10-20 09:30 UTC) : le billet est réclamé à cette heure-là.
    from datetime import datetime

    now_ms = int(datetime.fromisoformat(result["handoff"]["prepared_at"]).timestamp() * 1000) + 1_000
    ticket = agent_handoffs.claim(relay.runtime, "agentA", now_ms=now_ms)
    assert ticket is not None and ticket.handoff_id == handoff_id and ticket.packet == packet()
    assert ticket.mission_id == "mis_A"
    with pytest.raises(RelationRelayError) as refused:
        await relay.relay.handoff(caller=None, purpose="Le cerveau", packet=packet().to_payload())
    assert refused.value.code == "relation_caller_not_instance"


async def test_a_superfluous_field_is_named_and_the_local_refusal_is_journaled(fake_cc):  # noqa: F811
    """Bac à sable S06 : le relecteur ajoutait `members` à une QA ; le refus nomme le champ à retirer."""

    from mcp.shared.memory import create_connected_server_and_client_session

    from jarvis.runtime.journal import read_jsonl_tail

    fake, ws = fake_cc
    async with create_connected_server_and_client_session(build_server(tools=ws)) as session:
        result = await session.call_tool("relation_open", {
            "kind": "qa", "purpose": "Relire", "reviewer": "self", "reviewed": "bbbbbbbbbbbbbbbbb",
            "members": ["bbbbbbbbbbbbbbbbb"], CALLER_STAMP_KEY: STAMP})
    assert result.isError and "Retirez members" in result.content[0].text
    assert not [request for request in fake.requests if request[1] == "/api/missions/relations"]
    failed = [row for row in read_jsonl_tail(ws.target.runtime_root / "trace.jsonl", limit=50)
              if row.get("kind") == "relation.tool_failed"]
    assert failed and failed[-1]["data"]["code"] == "relation_arguments_invalid"
