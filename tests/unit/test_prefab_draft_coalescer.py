"""Brouillons coalescés (Slice 01a) : une rafale de retouches de source publie UNE version, sans rien ajouter aux
règles de la bibliothèque. Contrat : `docs/prefabs.md` › *Retention of studio scene sources* (coalescence).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from jarvis.adapters.file_prefab_library import LIBRARY_DIR, FilePrefabLibrary
from jarvis.core.prefab_draft_coalescer import PrefabDraftCoalescer
from jarvis.core.prefab_service import PrefabService
from jarvis.domain.prefab import PrefabRef
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode
from tests.fakes.prefabs import candidate, install_version

SCENE = "presentation-studio.scene1"
QUIET, MAX_WAIT = 0.15, 0.6


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.events.append((kind, dict(data or {})))


@pytest.fixture
def setup(tmp_path: Path):
    package, data = tmp_path / "package", tmp_path / "data"
    package.mkdir()
    data.mkdir()
    install_version(package, "jarvis.counter")
    recorder = Recorder()
    service = PrefabService(FilePrefabLibrary(package, data),
                            clock=lambda: datetime(2026, 11, 1, tzinfo=timezone.utc))
    return service, PrefabDraftCoalescer(service, quiet_s=QUIET, max_wait_s=MAX_WAIT, diagnostics=recorder), data, \
        recorder


def titles(data: Path, version: int) -> str:
    return json.loads((data / LIBRARY_DIR / SCENE / str(version) / "manifest.json").read_text("utf-8"))["title"]


def live(data: Path) -> list[int]:
    return sorted(int(p.name) for p in (data / LIBRARY_DIR / SCENE).iterdir())


async def test_a_burst_of_retouches_publishes_one_version_with_the_last_candidate(setup):
    service, coalescer, data, recorder = setup
    tasks = []
    for index in range(10):
        tasks.append(asyncio.create_task(coalescer.submit(candidate(id=SCENE, title=f"Retouche {index}"),
                                                          actor="user")))
        await asyncio.sleep(0.01)
    results = await asyncio.gather(*tasks)
    assert {item.version for item in results} == {1} and len({item.fingerprint for item in results}) == 1
    assert live(data) == [1] and titles(data, 1) == "Retouche 9"
    assert ("core.prefab.draft_coalesced", {"prefab_id": SCENE, "version": 1, "merged": 10}) in recorder.events
    assert coalescer.pending_ids == ()


async def test_two_bursts_apart_publish_two_versions_in_order(setup):
    _, coalescer, data, _ = setup
    first = await coalescer.submit(candidate(id=SCENE, title="A"), actor="user")
    second = await coalescer.submit(candidate(id=SCENE, title="B"), actor="user")
    assert (first.version, second.version) == (1, 2) and titles(data, 2) == "B"
    assert second.provenance.derived_from == PrefabRef(SCENE, 1)


async def test_a_continuous_stream_still_publishes_at_the_max_wait(setup):
    _, coalescer, data, _ = setup
    tasks = []
    for index in range(30):  # one retouch every 50 ms for 1.5 s: never quiet for 150 ms
        tasks.append(asyncio.create_task(coalescer.submit(candidate(id=SCENE, title=f"R{index}"), actor="user")))
        await asyncio.sleep(0.05)
    results = await asyncio.gather(*tasks)
    assert len({item.version for item in results}) >= 2  # never one endless unpublished burst
    assert len(live(data)) < 30  # and far fewer versions than retouches


async def test_a_different_actor_or_origin_flushes_the_pending_burst_first(setup):
    _, coalescer, data, _ = setup
    brain = asyncio.create_task(coalescer.submit(candidate(id=SCENE, title="brain"), actor="brain"))
    await asyncio.sleep(0.01)
    user = await coalescer.submit(candidate(id=SCENE, title="user"), actor="user")
    first = await brain
    assert (first.version, user.version) == (1, 2)
    assert (titles(data, 1), titles(data, 2)) == ("brain", "user")
    assert first.provenance.created_by.value == "brain" and user.provenance.created_by.value == "user"


async def test_every_caller_of_a_failed_burst_gets_the_same_typed_error(setup):
    _, coalescer, data, _ = setup
    tasks = [asyncio.create_task(coalescer.submit(candidate(id="jarvis.counter"), actor="user")) for _ in range(3)]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)
    assert all(isinstance(item, PrefabStoreError) and item.code is PrefabStoreErrorCode.BASE_PROTECTED
               for item in outcomes)
    assert coalescer.pending_ids == () and not (data / LIBRARY_DIR / "jarvis.counter").exists()


async def test_an_invalid_candidate_is_refused_at_once_not_held_for_the_quiet_period(setup):
    _, coalescer, data, _ = setup
    with pytest.raises(PrefabStoreError) as caught:
        await coalescer.submit({"manifest": {"id": SCENE}}, actor="user")
    assert caught.value.code is PrefabStoreErrorCode.INVALID_DEFINITION
    with pytest.raises(PrefabStoreError):
        await coalescer.submit("not a candidate", actor="user")
    assert coalescer.pending_ids == ()


async def test_flush_publishes_now_and_a_cancelled_caller_does_not_cancel_the_publication(setup):
    _, coalescer, data, _ = setup
    caller = asyncio.create_task(coalescer.submit(candidate(id=SCENE, title="kept"), actor="user"))
    await asyncio.sleep(0.01)
    caller.cancel()
    await coalescer.flush()  # long before the quiet period ends
    assert live(data) == [1] and titles(data, 1) == "kept" and coalescer.pending_ids == ()
    with pytest.raises(asyncio.CancelledError):
        await caller


async def test_flush_also_waits_for_a_publication_a_timer_already_started(setup):
    _, coalescer, data, _ = setup
    task = asyncio.create_task(coalescer.submit(candidate(id=SCENE), actor="user"))
    await asyncio.sleep(QUIET + 0.02)  # the timer fired: save is in flight or done
    await coalescer.flush()
    assert live(data) == [1]
    assert (await task).version == 1


def test_the_windows_are_validated():
    with pytest.raises(ValueError):
        PrefabDraftCoalescer(object(), quiet_s=0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        PrefabDraftCoalescer(object(), quiet_s=5, max_wait_s=1)  # type: ignore[arg-type]


class SlowService:
    """Service dont `save` attend une porte : permet d'annuler un appelant pendant la publication d'un autre."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.saved: list[tuple[object, str]] = []

    async def save(self, candidate_, *, actor, derived_from=None):
        await self.gate.wait()
        self.saved.append((candidate_["manifest"]["title"], actor))
        return f"publication-{len(self.saved)}"


async def test_cancelling_the_second_caller_during_an_actor_flush_keeps_the_first_draft():
    slow = SlowService()
    coalescer = PrefabDraftCoalescer(slow, quiet_s=5, max_wait_s=10)  # type: ignore[arg-type]
    first = asyncio.create_task(coalescer.submit(candidate(id=SCENE, title="brain draft"), actor="brain"))
    await asyncio.sleep(0.01)
    second = asyncio.create_task(coalescer.submit(candidate(id=SCENE, title="user draft"), actor="user"))
    await asyncio.sleep(0.05)  # the second caller is flushing the first burst: save waits on the gate
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second
    slow.gate.set()
    assert await asyncio.wait_for(first, 5) == "publication-1"  # no RuntimeError('CancelledError()'), nothing lost
    assert slow.saved == [("brain draft", "brain")]
    assert coalescer.pending_ids == ()


async def test_cancelling_the_timer_task_does_not_cancel_a_publication_in_flight():
    slow = SlowService()
    coalescer = PrefabDraftCoalescer(slow, quiet_s=0.05, max_wait_s=0.1)  # type: ignore[arg-type]
    caller = asyncio.create_task(coalescer.submit(candidate(id=SCENE, title="kept"), actor="user"))
    await asyncio.sleep(0.2)  # the timer fired; save is waiting on the gate
    timers = [t for t in asyncio.all_tasks() if "_fire_after" in repr(t)]
    for timer in timers:
        timer.cancel()
    slow.gate.set()
    assert await asyncio.wait_for(caller, 5) == "publication-1"
