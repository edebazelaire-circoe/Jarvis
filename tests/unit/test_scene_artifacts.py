"""Artefacts sémantiques de la scène constellation (handoff jarvis-constellation-scene-runtime, Slice 07).

Ce qui doit tenir :

- `attach_artifact` (domaine) écrit l'artefact **et** son lien `explains` dans un
  seul patch, ou rien : aucun refus du lien ne laisse d'artefact orphelin ;
- `scene_add_artifact` (outil du cerveau) garde **un** artefact par cible et par
  catégorie : un nouvel appel complète l'existant, un artefact archivé par
  l'utilisateur n'est jamais repris ; refus rendus avec leur motif ;
- arguments stricts et bornés, catalogue toujours sans archivage ni épinglage ;
- la consigne des artefacts n'existe qu'avec l'interrupteur, et le prompt sans
  interrupteur reste octet pour octet celui d'avant ;
- le rendu : vue d'inspection (catégorie, origine, entrées), liens ouvrables
  seulement pour une URL http(s) validée, jamais `innerHTML` ;
- l'archivage groupé ne prend jamais un artefact, l'archivage d'une étoile ne
  l'emporte pas (Décision 12, Slice 08).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import re

import pytest

from jarvis.domain.prompt_registry import PromptTarget
from jarvis.domain.scene import (
    MAX_PAYLOAD_ITEMS,
    MAX_SCENE_OBJECTS,
    MAX_SCENE_RELATIONS,
    ExecState,
    PatchOpKind,
    RelationKind,
    Representation,
    SceneCommand,
    SceneGeometry,
    SceneObjectFields,
    SceneObjectKind,
    SceneOp,
    ScenePayload,
    ScenePayloadItem,
    SceneRefusal,
    SceneRelation,
    SceneSnapshot,
    apply_scene_command,
)
from jarvis.runtime import claude_local
from jarvis.runtime.claude_local import BRAIN_ARTIFACT_PROMPT, BRAIN_DISPLAY_PROMPT, BRAIN_SYSTEM_PROMPT
from jarvis.runtime.display_mcp import (
    ARTIFACT_GROUPING_RULE,
    RECOMMENDED_ARTIFACT_CATEGORIES,
    TOOL_NAMES,
    DisplayMcpTarget,
    DisplayToolError,
    SceneDisplayTools,
    build_server,
)
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.prompt_catalog import default_prompt_registry
from jarvis.runtime.scene_view import CoreSceneTransport
from tests.integration.test_scene_transport import CoreProcess
from tests.unit.test_display_mcp import SpyTransport, observe, scene_object, user_command, wait_for
from tests.unit.test_scene_contracts import (
    APPLIED,
    BRAIN,
    DUPLICATE,
    GEO,
    GEO_2,
    INVALID,
    REJECTED,
    RUNTIME,
    USER,
    assert_unchanged,
    cmd,
    run,
    scene_with_stars,
    star,
    upsert,
)
from tests.unit.test_scene_renderer_logic import LAYOUT_JS, PAGE_JS, run_node
from tests.unit.test_scene_service import MemoryRepository


def attach(actor=BRAIN, object_id="art-new", target_id="star-a", relation_id="rel-art-new", **fields) -> SceneCommand:
    values = {"category": "research", "payload": ScenePayload(title="Liens officiels")}
    values.update(fields)
    return cmd(SceneOp.ATTACH_ARTIFACT, actor, object_id=object_id, target_id=target_id, relation_id=relation_id,
               fields=SceneObjectFields(**values))


# ------------------------------------------------------------------ domaine


def test_attach_artifact_writes_the_artifact_and_its_explains_link_in_one_revision():
    before = scene_with_stars()
    update = apply_scene_command(before, attach())
    assert update.outcome is APPLIED and update.snapshot.revision == before.revision + 1
    assert [op.op for op in update.patch.ops] == [PatchOpKind.PUT_OBJECT, PatchOpKind.PUT_RELATION]
    artifact = update.snapshot.get_object("art-new")
    assert artifact.kind is SceneObjectKind.ARTIFACT and artifact.origin is BRAIN and artifact.layer == 120
    relation = update.snapshot.get_relation("rel-art-new")
    assert relation.endpoints == (RelationKind.EXPLAINS, "art-new", "star-a")
    # Rejouer la même commande ne change rien.
    again = apply_scene_command(update.snapshot, attach())
    assert again.outcome is DUPLICATE and again.patch is None
    # Mettre à jour la charge garde le lien, une seule révision.
    richer = apply_scene_command(update.snapshot, attach(payload=ScenePayload(
        title="Liens officiels", items=(ScenePayloadItem(label="Site", url="https://example.org"),))))
    assert [op.op for op in richer.patch.ops] == [PatchOpKind.PUT_OBJECT]
    assert len(richer.snapshot.relations) == len(update.snapshot.relations)


def test_runtime_never_attaches_an_artifact_and_the_user_can():
    before = scene_with_stars()
    refused = apply_scene_command(before, attach(actor=RUNTIME))
    assert (refused.outcome, refused.reason) == (REJECTED, SceneRefusal.OP_NOT_ALLOWED)
    assert_unchanged(before, refused)
    assert apply_scene_command(before, attach(actor=USER)).outcome is APPLIED


@pytest.mark.parametrize(
    ("setup", "command", "outcome", "reason"),
    [
        ("archived_target", attach(), INVALID, SceneRefusal.OBJECT_ARCHIVED),
        ("none", attach(target_id="absent"), INVALID, SceneRefusal.UNKNOWN_OBJECT),
        ("taken_relation", attach(), INVALID, SceneRefusal.RELATION_CONFLICT),
        ("none", attach(relation_id="parent_of!claude:x"), REJECTED, SceneRefusal.RESERVED_ID),
        ("none", attach(relation_id="brain:rel"), REJECTED, SceneRefusal.RESERVED_ID),
        ("none", attach(object_id="claude:squat"), REJECTED, SceneRefusal.RESERVED_ID),
        ("relation_limit", attach(), INVALID, SceneRefusal.RELATION_LIMIT),
        ("full", attach(), INVALID, SceneRefusal.SCENE_FULL),
        ("none", attach(object_id="star-b"), INVALID, SceneRefusal.KIND_IMMUTABLE),
    ],
)
def test_a_refused_link_or_object_leaves_no_orphan_artifact(setup, command, outcome, reason):
    before = scene_with_stars()
    if setup == "archived_target":
        before = run(before, cmd(SceneOp.ARCHIVE, USER, object_id="star-a"))
    elif setup == "taken_relation":
        before = run(before, cmd(SceneOp.LINK, BRAIN, relation=SceneRelation("rel-art-new", RelationKind.GROUPS, "art-1", "star-p")))
    elif setup == "relation_limit":
        # Une scène synthétique aux 1 024 liens.
        relations = tuple(SceneRelation(f"brain-fill-{index}", RelationKind.GROUPS, "art-1", "star-p")
                          for index in range(MAX_SCENE_RELATIONS))
        before = SceneSnapshot(scene_id=before.scene_id, revision=before.revision, objects=before.objects, relations=relations)
    elif setup == "full":
        filler = tuple(apply_scene_command(SceneSnapshot(scene_id="x"), upsert(USER, f"note-{index}", kind=SceneObjectKind.ARTIFACT,
                                                                                  category="note")).snapshot.objects[0]
                       for index in range(MAX_SCENE_OBJECTS - len(before.objects)))
        before = SceneSnapshot(scene_id=before.scene_id, revision=before.revision, objects=before.objects + filler,
                               relations=before.relations)
    update = apply_scene_command(before, command)
    assert (update.outcome, update.reason) == (outcome, reason)
    assert_unchanged(before, update)
    assert before.get_object(command.object_id) is None or command.object_id == "star-b"


def test_a_pinned_artifact_follows_an_explicit_brain_move():
    # Réalignement baseline (main, 19/09/2026) : une épingle ne résiste qu'au
    # placement `resolver`, jamais à une commande explicite du cerveau.
    placed = run(scene_with_stars(), attach(geometry=GEO), cmd(SceneOp.PIN, USER, object_id="art-new"))
    update = apply_scene_command(placed, attach(geometry=GEO_2, payload=ScenePayload(title="autre titre")))
    assert (update.outcome, update.reason) == (APPLIED, None)
    moved = update.snapshot.get_object("art-new")
    assert moved.geometry == GEO_2 and moved.constraints.pinned_by_user
    # Sans géométrie, la charge passe.
    assert apply_scene_command(placed, attach(payload=ScenePayload(title="autre titre"))).outcome is APPLIED


@pytest.mark.parametrize(
    "arguments",
    [
        {"relation_id": "art-new"},  # forme d'un lien de signal
        {"target_id": "art-new"},  # s'expliquer soi-même
        {"kind": SceneObjectKind.WINDOW},
    ],
)
def test_attach_artifact_commands_are_strict(arguments):
    fields = {"category": "research"}
    ids = {"object_id": "art-new", "target_id": "star-a", "relation_id": "rel"}
    if "kind" in arguments:
        fields["kind"] = arguments["kind"]
    else:
        ids.update(arguments)
    with pytest.raises(ValueError):
        SceneCommand(op=SceneOp.ATTACH_ARTIFACT, actor=BRAIN, fields=SceneObjectFields(**fields), **ids)
    with pytest.raises(ValueError):
        SceneCommand(op=SceneOp.ATTACH_ARTIFACT, actor=BRAIN, object_id="a", fields=SceneObjectFields(category="c"), target_id="t")
    wire = attach().to_payload()
    assert SceneCommand.from_payload(wire) == attach()


def test_bulk_archive_never_takes_an_artifact_and_a_star_archive_leaves_it():
    before = run(scene_with_stars(), star("star-done", exec_state=ExecState.COMPLETED),
                 attach(target_id="star-done", object_id="art-done", relation_id="rel-art-done"))
    refused = apply_scene_command(before, cmd(SceneOp.ARCHIVE_MANY, USER, object_ids=("star-done", "art-done")))
    assert (refused.outcome, refused.reason) == (INVALID, SceneRefusal.NOT_BULK_ARCHIVABLE)
    assert_unchanged(before, refused)
    bulk = apply_scene_command(before, cmd(SceneOp.ARCHIVE_MANY, USER, object_ids=("star-done",)))
    assert bulk.outcome is APPLIED
    assert bulk.snapshot.get_object("art-done") is not None and bulk.snapshot.get_relation("rel-art-done") is None
    single = apply_scene_command(before, cmd(SceneOp.ARCHIVE, USER, object_id="star-done"))
    assert single.snapshot.get_object("art-done") is not None
    assert [op.object.object_id for op in single.patch.ops if op.op is PatchOpKind.ARCHIVE_OBJECT] == ["star-done"]


# ------------------------------------------------------------------ outil, Core réel


@pytest.fixture
async def core(tmp_path):
    process = CoreProcess(tmp_path)
    await process.start()
    try:
        yield process
    finally:
        await process.stop()


@pytest.fixture
async def tools(core, tmp_path):
    from jarvis.runtime.journal import RuntimeJournal

    display = SceneDisplayTools(CoreSceneTransport(host="127.0.0.1", port=core.port, token_file=core.token_file),
                                journal=RuntimeJournal(tmp_path / "runtime"))
    try:
        yield display
    finally:
        await display.close()


async def seed_star(core: CoreProcess, external_id: str = "research-1", status: str = "completed") -> str:
    await observe(core, {"external_id": external_id, "status": status, "kind": "agent", "label": "Trouver 3 liens officiels"})
    star_id = f"claude:{external_id}"
    await wait_for(core, lambda snap: any(o["object_id"] == star_id and o["exec_state"] == status for o in snap["objects"]))
    return star_id


async def snapshot(core: CoreProcess) -> dict:
    status, body, _ = await core.request("GET", "/v1/scene/snapshot")
    assert status == 200
    return body["snapshot"]


LINKS = [{"label": "Site officiel", "url": "https://www.python.org/"},
         {"label": "Documentation", "url": "https://docs.python.org/3/"}]


async def test_a_grouped_artifact_is_created_linked_to_its_star_and_completed_not_duplicated(core, tools, tmp_path):
    star_id = await seed_star(core)
    await tools.inspect()
    created = await tools.add_artifact(target_id=star_id, category="research", title="Python : liens officiels",
                                       summary="Trois sources.", items=LINKS)
    assert created["action"] == "created" and created["outcome"] == "applied" and created["items"] == 2
    assert created["object_id"].startswith("brain-artifact-") and created["rule"] == ARTIFACT_GROUPING_RULE
    assert created["relation_id"].startswith("brain-explains-") and "scene_changed" not in created
    stored = await scene_object(core, created["object_id"])
    # Point par défaut : une étoile de plus dans la constellation, pas une capsule.
    assert stored["origin"] == "brain" and stored["representation"] == "point" and stored["geometry"] is None
    assert stored["category"] == "research" and [i["label"] for i in stored["payload"]["items"]] == ["Site officiel", "Documentation"]
    snap = await snapshot(core)
    assert [(r["kind"], r["from_id"], r["to_id"]) for r in snap["relations"] if r["from_id"] == created["object_id"]] == [
        ("explains", created["object_id"], star_id)]

    # Seconde fin de travail : même cible, même catégorie → même artefact, entrées ajoutées sans doublon.
    more = await tools.add_artifact(target_id=star_id, category="research", title="Python : liens officiels",
                                    items=[LINKS[1], {"label": "PEP 8", "url": "https://peps.python.org/pep-0008/"}])
    assert (more["action"], more["object_id"], more["relation_id"], more["items"]) == (
        "updated", created["object_id"], created["relation_id"], 3)
    stored = await scene_object(core, created["object_id"])
    assert stored["payload"]["summary"] == "Trois sources."  # gardé : non redonné
    assert [i["label"] for i in stored["payload"]["items"]] == ["Site officiel", "Documentation", "PEP 8"]
    # Le même appel une fois de plus : rien ne change.
    same = await tools.add_artifact(target_id=star_id, category="research", title="Python : liens officiels", items=LINKS)
    assert same["outcome"] == "duplicate" and same["action"] == "updated"
    # Remplacer toute la liste ; une reprise ne change jamais la forme (reprise QA m4).
    replaced = await tools.add_artifact(target_id=star_id, category="research", title="Python : liens", items=LINKS[:1],
                                        items_mode="replace", representation="window")
    assert replaced["items"] == 1 and replaced["ignored"] == ["representation"]
    assert (await scene_object(core, created["object_id"]))["representation"] == "point"
    # Une autre catégorie pour la même étoile : un autre artefact.
    tests = await tools.add_artifact(target_id=star_id, category="tests", title="Tests verts")
    assert tests["action"] == "created" and tests["object_id"] != created["object_id"]
    snap = await snapshot(core)
    artifacts = [o for o in snap["objects"] if o["kind"] == "artifact"]
    assert len(artifacts) == 2 and len(snap["objects"]) == 3
    events = [e for e in read_jsonl_tail(tmp_path / "runtime" / "trace.jsonl", limit=100) if e["kind"] == "display.artifact"]
    assert [e["data"]["action"] for e in events] == ["created", "updated", "updated", "updated", "created"]
    assert all("Python" not in json.dumps(e) for e in events)  # identifiants, jamais le contenu


async def test_an_archived_or_unknown_target_is_refused_before_anything_is_sent(core, tools, tmp_path):
    star_id = await seed_star(core)
    await user_command(core, {"op": "archive", "object_id": star_id})
    revision = (await snapshot(core))["revision"]
    with pytest.raises(DisplayToolError) as archived:
        await tools.add_artifact(target_id=star_id, category="research", title="trop tard")
    assert (archived.value.outcome, archived.value.reason) == ("invalid", "object_archived")
    assert "La cible est archivée" in str(archived.value) and "Rien n'a été envoyé" in str(archived.value)
    with pytest.raises(DisplayToolError) as unknown:
        await tools.add_artifact(target_id="claude:absent", category="research", title="x")
    assert unknown.value.reason == "unknown_object" and "scene_inspect" in str(unknown.value)
    assert (await snapshot(core))["revision"] == revision
    refusals = [e for e in read_jsonl_tail(tmp_path / "runtime" / "trace.jsonl", limit=50) if e["kind"] == "display.tool_refused"]
    assert [e["data"]["reason"] for e in refusals] == ["object_archived", "unknown_object"]
    assert all(e["data"]["sent"] is False for e in refusals)


async def test_a_race_with_the_user_is_told_truthfully_and_never_revives_an_archived_artifact(core, tools, tmp_path):
    star_id = await seed_star(core)
    first = await tools.add_artifact(target_id=star_id, category="research", title="v1", items=LINKS[:1])
    read = tools._snapshot

    async def archive_after_read(target: str):
        async def wrapped():
            body = await read()
            tools._snapshot = read
            await user_command(core, {"op": "archive", "object_id": target})
            return body
        tools._snapshot = wrapped

    # L'utilisateur archive l'artefact entre la lecture et l'écriture : un nouveau est créé, l'ancien reste archivé.
    await archive_after_read(first["object_id"])
    again = await tools.add_artifact(target_id=star_id, category="research", title="v2", items=LINKS[1:])
    assert again["action"] == "created" and again["object_id"] != first["object_id"] and again["items"] == 1
    snap = await snapshot(core)
    assert first["object_id"] in snap["archived_ids"]

    # L'utilisateur archive l'étoile entre la lecture et l'écriture : Core refuse la commande envoyée,
    # un seul refus journalisé (celui de la commande), jamais « rien n'a été envoyé » (reprise QA m6).
    await archive_after_read(star_id)
    mark = len(read_jsonl_tail(tmp_path / "runtime" / "trace.jsonl", limit=10_000))
    with pytest.raises(DisplayToolError) as refused:
        await tools.add_artifact(target_id=star_id, category="tests", title="trop tard")
    assert refused.value.reason == "object_archived" and "La cible est archivée" in str(refused.value)
    assert "Rien n'a été envoyé" not in str(refused.value) and str(refused.value).startswith("attach_artifact refusé par la scène")
    snap = await snapshot(core)
    assert [o["object_id"] for o in snap["objects"] if o["kind"] == "artifact"] == [again["object_id"]]
    refusals = [e for e in read_jsonl_tail(tmp_path / "runtime" / "trace.jsonl", limit=10_000)[mark:] if e["kind"] == "display.tool_refused"]
    assert len(refusals) == 1 and "sent" not in refusals[0]["data"] and refusals[0]["data"]["op"] == "attach_artifact"


async def test_an_update_never_changes_the_form_or_place_the_user_chose_but_replaces_the_title(core, tools):
    """Reprise QA m4 (décision PM) : forme et géométrie à la création seulement ; le titre reste au cerveau."""

    star_id = await seed_star(core)
    created = await tools.add_artifact(target_id=star_id, category="research", title="v1",
                                       geometry={"x": 0, "y": 0, "w": 60, "h": 36})
    oid = created["object_id"]
    await user_command(core, {"op": "set_representation", "object_id": oid, "representation": "window",
                              "geometry": {"x": 10, "y": 10, "w": 80, "h": 50}})
    await user_command(core, {"op": "pin", "object_id": oid})
    await user_command(core, {"op": "patch_object", "object_id": oid, "fields": {"payload": {"title": "Titre de l'utilisateur"}}})
    before = await scene_object(core, oid)
    updated = await tools.add_artifact(target_id=star_id, category="research", title="v2", representation="point",
                                       geometry={"x": 9, "y": 9, "w": 60, "h": 36}, items=[{"label": "nouveau"}])
    assert updated["outcome"] == "applied" and updated["ignored"] == ["representation", "geometry"]
    after = await scene_object(core, oid)
    assert (after["representation"], after["geometry"], after["constraints"]) == (
        before["representation"], before["geometry"], before["constraints"])
    # Résiduel consigné : le titre choisi par l'utilisateur est remplacé par celui du cerveau.
    assert after["payload"]["title"] == "v2" and [i["label"] for i in after["payload"]["items"]] == ["nouveau"]


async def test_a_full_scene_refuses_the_artifact_with_its_reason(tmp_path):
    process = CoreProcess(tmp_path, scene_repository=MemoryRepository())
    await process.start()
    display = SceneDisplayTools(CoreSceneTransport(host="127.0.0.1", port=process.port, token_file=process.token_file))
    try:
        await process.core.scene.apply(SceneCommand.from_payload({
            "schema_version": 1, "op": "upsert_object", "actor": "user", "object_id": "target",
            "fields": {"kind": "window", "category": "note"}}))
        for index in range(MAX_SCENE_OBJECTS - 1):
            await process.core.scene.apply(SceneCommand.from_payload({
                "schema_version": 1, "op": "upsert_object", "actor": "user", "object_id": f"u{index}",
                "fields": {"kind": "artifact", "category": "note"}}))
        with pytest.raises(DisplayToolError) as refused:
            await display.add_artifact(target_id="target", category="research", title="de trop")
        assert refused.value.reason == "scene_full" and "scene_archive" in str(refused.value)
        relations = (await process.core.scene.snapshot()).relations
        assert relations == ()
    finally:
        await display.close()
        await process.stop()


@pytest.mark.parametrize(
    "arguments",
    [
        {"title": ""},
        {"title": "x" * 161},
        {"category": "pas une catégorie"},
        {"category": "c" * 33},
        {"summary": "s" * 2001},
        {"items": [{"label": "piège", "url": "javascript:alert(1)"}]},
        {"items": [{"label": "fichier", "url": "file:///C:/secret"}]},
        {"items": [{"label": f"x{index}"} for index in range(MAX_PAYLOAD_ITEMS + 1)]},
        {"items": [{"label": "é" * 150, "ref": "r" * 250, "url": f"https://example.org/{index}/" + "p" * 1500} for index in range(20)]},
        {"target_id": 42},
        {"items_mode": "merge"},
        {"representation": "hologram"},
        {"geometry": {"x": 0, "y": 0, "w": 0, "h": 1}},
        {"target_id": " padded "},
    ],
)
async def test_arguments_are_bounded_before_anything_is_sent_or_read(arguments):
    spy = SpyTransport()
    values = {"target_id": "claude:t", "category": "research", "title": "Titre", **arguments}
    with pytest.raises(DisplayToolError) as invalid:
        await SceneDisplayTools(spy).add_artifact(**values)
    assert invalid.value.code == "invalid_argument" and "rien n'a été envoyé" in str(invalid.value)
    assert len(str(invalid.value)) < 400 and spy.commands == []


async def test_appending_past_the_item_bound_is_refused_and_nothing_is_sent(core, tools):
    star_id = await seed_star(core)
    created = await tools.add_artifact(target_id=star_id, category="fichiers", title="Fichiers modifiés",
                                       items=[{"label": f"f{index}.py", "ref": "modifié"} for index in range(30)])
    revision = (await snapshot(core))["revision"]
    with pytest.raises(DisplayToolError) as invalid:
        await tools.add_artifact(target_id=star_id, category="fichiers", title="Fichiers modifiés",
                                 items=[{"label": f"g{index}.py"} for index in range(3)])
    assert invalid.value.code == "invalid_argument" and "items_mode=replace" in str(invalid.value)
    assert (await snapshot(core))["revision"] == revision
    assert len((await scene_object(core, created["object_id"]))["payload"]["items"]) == 30


async def test_the_tool_is_strict_over_mcp_and_the_catalog_still_has_no_archive_or_pin(core, tools):
    from mcp.shared.memory import create_connected_server_and_client_session

    star_id = await seed_star(core)
    server = build_server(tools=tools)
    listed = {tool.name: tool for tool in await server.list_tools()}
    assert tuple(listed) == TOOL_NAMES and "scene_add_artifact" in TOOL_NAMES
    schema = listed["scene_add_artifact"].inputSchema
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"target_id", "category", "title"}
    assert set(schema["properties"]) == {"target_id", "category", "title", "summary", "items", "items_mode", "representation", "geometry"}
    assert not re.search(r"archiv|pin|dispos|placed_by|exec_state|work_ref|actor|layer|object_id|relation_id", " ".join(schema["properties"]))
    for name in RECOMMENDED_ARTIFACT_CATEGORIES:
        assert name in listed["scene_add_artifact"].description
    async with create_connected_server_and_client_session(server) as session:
        extra = await session.call_tool("scene_add_artifact", {"target_id": star_id, "category": "research", "title": "t",
                                                               "archived": True, "object_id": "brain-artifact-x"})
        assert extra.isError and "archived" in extra.content[0].text and "object_id" in extra.content[0].text
        wrong = await session.call_tool("scene_add_artifact", {"target_id": star_id, "category": "research", "title": "t",
                                                               "items_mode": "merge"})
        assert wrong.isError and wrong.content[0].text.startswith("Argument invalide, rien n'a été envoyé")
        ok = await session.call_tool("scene_add_artifact", {"target_id": star_id, "category": "research", "title": "t",
                                                            "items": LINKS})
        assert ok.isError is False and json.loads(ok.content[0].text)["action"] == "created"
        refused = await session.call_tool("scene_add_artifact", {"target_id": "claude:nope", "category": "research", "title": "t"})
        assert refused.isError and refused.content[0].text.startswith("attach_artifact refusé par la scène")
    assert [o for o in (await snapshot(core))["objects"] if o["object_id"] == "brain-artifact-x"] == []


# ------------------------------------------------------------------ reprise QA : parallélisme, fusion, formes de lien


@pytest.mark.parametrize("parallel", [2, 3, 5])
async def test_parallel_calls_for_the_same_target_and_category_make_exactly_one_artifact(core, tools, parallel):
    star_id = await seed_star(core, f"parallel-{parallel}")
    results = await asyncio.gather(*(
        tools.add_artifact(target_id=star_id, category="research" if index % 2 else "Research", title="Liens",
                           items=[{"label": f"L{index}", "url": f"https://docs.python.org/{index}"}])
        for index in range(parallel)
    ))
    assert [r["action"] for r in results].count("created") == 1
    assert len({r["object_id"] for r in results}) == 1
    snap = await snapshot(core)
    [artifact] = [o for o in snap["objects"] if o["kind"] == "artifact"]
    assert artifact["category"] == "research" and len(artifact["payload"]["items"]) == parallel
    assert tools._artifact_locks == {}  # bornées : rien ne reste après les appels
    # Une autre cible en parallèle n'attend pas celle-ci et crée son propre artefact.
    other = await seed_star(core, f"parallel-other-{parallel}")
    both = await asyncio.gather(tools.add_artifact(target_id=star_id, category="tests", title="T"),
                                tools.add_artifact(target_id=other, category="tests", title="T"))
    assert [r["action"] for r in both] == ["created", "created"]


async def test_categories_group_without_case_and_items_merge_by_url_then_by_label_and_ref(core, tools):
    star_id = await seed_star(core)
    created = await tools.add_artifact(target_id=star_id, category="Research", title="Merge",
                                       items=[{"label": "Doc", "url": "https://docs.python.org/3/"}, {"label": "Note", "ref": "a"},
                                              {"label": "Doc bis", "url": "https://docs.python.org/3/"}])
    assert created["category"] == "research" and created["items"] == 2  # même URL dans l'appel : une entrée
    oid = created["object_id"]
    assert (await scene_object(core, oid))["category"] == "research"
    same_url = await tools.add_artifact(target_id=star_id, category="RESEARCH", title="Merge",
                                        items=[{"label": "Documentation", "url": "https://docs.python.org/3/", "ref": "officiel"}])
    assert same_url["object_id"] == oid and same_url["items"] == 2
    items = (await scene_object(core, oid))["payload"]["items"]
    assert items[0] == {"label": "Documentation", "ref": "officiel", "url": "https://docs.python.org/3/"}  # mis à jour sur place
    again = await tools.add_artifact(target_id=star_id, category="research", title="Merge",
                                     items=[{"label": "Note", "ref": "a"}, {"label": "Note", "ref": "b"}])
    assert again["items"] == 3
    assert [(i["label"], i["ref"]) for i in (await scene_object(core, oid))["payload"]["items"]] == [
        ("Documentation", "officiel"), ("Note", "a"), ("Note", "b")]
    replaced = await tools.add_artifact(target_id=star_id, category="research", title="Merge", items_mode="replace",
                                        items=[{"label": "x", "url": "https://a.example/"}, {"label": "y", "url": "https://a.example/"}])
    assert replaced["items"] == 1 and (await scene_object(core, oid))["payload"]["items"][0]["label"] == "y"
    snap = await snapshot(core)
    assert len([o for o in snap["objects"] if o["kind"] == "artifact"]) == 1


def test_a_signal_shaped_link_is_refused_to_brain_and_user_and_never_blocks_the_grouping():
    from jarvis.runtime.display_mcp import _grouped_artifact

    before = run(scene_with_stars())
    for actor in (BRAIN, USER):
        refused = apply_scene_command(before, cmd(SceneOp.LINK, actor, relation=SceneRelation(
            "art-1", RelationKind.EXPLAINS, "art-1", "star-a")))
        assert (refused.outcome, refused.reason) == (REJECTED, SceneRefusal.SIGNAL_SHAPE)
        assert_unchanged(before, refused)
        # D'autres natures ou un autre identifiant restent permis.
        assert apply_scene_command(before, cmd(SceneOp.LINK, actor, relation=SceneRelation(
            "art-1", RelationKind.GROUPS, "art-1", "star-a"))).outcome is APPLIED
        assert apply_scene_command(before, cmd(SceneOp.LINK, actor, relation=SceneRelation(
            "brain-explains-x", RelationKind.EXPLAINS, "art-1", "star-a"))).outcome is APPLIED
    # Un signal (objet attention) garde cette forme.
    note = run(before, upsert(BRAIN, "note-sig", kind=SceneObjectKind.ATTENTION, category="note"))
    assert apply_scene_command(note, cmd(SceneOp.LINK, BRAIN, relation=SceneRelation(
        "note-sig", RelationKind.EXPLAINS, "note-sig", "star-a"))).outcome is APPLIED
    # Scène héritée avec un tel lien : l'outil ne le reprend pas, il crée un artefact correctement relié.
    legacy = SceneSnapshot(scene_id=before.scene_id, revision=before.revision, objects=before.objects,
                           relations=(*before.relations, SceneRelation("art-1", RelationKind.EXPLAINS, "art-1", "star-a")))
    assert _grouped_artifact(legacy, "star-a", "research") == (None, 0)
    fine = run(before, attach(object_id="art-new", relation_id="brain-explains-new", category="RESEARCH"))
    assert _grouped_artifact(fine, "star-a", "research")[0][0].object_id == "art-new"


def test_orphan_artifacts_are_bulk_archivable_and_linked_ones_never():
    from jarvis.domain.scene import bulk_archivable, is_orphan_artifact

    before = run(scene_with_stars(), star("star-done", exec_state=ExecState.COMPLETED),
                 attach(target_id="star-done", object_id="art-done", relation_id="rel-art-done"),
                 attach(target_id="star-a", object_id="art-live", relation_id="rel-art-live"),
                 cmd(SceneOp.ARCHIVE, USER, object_id="star-done"))
    assert is_orphan_artifact(before, "art-done") and not is_orphan_artifact(before, "art-live")
    assert bulk_archivable(before, "art-done") and not bulk_archivable(before, "art-live")
    # `art-1` (scene_with_stars) n'a jamais été relié : orphelin aussi.
    assert is_orphan_artifact(before, "art-1") and not is_orphan_artifact(before, "star-a")
    linked = apply_scene_command(before, cmd(SceneOp.ARCHIVE_MANY, USER, object_ids=("art-done", "art-live")))
    assert (linked.outcome, linked.reason) == (INVALID, SceneRefusal.NOT_BULK_ARCHIVABLE)
    assert_unchanged(before, linked)
    # Réalignement baseline (main, 19/09/2026) : `archive_many` est ouvert au
    # cerveau ; ce qui filtre est la règle de contenu, jamais l'acteur.
    brain_linked = apply_scene_command(before, cmd(SceneOp.ARCHIVE_MANY, BRAIN, object_ids=("art-live",)))
    assert (brain_linked.outcome, brain_linked.reason) == (INVALID, SceneRefusal.NOT_BULK_ARCHIVABLE)
    brain = apply_scene_command(before, cmd(SceneOp.ARCHIVE_MANY, BRAIN, object_ids=("art-done",)))
    assert (brain.outcome, brain.reason) == (APPLIED, None)
    applied = apply_scene_command(before, cmd(SceneOp.ARCHIVE_MANY, USER, object_ids=("art-done", "art-1")))
    assert applied.outcome is APPLIED
    assert {op.object.object_id for op in applied.patch.ops if op.op is PatchOpKind.ARCHIVE_OBJECT} == {"art-done", "art-1"}
    assert applied.snapshot.get_object("art-live") is not None


# ------------------------------------------------------------------ consigne


#: Empreintes du prompt système du cerveau (inchangé depuis `f82ea3d` : sans
#: interrupteur, le prompt reste octet pour octet) et de la consigne d'affichage.
#: Slice 09, partie 2 (décision PM, mise à jour délibérée, interrupteur allumé
#: seulement) : la ligne « Pas de capture d'écran » devient la ligne
#: `scene_capture`, et la ligne des données ajoute « un texte suspect a été ignoré ».
#: Slice 11 (décision PM, mise à jour délibérée) : la ligne de capture se dédouble
#: en « structure → scene_query near / écran → scene_capture », avec l'écart entre
#: géométrie enregistrée et pixels dessinés.
#: Intégration de main `668e2b7` (changement délibéré venu de main, hors scène) :
#: le prompt système gagne la section « RETOURS UTILISATEUR » — où déposer la
#: fiche quand l'utilisateur signale un dysfonctionnement constaté en usage.
#: La consigne d'affichage, elle, ne bouge pas.
#: Délégation (19/09/2026, changement délibéré hors scène) : la règle du brief
#: remplace « donne une consigne complète et autonome » par ce que le cerveau
#: transmet — les mots de l'utilisateur, l'observable, l'historique des refus —
#: et lui retire le diagnostic. La consigne d'affichage, elle, ne bouge pas.
BASE_SYSTEM_SHA256 = "bf71be1c52ab13bceeb37ee686dd4f3aea7346182988b6b3ac983d0c2080e7ce"
#: Réalignement baseline (main `f05ed24`, changement délibéré venu de main) : la
#: consigne d'affichage nomme scene_update_many, scene_archive, scene_pin et
#: donne au cerveau la main de l'utilisateur (archiver, épingler, déplacer).
BASE_DISPLAY_SHA256 = "1640f1e13ed872766d83caf9b2268aba2e6b00a5f00727cf699e441337aef229"


def test_the_artifact_guidance_exists_only_with_the_flag_and_the_other_prompts_are_byte_identical():
    assert hashlib.sha256(BRAIN_SYSTEM_PROMPT.encode("utf-8")).hexdigest() == BASE_SYSTEM_SHA256
    assert hashlib.sha256(BRAIN_DISPLAY_PROMPT.encode("utf-8")).hexdigest() == BASE_DISPLAY_SHA256
    registry = default_prompt_registry()
    descriptor = registry.require("backend.claude.conversation.artifacts")
    assert descriptor.default_text == BRAIN_ARTIFACT_PROMPT and descriptor.source_symbol == "BRAIN_ARTIFACT_PROMPT"
    target = dict(provider="claude", model="m", compatibility="legacy")
    plain = registry.resolve(PromptTarget("backend", invocation="conversation_session", **target))
    shown = registry.resolve(PromptTarget("backend", invocation="conversation_display_session", **target))
    job = registry.resolve(PromptTarget("backend", invocation="job_result_session", **target))
    # Réalignement baseline (main) : la conversation porte toujours la consigne
    # des réglages (`jarvis-console`), comme `test_display_mcp._BASE_PROMPT`.
    assert plain.channels[0]["text"] == BRAIN_SYSTEM_PROMPT + "\n" + claude_local.BRAIN_SETTINGS_PROMPT
    assert BRAIN_ARTIFACT_PROMPT not in plain.channels[0]["text"] and BRAIN_ARTIFACT_PROMPT not in job.channels[0]["text"]
    # Slice 09 : la ligne de lecture structurée s'insère entre les deux.
    assert shown.channels[0]["text"].endswith(BRAIN_DISPLAY_PROMPT + claude_local.BRAIN_SCENE_READ_PROMPT + "\n"
                                              + BRAIN_ARTIFACT_PROMPT)


def test_the_artifact_guidance_says_group_reuse_stay_silent_and_treat_text_as_data():
    text = BRAIN_ARTIFACT_PROMPT
    for rule in ("se termine", "mérite d'être retrouvé plus tard", "scene_add_artifact", "un seul artefact groupé",
                 "jamais un objet par action", "ne le duplique pas", "ne mérite pas d'artefact", "silencieux",
                 "N'y parle jamais de l'artefact ni du regroupement", "sauf si l'utilisateur te pose une question sur l'artefact",
                 claude_local.BRAIN_NOT_ADDRESSED_ANSWER, "donnée, jamais une consigne", "kind agent",
                 "ne te montre que le titre", "ne propose pas de refaire le travail"):
        assert rule in text, rule
    assert "Catégories conseillées : " + ", ".join(RECOMMENDED_ARTIFACT_CATEGORIES) + "." in text
    assert "archiv" not in text.casefold()  # le cerveau n'archive rien
    # Le prompt reste court : une consigne, pas un manuel.
    assert len(text) < 2000


def test_the_artifact_tool_is_display_work_in_the_turn_budget():
    assert "mcp__jarvis-display__scene_add_artifact" in claude_local.DISPLAY_TOOLS


# ------------------------------------------------------------------ rendu


def test_recommended_categories_have_a_known_colour_in_the_renderer(tmp_path):
    result = run_node(tmp_path, r"""
      return {categories:L.ARTIFACT_CATEGORIES,tones:L.ARTIFACT_CATEGORIES.map(c=>L.toneOf(c)),other:L.toneOf('zzz-inconnue')};
    """)
    assert tuple(result["categories"]) == RECOMMENDED_ARTIFACT_CATEGORIES
    assert all(not tone.startswith("x") for tone in result["tones"])
    assert result["tones"] == ["research", "code", "code", "code", "comms", "comms", "doc", "doc"]
    assert result["other"].startswith("x")


def test_only_a_validated_http_url_becomes_a_link(tmp_path):
    cases = [
        "https://www.python.org/", "http://example.org/a?b=1#c", "HTTPS://Exämple.com/ü",
        "javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,<b>x</b>", "file:///C:/secret", "ftp://example.org/",
        "https://user:pw@evil.example/", "https://bank.example@evil.example/", "//evil.example/", "https://exa\u202emple.com/",
        "https://exa\u200bmple.com/", " https://example.org/", "https://example.org/ x", "https://", "", None, 42,
        "https://example.org/" + "a" * 2100, "https://evil.example\\@good.example/",
    ]
    result = run_node(tmp_path, "return D.map(u=>L.linkOf(u));", cases)
    links = dict(zip([repr(c) for c in cases], result))
    assert links[repr("https://www.python.org/")] == {"href": "https://www.python.org/", "host": "www.python.org"}
    assert links[repr("http://example.org/a?b=1#c")]["host"] == "example.org"
    # Slice 09, reprise QA (M3, décision PM) : règle unique partagée avec `scene_get` ; un hôte international,
    # un schéma en majuscules et une barre oblique inverse ne font plus de lien (corpus : test_scene_links.py).
    assert links[repr("HTTPS://Exämple.com/ü")] is None
    assert links[repr("https://evil.example\\@good.example/")] is None
    openable = {key for key, value in links.items() if value}
    assert openable == {repr("https://www.python.org/"), repr("http://example.org/a?b=1#c")}
    for value in result:
        if value:
            assert re.match(r"^https?://", value["href"])


def test_the_artifact_window_is_an_inspection_view_linked_to_its_star(tmp_path):
    result = run_node(tmp_path, r"""
      const star=obj('claude:r1','agent',{exec_state:'completed',payload:{title:'Trouver 3 liens\u202E officiels',summary:'',items:[]},
        geometry:{x:-60,y:-10,w:6,h:6},constraints:{placed_by:'resolver',pinned_by_user:false}});
      const items=[{label:'Site officiel',ref:'',url:'https://www.python.org/'},{label:'Piège',ref:'',url:'javascript:alert(1)'},
        {label:'Fichier',ref:'src/app.py',url:''},{label:'Leurre',ref:'',url:'https://banque.example@evil.example/'}];
      const art=obj('brain-artifact-1','artifact',{origin:'brain',category:'research',representation:'window',exec_state:'unknown',
        geometry:{x:0,y:-40,w:90,h:60},constraints:{placed_by:'brain',pinned_by_user:false},
        payload:{title:'Python : liens officiels',summary:'Trois sources.',items}});
      const capsule=Object.assign({},art,{object_id:'brain-artifact-2',representation:'capsule',geometry:{x:0,y:40,w:60,h:8}});
      const signal=obj('attention!claude:r1','attention',{geometry:{x:-50,y:-12,w:4,h:4}});
      const s=state([star,art,capsule,signal],[rel('brain-explains-1','explains','brain-artifact-1','claude:r1'),
        rel('brain-explains-2','explains','brain-artifact-2','claude:r1'),rel('attention!claude:r1','explains','attention!claude:r1','claude:r1')]);
      const vm=L.viewModel(s,L.resolveLayout(s),L.viewport(1920,1080));
      const hiddenStar=state([Object.assign({},star,{visibility:'hidden'}),art],[rel('brain-explains-1','explains','brain-artifact-1','claude:r1')]);
      const hiddenNode=L.viewModel(hiddenStar,L.resolveLayout(hiddenStar),L.viewport(1920,1080)).nodes.find(n=>n.id==='brain-artifact-1');
      const node=id=>vm.nodes.find(n=>n.id===id);
      return {window:node('brain-artifact-1'),capsule:node('brain-artifact-2'),star:node('claude:r1'),edges:vm.edges,
        hiddenExplains:hiddenNode.explains,explaining:L.artifactsExplaining(s,'claude:r1'),none:L.artifactsExplaining(s,'brain-artifact-1')};
    """)
    window = result["window"]
    assert window["shape"] == "window" and window["category"] == "research" and window["itemCount"] == 4
    assert window["explains"] == {"id": "claude:r1", "title": "Trouver 3 liens officiels", "kind": "agent", "kindLabel": "sous-agent",
                                  "execLabel": "terminé", "tone": "agent", "hidden": False}
    assert window["items"] == [
        {"label": "Site officiel", "ref": "", "url": "", "href": "https://www.python.org/", "host": "www.python.org"},
        {"label": "Piège", "ref": "", "url": "javascript:alert(1)", "href": "", "host": ""},
        {"label": "Fichier", "ref": "src/app.py", "url": "", "href": "", "host": ""},
        {"label": "Leurre", "ref": "", "url": "https://banque.example@evil.example/", "href": "", "host": ""},
    ]
    assert window["label"] == "Python : liens officiels · résultat · research · 4 entrées · explique « Trouver 3 liens officiels »"
    # Capsule : catégorie et titre, pas de détail.
    capsule = result["capsule"]
    assert capsule["shape"] == "capsule" and capsule["category"] == "research" and capsule["items"] == []
    assert capsule["explains"]["id"] == "claude:r1"
    # Le lien de l'artefact est marqué, le lien du signal reste un signal.
    by_id = {edge["id"]: edge for edge in result["edges"]}
    assert by_id["brain-explains-1"]["artifact"] is True and by_id["brain-explains-1"]["signal"] is False
    assert by_id["attention!claude:r1"]["artifact"] is False and by_id["attention!claude:r1"]["signal"] is True
    assert result["star"]["explains"] is None and "résultat" not in result["star"]["label"]
    assert result["hiddenExplains"]["hidden"] is True
    assert result["explaining"] == ["brain-artifact-1", "brain-artifact-2"] and result["none"] == []


def test_the_page_builds_links_only_from_validated_urls_and_never_with_markup():
    page = PAGE_JS.read_text(encoding="utf-8")
    layout = LAYOUT_JS.read_text(encoding="utf-8")
    assert "innerHTML" not in page and "insertAdjacentHTML" not in page and "outerHTML" not in page
    row = page[page.index("function itemRow(item)"):page.index("function setInnerTabs")]
    assert "link.href=href" in row and "/^https?:\\/\\//.test(item.href)" in row
    assert "link.target='_blank'" in row and "link.rel='noopener noreferrer'" in row and "link.referrerPolicy='no-referrer'" in row
    assert "setAttribute('href'" not in page and "javascript" not in row
    # Liens et origine : hors tabulation hors focus, clic natif sans geste.
    assert "if(event.target.closest('.sc-item-link,.sc-origin'))return;" in page
    assert "link.tabIndex=-1" in row
    assert "new URL(value)" in layout and "parsed.username||parsed.password" in layout


# ------------------------------------------------------------------ reprise QA : rendu


#: Les trois cas hostiles de QA (M1) : sous-domaine qui imite, hôte très long, référence qui pousse l'hôte.
# Slice 09, reprise QA : étiquettes de 63 caractères au plus (règle de lien partagée), hôte toujours > 120 caractères.
QA_HOSTILE_HOSTS = ["docs.python.org.evil-login.example", "accounts.google.com." + "a" * 50 + "." + "a" * 50 + ".evil.example",
                    "evil.example"]


def test_the_printed_host_keeps_its_registrable_end_and_is_never_pre_truncated(tmp_path):
    long_url = "https://" + QA_HOSTILE_HOSTS[1] + "/signin"
    result = run_node(tmp_path, r"""
      const tails={};
      for(const host of D.hosts)for(const n of [8,12,16,20,24,30,40,200])tails[`${host}|${n}`]=L.hostTail(host,n);
      const items=L.itemsOf({items:[{label:'Compte Google',url:D.long},
        {label:'Doc',ref:'docs.python.org — référence officielle complète de la bibliothèque standard',url:'https://evil.example/'}]});
      return {tails,items};
    """, {"hosts": QA_HOSTILE_HOSTS, "long": long_url})
    for key, tail in result["tails"].items():
        host, limit = key.rsplit("|", 1)
        limit = int(limit)
        assert host.endswith(tail.lstrip("…")), key  # toujours la fin de l'hôte, jamais son début
        assert len(tail) <= max(limit, 8) or tail == host, key
        if len(host) <= limit:
            assert tail == host
        registrable = ".".join(host.split(".")[-2:])
        if limit >= len(registrable) + 1:
            assert tail.endswith(registrable), key  # le domaine enregistrable reste lisible
    assert result["tails"][f"{QA_HOSTILE_HOSTS[0]}|20"] == "…evil-login.example"
    assert "docs.python.org" not in result["tails"][f"{QA_HOSTILE_HOSTS[0]}|20"]
    # Pas de coupe avant le dessin : l'hôte entier (> 120 caractères) pour le nom accessible et l'infobulle.
    assert result["items"][0]["host"] == QA_HOSTILE_HOSTS[1] and len(QA_HOSTILE_HOSTS[1]) > 120
    assert result["items"][1]["host"] == "evil.example" and result["items"][1]["ref"].startswith("docs.python.org")


def test_orphan_rule_matches_the_domain_and_the_page_counts_what_a_bulk_archive_leaves(tmp_path):
    from jarvis.domain.scene import is_orphan_artifact

    domain = run(scene_with_stars(), star("star-done", exec_state=ExecState.COMPLETED),
                 attach(target_id="star-done", object_id="art-done", relation_id="rel-art-done"),
                 attach(target_id="star-a", object_id="art-live", relation_id="rel-art-live"),
                 attach(target_id="star-done", object_id="art-both", relation_id="rel-art-both-1"),
                 cmd(SceneOp.LINK, BRAIN, relation=SceneRelation("rel-art-both-2", RelationKind.EXPLAINS, "art-both", "star-a")))
    archived = run(domain, cmd(SceneOp.ARCHIVE, USER, object_id="star-done"))
    result = run_node(tmp_path, r"""
      const toState=snap=>state(snap.objects,snap.relations);
      const before=toState(D.before),after=toState(D.after);
      return {orphansAfter:L.orphanArtifacts(after),left:L.artifactsLeftOrphan(before,['star-done']),
        each:Object.fromEntries([...after.objects.keys()].map(id=>[id,L.isOrphanArtifact(after,id)]))};
    """, {"before": domain.to_payload(), "after": archived.to_payload()})
    assert result["each"] == {item.object_id: is_orphan_artifact(archived, item.object_id) for item in archived.objects}
    assert sorted(result["orphansAfter"]) == ["art-1", "art-done"]
    assert result["left"] == ["art-done"]  # `art-both` reste relié à `star-a`, `art-1` n'était relié à rien


def test_expanding_from_the_menu_finds_free_space_near_the_star_outside_the_face_and_safe_area(tmp_path):
    result = run_node(tmp_path, r"""
      const star=obj('claude:s','agent',{exec_state:'completed',geometry:{x:-65,y:-3,w:6,h:6},constraints:{placed_by:'resolver',pinned_by_user:false}});
      const other=obj('brain-window-1','window',{origin:'brain',geometry:{x:-60,y:-50,w:64,h:40},constraints:{placed_by:'brain',pinned_by_user:false}});
      const art=obj('brain-artifact-1','artifact',{origin:'brain',category:'research',geometry:{x:-107,y:11,w:40,h:7},
        constraints:{placed_by:'resolver',pinned_by_user:false}});
      /* Scène de QA (m7) : une étoile voisine juste à gauche, qu'un angle préféré du résolveur mordait. */
      const neighbour=obj('claude:n','agent',{exec_state:'completed',geometry:{x:-81,y:-3,w:6,h:6},constraints:{placed_by:'resolver',pinned_by_user:false}});
      const s=state([star,neighbour,other,art],[rel('brain-explains-1','explains','brain-artifact-1','claude:s')]);
      const layout=L.resolveLayout(s);
      const box=L.placeFor(s,layout,'brain-artifact-1','window');
      const capsule=L.placeFor(s,layout,'brain-artifact-1','capsule');
      const inside=b=>b.x>=L.SAFE_AREA.x0&&b.y>=L.SAFE_AREA.y0&&b.x+b.w<=L.SAFE_AREA.x1&&b.y+b.h<=L.SAFE_AREA.y1;
      const face={x:L.FACE_ZONE.x0,y:L.FACE_ZONE.y0,w:L.FACE_ZONE.x1-L.FACE_ZONE.x0,h:L.FACE_ZONE.y1-L.FACE_ZONE.y0};
      const middle=b=>[b.x+b.w/2,b.y+b.h/2];
      const far=(a,b)=>{const p=middle(a),q=middle(b);return Math.hypot(p[0]-q[0],p[1]-q[1])};
      return {box,capsule,inside:inside(box),overStar:overlap(box,star.geometry)||overlap(box,neighbour.geometry),overOther:overlap(box,other.geometry),
        overFace:overlap(box,face),dist:far(box,star.geometry)};
    """)
    box = result["box"]
    assert box["w"] == 64 and box["h"] == 40 and result["inside"]
    assert not result["overStar"] and not result["overOther"] and not result["overFace"]
    assert result["dist"] < 60  # près de son étoile
    assert result["capsule"]["w"] == 40 and result["capsule"]["h"] == 7


def test_menu_offers_orphan_archive_only_when_there_are_orphans(tmp_path):
    from tests.unit.test_scene_interaction_logic import run_node as run_interact

    result = run_interact(tmp_path, r"""
      const s=state([obj('brain-artifact-1','artifact',{origin:'brain'}),obj('claude:s','agent',{exec_state:'completed'}),
        obj('brain-window-1','window',{origin:'brain'})]);
      const acts=(id,ctx)=>I.menuModel(s,id,ctx).items.filter(i=>i!=='-').map(i=>i.act+(i.label?'|'+i.label:''));
      return {artifact:acts('brain-artifact-1',{orphans:3}),none:acts('brain-artifact-1',{orphans:0}),star:acts('claude:s',{orphans:2}),
        window:acts('brain-window-1',{orphans:2})};
    """)
    assert "archive-orphans|Archiver les artefacts orphelins (3)…" in result["artifact"]
    assert not any(a.startswith("archive-orphans") for a in result["none"] + result["window"])
    assert any(a.startswith("archive-orphans") for a in result["star"])


def test_the_page_keeps_one_tab_stop_prints_the_host_first_and_leaves_links_their_native_menu():
    page = PAGE_JS.read_text(encoding="utf-8")
    row = page[page.index("function itemRow(item)"):page.index("function setInnerTabs")]
    # Reprise finale N1 : l'hôte est le premier enfant du lien ; une ligne étroite garde un lien cliquable sans libellé.
    assert row.index("link.append(host)") < row.index("link.append(element('span','sc-item-label'")
    assert "host.dataset.host=item.host" in row and "link.title=item.host" in row and "row.append(link," in row
    assert "const budget=narrow?width-2:width*0.72;" in page and "row.scrollWidth>row.clientWidth+1" in page
    assert "row.classList.toggle('sc-host-first',narrow)" in page and ".sc-items li.sc-host-first .sc-item-out{display:none}" in page
    assert ".sc-items .sc-item-link-ref{flex:0 100 auto" in page
    assert "const list=element('ul','sc-items');list.tabIndex=-1;" in page
    assert "event.key==='PageDown'||event.key==='PageUp'" in page
    menu = page[page.index("function onContextMenu(event)"):page.index("function select(id,mode)")]
    assert menu.index("closest('.sc-item-link'))return;") < menu.index("event.preventDefault()")
    assert ".sc-items .sc-item-host{flex:none" in page and "L.hostTail(full,max)" in page
    change = page[page.index("async function changeRepresentation"):page.index("async function pinHere")]
    assert "L.placeFor(state,currentLayout(),id,representation)" in change


# ------------------------------------------------------------------ reprise finale (QA N1, N2)


#: Hôtes de QA (N1) : la frontière de label laissait voir `…co.uk`, `…github.io`, `…com.au`.
QA_SUFFIX_HOSTS = ["secure.barclays.co.uk.login-check.co.uk", "safe.github.io.evil-user.github.io",
                   "commbank.com.au.secure-login.com.au", "docs.python.org.evil-login.example"]


def test_the_host_tail_always_shows_the_longest_suffix_that_fits(tmp_path):
    result = run_node(tmp_path, r"""
      const out={};
      for(const host of D)for(let n=1;n<=48;n++)out[`${host}|${n}`]=L.hostTail(host,n);
      return out;
    """, QA_SUFFIX_HOSTS)
    for key, tail in result.items():
        host, width = key.rsplit("|", 1)
        width = max(int(width), 8)
        if len(host) <= width:
            assert tail == host, key
            continue
        suffix = host[len(host) - (width - 1):]
        expected = "…" + (suffix[1:] if suffix.startswith(".") else suffix)
        assert tail == expected, (key, tail)
        assert len(tail) in (width, width - 1) and host.endswith(tail[1:])
    assert result[f"{QA_SUFFIX_HOSTS[0]}|17"] == "…ogin-check.co.uk"
    assert result[f"{QA_SUFFIX_HOSTS[1]}|18"] == "…il-user.github.io"
    assert result[f"{QA_SUFFIX_HOSTS[2]}|14"] == "…-login.com.au"
    # Jamais seulement les deux derniers labels quand la place en montre plus.
    assert result[f"{QA_SUFFIX_HOSTS[0]}|20"].endswith("login-check.co.uk")


def test_expanding_in_the_dense_qa_scene_takes_the_nearest_free_box_and_stays_fast(tmp_path):
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "scene_dense_expand_qa07r.json"
    result = run_node(tmp_path, r"""
      const s=D;
      const st={objects:new Map(s.objects.map(o=>[o.object_id,o])),relations:new Map(s.relations.map(r=>[r.relation_id,r])),archived_ids:new Set()};
      const id='brain-artifact-dense2';
      const layout=L.resolveLayout(st);
      const anchor=layout.placements.get(L.anchorsOf(st).get(id).to);
      const times=[];let box=null;
      for(let i=0;i<9;i++){const t0=Date.now();box=L.placeFor(st,layout,id,'window');times.push(Date.now()-t0)}
      const ov=(a,b)=>Math.max(0,Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x))*Math.max(0,Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y));
      const hits=[...layout.placements].filter(([k,b])=>k!==id&&ov(box,b)>0).map(([k])=>k);
      const face={x:L.FACE_ZONE.x0,y:L.FACE_ZONE.y0,w:L.FACE_ZONE.x1-L.FACE_ZONE.x0,h:L.FACE_ZONE.y1-L.FACE_ZONE.y0};
      const dist=b=>Math.hypot(b.x+b.w/2-(anchor.x+anchor.w/2),b.y+b.h/2-(anchor.y+anchor.h/2));
      /* Contrôle indépendant : toutes les boîtes libres au pas de 2, test exact. */
      let nearest=Infinity,freeCount=0;
      for(let y=L.SAFE_AREA.y0;y+40<=L.SAFE_AREA.y1;y+=2)for(let x=L.SAFE_AREA.x0;x+64<=L.SAFE_AREA.x1;x+=2){
        const b={x,y,w:64,h:40};
        if(ov(b,face)>0)continue;
        if([...layout.placements].some(([k,o])=>k!==id&&ov({x:x-1,y:y-1,w:66,h:42},o)>0))continue;
        freeCount++;nearest=Math.min(nearest,dist(b));
      }
      return {box,hits,faceOverlap:ov(box,face),distance:dist(box),nearest,freeCount,times,
        again:JSON.stringify(L.placeFor(st,L.resolveLayout(st),id,'window'))===JSON.stringify(box)};
    """, json.loads(fixture.read_text(encoding="utf-8")))
    assert result["freeCount"] > 0
    assert result["hits"] == [] and result["faceOverlap"] == 0  # QA avant : 4 étoiles recouvertes
    assert abs(result["distance"] - result["nearest"]) < 1e-9  # la plus proche des places libres
    assert result["again"] is True
    # Reprise QA Slice 09 (m10) : médiane des passes chaudes, borne large ; pas de mesure fine dans un test unitaire.
    warm = sorted(result["times"][1:])
    assert warm[len(warm) // 2] < 50
