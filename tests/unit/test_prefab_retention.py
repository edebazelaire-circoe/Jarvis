"""Capacité de la bibliothèque pour les sources de scène du Studio (Slice 01a) : rétention des versions non
épinglées des ids `presentation-studio.*`, borne des ids, erreurs typées visibles.

Vrai magasin sur dossiers temporaires, registre d'épinglages simulé. Contrat : `docs/prefabs.md` ›
*Retention of studio scene sources*. Le crash réel (processus tué entre les étapes) est dans
`test_prefab_retention_crash.py`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from jarvis.adapters.file_prefab_library import LIBRARY_DIR, FilePrefabLibrary
from jarvis.core import prefab_service as service_module
from jarvis.core.prefab_retention import CompositePinRegistry, retirable_versions
from jarvis.core.prefab_service import PrefabService
from jarvis.domain.prefab import MAX_VERSIONS_PER_ID, RETENTION_KEEP_LAST, RETENTION_TRIGGER_VERSIONS, is_retention_id
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode
from tests.fakes.prefabs import candidate, install_version

NOW = datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc)  # well after the fixtures' publication date
SCENE = "presentation-studio.scene1"


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.events.append((kind, level, dict(data or {})))

    def kinds(self) -> list[str]:
        return [kind for kind, _, _ in self.events]


class Pins:
    """Registre simulé : `pinned[id]` = versions épinglées, lu au moment de l'appel (donc sous le verrou)."""

    def __init__(self, pinned: dict[str, set[int]] | None = None, *, gate: asyncio.Event | None = None,
                 error: Exception | None = None) -> None:
        self.pinned = pinned or {}
        self.gate = gate
        self.error = error
        self.calls: list[tuple[str, ...]] = []
        self.entered = asyncio.Event()

    async def pinned_versions(self, prefab_ids):
        self.calls.append(tuple(prefab_ids))
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return {prefab_id: frozenset(self.pinned.get(prefab_id, ())) for prefab_id in prefab_ids}


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    package = tmp_path / "package"
    package.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    install_version(package, "jarvis.counter", title="Base counter")
    return package, data


def make_service(roots, pins=None, *, library=None) -> tuple[PrefabService, Recorder]:
    recorder = Recorder()
    return PrefabService(library or FilePrefabLibrary(*roots), diagnostics=recorder, clock=lambda: NOW,
                         pin_registry=pins), recorder


def populate(data: Path, prefab_id: str, count: int) -> None:
    for version in range(1, count + 1):
        install_version(data / LIBRARY_DIR, prefab_id, version)


def live_versions(data: Path, prefab_id: str) -> list[int]:
    folder = data / LIBRARY_DIR / prefab_id
    return sorted(int(path.name) for path in folder.iterdir()) if folder.exists() else []


def archived_versions(data: Path, prefab_id: str) -> list[int]:
    folder = data / LIBRARY_DIR / ".archive" / prefab_id
    return sorted(int(path.name) for path in folder.iterdir()) if folder.exists() else []


def snapshot(folder: Path) -> dict[str, bytes]:
    return {str(path.relative_to(folder)): path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file()}


async def refused(awaitable) -> PrefabStoreError:
    with pytest.raises(PrefabStoreError) as caught:
        await awaitable
    return caught.value


def edit(prefab_id: str = SCENE, title: str = "Scène"):
    return candidate(id=prefab_id, title=title)


# ------------------------------------------------------------------ politique pure


def test_the_namespace_policy_covers_only_studio_custom_ids():
    assert is_retention_id("presentation-studio.scene1")
    assert not is_retention_id("lab.presentation-studio")
    assert not is_retention_id("jarvis.window")
    assert not is_retention_id("presentation-studio")  # no dot: not even a valid id


async def test_retirable_versions_keeps_the_last_ones_the_pinned_and_the_refused(roots):
    _, data = roots
    populate(data, SCENE, 10)
    service, _ = make_service(roots)
    await service.start()
    entries = service._entries_of(SCENE)
    assert retirable_versions(entries, {2, 4}, 3) == [1, 3, 5, 6, 7]
    assert retirable_versions(entries, set(), 0) == list(range(1, 11))
    assert retirable_versions(entries, set(range(1, 11)), 3) == []


async def test_a_tampered_version_is_never_retired(roots):
    _, data = roots
    populate(data, SCENE, 6)
    (data / LIBRARY_DIR / SCENE / "2" / "style.css").write_text("tampered", encoding="utf-8")
    service, _ = make_service(roots)
    await service.start()
    assert 2 not in retirable_versions(service._entries_of(SCENE), set(), 2)


async def test_the_composite_registry_unions_every_store_and_fails_if_one_fails():
    union = CompositePinRegistry(Pins({SCENE: {1}}), Pins({SCENE: {2}, "presentation-studio.b": {9}}))
    assert await union.pinned_versions([SCENE, "presentation-studio.b"]) == {
        SCENE: frozenset({1, 2}), "presentation-studio.b": frozenset({9})}
    with pytest.raises(RuntimeError):
        await CompositePinRegistry(Pins(), Pins(error=RuntimeError("store down"))).pinned_versions([SCENE])


# ------------------------------------------------------------------ rétention des versions


async def test_a_long_rehearsal_never_hits_the_cap_when_nothing_is_pinned(roots):
    _, data = roots
    service, recorder = make_service(roots, Pins())
    for index in range(MAX_VERSIONS_PER_ID * 2 + 5):  # twice the old hard stop
        publication = await service.save(edit(title=f"Retouche {index}"), actor="user")
        assert publication.version == index + 1  # monotonic, never re-issued
    live = live_versions(data, SCENE)
    assert len(live) <= RETENTION_TRIGGER_VERSIONS and live[-1] == MAX_VERSIONS_PER_ID * 2 + 5
    archived = archived_versions(data, SCENE)
    assert sorted(live + archived) == list(range(1, MAX_VERSIONS_PER_ID * 2 + 6))  # nothing lost, nothing doubled
    assert "core.prefab.retired" in recorder.kinds()
    detail = await service.get(SCENE)
    assert detail.latest_version == MAX_VERSIONS_PER_ID * 2 + 5


async def test_pinned_versions_survive_every_pass_byte_for_byte(roots):
    _, data = roots
    populate(data, SCENE, RETENTION_TRIGGER_VERSIONS)
    pinned = {3, 5, 20}
    before = {v: snapshot(data / LIBRARY_DIR / SCENE / str(v)) for v in pinned}
    service, _ = make_service(roots, Pins({SCENE: pinned}))
    for index in range(80):
        await service.save(edit(title=f"Retouche {index}"), actor="user")
    live = live_versions(data, SCENE)
    assert pinned <= set(live)
    for version in pinned:
        assert snapshot(data / LIBRARY_DIR / SCENE / str(version)) == before[version]
        assert (await service.get(SCENE, version)).entry.ok
    assert set(range(1, 113)) == set(live) | set(archived_versions(data, SCENE))
    assert not (pinned & set(archived_versions(data, SCENE)))


async def test_pinning_every_version_ends_in_a_named_visible_error_never_a_silent_drop(roots):
    _, data = roots
    populate(data, SCENE, MAX_VERSIONS_PER_ID)
    pins = Pins({SCENE: set(range(1, MAX_VERSIONS_PER_ID + 1))})
    service, recorder = make_service(roots, pins)
    error = await refused(service.save(edit(), actor="user"))
    assert error.code is PrefabStoreErrorCode.VERSION_LIMIT and error.status == 409
    assert "64 versions vivantes" in error.message and "nouvel id" in error.message
    assert live_versions(data, SCENE) == list(range(1, MAX_VERSIONS_PER_ID + 1))
    assert archived_versions(data, SCENE) == []
    assert "core.prefab.saved" not in recorder.kinds()


async def test_the_pin_check_runs_under_the_write_lock_and_sees_a_pin_added_while_a_save_waits(roots):
    _, data = roots
    populate(data, SCENE, RETENTION_TRIGGER_VERSIONS)
    gate = asyncio.Event()
    pins = Pins({SCENE: set()}, gate=gate)
    service, _ = make_service(roots, pins)
    first = asyncio.create_task(service.save(edit(title="A"), actor="user"))
    await asyncio.wait_for(pins.entered.wait(), 5)  # the first save holds the lock, inside the pin check
    second = asyncio.create_task(service.save(edit(title="B"), actor="user"))
    await asyncio.sleep(0.2)
    assert not second.done() and len(pins.calls) == 1  # serialized behind the lock
    pins.pinned[SCENE].add(2)  # a studio document pins v2 while the check is in flight
    gate.set()
    published = [await first, await second]
    assert [p.version for p in published] == [RETENTION_TRIGGER_VERSIONS + 1, RETENTION_TRIGGER_VERSIONS + 2]
    assert 2 in live_versions(data, SCENE) and 1 not in live_versions(data, SCENE)


async def test_concurrent_saves_during_retention_keep_numbers_unique_and_the_set_consistent(roots):
    _, data = roots
    populate(data, SCENE, RETENTION_TRIGGER_VERSIONS + 4)
    service, _ = make_service(roots, Pins({SCENE: {7}}))
    results = await asyncio.gather(*(service.save(edit(title=f"C{index}"), actor="user") for index in range(12)))
    numbers = [item.version for item in results]
    assert len(set(numbers)) == 12
    live, archived = live_versions(data, SCENE), archived_versions(data, SCENE)
    assert not set(live) & set(archived)
    assert set(range(1, max(numbers) + 1)) == set(live) | set(archived)
    assert 7 in live
    fresh, _ = make_service(roots, Pins({SCENE: {7}}))
    await fresh.start()
    assert all(entry.ok for entry in fresh._entries_of(SCENE))


# ------------------------------------------------------------------ ferme par défaut


async def test_without_a_registry_nothing_is_archived_and_the_cap_is_a_typed_error(roots):
    _, data = roots
    populate(data, SCENE, MAX_VERSIONS_PER_ID)
    service, recorder = make_service(roots, None)
    error = await refused(service.save(edit(), actor="user"))
    assert error.code is PrefabStoreErrorCode.VERSION_LIMIT and "rétention indisponible" in error.message
    assert archived_versions(data, SCENE) == [] and len(live_versions(data, SCENE)) == MAX_VERSIONS_PER_ID
    assert ("core.prefab.retention_inactive", "warning") in [(kind, level) for kind, level, _ in recorder.events]


async def test_a_failing_registry_archives_nothing_traces_an_error_and_lets_a_save_under_the_cap_through(roots):
    _, data = roots
    populate(data, SCENE, RETENTION_TRIGGER_VERSIONS)
    service, recorder = make_service(roots, Pins(error=RuntimeError("store down")))
    publication = await service.save(edit(), actor="user")
    assert publication.version == RETENTION_TRIGGER_VERSIONS + 1
    assert archived_versions(data, SCENE) == []
    assert ("core.prefab.retention_failed", "error") in [(kind, level) for kind, level, _ in recorder.events]
    populate_more = Path(roots[1]) / LIBRARY_DIR / SCENE
    for version in range(RETENTION_TRIGGER_VERSIONS + 2, MAX_VERSIONS_PER_ID + 1):
        install_version(populate_more.parent, SCENE, version)
    error = await refused(service.save(edit(), actor="user"))
    assert error.code is PrefabStoreErrorCode.VERSION_LIMIT and "rétention indisponible" in error.message


async def test_a_library_failure_midway_stops_the_pass_and_the_save_still_goes_through(roots):
    _, data = roots
    populate(data, SCENE, RETENTION_TRIGGER_VERSIONS)

    class Flaky(FilePrefabLibrary):
        moved = 0

        def retire(self, prefab_id, version):
            Flaky.moved += 1
            if Flaky.moved > 2:
                raise PrefabStoreError(PrefabStoreErrorCode.STORAGE_IO, "disk refused")
            return super().retire(prefab_id, version)

    service, recorder = make_service(roots, Pins(), library=Flaky(*roots))
    publication = await service.save(edit(), actor="user")
    assert publication.version == RETENTION_TRIGGER_VERSIONS + 1
    assert archived_versions(data, SCENE) == [1, 2]
    assert ("core.prefab.retention_failed", "error") in [(kind, level) for kind, level, _ in recorder.events]


# ------------------------------------------------------------------ espace de noms réservé


async def test_user_prefabs_are_never_retired_and_keep_the_hard_cap(roots):
    _, data = roots
    populate(data, "lab.counter", MAX_VERSIONS_PER_ID)
    pins = Pins()
    service, _ = make_service(roots, pins)
    error = await refused(service.save(candidate(id="lab.counter"), actor="user"))
    assert error.code is PrefabStoreErrorCode.VERSION_LIMIT
    assert pins.calls == [] and not (data / LIBRARY_DIR / ".archive").exists()
    assert live_versions(data, "lab.counter") == list(range(1, MAX_VERSIONS_PER_ID + 1))


async def test_a_look_alike_id_outside_the_namespace_is_not_retired(roots):
    _, data = roots
    populate(data, "lab.presentation-studio", MAX_VERSIONS_PER_ID)
    pins = Pins()
    service, _ = make_service(roots, pins)
    error = await refused(service.save(candidate(id="lab.presentation-studio"), actor="user"))
    assert error.code is PrefabStoreErrorCode.VERSION_LIMIT and pins.calls == []


async def test_base_prefabs_stay_protected_and_the_package_is_never_written(roots):
    package, data = roots
    before = snapshot(package)
    service, _ = make_service(roots, Pins())
    error = await refused(service.save(candidate(id="jarvis.counter"), actor="user"))
    assert error.code is PrefabStoreErrorCode.BASE_PROTECTED
    assert snapshot(package) == before


# ------------------------------------------------------------------ numéros : jamais réattribués, 9999


async def test_a_retired_number_is_never_issued_again_even_after_a_restart(roots):
    _, data = roots
    populate(data, SCENE, RETENTION_TRIGGER_VERSIONS)
    service, _ = make_service(roots, Pins())
    await service.save(edit(), actor="user")  # retires 1..16
    assert 1 in archived_versions(data, SCENE)
    restarted, _ = make_service(roots, Pins())
    await restarted.start()
    publication = await restarted.save(edit(), actor="user")
    assert publication.version == RETENTION_TRIGGER_VERSIONS + 2


async def test_the_last_numbered_version_9999_ends_in_a_named_error_with_the_way_out(roots):
    _, data = roots
    install_version(data / LIBRARY_DIR, SCENE, 1)
    archive = data / LIBRARY_DIR / ".archive" / SCENE / "9999"
    archive.mkdir(parents=True)  # a retired v9999: the number is spent although it is not live
    service, _ = make_service(roots, Pins())
    error = await refused(service.save(edit(), actor="user"))
    assert error.code is PrefabStoreErrorCode.VERSION_LIMIT and "9999" in error.message
    assert "nouvel id" in error.message
    assert live_versions(data, SCENE) == [1]


# ------------------------------------------------------------------ ids


async def test_a_new_studio_id_at_the_quota_archives_the_oldest_idle_id(roots, monkeypatch):
    _, data = roots
    monkeypatch.setattr(service_module, "MAX_RETENTION_PREFAB_IDS", 3)
    for name in ("a", "b", "c"):
        populate(data, f"presentation-studio.{name}", 2)
    service, recorder = make_service(roots, Pins({"presentation-studio.a": {1}}))
    publication = await service.save(candidate(id="presentation-studio.d"), actor="user")
    assert publication.version == 1
    # `a` is pinned: the next oldest idle id (`b`) goes, whole, into the archive.
    assert live_versions(data, "presentation-studio.b") == []
    assert archived_versions(data, "presentation-studio.b") == [1, 2]
    assert live_versions(data, "presentation-studio.a") == [1, 2]
    assert ("core.prefab.id_retired", "info") in [(kind, level) for kind, level, _ in recorder.events]
    again = await service.save(candidate(id="presentation-studio.b"), actor="user")
    assert again.version == 3  # the archived numbers stay spent


async def test_the_id_quota_never_evicts_pinned_or_fresh_ids_and_says_so(roots, monkeypatch):
    _, data = roots
    monkeypatch.setattr(service_module, "MAX_RETENTION_PREFAB_IDS", 2)
    populate(data, "presentation-studio.a", 1)
    populate(data, "presentation-studio.b", 1)
    service, _ = make_service(roots, Pins({"presentation-studio.a": {1}, "presentation-studio.b": {1}}))
    error = await refused(service.save(candidate(id="presentation-studio.c"), actor="user"))
    assert error.code is PrefabStoreErrorCode.ID_LIMIT and error.status == 409 and "ids de prefab" in error.message
    assert not (data / LIBRARY_DIR / "presentation-studio.c").exists()
    fresh_clock = PrefabService(FilePrefabLibrary(*roots), clock=lambda: datetime(2026, 10, 3, 12, 30, 0,
                                                                                   tzinfo=timezone.utc),
                                pin_registry=Pins())  # 30 minutes after the fixtures' publication date
    error = await refused(fresh_clock.save(candidate(id="presentation-studio.c"), actor="user"))
    assert error.code is PrefabStoreErrorCode.ID_LIMIT
    assert live_versions(data, "presentation-studio.a") == [1] and live_versions(data, "presentation-studio.b") == [1]


async def test_a_user_id_at_the_total_cap_is_refused_and_no_studio_id_is_touched(roots, monkeypatch):
    _, data = roots
    monkeypatch.setattr(service_module, "MAX_PREFAB_IDS", 2)  # jarvis.counter + one studio id
    populate(data, "presentation-studio.a", 1)
    pins = Pins()
    service, _ = make_service(roots, pins)
    error = await refused(service.save(candidate(id="lab.new"), actor="user"))
    assert error.code is PrefabStoreErrorCode.ID_LIMIT
    assert pins.calls == [] and live_versions(data, "presentation-studio.a") == [1]


async def test_a_studio_id_at_the_total_cap_makes_room_by_archiving_an_idle_studio_id(roots, monkeypatch):
    _, data = roots
    monkeypatch.setattr(service_module, "MAX_PREFAB_IDS", 2)
    populate(data, "presentation-studio.a", 1)
    service, _ = make_service(roots, Pins())
    await service.save(candidate(id="presentation-studio.b"), actor="user")
    assert archived_versions(data, "presentation-studio.a") == [1]
    assert live_versions(data, "presentation-studio.b") == [1]
