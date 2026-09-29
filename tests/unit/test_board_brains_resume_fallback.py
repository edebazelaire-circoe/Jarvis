"""Reprise QA 04a : un identifiant de reprise mort ne rend jamais un Board impossible à activer.

Si `claude --resume <id>` sort au démarrage (session effacée, expirée), le pool
refait **un** essai avec un CLI neuf dans la même activation ; le nouvel
identifiant remonte à Core. Si le démarrage neuf échoue aussi : 502, rien de
validé. Une reprise qui marche ne relance rien. Processus réels (doublure
`RealStub`, mode `fail-resume` : échoue seulement avec `--resume`).
"""

from __future__ import annotations

import pytest

from jarvis.domain.workspace_board import DEFAULT_BOARD_ID
from tests.unit.test_board_brains import binding as pool_binding, make_pool
from tests.unit.test_board_brains_control_center import trace
from tests.unit.test_board_brains_readiness import real_agent, stack, stub  # noqa: F401 - fixtures

STALE = "11111111-2222-3333-4444-555555555555"


# ------------------------------------------------------------------ le pool


async def test_a_dead_resume_id_falls_back_to_a_fresh_cli_and_reports_its_new_id(tmp_path, stub):
    pool = make_pool(tmp_path, factory=lambda cli: real_agent(tmp_path), ready_settle_s=10.0)
    stub.mode("init")
    await pool.activate(pool_binding("conv-0"))                 # adopte le foreground de départ
    stub.mode("fail-resume")

    entry = await pool.activate(pool_binding("conv-a", agent_cli="claude", agent_session_id=STALE))

    assert [spawn["resume"] for spawn in stub.spawns()][1:] == [STALE, None], "one retry, without --resume"
    assert entry.agent.state == "running" and pool.foreground is entry
    new_id = entry.agent.session_id
    assert new_id and new_id != STALE
    assert entry.to_payload()["agent_session_id"] == new_id, "the activation answer carries the new id"
    assert entry.resume_id("claude") == new_id
    fallback = trace(tmp_path, "board_brain.resume_failed_fresh_start")
    assert len(fallback) == 1 and fallback[0]["level"] == "warning"
    data = fallback[0]["data"]
    assert data["board_id"] == entry.board_id and data["old_agent_session_id"] == STALE
    assert "No conversation found" in data["exit_detail"] and "code 1" in data["exit_detail"]
    assert trace(tmp_path, "board_brain.started")[-1]["data"]["conversation_id"] == "conv-a"
    await pool.aclose()


async def test_a_normal_resume_does_not_retry(tmp_path, stub):
    pool = make_pool(tmp_path, factory=lambda cli: real_agent(tmp_path), ready_settle_s=10.0)
    stub.mode("init")
    await pool.activate(pool_binding("conv-0"))                 # adopte le foreground de départ

    entry = await pool.activate(pool_binding("conv-a", agent_cli="claude", agent_session_id=STALE))

    assert [spawn["resume"] for spawn in stub.spawns()][1:] == [STALE]
    assert entry.agent.session_id == STALE
    assert trace(tmp_path, "board_brain.resume_failed_fresh_start") == []
    assert trace(tmp_path, "board_brain.resumed")[-1]["data"]["conversation_id"] == "conv-a"
    await pool.aclose()


async def test_resume_and_fresh_start_both_failing_leave_the_pool_unchanged(tmp_path, stub):
    pool = make_pool(tmp_path, factory=lambda cli: real_agent(tmp_path), ready_settle_s=10.0)
    stub.mode("init")
    first = await pool.activate(pool_binding("conv-a"))
    b = pool_binding("conv-b", agent_cli="claude", agent_session_id=STALE)
    await pool.activate(b)
    await pool.activate(pool_binding("conv-a", board_id=first.board_id))   # B suspendu, id gardé
    suspended = pool.find("conv-b")
    assert suspended.resume_id("claude") == STALE

    stub.mode("fail-start")
    with pytest.raises(RuntimeError, match="injected start failure"):
        await pool.activate(b)

    assert [spawn["resume"] for spawn in stub.spawns()][-2:] == [STALE, None]
    assert pool.foreground is first and first.agent.state == "running", "nothing changed"
    assert suspended.resume_id("claude") == STALE and suspended.agent.session_id == STALE, "old id kept"
    await pool.aclose()


# ------------------------------------------------------------------ bout en bout par Core


async def _board_b_with_a_saved_id(stack):  # noqa: ANN001, ANN202
    core = await stack.start_core()
    pool = stack.control.board_brains
    pool._factory = lambda cli: real_agent(stack.tmp_path)
    pool.ready_settle_s = 5.0
    _, created = await stack.call("POST", "/api/boards", json={"title": "Projet B"})
    board_b = created["board"]["board_id"]
    assert (await stack.call("POST", "/api/boards/switch", json={"board_id": board_b}))[0] == 200
    session = (await core.sessions.current()).session.jarvis_session_id
    old_id = (await core.sessions.binding_for(session, board_b)).agent_session_id
    assert old_id, "the first start reported its id to Core"
    assert (await stack.call("POST", "/api/boards/switch", json={"board_id": DEFAULT_BOARD_ID}))[0] == 200
    return core, pool, board_b, session, old_id


async def test_switch_to_a_board_whose_session_is_gone_succeeds_with_a_fresh_cli(stack, stub):
    stub.mode("init")
    core, pool, board_b, session, old_id = await _board_b_with_a_saved_id(stack)

    stub.mode("fail-resume")
    status, switched = await stack.call("POST", "/api/boards/switch", json={"board_id": board_b})

    assert status == 200, switched
    assert pool.foreground.board_id == board_b and pool.foreground.agent.state == "running"
    new_id = pool.foreground.agent.session_id
    assert new_id and new_id != old_id
    assert (await core.sessions.binding_for(session, board_b)).agent_session_id == new_id, "Core binding updated"
    fallback = trace(stack.tmp_path, "board_brain.resume_failed_fresh_start")[-1]
    assert fallback["data"]["old_agent_session_id"] == old_id and fallback["data"]["board_id"] == board_b


async def test_switch_whose_fresh_start_also_fails_is_502_and_commits_nothing(stack, stub):
    stub.mode("init")
    core, pool, board_b, session, old_id = await _board_b_with_a_saved_id(stack)
    foreground = pool.foreground
    before = await core.sessions.current()

    stub.mode("fail-start")
    status, refused = await stack.call("POST", "/api/boards/switch", json={"board_id": board_b})

    assert status == 502 and refused["error"]["code"] == "board_activation_failed"
    after = await core.sessions.current()
    assert after.binding.conversation_id == before.binding.conversation_id
    assert (await stack.call("GET", "/api/boards/active"))[1]["board"]["board_id"] == DEFAULT_BOARD_ID
    assert (await core.sessions.binding_for(session, board_b)).agent_session_id == old_id
    assert pool.foreground is foreground
    assert next(e for e in pool.entries() if e.board_id == board_b).resume_id("claude") == old_id
    assert trace(stack.tmp_path, "board_brain.resume_failed_fresh_start")[-1]["data"]["old_agent_session_id"] == old_id
