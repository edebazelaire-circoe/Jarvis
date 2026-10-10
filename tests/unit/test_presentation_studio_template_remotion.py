"""Promotion Remotion, un artefact par presentation, partition, licence et provenance (Remotion Slice 19).

Contre le vrai magasin, le vrai `PrefabService` et la vraie API d'edition (le monde de la Slice 20). Contrat : `docs/presentation-studio.md` >
*Template and prefab promotion contract* > *Remotion-aware promotion*, *One artefact per presentation*, *Score skeleton*.
"""

from __future__ import annotations

import base64
import json

import pytest

from jarvis.adapters.file_prefab_library import LIBRARY_DIR
from jarvis.domain import remotion_source
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.remotion_source import source_digest
from tests.fakes.remotion_scene import PNG_1X1, scene_candidate, scene_files
from tests.unit.presentation_studio_template_world import PROJECT_TITLE, World
from tests.unit.test_presentation_studio_score_service import S1, S2, score_body, scene_body

TITLE_VALUE = "Chiffre trimestriel"


def as_bytes(files):
    return {p: v if isinstance(v, bytes) else v.encode("utf-8") for p, v in files.items()}


def catalog(files, *, licence="MIT", verified=True, upstream=True):
    block = {"type": "composition", "compatibility": {"remotion": "native", "slidecar": "unsupported"},
             "stack": ["react", "remotion", "typescript"], "license": licence}
    if upstream:
        block["upstream"] = {"name": "acme/tpl", "url": "https://github.com/acme/tpl", "ref": "v1", "license": licence, "author": "acme"}
        if verified:
            block["upstream"].update({"commit": "a" * 40, "archive_sha256": "b" * 64, "imported_at": "2026-10-01T10:00:00Z",
                                      "changes": ["entry generated"], "source_sha256": source_digest(as_bytes(files))})
            block["runtime_license"] = "Remotion License (company licence may be required)"
    return block


def remo_body(scene_id):
    body = scene_body(scene_id)
    body.update({"prefab": {"id": "lab.remo", "version": 1}, "props": {"title": TITLE_VALUE, "accent": "#ff0000"}, "data": {},
                 "controls": [{"control_id": "headline", "path": "props.title", "label": "Titre", "group": "content"},
                              {"control_id": "accent", "path": "props.accent", "label": "Accent", "group": "visual"}],
                 "anchors": []})
    return body


async def remotion_world(tmp_path, *, files=None, cat="none", verified=False, scenes=(S1, S2)) -> World:
    world = World(tmp_path)
    await world.env.prefabs.start()
    files = files or scene_files()
    options = {"files": files}
    if cat != "none":
        options["catalog"] = cat
    await world.env.prefabs.save(scene_candidate("lab.remo", **options), actor="user", verified_import=verified)
    return await world.open(bodies=[remo_body(s) for s in scenes])


def pick(*scene_ids, dimensions=("accent",), parameters=("headline",)):
    return [{"scene_id": s, "dimensions": list(dimensions), "parameters": list(parameters)} for s in scene_ids]


def read(world, prefab_id, name, version=1):
    return (world.env.data / LIBRARY_DIR / prefab_id / str(version) / name).read_text(encoding="utf-8")


def library_catalog(world, prefab_id, version=1):
    return json.loads(read(world, prefab_id, "manifest.json", version)).get("catalog")


# ------------------------------------------------------------------ une scene Remotion -> un prefab de bibliotheque v3 etiquete


async def test_a_remotion_scene_is_promoted_as_an_engine_tagged_v3_prefab_with_its_tsx_untouched(tmp_path):
    world = await remotion_world(tmp_path)
    body = world.body("scene", slug="titre", scenes=pick(S1), keep_assets=True)
    plan = await world.plan(body)
    assert plan["ok"] is True and plan["scenes"][0]["engine"] == "remotion"
    answer = await world.promote(body)
    assert [p["id"] for p in answer["prefabs"]] == ["studio-template.titre"] and answer["published_to_library"] is True
    promoted = json.loads(read(world, "studio-template.titre", "manifest.json"))
    assert promoted["schema_version"] == 3 and promoted["catalog"]["compatibility"] == {"remotion": "native", "slidecar": "unsupported"}
    assert promoted["catalog"]["type"] == "composition" and promoted["source"]["engine"]["name"] == "remotion"
    for path in promoted["source"]["modules"]:
        assert read(world, "studio-template.titre", path) == read(world, "lab.remo", path), "the TSX is never rewritten"
    props = promoted["inputs"]["props"]["properties"]
    assert props["accent"]["default"] == "#ff0000" and props["title"]["default"] == "[title]", "content default neutralised"
    assert TITLE_VALUE not in world.promoted_text()
    publication = json.loads(read(world, "studio-template.titre", "publication.json"))
    assert publication["provenance"]["origin"] == "fork" and publication["provenance"]["derived_from"] == {"id": "lab.remo", "version": 1}


async def test_assets_of_a_source_that_is_not_an_import_need_an_explicit_keep(tmp_path):
    world = await remotion_world(tmp_path)
    before = world.library_files()
    plan = await world.plan(world.body("scene", scenes=pick(S1)))
    assert plan["ok"] is False and {f["code"] for f in plan["findings"] if f["blocking"]} == {"assets_need_acknowledgement"}
    await world.refused(world.promote(world.body("scene", scenes=pick(S1))), C.TEMPLATE_LEAK)
    assert world.library_files() == before and world.template_files() == {}


@pytest.mark.parametrize("leak", ["project id", "path", "content", "board"])
async def test_hard_coded_project_material_in_tsx_blocks_the_promotion_and_the_tsx_is_not_rewritten(tmp_path, leak):
    comment = {"project id": "// from pss_0000000000a1", "path": "// C:\\Users\\Clarice\\q3.png",
               "content": f"// {TITLE_VALUE}", "board": "// board_9f8e7d6c5b4a"}[leak]
    files = scene_files()
    files["src/lib/Title.tsx"] += comment + "\n"
    world = await remotion_world(tmp_path, files=files)
    before = (world.library_files(), world.template_files())
    plan = await world.plan(world.body("scene", scenes=pick(S1), keep_assets=True))
    blocking = [f for f in plan["findings"] if f["blocking"]]
    assert plan["ok"] is False and blocking and all(f["where"].startswith("scene:s1.source.src/lib/Title.tsx") for f in blocking)
    assert TITLE_VALUE not in json.dumps(plan) and "Clarice" not in json.dumps(plan), "findings carry counts, never the value"
    await world.refused(world.promote(world.body("scene", scenes=pick(S1), keep_assets=True)), C.TEMPLATE_LEAK)
    assert (world.library_files(), world.template_files()) == before


async def test_a_source_the_guards_refuse_today_is_not_promoted(tmp_path, monkeypatch):
    world = await remotion_world(tmp_path)
    monkeypatch.setattr(remotion_source, "SOURCE_GUARDS", (*remotion_source.SOURCE_GUARDS, lambda source: ["a guard added later"]))
    before = (world.library_files(), world.template_files())
    await world.refused(world.promote(world.body("scene", scenes=pick(S1), keep_assets=True)), C.SOURCE_INVALID)
    assert (world.library_files(), world.template_files()) == before


async def test_an_id_taken_by_other_remotion_content_is_a_blocking_finding_and_nothing_is_overwritten(tmp_path):
    world = await remotion_world(tmp_path)
    await world.promote(world.body("scene", scenes=pick(S1), keep_assets=True))
    before = world.library_files()
    other = world.body("scene", scenes=pick(S1, dimensions=(), parameters=()), keep_assets=True)
    plan = await world.plan(other)
    assert plan["ok"] is False and any(f["code"] == "prefab_id_taken" for f in plan["findings"])
    await world.refused(world.promote(other), C.TEMPLATE_LEAK)
    assert world.library_files() == before, "the published version is never rewritten and no second version appears"


# ------------------------------------------------------------------ provenance : verified_intact et licence


async def test_an_intact_import_keeps_its_verified_provenance_when_promoted(tmp_path):
    files = scene_files()
    world = await remotion_world(tmp_path, files=files, cat=catalog(files), verified=True)
    plan = await world.plan(world.body("scene", scenes=pick(S1)))
    assert plan["ok"] is True, "assets of an intact import are upstream's own"
    assert plan["scenes"][0]["verified_import"] is True
    await world.promote(world.body("scene", scenes=pick(S1)))
    view = (await world.env.prefabs.get("studio-template.rapport")).to_dict(catalog=True)["catalog"]
    assert view["upstream"]["verified_intact"] is True and view["upstream"]["commit"] == "a" * 40
    assert view["runtime_license"].startswith("Remotion License")


async def test_a_modified_import_can_never_be_promoted_as_verified(tmp_path):
    files = scene_files()
    world = await remotion_world(tmp_path, files=files, cat=catalog(files), verified=True)
    edited = scene_files("// edited by the user\n")
    revision = scene_candidate("lab.remo", files=edited, catalog=catalog(files))  # a revision carries the previous block unchanged
    await world.env.prefabs.save(revision, actor="user")
    document = world.env.folder(world.pid) / "variants" / f"{world.vid}.json"
    data = json.loads(document.read_text(encoding="utf-8"))
    for scene in data["scenes"]:
        scene["prefab"] = {"id": "lab.remo", "version": 2}
    document.write_text(json.dumps(data), encoding="utf-8")
    body = world.body("scene", scenes=pick(S1), keep_assets=True)
    plan = await world.plan(body)
    assert plan["scenes"][0]["verified_import"] is False
    assert [f["code"] for f in plan["findings"] if f["code"] == "upstream_verification_dropped"] == ["upstream_verification_dropped"]
    await world.promote(body)
    block = library_catalog(world, "studio-template.rapport")
    assert block["upstream"] == {"name": "acme/tpl", "url": "https://github.com/acme/tpl", "ref": "v1", "license": "MIT", "author": "acme"}
    assert "runtime_license" not in block, "nothing Core-verified survives a modification"
    view = (await world.env.prefabs.get("studio-template.rapport")).to_dict(catalog=True)["catalog"]
    assert "verified_intact" not in view["upstream"], "declared by the author, not verified by Core"


async def test_a_restrictive_upstream_licence_needs_an_explicit_named_acknowledgement(tmp_path):
    files = scene_files()
    world = await remotion_world(tmp_path, files=files, cat=catalog(files, licence="GPL-3.0", verified=False))
    body = world.body("scene", scenes=pick(S1), keep_assets=True)
    plan = await world.plan(body)
    assert plan["licences"] == {"GPL-3.0": ["scene:s1"]}
    assert [f["code"] for f in plan["findings"] if f["blocking"]] == ["licence_acknowledgement_required"]
    assert "GPL-3.0" in plan["findings"][0]["message"], "the licence is shown, by name"
    before = world.library_files()
    await world.refused(world.promote(body), C.TEMPLATE_LEAK)
    wrong = world.body("scene", scenes=pick(S1), keep_assets=True, licence_ack=["MIT"])
    await world.refused(world.promote(wrong), C.TEMPLATE_LEAK)
    assert world.library_files() == before
    answer = await world.promote(world.body("scene", scenes=pick(S1), keep_assets=True, licence_ack=["GPL-3.0"]))
    assert [f["code"] for f in answer["findings"]] == ["licence_acknowledged"]
    assert library_catalog(world, "studio-template.rapport")["license"] == "GPL-3.0", "the licence travels with the code"


async def test_an_upstream_without_a_declared_licence_reads_not_declared_and_needs_the_same_step(tmp_path):
    files = scene_files()
    cat = catalog(files, verified=False)
    cat.pop("license")
    cat["upstream"].pop("license")
    world = await remotion_world(tmp_path, files=files, cat=cat)
    plan = await world.plan(world.body("scene", scenes=pick(S1), keep_assets=True))
    assert plan["licences"] == {"not-declared": ["scene:s1"]} and plan["ok"] is False


async def test_a_permitted_licence_or_own_work_needs_no_acknowledgement(tmp_path):
    files = scene_files()
    world = await remotion_world(tmp_path, files=files, cat=catalog(files, verified=False))
    plan = await world.plan(world.body("scene", scenes=pick(S1), keep_assets=True))
    assert plan["licences"] == {} and plan["ok"] is True


# ------------------------------------------------------------------ une presentation = un artefact


async def test_a_remotion_presentation_is_one_artefact_with_embedded_sources_and_publishes_nothing(tmp_path):
    world = await remotion_world(tmp_path)
    library = world.library_files()
    answer = await world.promote(world.body("presentation", scenes=pick(S1, S2), keep_assets=True))
    assert answer["prefabs"] == [] and world.library_files() == library
    (document,) = [json.loads(t) for t in world.template_files().values()]
    (candidate,) = document["embedded"].values()
    assert set(candidate) == {"manifest", "sources", "assets"} and "public/dot.png" in candidate["assets"]
    assert base64.b64decode(candidate["assets"]["public/dot.png"]) == PNG_1X1
    assert document["catalog"]["type"] == "presentation" and document["catalog"]["compatibility"] == {
        "remotion": "native", "slidecar": "unsupported"}
    assert document["prefabs"] == [] and document["scenes"][0]["source"] == document["scenes"][1]["source"]
    assert TITLE_VALUE not in world.promoted_text() and PROJECT_TITLE not in world.promoted_text()


async def test_instantiating_publishes_presentation_scoped_prefabs_and_never_the_library(tmp_path):
    world = await remotion_world(tmp_path)
    answer = await world.promote(world.body("presentation", scenes=pick(S1, S2), keep_assets=True))
    library = world.library_files()
    made = await world.templates.instantiate(answer["template_id"], {"title": "Nouveau rapport"})
    ids = [row["prefab"]["id"] for row in made["rendered"]]
    assert len(set(ids)) == 2 and all(i.startswith(f"presentation-studio.p{made['presentation_id'][4:16]}.s") for i in ids)
    assert all(row["problems"] == [] for row in made["rendered"])
    new_files = set(world.library_files()) - set(library)
    assert new_files and all(name.startswith("presentation-studio.") for name in new_files), "only presentation-scoped sources appear"
    assert not list((world.env.data / LIBRARY_DIR).glob("studio-template.*"))
    variant = await world.studio.get_variant(made["presentation_id"], made["variant_id"])
    assert variant.scenes[0].props["title"] == "[title]" and variant.scenes[0].props["accent"] == "#ff0000"
    assert (await world.studio.get_variant(world.pid, world.vid)).scenes[0].prefab.prefab_id == "lab.remo", "the source is untouched"


async def test_an_embedded_intact_import_is_reverified_at_instantiation_and_a_forged_claim_is_refused(tmp_path):
    files = scene_files()
    world = await remotion_world(tmp_path, files=files, cat=catalog(files), verified=True)
    answer = await world.promote(world.body("presentation", scenes=pick(S1, S2)))
    made = await world.templates.instantiate(answer["template_id"], {"title": "Importe"})
    pin = made["rendered"][0]["prefab"]
    view = (await world.env.prefabs.get(pin["id"], pin["version"])).to_dict(catalog=True)["catalog"]
    assert view["upstream"]["verified_intact"] is True, "Core recomputed the digest from the embedded files"

    path = world.env.root / "presentation_templates" / f"{answer['template_id']}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    (candidate,) = document["embedded"].values()
    candidate["sources"]["src/lib/Title.tsx"] += "// forged\n"  # keeps the importer's keys, changes the files
    path.write_text(json.dumps(document), encoding="utf-8")
    before = [p.name for p in (world.env.root / "presentations").iterdir()]
    await world.refused(world.templates.instantiate(answer["template_id"], {"title": "Forge"}), C.CORRUPT_DOCUMENT)
    assert [p.name for p in (world.env.root / "presentations").iterdir()] == before, "refused before anything was created"


async def test_a_restrictive_licence_also_gates_a_presentation_template(tmp_path):
    files = scene_files()
    world = await remotion_world(tmp_path, files=files, cat=catalog(files, licence="CC-BY-NC-4.0", verified=False))
    await world.refused(world.promote(world.body("presentation", scenes=pick(S1, S2), keep_assets=True)), C.TEMPLATE_LEAK)
    await world.promote(world.body("presentation", scenes=pick(S1, S2), keep_assets=True, licence_ack=["CC-BY-NC-4.0"]))
    (document,) = [json.loads(t) for t in world.template_files().values()]
    assert document["catalog"]["licence_ack"] == ["CC-BY-NC-4.0"] and document["catalog"]["licences"] == ["CC-BY-NC-4.0"]


# ------------------------------------------------------------------ la partition : un squelette, jamais la parole


async def test_the_score_travels_as_a_skeleton_without_speech_cues_or_control_values(tmp_path):
    world = await World(tmp_path).open()
    variant = await world.studio.get_variant(world.pid, world.vid)
    await world.studio.create_score(world.pid, world.vid, {"expected_variant_revision": variant.revision, **score_body()})
    plan = await world.plan(world.body("presentation"))
    assert plan["ok"] is True and plan["score"] == {"items": 3, "carried": "skeleton"}
    answer = await world.promote(world.body("presentation"))
    (document,) = [json.loads(t) for t in world.template_files().values()]
    score = document["score"]
    assert [i["presenter"] for i in score["items"]] == ["jarvis", "user", "none"]
    assert score["cues"] == [] and score["sequences"] == [] and score["recovery_points"] == []
    assert [i["note"] for i in score["items"]] == ["[intention]", "[intention]", ""] and all(i["text"] == "" for i in score["items"])
    assert all(i["cue_id"] is None and i["motion"] == [] for i in score["items"])
    text = json.dumps(score)
    for word in ("Bonjour", "passons", "compact", "Explain", S1, "psi_000000000001"):
        assert word not in text, word
    assert document["report"]["score_dropped"]["cues"] == 1 and document["report"]["score_dropped"]["speech"] == 2

    made = await world.templates.instantiate(answer["template_id"], {"title": "Avec partition"})
    assert made["score_id"]
    got = await world.studio.get_score(made["presentation_id"], made["variant_id"])
    assert got["problems"] == [] and len(got["score"]["items"]) == 3
    assert {i["scene_id"] for i in got["score"]["items"]} <= set(made["scene_ids"])
    assert got["score"]["items"][0]["item_id"] != "psi_000000000001"



# ------------------------------------------------------------------ rien n'est ecrase


async def test_promoting_twice_writes_two_records_and_never_rewrites_the_first(tmp_path):
    world = await remotion_world(tmp_path)
    body = world.body("presentation", scenes=pick(S1, S2), keep_assets=True)
    first = await world.promote(body)
    snapshot = dict(world.template_files())
    library = world.library_files()
    second = await world.promote(body)
    assert first["template_id"] != second["template_id"] and len(world.template_files()) == 2
    assert {k: v for k, v in world.template_files().items() if k in snapshot} == snapshot, "the first record is byte-identical"
    assert world.library_files() == library


async def test_instantiating_twice_gives_two_presentations_with_their_own_source_ids(tmp_path):
    world = await remotion_world(tmp_path)
    answer = await world.promote(world.body("presentation", scenes=pick(S1, S2), keep_assets=True))
    one = await world.templates.instantiate(answer["template_id"], {"title": "Un"})
    two = await world.templates.instantiate(answer["template_id"], {"title": "Deux"})
    ids = {r["prefab"]["id"] for made in (one, two) for r in made["rendered"]}
    assert one["presentation_id"] != two["presentation_id"] and len(ids) == 4, "no source id is shared or reused between presentations"
    assert len(world.template_files()) == 1, "instantiating never touches the record"


# ------------------------------------------------------------------ Remotion Slice 19, rework QA : taille reelle, provenance ancree, scanner, licence, rollback


def heavy_files(*sizes_kb: int) -> dict:
    files = scene_files()
    for n, kb in enumerate(sizes_kb):
        files[f"src/lib/Heavy{n}.tsx"] = "export const note = 1;\n" + "".join(f"// {'x' * 94}\n" for _ in range(kb * 10))
    return files


async def test_the_plan_measures_the_serialized_record_against_the_real_cap_and_says_which_part_weighs(tmp_path):
    """QA B2 probe: 240 + 200 + 200 KB of modules used to read `ok` in the plan and fail at the write."""

    world = await remotion_world(tmp_path, files=heavy_files(240, 200, 200))
    body = world.body("presentation", scenes=pick(S1, S2), keep_assets=True)
    plan = await world.plan(body)
    blocking = [f for f in plan["findings"] if f["blocking"]]
    assert plan["ok"] is False and [f["code"] for f in blocking] == ["embedded_too_large"]
    assert "262144" in blocking[0]["message"] and "embedded sources weigh" in blocking[0]["message"]
    before = (world.library_files(), world.template_files())
    await world.refused(world.promote(body), C.TEMPLATE_LEAK)
    assert (world.library_files(), world.template_files()) == before, "nothing written, no LIMIT error after the fact"


async def test_a_record_close_to_the_real_cap_is_planned_written_read_and_instantiated(tmp_path):
    world = await remotion_world(tmp_path, files=heavy_files(75, 75, 75))
    body = world.body("presentation", scenes=pick(S1, S2), keep_assets=True)
    assert (await world.plan(body))["ok"] is True
    answer = await world.promote(body)
    (path,) = (world.env.root / "presentation_templates").glob("*.json")
    size = path.stat().st_size
    assert 205_000 < size <= 256 * 1024, size
    made = await world.templates.instantiate(answer["template_id"], {"title": "Lourd"})
    assert all(r["problems"] == [] for r in made["rendered"])


async def test_a_hand_edited_record_cannot_forge_a_verified_import_even_when_self_consistent(tmp_path):
    """QA a: files edited, `source_sha256` recomputed, a fake commit, the content hash recomputed: consistent, but nothing Core holds witnesses it."""

    from jarvis.domain.presentation_studio_template_remotion import content_hash
    from jarvis.domain.remotion_source import decode_candidate_files

    files = scene_files()
    world = await remotion_world(tmp_path, files=files, cat=catalog(files), verified=True)
    answer = await world.promote(world.body("presentation", scenes=pick(S1, S2)))
    path = world.env.root / "presentation_templates" / f"{answer['template_id']}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    ((old, candidate),) = document["embedded"].items()
    candidate["sources"]["src/lib/Title.tsx"] += "// edited by hand\n"
    up = candidate["manifest"]["catalog"]["upstream"]
    up["source_sha256"] = source_digest(decode_candidate_files(candidate["sources"], candidate["assets"]))
    up["commit"] = "c" * 40
    document["embedded"] = {content_hash(candidate): candidate}
    for row in document["scenes"]:
        row["source"] = content_hash(candidate)
    path.write_text(json.dumps(document), encoding="utf-8")
    made = await world.templates.instantiate(answer["template_id"], {"title": "Forge coherent"})
    assert {p["provenance"] for p in made["provenance"]} == {"declared_not_reverified"}, "told to the user, not hidden"
    pin = made["rendered"][0]["prefab"]
    view = (await world.env.prefabs.get(pin["id"], pin["version"])).to_dict(catalog=True)["catalog"]
    assert "verified_intact" not in view["upstream"] and "commit" not in view["upstream"] and not view.get("runtime_license")
    assert view["upstream"]["name"] == "acme/tpl", "the origin stays a declaration"


async def test_a_genuine_embedded_import_is_reverified_against_what_the_library_holds(tmp_path):
    files = scene_files()
    world = await remotion_world(tmp_path, files=files, cat=catalog(files), verified=True)
    answer = await world.promote(world.body("presentation", scenes=pick(S1, S2)))
    made = await world.templates.instantiate(answer["template_id"], {"title": "Authentique"})
    assert {p["provenance"] for p in made["provenance"]} == {"verified"}


async def test_the_scanner_knows_the_real_board_grammar_unicode_tricks_svg_text_and_the_words_of_the_score(tmp_path):
    cases = {
        "board_dash_underscore": "// board_9f8e-7d6c_5b4a3c2d",
        "live_ref": "// board:board_abc123def/memory/notes.md",
        "fullwidth_id": "// ｐｓｓ_0000000000a1",
        "fullwidth_path": "// Ｃ:\\Users\\Clarice\\q3.png",
    }
    for name, line in cases.items():
        files = scene_files()
        files["src/lib/Title.tsx"] += line + "\n"
        (tmp_path / name).mkdir()
        world = await remotion_world(tmp_path / name, files=files)
        plan = await world.plan(world.body("scene", scenes=pick(S1), keep_assets=True))
        assert plan["ok"] is False and any(f["blocking"] and f["where"].startswith("scene:s1.source.src/lib/Title.tsx") for f in plan["findings"]), name
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><title>Chiffre trimestriel</title></svg>'
    files = scene_files()
    files["public/logo.svg"] = svg
    (tmp_path / "svg").mkdir()
    world = await remotion_world(tmp_path / "svg", files=files)
    plan = await world.plan(world.body("scene", scenes=pick(S1), keep_assets=True))
    assert any(f["code"] == "project_content" and f["where"].endswith("public/logo.svg") for f in plan["findings"]), "SVG text and metadata are scanned"


async def test_what_the_score_says_counts_as_project_content_in_the_sources(tmp_path):
    files = scene_files()
    files["src/lib/Title.tsx"] += '// "Passons maintenant aux resultats du trimestre"\n'
    world = await remotion_world(tmp_path, files=files)
    variant = await world.studio.get_variant(world.pid, world.vid)
    body = {"start_item_id": "psi_000000000001", "items": [{"item_id": "psi_000000000001", "scene_id": S1, "presenter": "jarvis", "kind": "speech",
                                                              "text": "Passons maintenant aux resultats du trimestre"}],
            "cues": [], "sequences": [], "recovery_points": []}
    await world.studio.create_score(world.pid, world.vid, {"expected_variant_revision": variant.revision, **body})
    plan = await world.plan(world.body("presentation", scenes=pick(S1, S2), keep_assets=True))
    assert any(f["code"] == "project_content" and "Title.tsx" in f["where"] for f in plan["findings"] if f["blocking"])


async def test_a_failure_after_the_presentation_exists_marks_it_names_it_and_deletes_nothing(tmp_path, monkeypatch):
    """QA f: three failure points. Core has no deletion of a presentation or a prefab: the half-made presentation is marked and named."""

    from tests.unit.test_presentation_studio_score_service import score_body

    world = await World(tmp_path).open()
    variant = await world.studio.get_variant(world.pid, world.vid)
    await world.studio.create_score(world.pid, world.vid, {"expected_variant_revision": variant.revision, **score_body()})
    scored = await world.promote(world.body("presentation", slug="note"))
    for step, name in (("save_variant", "save_variant"), ("art_direction", "create_fallback_art_direction"), ("create_score", "create_score")):
        real = getattr(world.studio, name)

        async def boom(*args, **kwargs):
            raise PresentationStudioError(C.STORAGE_IO, "disk full")

        monkeypatch.setattr(world.studio, name, boom)
        before = {p["presentation_id"] for p in (await world.studio.list_presentations()).presentations}
        error = await world.refused(world.templates.instantiate(scored["template_id"], {"title": f"Echec {step}"}), C.STORAGE_IO)
        monkeypatch.setattr(world.studio, name, real)
        created = [p for p in (await world.studio.list_presentations()).presentations if p["presentation_id"] not in before]
        assert len(created) == 1 and created[0]["presentation_id"] in error.message, step
        assert created[0]["title"].startswith("[instantiation échouée] "), "visible in the list"
        assert "nothing was deleted" in error.message
    rows = [r for r in world.sink.rows if r[0] == "core.presentation_studio.template_instantiation_failed"]
    assert len(rows) == 3 and all(r[1] == "warning" for r in rows)
    assert len(world.template_files()) == 1, "the record is untouched"


async def test_a_failure_while_installing_embedded_sources_leaves_unpinned_prefabs_and_a_marked_presentation(tmp_path, monkeypatch):
    world = await remotion_world(tmp_path)
    answer = await world.promote(world.body("presentation", scenes=pick(S1, S2), keep_assets=True))
    real = world.env.prefabs.save
    calls = {"n": 0}

    async def second_save_fails(candidate, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode

            raise PrefabStoreError(PrefabStoreErrorCode.STORAGE_IO, "disk full")
        return await real(candidate, **kwargs)

    monkeypatch.setattr(world.env.prefabs, "save", second_save_fails)
    error = await world.refused(world.templates.instantiate(answer["template_id"], {"title": "Moitie"}), C.STORAGE_IO)
    assert "[instantiation échouée]" in error.message and "nothing was deleted" in error.message
    listed = (await world.studio.list_presentations()).presentations
    assert any(p["title"].startswith("[instantiation échouée] ") for p in listed)


async def test_a_duplicate_key_or_nan_in_a_record_is_corruption_and_the_hash_of_every_source_is_checked(tmp_path):
    world = await remotion_world(tmp_path)
    answer = await world.promote(world.body("presentation", scenes=pick(S1, S2), keep_assets=True))
    path = world.env.root / "presentation_templates" / f"{answer['template_id']}.json"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('"kind": "presentation",', '"kind": "presentation", "kind": "presentation",', 1), encoding="utf-8")
    await world.refused(world.templates.get_template(answer["template_id"]), C.CORRUPT_DOCUMENT)
    path.write_text(text.replace('"revision": 1', '"revision": NaN'), encoding="utf-8")
    await world.refused(world.templates.get_template(answer["template_id"]), C.CORRUPT_DOCUMENT)
    document = json.loads(text)
    ((key, candidate),) = document["embedded"].items()
    candidate["sources"]["src/Scene.tsx"] += "// tampered\n"
    path.write_text(json.dumps(document), encoding="utf-8")
    error = await world.refused(world.templates.get_template(answer["template_id"]), C.CORRUPT_DOCUMENT)
    assert "content hash" in error.message


def test_licence_names_can_be_as_long_as_an_upstream_licence():
    from jarvis.domain.presentation_studio_template import MAX_LICENCE_NAME, parse_promote

    assert MAX_LICENCE_NAME == 120
    request = parse_promote({"kind": "scene", "title": "x", "slug": "x", "licence_ack": ["L" * 120]}, strict=False)
    assert request.licence_ack == ("L" * 120,)


async def test_the_brain_cannot_give_a_licence_acknowledgement_or_keep_assets_even_straight_to_core(tmp_path):
    files = scene_files()
    world = await remotion_world(tmp_path, files=files, cat=catalog(files, licence="GPL-3.0", verified=False))
    for extra in ({"licence_ack": ["GPL-3.0"]}, {"keep_assets": True}):
        await world.refused(world.promote(world.body("scene", scenes=pick(S1), actor="brain", **extra)), C.INVALID_PRESENTATION)
    assert world.template_files() == {} and not list((world.env.data / LIBRARY_DIR).glob("studio-template.*"))
