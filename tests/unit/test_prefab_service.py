"""Catalogue et autorité de validation des prefabs dans Core (Slice 02).

Vrai magasin sur dossiers temporaires, témoin de conversation simulé. Contrat :
`docs/prefabs.md` › *Storage and library*, *Base-edit gate*, *Modules and validation authority*.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from jarvis.adapters.file_prefab_library import LIBRARY_DIR, FilePrefabLibrary
from jarvis.core.prefab_service import PrefabService
from jarvis.domain.prefab import (
    MAX_ERROR_CHARS, PrefabInstanceRef, PrefabRef, ProvenanceOrigin, Publication,
)
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode
from tests.fakes.prefabs import candidate, install_version

NOW = datetime(2026, 10, 3, 9, 30, tzinfo=timezone.utc)
REQUEST = "  Rends la checklist plus lisible, police plus grande  "


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.events.append((kind, level, dict(data or {})))

    def kinds(self) -> list[str]:
        return [kind for kind, _, _ in self.events]


class Witness:
    def __init__(self, answer: str | None = "evt-42", error: Exception | None = None) -> None:
        self.answer = answer
        self.error = error
        self.asked: list[str] = []

    async def __call__(self, text: str) -> str | None:
        self.asked.append(text)
        if self.error is not None:
            raise self.error
        return self.answer


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    package = tmp_path / "package"
    package.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    install_version(package, "jarvis.counter", title="Base counter")
    return package, data


def make_service(roots, *, witness=None) -> tuple[PrefabService, Recorder]:
    recorder = Recorder()
    service = PrefabService(FilePrefabLibrary(*roots), user_utterance_witness=witness, diagnostics=recorder,
                            clock=lambda: NOW)
    return service, recorder


async def refused(awaitable) -> PrefabStoreError:
    with pytest.raises(PrefabStoreError) as caught:
        await awaitable
    return caught.value


def tree_state(root: Path) -> list[tuple[str, int, int]]:
    return sorted((str(path.relative_to(root)), path.stat().st_size, path.stat().st_mtime_ns)
                  for path in root.rglob("*"))


def on_disk(data: Path, prefab_id: str, version: int) -> Publication:
    path = data / LIBRARY_DIR / prefab_id / str(version) / "publication.json"
    return Publication.decode_text(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ save : custom, fork, révision


async def test_save_new_id_is_custom_and_core_assigns_the_version(roots):
    service, recorder = make_service(roots)
    publication = await service.save(candidate(id="lab.counter", version=7), actor="brain")
    assert (publication.prefab_id, publication.version) == ("lab.counter", 1)
    assert publication.provenance.origin is ProvenanceOrigin.CUSTOM
    assert publication.provenance.derived_from is None
    assert publication.provenance.created_by.value == "brain"
    assert publication.published_at == "2026-10-03T09:30:00Z"
    assert on_disk(roots[1], "lab.counter", 1) == publication
    manifest = json.loads((roots[1] / LIBRARY_DIR / "lab.counter" / "1" / "manifest.json").read_text("utf-8"))
    assert manifest["version"] == 1
    assert ("core.prefab.saved", "info") in [(kind, level) for kind, level, _ in recorder.events]
    detail = await service.get("lab.counter")
    assert detail.entry.fingerprint == publication.fingerprint


async def test_fork_requires_an_existing_healthy_source(roots):
    service, _ = make_service(roots)
    publication = await service.save(candidate(id="lab.fork"), actor="user",
                                     derived_from=PrefabRef("jarvis.counter", 1))
    assert publication.provenance.origin is ProvenanceOrigin.FORK
    assert publication.provenance.derived_from == PrefabRef("jarvis.counter", 1)
    assert (await refused(service.save(candidate(id="lab.f2"), actor="user",
                                       derived_from=PrefabRef("jarvis.nothing", 1)))).code \
        is PrefabStoreErrorCode.UNKNOWN_PREFAB
    assert (await refused(service.save(candidate(id="lab.f3"), actor="user",
                                       derived_from=PrefabRef("jarvis.counter", 9)))).code \
        is PrefabStoreErrorCode.UNKNOWN_VERSION
    assert not (roots[1] / LIBRARY_DIR / "lab.f2").exists()


async def test_saving_an_existing_custom_id_is_a_revision(roots):
    service, _ = make_service(roots)
    await service.save(candidate(id="lab.counter"), actor="user")
    second = await service.save(candidate(id="lab.counter", title="Counter v2"), actor="brain")
    assert second.version == 2
    assert second.provenance.origin is ProvenanceOrigin.REVISION
    assert second.provenance.derived_from == PrefabRef("lab.counter", 1)
    assert (await service.get("lab.counter", 1)).entry.manifest.title == "Counter"
    detail = await service.get("lab.counter")
    assert detail.entry.version == 2 and detail.latest_version == 2
    assert [row["origin"] for row in detail.history] == ["custom", "revision"]
    error = await refused(service.save(candidate(id="lab.counter"), actor="user",
                                       derived_from=PrefabRef("jarvis.counter", 1)))
    assert error.code is PrefabStoreErrorCode.INVALID_DEFINITION


async def test_save_refuses_base_ids_invalid_candidates_and_actors(roots):
    service, recorder = make_service(roots)
    before = tree_state(roots[0])
    error = await refused(service.save(candidate(id="jarvis.counter"), actor="brain"))
    assert error.code is PrefabStoreErrorCode.BASE_PROTECTED and "prefab_edit_base" in error.message
    assert error.status == 403
    assert "core.prefab.save_refused" in recorder.kinds()
    error = await refused(service.save(candidate("test.bad_lint"), actor="brain"))
    assert error.code is PrefabStoreErrorCode.INVALID_DEFINITION and len(error.errors) >= 3
    assert all(len(item) <= MAX_ERROR_CHARS for item in error.errors)
    error = await refused(service.save(candidate(id="lab.x"), actor="system"))
    assert error.code is PrefabStoreErrorCode.INVALID_DEFINITION
    assert tree_state(roots[0]) == before
    assert not (roots[1] / LIBRARY_DIR).exists()


# ------------------------------------------------------------------ porte d'édition de base


@pytest.mark.parametrize("prefab_id,confirmed,request_text,reason", [
    ("jarvis.missing", True, REQUEST, "not an existing base prefab id"),
    ("lab.counter", True, REQUEST, "not an existing base prefab id"),
    ("jarvis.counter", False, REQUEST, "confirmed_by_user must be true"),
    ("jarvis.counter", "true", REQUEST, "confirmed_by_user must be true"),
    ("jarvis.counter", 1, REQUEST, "confirmed_by_user must be true"),
    ("jarvis.counter", True, "  trop court ", "user_request must quote"),
    ("jarvis.counter", True, "x" * 501, "user_request must quote"),
    ("jarvis.counter", True, None, "user_request must quote"),
])
async def test_edit_base_gate_conditions_1_to_3(roots, prefab_id, confirmed, request_text, reason):
    witness = Witness()
    service, recorder = make_service(roots, witness=witness)
    error = await refused(service.edit_base(prefab_id, candidate(id=prefab_id), user_request=request_text,
                                            confirmed_by_user=confirmed))
    assert error.code is PrefabStoreErrorCode.BASE_EDIT_UNCONFIRMED and reason in error.message
    assert witness.asked == []
    assert recorder.events[-1][0] == "core.prefab.base_edit_refused"
    assert not (roots[1] / LIBRARY_DIR).exists()


@pytest.mark.parametrize("witness,reason", [
    (None, "no conversation witness is wired"),
    (Witness(answer=None), "not found in a recent user turn"),
    (Witness(answer=""), "not found in a recent user turn"),
    (Witness(error=RuntimeError("events store closed")), "witness lookup failed: RuntimeError: events store closed"),
])
async def test_edit_base_gate_condition_4_witness(roots, witness, reason):
    service, _ = make_service(roots, witness=witness)
    error = await refused(service.edit_base("jarvis.counter", candidate(id="jarvis.counter"), user_request=REQUEST,
                                            confirmed_by_user=True))
    assert error.code is PrefabStoreErrorCode.BASE_EDIT_UNCONFIRMED and reason in error.message
    assert not (roots[1] / LIBRARY_DIR).exists()


async def test_edit_base_with_a_witness_publishes_into_the_data_root_only(roots):
    witness = Witness("evt-42")
    service, recorder = make_service(roots, witness=witness)
    package_before = tree_state(roots[0])
    publication = await service.edit_base("jarvis.counter", candidate(id="jarvis.counter", title="Bigger"),
                                          user_request=REQUEST, confirmed_by_user=True)
    assert witness.asked == [REQUEST.strip()]
    assert (publication.prefab_id, publication.version) == ("jarvis.counter", 2)
    provenance = publication.provenance
    assert provenance.origin is ProvenanceOrigin.BASE_EDIT
    assert provenance.derived_from == PrefabRef("jarvis.counter", 1)
    assert provenance.base_edit.user_request == REQUEST.strip()
    assert provenance.base_edit.witness == "conversation_event:evt-42"
    assert on_disk(roots[1], "jarvis.counter", 2) == publication
    assert tree_state(roots[0]) == package_before
    kind, level, data = recorder.events[-1]
    assert (kind, level) == ("core.prefab.base_edited", "warning")
    assert REQUEST.strip() not in json.dumps(data)  # the user's words stay out of the journal
    summary = (await service.search("counter"))[0]
    assert summary.prefab_id == "jarvis.counter" and summary.latest_version == 2 and summary.base_edited
    detail = await service.get("jarvis.counter")
    assert detail.entry.manifest.title == "Bigger"
    assert [row["origin"] for row in detail.history] == ["base", "base_edit"]


async def test_edit_base_refuses_a_candidate_for_another_id(roots):
    service, _ = make_service(roots, witness=Witness())
    error = await refused(service.edit_base("jarvis.counter", candidate(id="jarvis.other"), user_request=REQUEST,
                                            confirmed_by_user=True))
    assert error.code is PrefabStoreErrorCode.INVALID_DEFINITION


# ------------------------------------------------------------------ catalogue : altération, conflit, recherche


async def test_a_version_edited_in_place_is_tampered_and_refused(roots):
    install_version(roots[1] / LIBRARY_DIR, "lab.counter")
    (roots[1] / LIBRARY_DIR / "lab.counter" / "1" / "template.html").write_text("<p>edited</p>", encoding="utf-8")
    service, recorder = make_service(roots)
    await service.start()
    error = await refused(service.get("lab.counter", 1))
    assert error.code is PrefabStoreErrorCode.TAMPERED and "fingerprint differs" in error.message
    assert (await refused(service.get("lab.counter"))).code is PrefabStoreErrorCode.TAMPERED
    assert [summary.prefab_id for summary in await service.search()] == ["jarvis.counter"]
    tampered = [data for kind, level, data in recorder.events if kind == "core.prefab.tampered"]
    assert len(tampered) == 1 and tampered[0]["prefab_id"] == "lab.counter"
    await service.search()
    assert recorder.kinds().count("core.prefab.tampered") == 1  # reported once, not on every listing
    result = await service.validate_instance(PrefabInstanceRef("lab.counter", 1, {}, {"count": 1}))
    assert not result.ok and result.code is PrefabStoreErrorCode.TAMPERED


@pytest.mark.parametrize("damage,needle", [
    (lambda folder: (folder / "publication.json").unlink(), "publication.json is missing"),
    (lambda folder: (folder / "publication.json").write_text("{}", encoding="utf-8"), "publication.json is invalid"),
    (lambda folder: (folder / "manifest.json").write_text("{", encoding="utf-8"), "definition on disk is invalid"),
    (lambda folder: (folder / "behavior.js").unlink(), "behavior.js is missing"),
])
async def test_other_damage_is_tampered(roots, damage, needle):
    install_version(roots[1] / LIBRARY_DIR, "lab.counter")
    damage(roots[1] / LIBRARY_DIR / "lab.counter" / "1")
    service, _ = make_service(roots)
    error = await refused(service.get("lab.counter", 1))
    assert error.code is PrefabStoreErrorCode.TAMPERED and needle in error.message


async def test_a_shipped_origin_in_the_data_root_is_tampered(roots):
    install_version(roots[1] / LIBRARY_DIR, "jarvis.planted")  # origin base, outside the package
    service, _ = make_service(roots)
    error = await refused(service.get("jarvis.planted", 1))
    assert error.code is PrefabStoreErrorCode.TAMPERED and "does not belong" in error.message


async def test_the_package_wins_a_version_conflict(roots):
    install_version(roots[1] / LIBRARY_DIR, "jarvis.counter", origin=ProvenanceOrigin.BASE, title="Shadow")
    service, recorder = make_service(roots)
    detail = await service.get("jarvis.counter", 1)
    assert detail.entry.root.value == "package" and detail.entry.manifest.title == "Base counter"
    assert "core.prefab.version_conflict" in recorder.kinds()


async def test_search_ranks_filters_and_bounds(roots):
    service, _ = make_service(roots)
    await service.save(candidate(id="lab.timer", title="Timer", aliases=["chrono"], tags=["time"],
                                 description="Counts down"), actor="user")
    await service.save(candidate(id="lab.notes", title="Notes", aliases=[], tags=["text"],
                                 description="A counter of notes"), actor="user")
    ranked = [row.prefab_id for row in await service.search("counter")]
    assert ranked[0] == "jarvis.counter" and set(ranked) == {"jarvis.counter", "lab.notes"}
    assert [row.prefab_id for row in await service.search("chrono")] == ["lab.timer"]
    assert [row.prefab_id for row in await service.search("lab.timer")] == ["lab.timer"]
    assert await service.search("counter timer") == ()
    assert [row.prefab_id for row in await service.search(prefab_class="base")] == ["jarvis.counter"]
    assert len(await service.search(prefab_class="custom", limit=1)) == 1
    assert await service.search(family="indicator") == ()
    row = (await service.search("chrono"))[0].to_dict()
    assert row == {"id": "lab.timer", "latest_version": 1, "versions": [1], "title": "Timer", "family": "window",
                   "class": "custom", "description": "Counts down",
                   "input_names": ["props.label", "props.accent", "props.mode", "data.count", "data.notes",
                                   "data.link", "data.history"],
                   "event_names": ["incremented", "reset_requested"], "base_edited": False}
    for bad in ({"limit": 0}, {"limit": 51}, {"query": "x" * 121}):
        assert (await refused(service.search(**bad))).code is PrefabStoreErrorCode.INVALID_DEFINITION


async def test_get_and_bundle(roots):
    service, _ = make_service(roots)
    body = (await service.get("jarvis.counter", 1)).to_dict(include_source=True)
    assert body["class"] == "base" and body["publication"]["provenance"]["origin"] == "base"
    assert set(body["files"]) == {"template", "style", "behavior"}
    assert "files" not in (await service.get("jarvis.counter")).to_dict()
    bundle = await service.bundle("jarvis.counter", 1)
    assert bundle["runtime"] is None and bundle["manifest"]["id"] == "jarvis.counter"
    assert len(bundle["fingerprint"]) == 64
    assert (await refused(service.get("jarvis.none"))).code is PrefabStoreErrorCode.UNKNOWN_PREFAB
    assert (await refused(service.get("Not an id"))).code is PrefabStoreErrorCode.UNKNOWN_PREFAB
    assert (await refused(service.bundle("jarvis.counter", 2))).code is PrefabStoreErrorCode.UNKNOWN_VERSION


async def test_a_version_dropped_after_start_is_found_on_demand(roots):
    service, _ = make_service(roots)
    await service.start()
    install_version(roots[0], "jarvis.late")
    assert (await service.get("jarvis.late")).entry.version == 1


# ------------------------------------------------------------------ validation


def test_validate_candidate_reports_all_errors_or_the_fingerprint(roots):
    service, _ = make_service(roots)
    good = service.validate_candidate(candidate())
    assert good.ok and len(good.fingerprint) == 64 and good.to_dict()["errors"] == []
    bad = service.validate_candidate(candidate("test.bad_lint"))
    assert not bad.ok and len(bad.errors) >= 3 and "fingerprint" not in bad.to_dict()
    assert not (roots[1] / LIBRARY_DIR).exists()


async def test_validate_instance(roots):
    service, _ = make_service(roots)
    ok = await service.validate_instance(PrefabInstanceRef("jarvis.counter", 1, {"mode": "compact"}, {"count": 2}))
    assert ok.ok and ok.props == {"label": "Count", "accent": "#6ee7ff", "mode": "compact"}
    assert ok.data == {"count": 2, "notes": "", "history": []}
    unknown = await service.validate_instance(PrefabInstanceRef("jarvis.nothing", 1, {}, {}))
    assert unknown.code is PrefabStoreErrorCode.UNKNOWN_PREFAB
    version = await service.validate_instance(PrefabInstanceRef("jarvis.counter", 4, {}, {"count": 1}))
    assert version.code is PrefabStoreErrorCode.UNKNOWN_VERSION
    bad = await service.validate_instance(PrefabInstanceRef(
        "jarvis.counter", 1, {"accent": "red", "extra": 1}, {"count": -1, "history": [{"delta": 999}] * 8}))
    assert not bad.ok and bad.code is PrefabStoreErrorCode.INVALID_DEFINITION
    assert bad.detail.startswith("jarvis.counter@1: props: unknown keys ['extra']; props.accent: must be a #rrggbb")
    assert len(bad.detail) == MAX_ERROR_CHARS and bad.detail.endswith("…")  # eight history errors: clipped


# ------------------------------------------------------------------ démarrage


async def test_start_sweeps_interrupted_publications_and_reports_the_catalogue(roots):
    staging = roots[1] / LIBRARY_DIR / ".staging-0123456789abcdef"
    staging.mkdir(parents=True)
    (staging / "manifest.json").write_text("{}", encoding="utf-8")
    service, recorder = make_service(roots)
    await service.start()
    assert not staging.exists()
    swept = next(data for kind, _, data in recorder.events if kind == "core.prefab.swept")
    assert swept == {"removed": [staging.name]}
    loaded = next(data for kind, _, data in recorder.events if kind == "core.prefab.catalog_loaded")
    assert loaded == {"versions": 1, "healthy": 1, "ids": 1}


async def test_start_never_raises(roots):
    class Broken:
        def sweep(self):
            raise OSError("disk gone")

        def scan(self):
            raise OSError("disk gone")

    recorder = Recorder()
    service = PrefabService(Broken(), diagnostics=recorder)
    await service.start()
    assert recorder.kinds() == ["core.prefab.sweep_failed", "core.prefab.catalog_unavailable"]
