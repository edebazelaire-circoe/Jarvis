"""Le panneau Agents projette l'état de travail de Core (handoff work-state, tâche 13).

Ce qui doit tenir :

- `GET /api/work` rend l'instantané normalisé de Core, et rien d'autre : les
  mêmes faits que le contexte du cerveau (même `store_id`, même révision) ;
- une lecture plus ancienne que l'état servi ne le rembobine pas ; un autre
  `store_id` (Core redémarré) remplace tout ;
- la route est en lecture seule ; aucune route du Control Center n'écrit
  l'état de travail ;
- Core indisponible : dit tel quel, sans éléments ; `/api/agent/tasks` reste
  servi, comme diagnostic ;
- la trace brute se retrouve depuis l'`external_id` d'un travail Core ;
- Codex, sans sous-tâches vérifiées, donne un état vide propre.

Les règles pures de la page (garde de révision, durées, projection d'une
carte) sont prouvées en exécutant `control_center_work.js` avec node — le
fichier même que `ControlCenter.index` insère dans la page servie — et non en
relisant sa source.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import time
from typing import Any

from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.core.work_state import WorkStateStore
from jarvis.domain.brain_context import build_brain_work_context
from jarvis.domain.work_state import WorkObservation, WorkStatus
from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime.claude_local import ClaudeLocalAgent
from jarvis.runtime.control_center import WORK_SCRIPT_MARKER, ControlCenter
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.work_ingress import TrackerWorkObserver, WorkIngressForwarder
from jarvis.runtime.work_view import (
    CORE_REFUSED,
    CORE_UNREACHABLE,
    INVALID_SNAPSHOT,
    NOT_CONFIGURED,
    CoreWorkView,
    accept_snapshot,
)

CONTROL_CENTER_HTML = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center.html"
WORK_JS = CONTROL_CENTER_HTML.with_name("control_center_work.js")
SESSION = "ac329510-db70-42d4-84ac-5fddd9b11c0d"
T0 = 1_789_047_300.0
BASE = datetime(2026, 9, 11, 15, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------- outils


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class StoreReader:
    """Ce que `CoreWorkTransport.snapshot()` rend : la réponse de `GET /v1/work/snapshot`."""

    def __init__(self, store: WorkStateStore) -> None:
        self.store = store
        self.calls = 0

    async def snapshot(self) -> dict[str, Any]:
        self.calls += 1
        return {"store_id": self.store.store_id, **self.store.current_snapshot().to_payload()}

    async def close(self) -> None:
        pass


class ScriptedReader:
    """Rend, dans l'ordre, les réponses ou exceptions prévues."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.closed = False

    async def snapshot(self) -> dict[str, Any]:
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            return await answer()
        return answer

    async def close(self) -> None:
        self.closed = True


def observation(key: str, status: WorkStatus, t: float, **fields: Any) -> WorkObservation:
    return WorkObservation(source="claude", external_id=key, status=status, observed_at=BASE + timedelta(seconds=t), **fields)


async def populated_store() -> WorkStateStore:
    store = WorkStateStore()
    await store.apply(observation("toolu_A", WorkStatus.RUNNING, 0, kind="agent", label="Analyse du dépôt", activity="Read · app.py", model="claude-sonnet-5"))
    await store.apply(observation("toolu_B", WorkStatus.RUNNING, 5, kind="agent", label="Recherche web", model="claude-haiku-4-5"))
    await store.apply(observation("toolu_B", WorkStatus.FAILED, 65, error_class="timeout", summary="Délai dépassé."))
    await store.apply(observation("toolu_C", WorkStatus.RUNNING, 10, kind="agent", label="Relecture"))
    await store.apply(observation("toolu_C", WorkStatus.COMPLETED, 40, summary="Relecture faite, 2 remarques."))
    await store.apply(
        WorkObservation(source="job", external_id="job-1", status=WorkStatus.RUNNING, observed_at=BASE + timedelta(seconds=20), kind="job", label="calendar_sync")
    )
    return store


def snapshot_payload(store_id: str, revision: int, *items: dict) -> dict:
    return {"store_id": store_id, "revision": revision, "items": list(items), "updated_at": BASE.isoformat()}


def item_payload(key: str, status: str, revision: int, **fields: Any) -> dict:
    terminal = status in {"completed", "failed", "cancelled", "interrupted"}
    return {
        "source": "claude", "external_id": key, "status": status, "revision": revision,
        "started_at": BASE.isoformat(), "updated_at": (BASE + timedelta(seconds=30)).isoformat(),
        "ended_at": (BASE + timedelta(seconds=30)).isoformat() if terminal else None, **fields,
    }


def control_with(tmp_path: Path, reader: Any = None, *, ingress: bool = True, clock: Clock | None = None) -> ControlCenter:
    view = CoreWorkView(reader) if reader is not None else None
    forwarder = WorkIngressForwarder(source="claude", transport=_NoTransport()) if ingress else None
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, work_ingress=forwarder, work_view=view)
    if clock is not None:
        control.agent.subtasks.clock = clock
    return control


class _NoTransport:
    async def post(self, batch):  # noqa: ANN001
        raise ConnectionError("pas de Core dans ce test")

    async def close(self) -> None:
        pass


async def get_work(control: ControlCenter) -> dict:
    return json.loads((await control.work(None)).text)  # type: ignore[arg-type]


def feed(agent: ClaudeLocalAgent, *events: dict) -> None:
    for event in events:
        agent._record(event)


def agent_call(tool_use_id: str, description: str) -> dict:
    return {
        "type": "assistant", "parent_tool_use_id": None, "session_id": SESSION,
        "message": {"model": "claude-opus-5", "role": "assistant", "content": [
            {"type": "tool_use", "id": tool_use_id, "name": "Agent",
             "input": {"description": description, "prompt": "Prompt secret du sous-agent.", "run_in_background": True}},
        ]},
    }


def task_started(task_id: str, tool_use_id: str | None, description: str) -> dict:
    event = {
        "type": "system", "subtype": "task_started", "task_id": task_id, "description": description,
        "is_backgrounded": True, "task_type": "local_agent", "subagent_type": "general-purpose",
        "prompt": "Prompt secret du sous-agent.", "session_id": SESSION,
    }
    if tool_use_id is not None:
        event["tool_use_id"] = tool_use_id
    return event


def notification(task_id: str, tool_use_id: str, status: str, summary: str = "") -> dict:
    return {
        "type": "system", "subtype": "task_notification", "task_id": task_id, "tool_use_id": tool_use_id,
        "status": status, "summary": summary, "session_id": SESSION,
    }


class FakeRequest:
    def __init__(self, task_id: str = "", **query: str) -> None:
        self.match_info = {"task_id": task_id}
        self.query = query


# ============================================================ garde de révision


@pytest.mark.parametrize(
    "held, store_id, revision, accepted",
    [
        (None, "s1", 0, True),  # premier instantané
        (("s1", 5), "s1", 6, True),  # progrès
        (("s1", 5), "s1", 5, True),  # même état
        (("s1", 5), "s1", 4, False),  # réponse périmée : ne rembobine pas
        (("s1", 5), "s2", 1, True),  # Core redémarré : tout est remplacé
    ],
)
def test_the_revision_guard(held, store_id, revision, accepted):
    assert accept_snapshot(held, store_id, revision) is accepted


async def test_a_stale_snapshot_never_rewinds_the_served_state():
    reader = ScriptedReader(
        snapshot_payload("s1", 3, item_payload("toolu_A", "completed", 3, summary="Fini.")),
        snapshot_payload("s1", 2, item_payload("toolu_A", "running", 2, activity="Read · x.py")),
    )
    view = CoreWorkView(reader)

    first = await view.read()
    late = await view.read()

    assert first["revision"] == 3 and first["stale"] is False
    assert late["revision"] == 3 and late["stale"] is True
    assert late["items"] == first["items"]
    assert late["items"][0]["status"] == "completed"
    assert view.held == ("s1", 3)


async def test_concurrent_reads_answering_out_of_order_keep_the_newest():
    release_old = asyncio.Event()

    async def old() -> dict:
        await release_old.wait()
        return snapshot_payload("s1", 1, item_payload("toolu_A", "running", 1))

    async def new() -> dict:
        return snapshot_payload("s1", 2, item_payload("toolu_A", "completed", 2))

    view = CoreWorkView(ScriptedReader(old, new))
    slow = asyncio.create_task(view.read())
    await asyncio.sleep(0)
    fresh = await view.read()
    release_old.set()
    late = await slow

    assert fresh["revision"] == 2
    assert late["revision"] == 2 and late["stale"] is True
    assert late["items"][0]["status"] == "completed"


async def test_a_new_store_id_replaces_everything_even_at_a_lower_revision():
    view = CoreWorkView(ScriptedReader(
        snapshot_payload("s1", 9, item_payload("toolu_A", "running", 9)),
        snapshot_payload("s2", 1, item_payload("toolu_Z", "running", 1)),
    ))

    await view.read()
    restarted = await view.read()

    assert (restarted["store_id"], restarted["revision"], restarted["stale"]) == ("s2", 1, False)
    assert [item["external_id"] for item in restarted["items"]] == ["toolu_Z"]


async def test_only_declared_work_fields_reach_the_ui():
    leaky = item_payload("toolu_A", "running", 1, label="Analyse", raw={"prompt": "secret"}, prompt="secret", subagent_type="Explore")
    view = CoreWorkView(ScriptedReader(snapshot_payload("s1", 1, leaky)))

    body = await view.read()

    text = json.dumps(body, ensure_ascii=False)
    assert "secret" not in text and "Explore" not in text
    assert body["items"][0]["label"] == "Analyse"


# ============================================================ Core indisponible


@pytest.mark.parametrize(
    "failure, code",
    [
        (ConnectionError("Core session token is unavailable; is `jarvis core` running?"), CORE_UNREACHABLE),
        (OSError("connexion refusée"), CORE_UNREACHABLE),
        (CoreProtocolError(401, "unauthorized", "invalid local session credential"), CORE_REFUSED),
        ({"revision": 1, "items": []}, INVALID_SNAPSHOT),  # pas de store_id
        ({"store_id": "s1", "revision": "trois", "items": []}, INVALID_SNAPSHOT),
    ],
)
async def test_an_unreadable_core_is_reported_as_unavailable_without_items(failure, code):
    body = await CoreWorkView(ScriptedReader(failure)).read()

    assert body["source"] == "core"
    assert body["core_reachable"] is False
    assert body["items"] == [] and body["store_id"] is None and body["revision"] is None
    assert body["error"]["code"] == code and body["error"]["message"]


async def test_a_hanging_core_times_out_instead_of_piling_up_requests():
    async def hang() -> dict:
        await asyncio.sleep(30)
        return {}

    body = await CoreWorkView(ScriptedReader(hang), timeout_s=0.05).read()

    assert body["core_reachable"] is False and body["error"]["code"] == CORE_UNREACHABLE


async def test_an_invalid_snapshot_is_journaled_once_per_error_type(tmp_path):
    from jarvis.runtime.journal import RuntimeJournal

    journal = RuntimeJournal(tmp_path)
    view = CoreWorkView(ScriptedReader({"revision": 1}, {"revision": 2}), journal=journal)

    await view.read()
    await view.read()

    reported = [entry for entry in read_jsonl_tail(journal.trace_path, limit=50) if entry["kind"] == "work.view_invalid_snapshot"]
    assert len(reported) == 1


async def test_core_coming_back_keeps_the_revision_guard():
    view = CoreWorkView(ScriptedReader(
        snapshot_payload("s1", 4, item_payload("toolu_A", "completed", 4)),
        ConnectionError("Core arrêté"),
        snapshot_payload("s1", 3, item_payload("toolu_A", "running", 3)),
    ))

    await view.read()
    down = await view.read()
    back = await view.read()

    assert down["core_reachable"] is False
    assert back["revision"] == 4 and back["stale"] is True


# ============================================================ route du Control Center


async def test_the_route_without_a_core_reader_says_so(tmp_path):
    body = await get_work(control_with(tmp_path))

    assert body["core_reachable"] is False and body["error"]["code"] == NOT_CONFIGURED
    assert body["items"] == []


async def test_the_route_projects_core_and_says_whether_subtasks_are_relayed(tmp_path):
    clock = Clock()
    store = await populated_store()
    control = control_with(tmp_path, StoreReader(store), clock=clock)

    body = await get_work(control)

    assert body["source"] == "core" and body["core_reachable"] is True
    assert body["store_id"] == store.store_id and body["revision"] == store.revision
    assert body["now_ms"] == int(T0 * 1000)
    assert body["agent_cli"] == "claude" and body["subtasks_supported"] is True
    assert [item["external_id"] for item in body["items"]] == [item.external_id for item in store.current_snapshot().items]

    unrelayed = await get_work(control_with(tmp_path / "sans-relais", StoreReader(store), ingress=False))
    assert unrelayed["subtasks_supported"] is False


async def test_reading_the_route_never_builds_an_agent(tmp_path):
    """Une route de lecture ne construit rien.

    Construire l'agent abonne un observateur de plus au suivi et reprend
    `work_ingress.on_resync` : un effet de bord qu'une lecture n'a pas à
    produire. Sans agent bâti, la route se contente de l'horloge du processus.
    """
    store = await populated_store()
    forwarder = WorkIngressForwarder(source="claude", transport=_NoTransport())
    control = ControlCenter(
        runtime_root=tmp_path, project_root=tmp_path, work_ingress=forwarder, work_view=CoreWorkView(StoreReader(store))
    )
    control._agents.clear()  # Control Center dont l'agent n'est pas (ou plus) bâti
    forwarder.on_resync = None
    before = int(time.time() * 1000)

    body = await get_work(control)

    assert control._agents == {} and forwarder.on_resync is None
    assert body["core_reachable"] is True and body["agent_cli"] == "claude"
    # L'horloge du processus est celle-là même que porte le suivi de l'agent.
    assert before <= body["now_ms"] <= int(time.time() * 1000)
    # L'agent construit par ailleurs reste, lui, celui qui relaie à Core, et
    # c'est son horloge que la route rend alors.
    control.agent.subtasks.clock = Clock()
    assert forwarder.on_resync is not None
    assert (await get_work(control))["now_ms"] == int(T0 * 1000)


async def test_the_ui_and_the_brain_read_the_same_facts(tmp_path):
    store = await populated_store()
    control = control_with(tmp_path, StoreReader(store))
    now = BASE + timedelta(seconds=120)

    ui = await get_work(control)
    brain = build_brain_work_context(store.current_snapshot(), now=now, store_id=store.store_id)

    assert (ui["store_id"], ui["revision"]) == (brain.store_id, brain.revision)
    shown = {(item["source"], item["external_id"]): item for item in ui["items"]}
    assert len(brain.items) == len(shown) == 4
    for entry in brain.items:
        item = shown[(entry.source, entry.external_id)]
        assert item["status"] == entry.status.value
        assert item["label"] == entry.label and item["activity"] == entry.activity and item["model"] == entry.model
        assert item["summary"] == entry.summary and item["error_class"] == entry.error_class
        assert item["work_id"] == entry.work_id and item["parent_external_id"] == entry.parent_external_id
        assert datetime.fromisoformat(item["started_at"]) == entry.started_at
        ended = datetime.fromisoformat(item["ended_at"]) if item["ended_at"] else None
        assert ended == entry.ended_at
        # La durée affichée se déduit des seules dates faisant foi, comme celle du cerveau.
        elapsed = ((ended or now) - datetime.fromisoformat(item["started_at"])).total_seconds()
        assert int(elapsed) == entry.elapsed_s


async def test_completed_and_failed_work_carry_their_end_and_error_class(tmp_path):
    store = await populated_store()
    body = await get_work(control_with(tmp_path, StoreReader(store)))

    items = {item["external_id"]: item for item in body["items"]}
    failed, done, running = items["toolu_B"], items["toolu_C"], items["toolu_A"]
    assert failed["status"] == "failed" and failed["error_class"] == "timeout" and failed["ended_at"]
    assert done["status"] == "completed" and done["error_class"] is None and done["summary"] == "Relecture faite, 2 remarques."
    assert running["status"] == "running" and running["ended_at"] is None and running["activity"] == "Read · app.py"
    # Finis : du plus récent au plus ancien, après les actifs (ordre de Core, repris tel quel).
    assert [item["external_id"] for item in body["items"]] == ["toolu_A", "job-1", "toolu_B", "toolu_C"]


async def test_the_ui_can_never_write_work_state(tmp_path):
    store = await populated_store()
    reader = StoreReader(store)
    control = control_with(tmp_path, reader)
    revision = store.revision

    work_routes = [route for route in control._app.router.routes() if route.resource.canonical.startswith("/api/work")]
    assert {route.method for route in work_routes} <= {"GET", "HEAD"}
    assert not any("observation" in route.resource.canonical for route in control._app.router.routes())
    async with TestClient(TestServer(control._app)) as client:
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            response = await client.request(method, "/api/work", json={"items": []})
            assert response.status == 405
        assert (await client.get("/api/work")).status == 200

    assert store.revision == revision  # lire ne change rien
    assert not hasattr(control.work_view, "observe") and not hasattr(control.work_view, "ingest")


async def test_core_unavailable_keeps_the_diagnostic_route_alive(tmp_path):
    clock = Clock()
    control = control_with(tmp_path, ScriptedReader(ConnectionError("Core arrêté")), clock=clock)
    feed(control.agent, agent_call("toolu_A", "Persist"), task_started("a1", "toolu_A", "Persist"))

    body = await get_work(control)
    tasks = json.loads((await control.agent_tasks(None)).text)  # type: ignore[arg-type]

    assert body["core_reachable"] is False and body["items"] == []
    assert body["error"]["code"] == CORE_UNREACHABLE
    assert [task["id"] for task in tasks["tasks"]] == ["a1"]  # compatibilité : toujours servi


async def test_codex_degrades_to_a_clean_empty_state(tmp_path):
    (tmp_path / "control-center-settings.json").write_text(json.dumps({"agent_cli": "codex"}), encoding="utf-8")
    control = control_with(tmp_path, StoreReader(WorkStateStore()))

    body = await get_work(control)

    assert body["core_reachable"] is True and body["items"] == []
    assert body["agent_cli"] == "codex" and body["subtasks_supported"] is False


# ============================================================ trace de diagnostic


async def test_the_raw_trace_is_found_from_the_core_external_id(tmp_path):
    clock = Clock()
    control = control_with(tmp_path, ingress=False, clock=clock)
    store = WorkStateStore()
    observations: list[WorkObservation] = []
    observer = TrackerWorkObserver(control.agent.subtasks, observations.append)
    control.agent.subtasks.subscribe(observer.sync)
    control.work_view = CoreWorkView(StoreReader(store))

    feed(control.agent, agent_call("toolu_A", "Persist"))
    clock.advance(2)
    feed(control.agent, task_started("a1", "toolu_A", "Persist"), agent_call("toolu_B", "Tests"))
    clock.advance(30)
    feed(control.agent, task_started("b1", "toolu_B", "Tests"), notification("b1", "toolu_B", "completed", "Verts."))
    for item in observations:
        await store.apply(item)

    body = await get_work(control)
    diagnostic = json.loads((await control.agent_tasks(None)).text)["tasks"]  # type: ignore[arg-type]

    assert {item["external_id"] for item in body["items"]} == {"toolu_A", "toolu_B"}
    # La jointure du panneau : `work_key` du diagnostic = `external_id` de Core.
    assert {task["work_key"] for task in diagnostic} == {"toolu_A", "toolu_B"}
    for item in body["items"]:
        trace = await control.agent_task_trace(FakeRequest(item["external_id"]))
        assert trace.status == 200
        payload = json.loads(trace.text)
        assert payload["task"]["work_key"] == item["external_id"]
        assert payload["entries"]  # la trace brute reste là, pour le diagnostic
    # L'identifiant public a changé (tool_use_id → task_id) ; Core garde le premier.
    assert {task["id"] for task in diagnostic} == {"a1", "b1"}


def test_the_tracker_finds_a_task_by_its_work_key_as_a_last_resort(tmp_path):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude")
    feed(agent, task_started("a1", "toolu_A", "Persist"))
    [task] = agent.subtasks.tasks()
    task.work_key = "toolu_OLD"  # une fusion peut laisser une clé étrangère aux deux identifiants

    assert agent.subtasks.find("toolu_OLD") is task
    assert agent.subtasks.find("a1") is task and agent.subtasks.find("toolu_A") is task
    assert agent.subtasks.find("inconnu") is None and agent.subtasks.find("") is None


# ============================================================ page


def html() -> str:
    return CONTROL_CENTER_HTML.read_text(encoding="utf-8")


def test_the_panel_reads_core_and_keeps_the_trace_as_diagnostic():
    page = html()

    assert "api('/api/work')" in page
    assert "api('/api/agent/tasks')" in page  # diagnostic joint, toujours lu
    assert "/api/agent/tasks/${encodeURIComponent(tr.id)}/trace" in page
    assert "diag.set(`${t.provider}|${t.work_key}`,t)" in page  # jointure par work_key = external_id
    # Libellés : état normalisé Core d'un côté, trace brute du fournisseur de l'autre.
    assert "Source : état normalisé Core" in page
    assert "État normalisé · Core (fait foi)" in page
    assert "Trace brute du fournisseur · diagnostic" in page
    assert "Diagnostic fournisseur · brut, non autoritaire" in page


def test_the_panel_never_writes_work_state():
    page = html() + WORK_JS.read_text(encoding="utf-8")

    for call in re.findall(r"api\('/api/work'[^)]*\)", page):
        assert call == "api('/api/work')"
    assert "/v1/work" not in page


async def test_the_pure_logic_is_a_file_the_page_and_the_tests_load_alike(tmp_path):
    """La page sert ce fichier-ci : ce que node exécute est ce que le navigateur reçoit."""

    assert WORK_SCRIPT_MARKER in html()

    served = (await ControlCenter(runtime_root=tmp_path, project_root=tmp_path).index(None)).text

    assert WORK_SCRIPT_MARKER not in served
    assert WORK_JS.read_text(encoding="utf-8") in served
    assert "function acceptWork(held,next){" in served


# --- règles pures, exécutées (node) -----------------------------------------


def test_the_panel_guards_revisions_like_the_server(page_logic):
    cases = [(None, "s1", 0), (("s1", 5), "s1", 6), (("s1", 5), "s1", 5), (("s1", 5), "s1", 4), (("s1", 5), "s2", 1)]
    payload = [
        {"held": None if held is None else {"store_id": held[0], "revision": held[1]},
         "next": {"store_id": store_id, "revision": revision}}
        for held, store_id, revision in cases
    ]

    accepted = page_logic(f"return {json.dumps(payload)}.map(c=>W.acceptWork(c.held,c.next))")

    # Même verdict que `accept_snapshot`, la règle du serveur, cas pour cas.
    assert accepted == [accept_snapshot(held, store_id, revision) for held, store_id, revision in cases]


def test_a_stale_or_unreadable_snapshot_never_replaces_the_held_one(page_logic):
    verdicts = page_logic("""
      const held={store_id:'s1',revision:5};
      return {
        stale:W.acceptWork(held,{store_id:'s1',revision:4}),
        same:W.acceptWork(held,{store_id:'s1',revision:5}),
        newer:W.acceptWork(held,{store_id:'s1',revision:6}),
        restarted:W.acceptWork(held,{store_id:'s2',revision:1}),
        first:W.acceptWork(null,{store_id:'s1',revision:0}),
        nothing:W.acceptWork(held,null),
        noStore:W.acceptWork(held,{revision:9}),
        textRevision:W.acceptWork(held,{store_id:'s1',revision:'9'}),
      };
    """)

    assert verdicts == {
        "stale": False, "same": True, "newer": True, "restarted": True,
        "first": True, "nothing": False, "noStore": False, "textRevision": False,
    }


def test_elapsed_time_comes_from_core_dates_and_the_skew_corrected_clock(page_logic):
    started_ms = int(BASE.timestamp() * 1000)
    skew_ms = 5_000  # l'horloge du serveur avance de 5 s sur celle du navigateur
    sent_at, received_at = started_ms - 1_000, started_ms + 1_000
    server_now = started_ms + skew_ms  # réponse datée au milieu de l'aller-retour
    local_now = started_ms + 40_000  # 45 s d'heure serveur après le départ

    measured = page_logic(f"""
      const skew=W.clockSkew({server_now},{sent_at},{received_at});
      const now={local_now}+skew;
      const card=item=>W.coreTask(item,null);
      return {{
        skew,
        noClock:W.clockSkew('bientôt',{sent_at},{received_at}),
        running:W.taskElapsed(card({json.dumps(item_payload("toolu_A", "running", 1))}),now),
        done:W.taskElapsed(card({json.dumps(item_payload("toolu_B", "completed", 2))}),now),
        endedWithoutDate:W.taskElapsed(card({json.dumps(item_payload("toolu_C", "completed", 3, ended_at=None))}),now),
        neverStarted:W.taskElapsed(card({json.dumps(item_payload("toolu_D", "pending", 1, started_at=None))}),now),
        clockBehind:W.taskElapsed(card({json.dumps(item_payload("toolu_E", "running", 1))}),{started_ms}-9_000),
      }};
    """)

    assert measured["skew"] == skew_ms and measured["noClock"] is None
    # En cours : depuis `started_at`, à l'heure du serveur (40 s locales + 5 s de décalage).
    assert measured["running"] == 45_000
    # Terminé : durée figée par `ended_at`, indifférente à l'heure courante.
    assert measured["done"] == 30_000
    # Aucune durée inventée : ni pour un terminal sans date de fin, ni sans début.
    assert measured["endedWithoutDate"] is None and measured["neverStarted"] is None
    # Une horloge locale en retard ne rend jamais une durée négative.
    assert measured["clockBehind"] == 0


def test_only_core_s_non_terminal_statuses_tick(page_logic):
    statuses = [status.value for status in WorkStatus]

    running = page_logic(f"return {json.dumps(statuses)}.map(s=>W.isRunning({{status:s}}))")

    assert running == [not WorkStatus(status).is_terminal for status in statuses]
    assert page_logic("return [W.isRunning(null),W.isRunning({status:'inconnu'})]") == [False, False]


def test_a_card_takes_its_state_from_core_and_only_diagnostics_from_the_tracker(page_logic):
    item = item_payload("toolu_A", "completed", 7, kind="agent", label="Analyse du dépôt", summary="Fait.", model="claude-sonnet-5")
    diagnostic = {
        "id": "a1", "provider": "claude", "work_key": "toolu_A", "kind": "agent",
        "status": "running", "description": "Libellé périmé", "summary": "", "model": "claude-haiku-4-5",
        "prompt": "Prompt du sous-agent.", "subagent_type": "Explore", "tool_use_id": "toolu_A",
    }

    card = page_logic(f"return W.coreTask({json.dumps(item)},{json.dumps(diagnostic)})")

    # L'état vient de Core et de lui seul : aucun automate concurrent dans la page.
    assert (card["status"], card["description"], card["summary"], card["model"]) == (
        "completed", "Analyse du dépôt", "Fait.", "claude-sonnet-5")
    assert card["started_ms"] == int(BASE.timestamp() * 1000)
    assert card["ended_ms"] == int((BASE + timedelta(seconds=30)).timestamp() * 1000)
    assert (card["id"], card["core"], card["diag"], card["provider_id"]) == ("toolu_A", True, True, "a1")
    # Le diagnostic n'apporte que ce que Core ne porte pas.
    assert (card["prompt"], card["subagent_type"]) == ("Prompt du sous-agent.", "Explore")
    # Sans diagnostic, la carte tient debout seule.
    assert page_logic(f"const c=W.coreTask({json.dumps(item)},undefined);return [c.diag,c.provider_id,c.prompt===undefined]") == [
        False, "", True]


def test_every_core_status_has_a_display():
    page = html()

    for status in WorkStatus:
        assert f"  {status.value}:{{cls:" in page, status


def test_degraded_and_empty_states_are_explicit():
    page = html()

    assert "Affichage dégradé : projection locale du Control Center (suivi du fournisseur), non autoritaire" in page
    assert "Core indisponible : ${c.error}" in page
    assert "Aucun sous-agent suivi pour ce CLI." in page
    assert "Autres travaux Core" in page
