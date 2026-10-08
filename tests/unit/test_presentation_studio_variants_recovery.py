"""Reprise du graphe de variantes sur des états disque fabriqués (jarvis-interactive-presentation-studio, Slice 16).

Le manifeste fait foi. Orphelin de variante, noeud indexé sans fichier, document lié à moitié copié, déplacement d'archivage
interrompu dans un sens comme dans l'autre, même fichier des deux côtés, fichier archivé disparu, manifeste v1, manifeste plus
récent, manifeste illisible : chaque cas a un résultat déterministe, un rapport visible et aucun fichier détruit. Les arrêts
réels (`Popen.kill`) sont dans `test_presentation_studio_variants_crash.py`.
"""

from __future__ import annotations

import json
import shutil

import pytest

from jarvis.domain.presentation_studio import PresentationStudioErrorCode as C
from tests.unit.test_presentation_studio_variants_crash import World, refused_code


@pytest.fixture
async def world(tmp_path) -> World:
    return await World(tmp_path).build()


def manifest(world: World) -> dict:
    return json.loads((world.folder / "presentation.json").read_text(encoding="utf-8"))


def rows(world: World, kind: str) -> list[tuple[str, dict]]:
    return [(level, data) for k, level, data in world.sink.rows if k == kind]


async def test_a_variant_file_that_no_manifest_names_is_reported_as_an_orphan_and_stays_exactly_where_it_is(world):
    stray = "psv_" + "5" * 32
    document = json.loads((world.folder / "variants" / f"{world.b}.json").read_text(encoding="utf-8"))
    document.update(variant_id=stray, variant_number=9, title="Tombee du ciel")
    (world.folder / "variants" / f"{stray}.json").write_text(json.dumps(document), encoding="utf-8")
    before = (world.folder / "variants" / f"{stray}.json").read_bytes()
    variants = world.fresh()
    await variants.start()
    graph = await variants.graph(world.pid)
    assert stray not in {n["variant_id"] for n in graph["nodes"]} and graph["reconciliation"]["orphan_variants"] == [stray]
    assert (world.folder / "variants" / f"{stray}.json").read_bytes() == before
    assert rows(world, "core.presentation_studio.reconcile_orphans")[0][0] == "warning"
    # the hand-made orphan carries number 9 > counter 4: the next branch is 5, the orphan is never adopted nor collided with
    assert (await variants.create_branch(world.pid, {"title": "suite"}))["node"]["variant_number"] == 5


async def test_a_node_whose_file_is_nowhere_is_a_corrupt_document_reported_at_start_and_on_every_read(world):
    (world.folder / "variants" / f"{world.b}.json").unlink()
    variants = world.fresh()
    summary = await variants.start()
    assert summary["flagged"] == 1
    flagged = rows(world, "core.presentation_studio.reconcile_orphans")
    assert flagged[0][0] == "error" and flagged[0][1]["missing"] == [world.b]
    await refused_code(world.studio.get(world.pid), C.CORRUPT_DOCUMENT)
    await refused_code(variants.graph(world.pid), C.CORRUPT_DOCUMENT)
    await refused_code(variants.create_branch(world.pid, {"title": "x"}), C.CORRUPT_DOCUMENT)


async def test_a_half_copied_linked_document_is_an_orphan_that_is_reported_and_kept(world):
    half = "psr_" + "7" * 12
    (world.folder / "scores" / f"{half}.json").write_text('{"schema": "jarvis.presentation_studio.score", "sc', encoding="utf-8")
    variants = world.fresh()
    await variants.start()
    report = await variants.check(world.pid)
    assert report["orphan_linked"] == {"score": [half], "art_direction": []}
    assert (world.folder / "scores" / f"{half}.json").read_text(encoding="utf-8").endswith('"sc')  # never repaired, never deleted
    assert len(list((world.folder / "scores").glob("*.json"))) == 5  # four real scores and the half copy
    # a half-written temporary of the atomic writer is the store's own leftover: swept, never promoted
    leftover = world.folder / "scores" / f"{'psr_' + '8' * 12}.json.deadbeef.tmp"
    leftover.write_text("{", encoding="utf-8")
    world.studio.store.sweep()
    assert not leftover.exists()


async def test_a_half_copied_art_direction_is_an_orphan_that_is_reported_and_kept(world):
    half = "psd_" + "7" * 12
    (world.folder / "art_directions" / f"{half}.json").write_text('{"schema": "jarvis.presentation_studio.art_dir', encoding="utf-8")
    variants = world.fresh()
    await variants.start()
    report = await variants.check(world.pid)
    assert report["orphan_linked"] == {"score": [], "art_direction": [half]} and report["clean"] is False
    assert (world.folder / "art_directions" / f"{half}.json").read_text(encoding="utf-8").endswith("art_dir")
    leftover = world.folder / "art_directions" / f"{'psd_' + '8' * 12}.json.deadbeef.tmp"
    leftover.write_text("{", encoding="utf-8")
    world.studio.store.sweep()
    assert not leftover.exists(), "the Slice 09 sweep clears our torn temporary of the art direction folder"
    assert rows(world, "core.presentation_studio.reconcile_orphans")


async def test_an_archived_entry_whose_file_is_still_in_variants_is_moved_to_archive_by_the_next_start(world):
    plan = await world.variants.plan_archive(world.pid, world.a)
    await world.variants.archive(world.pid, world.a, {"confirmation": plan["confirmation"]})
    shutil.move(str(world.folder / "archive" / f"{world.c}.json"), str(world.folder / "variants" / f"{world.c}.json"))
    variants = world.fresh()
    summary = await variants.start()
    assert summary["moved"] == 1 and world.files("archive") == {world.a, world.c} and world.files("variants") == {world.one, world.b}
    assert rows(world, "core.presentation_studio.reconciled")[0][0] == "warning"


async def test_the_same_variant_in_both_folders_is_reported_and_neither_copy_is_touched(world):
    plan = await world.variants.plan_archive(world.pid, world.b)
    await world.variants.archive(world.pid, world.b, {"confirmation": plan["confirmation"]})
    shutil.copy(world.folder / "archive" / f"{world.b}.json", world.folder / "variants" / f"{world.b}.json")
    live_bytes, archive_bytes = (world.folder / "variants" / f"{world.b}.json").read_bytes(), (world.folder / "archive" / f"{world.b}.json").read_bytes()
    variants = world.fresh()
    await variants.start()
    assert (await variants.check(world.pid))["duplicate_files"] == [world.b]
    assert (world.folder / "variants" / f"{world.b}.json").read_bytes() == live_bytes
    assert (world.folder / "archive" / f"{world.b}.json").read_bytes() == archive_bytes
    # the manifest still says archived: the graph does not list it live, and restoring it refuses to replace anything
    assert world.b not in {n["variant_id"] for n in (await variants.graph(world.pid))["nodes"]}
    await refused_code(variants.restore(world.pid, world.b), C.ALREADY_EXISTS)


async def test_an_archived_variant_whose_file_vanished_cannot_be_restored_and_says_so(world):
    plan = await world.variants.plan_archive(world.pid, world.b)
    await world.variants.archive(world.pid, world.b, {"confirmation": plan["confirmation"]})
    (world.folder / "archive" / f"{world.b}.json").unlink()
    variants = world.fresh()
    await variants.start()
    report = await variants.check(world.pid)
    assert report["missing"] == [world.b] and report["unverified"] == [world.b] and report["orphan_linked"] == {}
    await refused_code(variants.restore(world.pid, world.b), C.UNKNOWN_VARIANT)
    node = next(n for n in (await variants.graph(world.pid, include_archived=True))["nodes"] if n["variant_id"] == world.b)
    assert node["state"] == "archived" and node["title"] is None and node["problem"] == C.UNKNOWN_VARIANT.value


async def test_an_archived_file_that_disagrees_with_the_manifest_is_never_restored(world):
    plan = await world.variants.plan_archive(world.pid, world.a)
    await world.variants.archive(world.pid, world.a, {"confirmation": plan["confirmation"]})
    path = world.folder / "archive" / f"{world.c}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["parent_variant_id"] = world.one  # re-parented by hand
    path.write_text(json.dumps(document), encoding="utf-8")
    before = world.files("archive")
    await refused_code(world.variants.restore(world.pid, world.c), C.CORRUPT_DOCUMENT)
    assert world.files("archive") == before and world.files("variants") == {world.one, world.b}


async def test_a_slice_02_manifest_is_read_through_its_upgrade_and_rewritten_as_v2_by_the_first_graph_operation(world):
    path = world.folder / "presentation.json"
    document = manifest(world)
    old = {**document, "schema_version": 1, "variants": [{"variant_id": e["variant_id"], "variant_number": e["variant_number"]}
                                                           for e in document["variants"]]}
    del old["archived"]
    path.write_text(json.dumps(old), encoding="utf-8")
    variants = world.fresh()
    await variants.start()
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1, "reading and reconciling never rewrite"
    graph = await variants.graph(world.pid)
    assert [n["created_by"] for n in graph["nodes"]] == ["system"] * 4
    await variants.create_branch(world.pid, {"title": "premiere ecriture"})
    assert manifest(world)["schema_version"] == 2


async def test_a_manifest_from_a_newer_jarvis_is_refused_and_left_untouched(world):
    path = world.folder / "presentation.json"
    path.write_text(json.dumps({**manifest(world), "schema_version": 3}), encoding="utf-8")
    before = path.read_bytes()
    variants = world.fresh()
    summary = await variants.start()
    assert summary["unreadable"] == 1 and rows(world, "core.presentation_studio.reconcile_failed")[0][0] == "error"
    for work in (variants.create_branch(world.pid, {"title": "x"}), variants.switch(world.pid, world.b),
                 variants.rename(world.pid, world.b, {"title": "x"}), variants.graph(world.pid)):
        await refused_code(work, C.UNSUPPORTED_SCHEMA_VERSION)
    assert path.read_bytes() == before


async def test_start_never_raises_on_garbage_and_reports_it(world):
    (world.folder / "presentation.json").write_text("{nope", encoding="utf-8")
    (world.root / "presentations" / "strange-folder").mkdir()
    variants = world.fresh()
    summary = await variants.start()
    assert summary["unreadable"] == 1
    assert rows(world, "core.presentation_studio.reconcile_failed")


async def test_a_counter_below_an_indexed_number_is_corruption_not_a_silent_reuse(world):
    path = world.folder / "presentation.json"
    document = manifest(world)
    document["variant_counter"] = 2  # variants 3 and 4 exist
    path.write_text(json.dumps(document), encoding="utf-8")
    variants = world.fresh()
    await refused_code(variants.create_branch(world.pid, {"title": "x"}), C.CORRUPT_DOCUMENT)
    assert manifest(world)["variant_counter"] == 2


async def test_the_start_report_counts_what_it_found_presentation_by_presentation(tmp_path):
    clean = await World(tmp_path).build()
    halfway = await World(tmp_path).build()
    orphaned = await World(tmp_path).build()
    broken = await World(tmp_path).build()
    (halfway.folder / "archive").mkdir()
    (halfway.folder / "variants" / f"{halfway.c}.json").rename(halfway.folder / "archive" / f"{halfway.c}.json")
    (halfway.folder / "variants" / f"{halfway.a}.json").rename(halfway.folder / "archive" / f"{halfway.a}.json")
    stray = "psv_" + "6" * 32
    (orphaned.folder / "variants" / f"{stray}.json").write_bytes((orphaned.folder / "variants" / f"{orphaned.b}.json").read_bytes())
    (broken.folder / "presentation.json").write_text("{nope", encoding="utf-8")
    variants = clean.fresh()
    summary = await variants.start()
    assert summary == {"presentations": 4, "reconciled": 3, "unreadable": 1, "moved": 2, "flagged": 1}
    again = await variants.start()  # idempotent: the second start finds the orphan again and nothing to move
    assert again == {"presentations": 4, "reconciled": 3, "unreadable": 1, "moved": 0, "flagged": 1}
    reports = {pid: variants._reports[pid] for pid in (clean.pid, halfway.pid, orphaned.pid)}
    assert reports[clean.pid]["clean"] is True and reports[halfway.pid]["moved"] == []  # the 2nd pass found it already fixed
    assert reports[orphaned.pid]["orphan_variants"] == [stray]
    assert len(rows(clean, "core.presentation_studio.reconcile_failed")) == 2  # the broken manifest, once per start


async def test_a_v1_manifest_is_copied_once_before_its_first_rewrite_through_the_service(world):
    path = world.folder / "presentation.json"
    document = manifest(world)
    old = {**document, "schema_version": 1, "variants": [{"variant_id": e["variant_id"], "variant_number": e["variant_number"]}
                                                           for e in document["variants"]]}
    del old["archived"]
    path.write_text(json.dumps(old), encoding="utf-8")
    original = path.read_bytes()
    variants = world.fresh()
    await variants.start()
    await variants.graph(world.pid)
    assert not (world.folder / "presentation.json.v1.bak").exists(), "reading, reconciling and listing copy nothing"
    await variants.create_branch(world.pid, {"title": "ecriture"})
    backup = world.folder / "presentation.json.v1.bak"
    assert backup.read_bytes() == original and manifest(world)["schema_version"] == 2
    await variants.create_branch(world.pid, {"title": "encore"})
    assert backup.read_bytes() == original
