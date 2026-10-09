"""Promotion et instanciation de modeles contre le vrai magasin, le vrai PrefabService et la vraie API d'edition (Slice 20).

Selection explicite, assainissement (plus aucun contenu du projet dans la bibliotheque partagee ni dans le modele), detection de fuites
qui interdit l'ecriture, parametrage, derivation, deduplication, reprise apres une panne entre les deux ecritures, et
instanciation-rendu d'un modele promu. Contrat : `docs/presentation-studio.md` > *Template and prefab promotion contract*.
"""

from __future__ import annotations

import json
import re

import pytest

from jarvis.adapters.file_prefab_library import LIBRARY_DIR
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_art_direction_authoring import generate_fallback_profile
from tests.unit.presentation_studio_template_world import PROJECT_TITLE, PROJECT_WORDS, World, hero_source
from tests.unit.test_presentation_studio_score_service import S1, S2

PROJECT_ID = re.compile(r"\b(?:pst|psv|pss|psx|psc|psi|psa)_[0-9a-f]{6,}\b|presentation-studio\.|lab\.counter")


def prefab_file(world: World, prefab_id: str, name: str, version: int = 1) -> str:
    return (world.env.data / LIBRARY_DIR / prefab_id / str(version) / name).read_text(encoding="utf-8")


def manifest(world: World, prefab_id: str, version: int = 1) -> dict:
    return json.loads(prefab_file(world, prefab_id, "manifest.json", version))


def publication(world: World, prefab_id: str, version: int = 1) -> dict:
    return json.loads(prefab_file(world, prefab_id, "publication.json", version))


def only_template(world: World) -> dict:
    files = world.template_files()
    assert len(files) == 1
    return json.loads(next(iter(files.values())))


@pytest.fixture
async def world(tmp_path) -> World:
    return await World(tmp_path).open(props={"accent": "#ff0000"})


# ------------------------------------------------------------------ plan : decrit, n'ecrit rien

async def test_the_plan_lists_the_candidates_and_writes_nothing(world):
    before = (world.library_files(), world.template_files(), world.project_files())
    plan = await world.plan(world.body("presentation", scenes=False))
    assert plan["ok"] is True and plan["selection_required"] is True and plan["blocking"] == 0
    first = plan["scenes"][0]
    controls = {c["control_id"]: c for c in first["controls"]}
    assert controls["accent"]["eligible_dimension"] is True and controls["accent"]["role"] == "look"
    assert controls["headline"]["eligible_dimension"] is False and controls["headline"]["role"] == "content"
    assert first["source"] == {"id": "lab.counter", "version": 1}
    assert plan["would_publish"] == ["studio-template.rapport-1"]  # the two scenes share one sanitized source
    assert (world.library_files(), world.template_files(), world.project_files()) == before
    text = json.dumps(plan, ensure_ascii=False)
    for word in (*PROJECT_WORDS, PROJECT_TITLE, "#ff0000"):
        assert word not in text, "the plan never echoes a value of the project"


async def test_a_promotion_without_the_explicit_selection_is_refused(world):
    before = (world.library_files(), world.template_files())
    missing = await world.refused(world.promote(world.body("presentation", scenes=False)), C.TEMPLATE_SELECTION_REQUIRED)
    assert "plan" in missing.message
    partial = world.body("presentation", scenes=[{"scene_id": S1, "dimensions": [], "parameters": []}])
    assert "1 scene" in (await world.refused(world.promote(partial), C.TEMPLATE_SELECTION_REQUIRED)).message
    await world.refused(world.promote(world.body("art_direction")), C.TEMPLATE_SELECTION_REQUIRED)
    assert (world.library_files(), world.template_files()) == before


async def test_a_content_control_cannot_be_kept_as_a_dimension(world):
    body = world.body("scene", scenes=[{"scene_id": S1, "dimensions": ["headline"], "parameters": []}])
    error = await world.refused(world.promote(body), C.INVALID_PRESENTATION)
    assert "parameter" in error.message
    for scenes, fragment in (
            ([{"scene_id": S1, "dimensions": ["nope"], "parameters": []}], "not controls of this scene"),
            ([{"scene_id": S1, "dimensions": ["accent"], "parameters": ["accent"]}], "both as dimension and as parameter")):
        refused = await world.refused(world.promote(world.body("scene", scenes=scenes)), C.INVALID_PRESENTATION)
        assert fragment in refused.message
    await world.refused(world.promote(world.body("scene", scenes=[{"scene_id": "pss_00000000beef", "dimensions": [],
                                                                     "parameters": []}])), C.UNKNOWN_SCENE)
    assert world.template_files() == {} and not list((world.env.data / LIBRARY_DIR).glob("studio-template.*"))


# ------------------------------------------------------------------ une scene -> un prefab de la bibliotheque partagee

async def test_a_scene_becomes_a_forked_prefab_of_the_shared_library_without_project_content(world):
    answer = await world.promote(world.body("scene", slug="titre", title="Titre de section", description="Un titre propre."))
    assert [p["id"] for p in answer["prefabs"]] == ["studio-template.titre"] and answer["prefabs"][0]["version"] == 1
    published = publication(world, "studio-template.titre")
    assert published["provenance"]["origin"] == "fork"
    assert published["provenance"]["derived_from"] == {"id": "lab.counter", "version": 1}
    assert published["provenance"]["created_by"] == {"actor": "user"}

    candidate = manifest(world, "studio-template.titre")
    assert candidate["aliases"] == [] and "presentation-template" in candidate["tags"]
    assert candidate["title"] == "Titre de section" and candidate["description"].startswith("Un titre propre.")
    props = candidate["inputs"]["props"]["properties"]
    assert props["accent"]["default"] == "#ff0000", "the chosen dimension keeps its look"
    assert props["label"]["default"] == "[label]", "a content default is replaced by a neutral placeholder"
    assert candidate["sample"]["props"]["label"] == "[label]" and candidate["sample"]["data"]["count"] == 0
    # the source is the project's source (reusable code), not a copy of the project's values
    assert prefab_file(world, "studio-template.titre", "template.html") == prefab_file(world, "lab.counter", "template.html")

    document = only_template(world)
    scene = document["scenes"][0]["scene"]
    assert scene["prefab"] == {"id": "studio-template.titre", "version": 1}
    assert scene["props"]["label"] == "[label]" and scene["props"]["accent"] == "#ff0000"
    assert scene["title"] == "" and scene["section"] == "" and scene["preview"] == {"caption": "", "alt": ""}
    assert [c["control_id"] for c in scene["controls"]] == ["headline", "accent", "count"], "only the selected controls remain"
    assert all(c.get("default") is None for c in scene["controls"])
    assert [a["anchor_id"] for a in scene["anchors"]] == ["reveal", "marker"]
    roles = {(p["control_id"], p["kind"]) for p in document["parameters"]}
    assert roles == {("headline", "parameter"), ("accent", "dimension"), ("count", "parameter")}


async def test_no_trace_of_the_project_survives_in_the_library_or_the_template(world):
    await world.promote(world.body("presentation", title="Rapport type"))
    text = world.promoted_text()
    for word in (*PROJECT_WORDS, PROJECT_TITLE):
        assert word not in text
    assert not PROJECT_ID.search(text.replace("studio-template.", "")), PROJECT_ID.findall(text)
    document = only_template(world)
    assert "derived_from" in document, "the derivation is the one place the project is named"


async def test_an_unselected_look_returns_to_the_source_default_instead_of_the_projects_value(world):
    body = world.body("scene", scenes=[{"scene_id": S1, "dimensions": [], "parameters": ["headline"]}])
    await world.promote(body)
    assert "#ff0000" not in world.promoted_text()
    assert manifest(world, "studio-template.rapport")["inputs"]["props"]["properties"]["accent"]["default"] == "#6ee7ff"
    plan = await world.plan(body)
    assert plan["scenes"][0]["stripped"]["look_reset"] == 1 and plan["scenes"][0]["kept"] == {"dimensions": 0, "parameters": 1}


# ------------------------------------------------------------------ detection : la fuite interdit l'ecriture

LEAKS = {
    "content in the template": hero_source(template='<section class="jv-panel"><h2>Visiteurs</h2>'
                                                    '<p class="count" data-jv-text="data.count"></p></section>'),
    "a project id in the style": hero_source(style=".count { color: var(--jv-accent); } /* from pss_0000000000a1 */"),
    "a local path in the behavior": hero_source(behavior="jarvis.on('init', function () { var f = 'C:\\\\Users\\\\Clarice\\\\q3.png'; });"),
}


@pytest.mark.parametrize("leak", LEAKS)
async def test_hard_coded_project_material_blocks_the_promotion_and_nothing_is_written(tmp_path, leak):
    world = await World(tmp_path).open(sources={"lab.leaky": LEAKS[leak]}, scene_prefab="lab.leaky")
    before = (world.library_files(), world.template_files())
    plan = await world.plan(world.body("scene"))
    assert plan["ok"] is False and plan["blocking"] >= 1
    codes = {f["code"] for f in plan["findings"] if f["blocking"]}
    assert codes & {"project_content", "project_identifier", "local_path"}
    assert "Visiteurs" not in json.dumps(plan) and "Clarice" not in json.dumps(plan), "findings carry counts, never the value"
    error = await world.refused(world.promote(world.body("scene")), C.TEMPLATE_LEAK)
    assert "nothing written" in error.message and error.status == 409
    assert (world.library_files(), world.template_files()) == before


async def test_a_generic_external_url_is_a_warning_not_a_refusal(tmp_path):
    source = hero_source(template='<section class="jv-panel"><a href="https://docs.example.org/guide">guide</a>'
                                  '<h2 data-jv-text="props.label"></h2></section>')
    world = await World(tmp_path).open(sources={"lab.linked": source}, scene_prefab="lab.linked")
    answer = await world.promote(world.body("scene"))
    assert [f["code"] for f in answer["findings"]] == ["external_url"] and answer["findings"][0]["blocking"] is False


async def test_a_presentation_resource_locator_is_content_of_the_project(tmp_path):
    source = hero_source(behavior="jarvis.on('init', function () { /* see docs/rapport-trimestriel.pdf */ });")
    world = await World(tmp_path).open(sources={"lab.res": source}, scene_prefab="lab.res")
    presentation = await world.studio.get(world.pid)
    await world.studio.save_presentation(world.pid, {
        "expected_revision": presentation.presentation.revision, "title": PROJECT_TITLE,
        "active_variant_id": world.vid,
        "resources": [{"kind": "document", "locator": "docs/rapport-trimestriel.pdf", "title": "Rapport"}]})
    plan = await world.plan(world.body("scene"))
    assert plan["ok"] is False and {f["where"] for f in plan["findings"]} >= {"scene:s1.source.behavior"}


# ------------------------------------------------------------------ presentation entiere, deduplication, derivation

async def test_a_whole_variant_is_promoted_with_one_shared_prefab_per_sanitized_source(world):
    answer = await world.promote(world.body("presentation"))
    assert [p["id"] for p in answer["prefabs"]] == ["studio-template.rapport-1"], "identical sanitized scenes share a prefab"
    document = only_template(world)
    assert [s["key"] for s in document["scenes"]] == ["s1", "s2"] and document["kind"] == "presentation"
    assert document["derived_from"]["scenes"] == [
        {"key": "s1", "scene_id": S1, "prefab": {"id": "lab.counter", "version": 1}},
        {"key": "s2", "scene_id": S2, "prefab": {"id": "lab.counter", "version": 1}}]
    assert document["derived_from"]["presentation_id"] == world.pid
    assert document["art_direction"] is None and document["prefabs"] == [{"id": "studio-template.rapport-1", "version": 1}]


async def test_scenes_that_keep_different_looks_get_their_own_prefab(world):
    scenes = [{"scene_id": S1, "dimensions": ["accent"], "parameters": ["headline"]},
              {"scene_id": S2, "dimensions": [], "parameters": ["headline"]}]
    answer = await world.promote(world.body("presentation", scenes=scenes))
    assert [p["id"] for p in answer["prefabs"]] == ["studio-template.rapport-1", "studio-template.rapport-2"]
    assert publication(world, "studio-template.rapport-2")["provenance"]["derived_from"] == {"id": "lab.counter", "version": 1}


async def test_the_brain_actor_is_recorded_on_the_library_publication(world):
    await world.promote(world.body("scene", actor="brain"))
    assert publication(world, "studio-template.rapport")["provenance"]["created_by"] == {"actor": "brain"}
    assert only_template(world)["created_by"] == "brain"


# ------------------------------------------------------------------ reprise, identifiants pris, panne entre les deux ecritures

async def test_repeating_the_same_promotion_reuses_the_published_prefab(world):
    first = await world.promote(world.body("scene"))
    second = await world.promote(world.body("scene"))
    assert first["prefabs"][0]["published"] is True and second["prefabs"][0] == {
        "id": "studio-template.rapport", "version": 1, "published": False, "reused": True}
    assert len(list((world.env.data / LIBRARY_DIR / "studio-template.rapport").iterdir())) == 1, "no second version"
    assert len(world.template_files()) == 2 and first["template_id"] != second["template_id"]


async def test_an_id_taken_by_other_content_is_a_blocking_finding(world):
    await world.promote(world.body("scene"))
    other = world.body("scene", scenes=[{"scene_id": S1, "dimensions": [], "parameters": []}])
    plan = await world.plan(other)
    assert plan["ok"] is False and plan["scenes"][0]["prefab_state"] == "taken"
    assert any(f["code"] == "prefab_id_taken" for f in plan["findings"])
    await world.refused(world.promote(other), C.TEMPLATE_LEAK)


async def test_a_failure_between_the_two_writes_leaves_a_resumable_state(world, monkeypatch):
    real = world.store.create
    calls = {"n": 0}

    def flaky(template_id, text):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PresentationStudioError(C.STORAGE_IO, "disk full")
        return real(template_id, text)

    monkeypatch.setattr(world.store, "create", flaky)
    await world.refused(world.promote(world.body("scene")), C.STORAGE_IO)
    assert world.template_files() == {} and (world.env.data / LIBRARY_DIR / "studio-template.rapport" / "1").is_dir()
    warned = [row for row in world.sink.rows if row[0] == "core.presentation_studio.template_orphans"]
    assert warned and warned[0][1] == "warning"
    resumed = await world.promote(world.body("scene"))
    assert resumed["prefabs"][0]["reused"] is True and len(world.template_files()) == 1


async def test_a_stale_revision_and_an_unconfirmed_reload_are_refused(tmp_path):
    world = await World(tmp_path).open(extra_versions=(2,), props={"accent": "#ff0000"})
    variant = await world.studio.get_variant(world.pid, world.vid)
    await world.refused(world.promote(world.body("scene", expected_revision=variant.revision + 5)), C.STALE_REVISION)

    # a hot reload published version 2 and the host has not confirmed it yet: the document says so (`last_valid_pin`)
    path = world.env.folder(world.pid) / "variants" / f"{world.vid}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    for scene in document["scenes"]:
        scene["prefab"] = {"id": "lab.counter", "version": 2}
        scene["last_valid_pin"] = {"id": "lab.counter", "version": 1}
    path.write_text(json.dumps(document), encoding="utf-8")
    await world.refused(world.promote(world.body("scene")), C.SCENE_RELOADING)
    assert world.template_files() == {}


# ------------------------------------------------------------------ instanciation et rendu

async def test_a_promoted_presentation_is_instantiated_into_a_new_presentation_that_renders(world):
    answer = await world.promote(world.body("presentation"))
    source_before = world.project_files()
    made = await world.templates.instantiate(answer["template_id"], {"title": "Nouveau rapport"})
    assert made["kind"] == "presentation" and made["presentation_id"] != world.pid
    assert len(made["scene_ids"]) == 2 and made["art_direction_id"].startswith("psd_")
    for row in made["rendered"]:
        assert row["problems"] == [] and row["payload"]["bytes"] > 0
        assert row["prefab"] == {"id": "studio-template.rapport-1", "version": 1}
    variant = await world.studio.get_variant(made["presentation_id"], made["variant_id"])
    scene = variant.scenes[0]
    assert scene.props["label"] == "[label]" and scene.props["accent"] == "#ff0000" and scene.data["count"] == 0
    assert scene.scene_id not in (S1, S2) and scene.source_revision == 0 and scene.last_valid_pin is None
    assert [c.control_id for c in scene.controls] == ["headline", "accent", "count"]
    stage = await world.studio.describe_scene(made["presentation_id"], made["variant_id"], scene.scene_id)
    assert stage["stage"]["mode"] == "patch_stable_window" and stage["problems"] == []
    # the instantiated work is validated by the same gates as any scene: its prefab is a healthy version of the shared library
    detail = await world.env.prefabs.get("studio-template.rapport-1", 1)
    assert detail.entry.ok
    assert world.project_files() == source_before, "instantiating never touches the source presentation"


async def test_a_promoted_scene_is_added_to_a_variant_through_the_edit_api(world):
    answer = await world.promote(world.body("scene", scenes=[{"scene_id": S1, "dimensions": ["accent"],
                                                              "parameters": ["headline"]}]))
    target = await world.studio.get_variant(world.pid, world.vid)
    made = await world.templates.instantiate(answer["template_id"], {
        "presentation_id": world.pid, "variant_id": world.vid, "expected_revision": target.revision})
    after = await world.studio.get_variant(world.pid, world.vid)
    added = after.scenes[-1]
    assert made["kind"] == "scene" and made["scene_id"] == added.scene_id and added.scene_id not in (S1, S2)
    assert len(after.scenes) == 3 and added.prefab.prefab_id == "studio-template.rapport"
    assert added.props["label"] == "[label]" and after.revision == made["revision"]
    await world.refused(world.templates.instantiate(answer["template_id"], {
        "presentation_id": world.pid, "variant_id": world.vid, "expected_revision": target.revision}), C.STALE_REVISION)
    await world.refused(world.templates.instantiate(answer["template_id"], {}), C.INVALID_PRESENTATION)


async def test_instantiating_needs_every_library_version_the_template_cites(world):
    answer = await world.promote(world.body("presentation"))
    folder = world.env.data / LIBRARY_DIR / "studio-template.rapport-1" / "1" / "template.html"
    folder.write_text(folder.read_text(encoding="utf-8") + "<!-- tampered -->", encoding="utf-8")
    await world.env.prefabs.start()  # rescan: the version no longer matches its publication
    await world.refused(world.templates.instantiate(answer["template_id"], {"title": "X"}), C.PREFAB_UNAVAILABLE)


# ------------------------------------------------------------------ direction artistique et mouvement

async def art_world(tmp_path) -> World:
    from jarvis.domain.presentation_studio_art_direction import ArtDirectionProfile

    tmp_path.mkdir(parents=True, exist_ok=True)
    world = await World(tmp_path).open(art=False)
    document = generate_fallback_profile({"title": PROJECT_TITLE}).to_dict()
    document["name"] = "Atelier Hammer maison"
    document["imagery"]["motifs"] = ["logo Atelier Hammer"]
    document["references"] = [{"kind": "document", "locator": "docs/charte-hammer.pdf", "title": "Charte Hammer"}]
    document["provenance"] = {"origin": "inferred", "sections": {}, "fallback": False, "confidence": 0.9,
                              "notes": ["extracted from the Hammer deck"]}
    await world.add_art(ArtDirectionProfile.from_dict(document))
    return world


async def test_an_art_direction_is_promoted_without_name_references_notes_or_motifs(tmp_path):
    world = await art_world(tmp_path)
    body = world.body("art_direction", slug="charte", title="Charte sobre",
                      art_direction={"sections": ["palette", "dataviz", "typography", "imagery"]})
    plan = await world.plan(body)
    assert plan["ok"] is True and plan["art_direction"]["stripped"]["references_dropped"] == 1
    assert plan["art_direction"]["stripped"]["motifs_dropped"] == 1
    answer = await world.promote(body)
    assert answer["prefabs"] == [] and answer["kind"] == "art_direction"
    text = world.promoted_text()
    for leak in ("Hammer", "charte-hammer", "extracted"):
        assert leak not in text
    document = only_template(world)
    assert sorted(document["art_direction"]["sections"]) == ["dataviz", "imagery", "palette", "typography"]
    assert document["art_direction"]["sections"]["imagery"]["motifs"] == []
    assert not list((world.env.data / LIBRARY_DIR).glob("studio-template.*")), "the library holds prefabs only: no DA entry"


async def test_kept_motifs_that_name_the_project_block_the_promotion(tmp_path):
    world = await art_world(tmp_path)
    body = world.body("art_direction", art_direction={"sections": ["imagery"], "motifs": "keep"})
    plan = await world.plan(body)
    assert plan["ok"] is False and any(f["where"] == "art_direction.imagery.motifs" for f in plan["findings"])
    await world.refused(world.promote(body), C.TEMPLATE_LEAK)


async def test_a_motion_pattern_overlays_the_destinations_art_direction_and_keeps_its_references(tmp_path):
    source = await art_world(tmp_path / "source")
    answer = await source.promote(source.body("motion", slug="mouvement", title="Mouvement lent"))
    assert list(only_template(source)["art_direction"]["sections"]) == ["motion"]

    # the destination has its own references; the motion template must leave them alone
    destination = await art_world(tmp_path / "destination")
    template_id = answer["template_id"]
    destination.store.create(template_id, source.template_files()[f"{template_id}.json"])
    variant = await destination.studio.get_variant(destination.pid, destination.vid)
    before = (await destination.studio.get_art_direction(destination.pid, destination.vid))["art_direction"]["profile"]
    made = await destination.templates.instantiate(template_id, {
        "presentation_id": destination.pid, "variant_id": destination.vid, "expected_revision": variant.revision})
    after = (await destination.studio.get_art_direction(destination.pid, destination.vid))["art_direction"]
    assert made["sections"] == ["motion"] and after["revision"] == 2
    assert after["profile"]["references"] == before["references"] and after["profile"]["palette"] == before["palette"]
    assert after["profile"]["name"] == before["name"]
    assert after["profile"]["provenance"]["sections"]["motion"] == "provided"


async def test_promoting_an_art_direction_needs_the_variant_to_have_one(tmp_path):
    world = await World(tmp_path).open(art=False)
    await world.refused(world.promote(world.body("motion")), C.UNKNOWN_ART_DIRECTION)


async def test_a_presentation_template_can_carry_selected_art_direction_sections(tmp_path):
    world = await art_world(tmp_path)
    answer = await world.promote(world.body("presentation", art_direction={"sections": ["palette", "dataviz", "motion"]}))
    document = only_template(world)
    assert sorted(document["art_direction"]["sections"]) == ["dataviz", "motion", "palette"]
    made = await world.templates.instantiate(answer["template_id"], {"title": "Autre"})
    art = (await world.studio.get_art_direction(made["presentation_id"], made["variant_id"]))["art_direction"]["profile"]
    assert art["palette"] == document["art_direction"]["sections"]["palette"] and art["references"] == []
    assert "Hammer" not in json.dumps(art)


# ------------------------------------------------------------------ lecture, redemarrage, fichiers abimes

async def test_templates_are_listed_read_and_survive_a_restart(world):
    scene = await world.promote(world.body("scene"))
    deck = await world.promote(world.body("presentation", slug="deck", title="Deck"))
    restarted = world.service()
    listing = await restarted.list_templates()
    assert listing["count"] == 2 and {r["template_id"] for r in listing["templates"]} == {scene["template_id"], deck["template_id"]}
    assert [r["kind"] for r in (await restarted.list_templates("scene"))["templates"]] == ["scene"]
    got = await restarted.get_template(deck["template_id"])
    assert got["template"]["template_id"] == deck["template_id"] and got["prefab_availability"] == [
        {"id": "studio-template.deck-1", "version": 1, "available": True}]
    await world.refused(restarted.get_template("ptp_00000000dead"), C.UNKNOWN_TEMPLATE)
    await world.refused(restarted.get_template("../x"), C.INVALID_PRESENTATION)
    with pytest.raises(PresentationStudioError):
        await restarted.list_templates("nope")


async def test_a_damaged_or_newer_template_is_reported_not_hidden(world):
    answer = await world.promote(world.body("scene"))
    folder = world.env.root / "presentation_templates"
    (folder / "ptp_aaaaaaaaaaaa.json").write_text("{not json", encoding="utf-8")
    document = json.loads((folder / f"{answer['template_id']}.json").read_text(encoding="utf-8"))
    document["schema_version"] = 9
    (folder / "ptp_bbbbbbbbbbbb.json").write_text(json.dumps(document), encoding="utf-8")
    listing = await world.service().list_templates()
    assert listing["count"] == 1
    assert {p["template_id"]: p["code"] for p in listing["problems"]} == {
        "ptp_aaaaaaaaaaaa": C.CORRUPT_DOCUMENT.value, "ptp_bbbbbbbbbbbb": C.UNSUPPORTED_SCHEMA_VERSION.value}


async def test_a_template_document_cannot_carry_a_prefab_definition(world):
    answer = await world.promote(world.body("scene"))
    path = world.env.root / "presentation_templates" / f"{answer['template_id']}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["manifest"] = {"id": "x.y"}
    path.write_text(json.dumps(document), encoding="utf-8")
    await world.refused(world.service().get_template(answer["template_id"]), C.INVALID_PRESENTATION)


async def test_diagnostics_carry_ids_and_counts_never_project_words(world):
    await world.promote(world.body("presentation"))
    await world.plan(world.body("presentation", scenes=False))
    rows = [row for row in world.sink.rows if row[0].startswith("core.presentation_studio.template_")]
    assert {r[0] for r in rows} >= {"core.presentation_studio.template_planned", "core.presentation_studio.template_promoted"}
    dumped = json.dumps(rows, ensure_ascii=False)
    for word in (*PROJECT_WORDS, PROJECT_TITLE, "Rapport type"):
        assert word not in dumped
