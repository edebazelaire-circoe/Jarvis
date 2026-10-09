"""Variables typées partagées et édition rapide d'une scène Remotion (Slice 13).

Aucun second éditeur : le schéma de propriétés d'une composition est le `inputs` du manifeste, les contrôles sont les `StudioControl`
existants, la modification durable est `control.set` / `control.reset` avec CAS (`if_current`, révision de base). Ces épreuves tiennent
le genre des contrôles, les paramètres qu'un moteur ne porte pas (étiquetés, jamais cachés), la parité des listes de contrôles entre
Slidecar et Remotion, et le trajet complet sur le vrai `PrefabService` : l'aperçu n'écrit rien, la base périmée et la valeur périmée
sont refusées, une valeur hors bornes ou piégée est refusée, la réinitialisation rend le défaut, et les `inputProps` qui en sortent
sont ceux que la page de scène enverrait au bac à sable. Contrat : `docs/presentation-studio.md` > *Typed variables and fast edits*.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from jarvis.adapters.file_prefab_library import FilePrefabLibrary
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.core.prefab_service import PrefabService
from jarvis.core.presentation_studio_edit import PresentationStudioEditService
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.domain.prefab import parse_input_schema, parse_manifest
from jarvis.domain.presentation_studio_checks import PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_edit import EditStatus
from jarvis.domain.presentation_studio_engine import Engine
from jarvis.domain.presentation_studio_scene import StudioScene, describe_control
from jarvis.domain.remotion_controls import (
    URL_REASON, ControlKind, build_input_props, control_kind, engine_of, engine_support, input_contract,
)
from jarvis.domain.remotion_source import build_candidate
from tests.fakes.prefabs import candidate as html_candidate, install_version
from tests.fakes.remotion_scene import COMPOSITION, ENGINE, scene_files

NOW = datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc)
SCENE = "presentation-studio.p000000000001.s000000000001"
S1 = "pss_000000000001"

PROPS = {"type": "object", "properties": {
    "title": {"type": "string", "default": "Bonjour", "max_length": 80},
    "accent": {"type": "color", "default": "#3366ff"},
    "gap": {"type": "integer", "default": 8, "min": 0, "max": 100},
    "stagger": {"type": "number", "default": 2, "min": 0, "max": 30},
    "fade_frames": {"type": "integer", "default": 10, "min": 1, "max": 90},
    "logo": {"type": "url"}}}
DATA = {"type": "object", "properties": {"series": {"type": "array", "max_items": 5, "default": [], "items": {"type": "number"}}}}
SAMPLE = {"props": {"title": "Bonjour"}, "data": {"series": [1, 2]}}
CONTROLS = [
    {"control_id": "headline", "path": "props.title", "label": "Titre", "group": "content"},
    {"control_id": "accent", "path": "props.accent", "label": "Accent", "group": "visual", "default": "#3366ff"},
    {"control_id": "gap", "path": "props.gap", "label": "Écart", "group": "layout", "bounds": {"min": 4, "max": 60}},
    {"control_id": "stagger", "path": "props.stagger", "label": "Décalage", "group": "motion"},
    {"control_id": "fade", "path": "props.fade_frames", "label": "Fondu", "group": "motion"},
    {"control_id": "logo", "path": "props.logo", "label": "Logo", "group": "content"},
    {"control_id": "series", "path": "data.series", "label": "Série", "group": "content"},
]


def remotion_candidate(props=PROPS, data=DATA, sample=SAMPLE):
    return build_candidate(prefab_id=SCENE, title="Scène", composition=COMPOSITION, engine=ENGINE, files=scene_files(),
                           props=props, data=data, sample=sample)


def remotion_manifest(**kwargs):
    return parse_manifest(remotion_candidate(**kwargs)["manifest"])


def slidecar_manifest():
    return parse_manifest(html_candidate(inputs={"props": PROPS, "data": DATA}, events={}, sample=SAMPLE)["manifest"])


def scene(manifest) -> StudioScene:
    return StudioScene.from_dict({
        "scene_id": S1, "prefab": {"id": manifest.prefab_id, "version": manifest.version}, "title": "Scène",
        "props": {"title": "Bonjour", "accent": "#3366ff", "gap": 8, "stagger": 2, "fade_frames": 10},
        "data": {"series": [1, 2]}, "controls": CONTROLS, "anchors": []})


# ------------------------------------------------------------------ le genre d'un contrôle

@pytest.mark.parametrize(("schema", "path", "group", "kind"), [
    ({"type": "color"}, "props.accent", "visual", ControlKind.COLOR),
    ({"type": "string"}, "props.title", "content", ControlKind.TEXT),
    ({"type": "text"}, "props.body", "content", ControlKind.TEXT),
    ({"type": "integer"}, "props.gap", "layout", ControlKind.SPACING),
    ({"type": "number"}, "props.paddingTop", "visual", ControlKind.SPACING),
    ({"type": "number"}, "props.corner_radius", "visual", ControlKind.SPACING),
    ({"type": "integer"}, "props.fade_frames", "motion", ControlKind.TIMING),
    ({"type": "number"}, "props.stagger", "motion", ControlKind.TIMING),
    ({"type": "number"}, "props.durationMs", "visual", ControlKind.TIMING),
    ({"type": "enum", "values": ["a", "b"]}, "props.easing", "motion", ControlKind.MOTION),
    ({"type": "boolean"}, "props.glow", "visual", ControlKind.VALUE),
    ({"type": "number"}, "data.total", "content", ControlKind.DATA),
    ({"type": "string"}, "data.caption", "content", ControlKind.DATA),
])
def test_a_control_has_a_kind_read_from_its_type_root_group_and_name(schema, path, group, kind):
    assert control_kind(path, parse_input_schema(schema), group) is kind


# ------------------------------------------------------------------ ce qu'un moteur ne porte pas

def test_a_parameter_the_engine_cannot_carry_is_tagged_with_its_reason_never_hidden():
    url = parse_input_schema({"type": "url"})
    assert engine_support(Engine.REMOTION, url, "props.logo") == {"status": "unsupported", "reason": URL_REASON}
    assert engine_support(Engine.SLIDECAR, url, "props.logo") == {"status": "supported", "reason": ""}
    text = parse_input_schema({"type": "string"})
    assert engine_support(Engine.REMOTION, text, "props.data")["status"] == "unsupported"
    assert engine_support(Engine.REMOTION, text, "props.title")["status"] == "supported"


def test_the_contract_lists_what_is_withheld_and_drops_it_from_the_schema_it_carries():
    contract = input_contract(remotion_manifest())
    assert contract["engine"] == "remotion" and contract["carries_data"] is True
    assert contract["withheld"] == [{"path": "props.logo", "reason": URL_REASON}]
    assert "logo" not in contract["props"]["properties"] and "accent" in contract["props"]["properties"]
    assert json.loads(json.dumps(contract)) == contract, "pure JSON: it crosses to the browser as is"
    slidecar = input_contract(slidecar_manifest())
    assert slidecar["engine"] == "slidecar" and slidecar["withheld"] == [] and "logo" in slidecar["props"]["properties"]


def test_a_list_holding_a_withheld_parameter_is_withheld_whole_and_nested_ones_are_pruned():
    props = {"type": "object", "required": ["card"], "properties": {
        "card": {"type": "object", "required": ["image", "name"],
                 "properties": {"image": {"type": "url"}, "name": {"type": "string"}}},
        "cards": {"type": "array", "items": {"type": "object", "properties": {"image": {"type": "url"}}}},
        "tags": {"type": "array", "items": {"type": "string"}}}}
    sample = {"props": {"card": {"image": "https://x.test/a", "name": "n"}}, "data": {}}
    contract = input_contract(remotion_manifest(props=props, data=None, sample=sample))
    assert [item["path"] for item in contract["withheld"]] == ["props.card.image", "props.cards"]
    assert contract["props"]["properties"]["card"]["required"] == ["name"] and "cards" not in contract["props"]["properties"]
    built = build_input_props(contract, {"card": {"image": "https://x.test/a", "name": "n"}, "tags": ["a"]}, {})
    assert built.ok and built.input_props == {"card": {"name": "n"}, "tags": ["a"]} and built.dropped == ("props.card.image",)


def test_a_manifest_property_named_data_is_reserved_in_a_remotion_scene_and_data_is_then_not_carried():
    props = {"type": "object", "properties": {"data": {"type": "string", "default": "x"}, "title": {"type": "string", "default": "t"}}}
    contract = input_contract(remotion_manifest(props=props, sample={"props": {}, "data": {}}))
    assert [item["path"] for item in contract["withheld"]] == ["props.data"] and contract["carries_data"] is False
    assert build_input_props(contract, {}, {"series": [1]}).input_props == {"title": "t"}, "the reserved key stays unused"


# ------------------------------------------------------------------ parité Slidecar / Remotion

def test_the_controls_list_has_the_same_shape_in_slidecar_and_remotion_except_for_what_one_engine_cannot_carry():
    rows = {}
    for engine, manifest in (("remotion", remotion_manifest()), ("slidecar", slidecar_manifest())):
        built = scene(manifest)
        rows[engine] = [describe_control(built, manifest, control) for control in built.controls]
    assert [r["control_id"] for r in rows["remotion"]] == [r["control_id"] for r in rows["slidecar"]]
    assert [r["kind"] for r in rows["remotion"]] == ["text", "color", "spacing", "timing", "timing", "text", "data"]
    for remotion, slidecar in zip(rows["remotion"], rows["slidecar"], strict=True):
        stripped = [{k: v for k, v in row.items() if k not in ("engine", "support")} for row in (remotion, slidecar)]
        assert stripped[0] == stripped[1], remotion["control_id"]
        assert slidecar["support"]["status"] == "supported"
    assert [r["control_id"] for r in rows["remotion"] if r["support"]["status"] == "unsupported"] == ["logo"]
    assert rows["remotion"][5]["support"]["reason"] == URL_REASON
    assert {r["engine"] for r in rows["remotion"]} == {"remotion"} and {r["engine"] for r in rows["slidecar"]} == {"slidecar"}
    assert engine_of(remotion_manifest()) is Engine.REMOTION and engine_of(slidecar_manifest()) is Engine.SLIDECAR


# ------------------------------------------------------------------ le trajet complet, sur le vrai PrefabService

class World:
    def __init__(self, tmp: Path) -> None:
        package, data, studio = tmp / "package", tmp / "data", tmp / "studio"
        for folder in (package, data, studio):
            folder.mkdir()
        install_version(package, "jarvis.counter", title="Base")
        self.prefabs = PrefabService(FilePrefabLibrary(package, data), clock=lambda: NOW)
        self.studio_root = studio

    async def open(self):
        await self.prefabs.start()
        await self.prefabs.save(remotion_candidate(), actor="user")
        self.studio = PresentationStudioService(FilePresentationStudioStore(self.studio_root), prefabs=self.prefabs)
        self.edit = PresentationStudioEditService(self.studio)
        view = await self.studio.create({"title": "Remotion"})
        self.pid, self.vid = view.presentation.presentation_id, view.presentation.active_variant_id
        variant = await self.studio.get_variant(self.pid, self.vid)
        await self.studio.save_variant(self.pid, self.vid, {
            "expected_revision": variant.revision, "title": variant.title, "scenes": [scene(remotion_manifest()).to_dict()],
            "art_direction_id": None, "score_id": None})
        return self

    @property
    def file(self) -> Path:
        return self.studio_root / "presentations" / self.pid / "variants" / f"{self.vid}.json"

    def digest(self) -> str:
        return hashlib.sha256(self.file.read_bytes()).hexdigest()

    async def revision(self) -> int:
        return (await self.studio.get_variant(self.pid, self.vid)).revision

    async def run(self, *ops, revision=None, mode="commit"):
        basis = await self.revision() if revision is None else revision
        return await self.edit.edit(self.pid, self.vid, {"actor": "user", "mode": mode, "basis": {"variant_revision": basis},
                                                         "ops": list(ops)})

    async def input_props(self):
        """Ce que la page de scène enverrait au bac à sable pour l'état canonique d'aujourd'hui."""

        current = (await self.studio.get_variant(self.pid, self.vid)).scenes[0]
        return build_input_props(input_contract(remotion_manifest()), current.props, current.data)


def op_set(control_id, value, **extra):
    return {"op": "control.set", "scene_id": S1, "control_id": control_id, "value": value, **extra}


def op_reset(control_id, **extra):
    return {"op": "control.reset", "scene_id": S1, "control_id": control_id, **extra}


@pytest.fixture
async def world(tmp_path):
    return await World(tmp_path).open()


async def test_a_colour_a_spacing_and_a_stagger_edit_commit_through_control_set_and_become_the_inputprops(world):
    result = await world.run(op_set("accent", "#ff0000"), op_set("gap", 24), op_set("stagger", 3.5), op_set("fade", 30),
                             op_set("headline", "Titre"), op_set("series", [4, 5, 6]))
    assert result.status is EditStatus.APPLIED and result.committed and result.tier.value == "structure", "a list value is structure"
    built = await world.input_props()
    assert built.ok and built.input_props == {"title": "Titre", "accent": "#ff0000", "gap": 24, "stagger": 3.5, "fade_frames": 30,
                                              "data": {"series": [4, 5, 6]}}
    stored = json.loads(world.file.read_text(encoding="utf-8"))["scenes"][0]
    assert stored["props"]["accent"] == "#ff0000" and stored["data"]["series"] == [4, 5, 6], "the canonical state is the saved one"


async def test_a_preview_changes_nothing_that_is_saved_and_a_commit_only_what_it_says(world):
    before, revision = world.digest(), await world.revision()
    preview = await world.run(op_set("accent", "#00ff00"), mode="preview")
    assert preview.status is EditStatus.APPLIED and not preview.committed and preview.ops[0]["after"] == "#00ff00"
    assert world.digest() == before and await world.revision() == revision, "a preview-only value is never persisted"
    assert (await world.input_props()).input_props["accent"] == "#3366ff"
    committed = await world.run(op_set("accent", "#00ff00"))
    assert committed.committed and committed.revision == revision + 1
    assert (await world.input_props()).input_props["accent"] == "#00ff00"


@pytest.mark.parametrize(("control_id", "value"), [
    ("accent", "red"), ("accent", "#f00"), ("gap", 61), ("gap", 3), ("gap", 12.5), ("gap", "12"), ("stagger", True),
    ("fade", 0), ("headline", "x" * 81), ("headline", "a\nb"), ("series", [1, 2, 3, 4, 5, 6]), ("series", ["a"]),
    ("headline", {"a": 1}),
])
async def test_a_value_outside_the_type_or_the_bounds_is_refused_and_writes_nothing(world, control_id, value):
    digest = world.digest()
    result = await world.run(op_set(control_id, value))
    assert result.status is EditStatus.REFUSED and result.code == C.VALUE_REFUSED.value and not result.committed
    assert world.digest() == digest


@pytest.mark.parametrize("value", [[{"__proto__": {"polluted": True}}], [{"constructor": {"prototype": {}}}], [[{"prototype": 1}]]])
async def test_a_prototype_trick_in_a_value_is_refused_before_anything_is_stored(world, value):
    digest = world.digest()
    result = await world.run(op_set("series", value))
    assert result.status is EditStatus.REFUSED and not result.committed and world.digest() == digest
    assert result.code in (C.INVALID_PRESENTATION.value, C.VALUE_REFUSED.value)


async def test_a_control_the_engine_cannot_carry_is_refused_saying_so_instead_of_doing_nothing(world):
    digest = world.digest()
    result = await world.run(op_set("logo", "https://example.test/logo.png"))
    assert result.status is EditStatus.REFUSED and result.code == C.VALUE_REFUSED.value
    assert "not supported by the remotion engine" in result.message and "staticFile" in result.message
    assert world.digest() == digest
    assert (await world.run(op_reset("logo"))).status is EditStatus.APPLIED, "clearing a value the engine ignores stays possible"


async def test_a_stale_base_revision_and_a_stale_current_value_are_both_rejected(world):
    first = await world.run(op_set("gap", 20))
    digest = world.digest()
    base = await world.run(op_set("gap", 30), revision=first.revision - 1)
    assert base.status is EditStatus.STALE and base.code == C.STALE_REVISION.value and world.digest() == digest
    value = await world.run(op_set("gap", 30, if_current=8))
    assert value.status is EditStatus.STALE and "no longer what the edit expected" in value.message and world.digest() == digest
    fresh = await world.run(op_set("gap", 30, if_current=20))
    assert fresh.status is EditStatus.APPLIED and fresh.committed


async def test_reset_gives_back_the_curated_default_or_the_manifest_default_and_is_undoable(world):
    await world.run(op_set("accent", "#ff0000"), op_set("headline", "Autre"), op_set("gap", 50))
    reset = await world.run(op_reset("accent", if_current="#ff0000"), op_reset("headline"), op_reset("gap"))
    assert reset.status is EditStatus.APPLIED and reset.committed
    current = (await world.studio.get_variant(world.pid, world.vid)).scenes[0]
    assert current.props["accent"] == "#3366ff", "the curated default is written explicitly"
    assert "title" not in current.props and "gap" not in current.props, "no curated default: the key is unset"
    assert (await world.input_props()).input_props["title"] == "Bonjour", "the manifest default fills the unset key"
    assert reset.undo is not None, "the inverse is recorded: a reset is not destructive"
    assert (await world.run(op_reset("accent", if_current="#000000"))).status is EditStatus.STALE


def test_values_that_are_not_valid_for_the_contract_are_never_built_into_inputprops():
    contract = input_contract(remotion_manifest())
    for bad in ({"title": "x", "accent": "#12345"}, {"stagger": 31}, {"unknown": 1}):
        built = build_input_props(contract, bad, {})
        assert not built.ok and built.input_props == {} and built.problems
