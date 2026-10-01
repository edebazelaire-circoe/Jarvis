"""Reprise QA 04a (après la Slice 06) : activation prête pour de vrai, entrées des Sessions closes.

A1 — une activation ne réussit qu'une fois le CLI réellement debout : un CLI
qui sort juste après son lancement (doublure `fail-start`) fait échouer
l'activation, donc la bascule de Core (502 `board_activation_failed`, rien de
validé). Le processus est **réel** (un petit script Python lancé à la place de
`claude`), seul l'exécutable est remplacé.

A2 — après un redémarrage de Core (Session neuve), les entrées du pool liées à
l'ancienne Session sont closes (et oubliées si elles sont suspendues) : le bloc
`boards.bindings` de `/api/status` ne les montre plus comme ouvertes.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
import textwrap
from pathlib import Path

import pytest

from jarvis.domain.workspace_board import DEFAULT_BOARD_ID, BrainLifecycle, new_session_id
from jarvis.runtime import claude_local
from jarvis.runtime.claude_local import ClaudeLocalAgent
from tests.unit.test_board_brains import binding as pool_binding, make_pool, start_subagent
from tests.unit.test_board_brains_control_center import trace
from tests.unit.test_board_switch_control_center import Stack

STUB = textwrap.dedent('''
    """Doublure du CLI Claude en stream-json ; le mode est lu dans un fichier drapeau."""
    import json, os, sys, uuid
    flag = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stub-mode")
    mode = open(flag, encoding="utf-8").read().strip() if os.path.exists(flag) else "init"
    argv = sys.argv[1:]
    resumed = argv[argv.index("--resume") + 1] if "--resume" in argv else None
    with open(os.path.join(os.path.dirname(flag), "stub-spawns.log"), "a", encoding="utf-8") as log:
        log.write(json.dumps({"resume": resumed}) + "\\n")
    if mode == "fail-start":
        sys.stderr.write("stub: injected start failure\\n"); sys.stderr.flush(); sys.exit(3)
    if mode == "fail-resume" and resumed:
        sys.stderr.write("No conversation found with session ID: %s\\n" % resumed); sys.stderr.flush(); sys.exit(1)
    sid = resumed or str(uuid.uuid4())
    if mode == "fail-resume":
        mode = "init"  # sans --resume : un démarrage neuf ordinaire
    if mode == "init":
        sys.stdout.write(json.dumps({"type": "system", "subtype": "init", "session_id": sid}) + "\\n")
        sys.stdout.flush()
    for line in sys.stdin:
        sys.stdout.write(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                                     "result": "ok", "session_id": sid}) + "\\n")
        sys.stdout.flush()
''')


class RealStub:
    """`claude` remplacé par un vrai processus Python (le script ci-dessus)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.script = root / "stub_claude.py"
        self.script.write_text(STUB, encoding="utf-8")

    def mode(self, value: str) -> None:
        (self.root / "stub-mode").write_text(value, encoding="utf-8")

    def spawns(self) -> list[dict]:
        """Un enregistrement par lancement : `{"resume": <id ou None>}`."""

        log = self.root / "stub-spawns.log"
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []

    def spawner(self):  # noqa: ANN201
        real = asyncio.create_subprocess_exec
        script = str(self.script)

        async def spawn(executable, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            del executable
            kept = {k: v for k, v in kwargs.items() if k in {"stdin", "stdout", "stderr", "cwd", "env"}}
            return await real(sys.executable, script, *args, **kept)

        return spawn


@pytest.fixture
def stub(tmp_path, monkeypatch) -> RealStub:
    stub = RealStub(tmp_path)
    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", stub.spawner())
    return stub


def real_agent(root: Path) -> ClaudeLocalAgent:
    return ClaudeLocalAgent(runtime_root=root, cwd=root)


# ------------------------------------------------------------------ A1 : l'agent


async def test_a1_a_cli_that_exits_at_start_is_not_ready_and_says_why(tmp_path, stub):
    stub.mode("fail-start")
    agent = real_agent(tmp_path)
    await agent.start(resume=False)
    with pytest.raises(RuntimeError) as failed:
        await agent.wait_ready(settle_s=10.0)
    assert "code 3" in str(failed.value) and "injected start failure" in str(failed.value)
    await agent.stop()


async def test_a1_an_init_event_makes_the_cli_ready_without_waiting_the_window(tmp_path, stub):
    stub.mode("init")
    agent = real_agent(tmp_path)
    await agent.start(resume=False)
    loop = asyncio.get_running_loop()
    began = loop.time()
    await agent.wait_ready(settle_s=30.0)
    assert loop.time() - began < 15.0, "init ends the wait, not the 30 s window"
    ready = trace(tmp_path, "agent.ready")[-1]["data"]
    assert ready["signal"] == "init"
    await agent.stop()


async def test_a1_a_silent_live_cli_is_ready_at_the_end_of_the_window(tmp_path, stub):
    """Le vrai CLI n'écrit rien avant sa première entrée : vivant au bout de la fenêtre = prêt."""

    stub.mode("silent")
    agent = real_agent(tmp_path)
    await agent.start(resume=False)
    await agent.wait_ready(settle_s=0.3)
    assert agent.state == "running"
    assert trace(tmp_path, "agent.ready")[-1]["data"]["signal"] == "settled"
    await agent.stop()


# ------------------------------------------------------------------ A1 : le pool


async def test_a1_the_pool_refuses_an_activation_whose_cli_exits_at_start(tmp_path, stub):
    pool = make_pool(tmp_path, factory=lambda cli: real_agent(tmp_path), ready_settle_s=10.0)
    stub.mode("init")
    first = await pool.activate(pool_binding("conv-a"))
    assert first.agent.state == "running"

    stub.mode("fail-start")
    with pytest.raises(RuntimeError, match="injected start failure"):
        await pool.activate(pool_binding("conv-b"))

    assert pool.foreground is first and first.agent.state == "running", "nothing changed"
    assert pool.find("conv-b") is None, "the created entry is forgotten"
    stopped = trace(tmp_path, "agent.stop")[-1]["data"]
    assert stopped["reason"] == "start_failed"
    await pool.aclose()


# ------------------------------------------------------------------ A1 : bout en bout par Core


@pytest.fixture
async def stack(tmp_path):
    stack = Stack(tmp_path)
    await stack.serve_control()
    try:
        yield stack
    finally:
        await stack.close()


async def test_a1_a_switch_whose_cli_exits_at_start_is_502_and_commits_nothing(stack, stub):
    core = await stack.start_core()
    before = await core.sessions.current()
    foreground = stack.control.board_brains.foreground
    pool = stack.control.board_brains
    pool._factory = lambda cli: real_agent(stack.tmp_path)
    pool.ready_settle_s = 5.0
    _, created = await stack.call("POST", "/api/boards", json={"title": "Projet B"})
    board_b = created["board"]["board_id"]

    stub.mode("fail-start")
    status, refused = await stack.call("POST", "/api/boards/switch", json={"board_id": board_b})

    assert status == 502 and refused["error"]["code"] == "board_activation_failed"
    assert "injected start failure" in refused["error"]["message"]
    after = await core.sessions.current()
    assert after.session == before.session and after.binding.conversation_id == before.binding.conversation_id
    assert (await stack.call("GET", "/api/boards/active"))[1]["board"]["board_id"] == DEFAULT_BOARD_ID
    assert core.speech_authority.conversation_id == before.binding.conversation_id
    assert pool.foreground is foreground and all(e.board_id != board_b for e in pool.entries())
    assert trace(stack.tmp_path, "board_brain.activation_failed")[-1]["level"] == "error"

    stub.mode("init")                                          # le CLI réparé : la même bascule passe
    status, switched = await stack.call("POST", "/api/boards/switch", json={"board_id": board_b})
    assert status == 200 and pool.foreground.board_id == board_b


# ------------------------------------------------------------------ A2


async def test_a2_activating_a_new_session_closes_every_entry_of_the_old_one(tmp_path):
    pool = make_pool(tmp_path)
    await pool.activate(pool_binding("conv-a"))
    b = await pool.activate(pool_binding("conv-b"))
    start_subagent(b.agent, "t-long")                         # B travaille
    await pool.activate(pool_binding("conv-c"))               # B en fond, A suspendu
    assert pool.find("conv-a").lifecycle is BrainLifecycle.SUSPENDED
    assert pool.find("conv-b").lifecycle is BrainLifecycle.BACKGROUND_RUNNING

    fresh = dataclasses.replace(pool_binding("conv-new"), jarvis_session_id=new_session_id())
    await pool.activate(fresh)                                # Core redémarré : Session neuve

    assert pool.find("conv-a") is None, "suspended entry of the closed Session forgotten"
    assert pool.find("conv-c") is None, "previous foreground (idle) forgotten"
    working = pool.find("conv-b")
    assert working is not None and working.closed and working.lifecycle is BrainLifecycle.BACKGROUND_RUNNING
    assert {row["conversation_id"]: row["closed"] for row in pool.snapshot()} == {"conv-b": True, "conv-new": False}
    await pool.aclose()


async def _bindings(control) -> list[dict]:
    return json.loads((await control.status(None)).text)["boards"]["bindings"]


async def test_a2_after_a_new_session_the_status_shows_no_open_binding_of_the_old_session(stack):
    await stack.start_core()
    _, created = await stack.call("POST", "/api/boards", json={"title": "Projet B"})
    board_b = created["board"]["board_id"]
    assert (await stack.call("POST", "/api/boards/switch", json={"board_id": board_b}))[0] == 200
    stack.control.board_brains.foreground.agent.start_subagent("t1")          # B travaille encore
    assert (await stack.call("POST", "/api/boards/switch", json={"board_id": DEFAULT_BOARD_ID}))[0] == 200
    rows = await _bindings(stack.control)
    assert {(r["board_id"], r["lifecycle"], r["closed"]) for r in rows} == {
        (DEFAULT_BOARD_ID, "foreground", False), (board_b, "background_running", False)}

    await stack.stop_core()
    core = await stack.start_core()                                           # même Session, reprise
    # Slice 03 (session-context, D02) : un redémarrage n'est plus une frontière
    # de Session ; rien n'est clos, B finit son travail en arrière-plan.
    rows = await _bindings(stack.control)
    assert {(r["board_id"], r["lifecycle"], r["closed"]) for r in rows} == {
        (DEFAULT_BOARD_ID, "foreground", False), (board_b, "background_running", False)}

    assert (await stack.call("POST", "/api/sessions/new", json={}))[0] == 201  # la seule frontière
    current = await core.sessions.current()
    rows = await _bindings(stack.control)
    open_rows = [r for r in rows if not r["closed"]]
    assert open_rows == [{"board_id": current.binding.board_id, "lifecycle": "foreground",
                          "agent_cli": open_rows[0]["agent_cli"], "closed": False}]
    assert [(r["board_id"], r["lifecycle"]) for r in rows if r["closed"]] == [(board_b, "background_running")]
