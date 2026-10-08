"""Presentation Studio: the authoring brief and the first-draft submission (handoff jarvis-interactive-presentation-studio, Slice 11).

The heavy creative work is done by the Jarvis brain (an LLM). This module is the **deterministic contract** it hands its
work over in, so that quality is enforced by code and not by hope: one `AuthoringBrief` (what was asked) and one
`PresentationDraft` (everything the brain produced, in ONE submission). Contract: `docs/presentation-studio.md`
> *Authoring contract (Slice 11)*.

Rules that hold for the whole module:

- **Strict and bounded.** Every object is exact (an unknown key is refused, a runtime-state name keeps its own code),
  every collection and string is bounded. A draft is parsed *completely* before anything is judged: all the schema problems
  are collected (at most `MAX_PROBLEMS`) so the brain fixes them in one round, not one at a time.
- **Logical keys, never ids.** The brain names scenes, bundles and candidates with slugs of its own (`intro`, `hero`).
  Every `pst_`, `psv_`, `pss_`, `psi_`, `psc_`, `psr_` and `psd_` id is allocated by Core in `presentation_studio_authoring_build.py`;
  a brain can neither invent nor choose one. Only a prefab pin `{id, version}` of an existing prefab comes from a tool result.
- **Everything the brain wrote is untrusted data.** Titles, speech, notes, cue phrases, rationales and resource titles are stored
  and displayed, never interpreted or obeyed (the same line as the score and the art direction).
- **Reuse, never a second model.** Scenes are `StudioScene`, controls `StudioControl`, the score is the Slice 10 contract
  (`ScoreItem`, `CuePredicate`, `ActionRef`), the art direction the Slice 09 profile (`profile`, derived `signals`, or the
  deterministic `fallback`), a prefab source is the `PrefabService` candidate. This module adds only the submission envelope.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import Any

from jarvis.domain.prefab import PrefabBundle, PrefabDefinitionError, PrefabRef, canonical_json, parse_candidate
from jarvis.domain.presentation_studio import MAX_RESOURCES, resource_from_dict
from jarvis.domain.presentation_studio_art_direction import ArtDirectionProfile, parse_profile
from jarvis.domain.presentation_studio_art_direction_authoring import (
    MAX_DIVERGE, SeedContext, derive_from_signals, generate_fallback_profile, parse_design_signals,
)
from jarvis.domain.presentation_studio_checks import (
    MAX_TITLE, PresentationStudioError, _check_int, _exact_keys, _fail,
)
from jarvis.domain.presentation_studio_scene import SLUG, ScenePreview, ScoreAnchor, StudioControl, StudioScene
from jarvis.domain.presentation_studio_score import (
    MAX_LABEL, ActionKind, ActionRef, CuePredicate, Interruption, Presenter, ScoreItem,
)
from jarvis.domain.presentation_studio_variants import MAX_RATIONALE_BYTES, check_rationale, rationale_bytes
from jarvis.domain.presentation_working_set import ResourceReference

# ------------------------------------------------------------------ bounds (documented in the contract)

#: Prefab bundles one draft may publish (each is up to ~160 KiB of source; the relay body bound follows).
MAX_DRAFT_BUNDLES = 16
#: Scenes and score items of a draft: 75 % of the document caps (`MAX_SCENES` 64, `MAX_ITEMS` 200), the rest is headroom for edits.
MAX_DRAFT_SCENES = 48
MAX_DRAFT_ITEMS = 150
MIN_CANDIDATES = 2
MAX_CANDIDATES = MAX_DIVERGE
MAX_PROBLEMS = 20
MAX_BRIEF_LINE = 200
MAX_BRIEF_LIST = 8
MAX_TONE_WORD = 24
MIN_DURATION_S = 5
MAX_DURATION_S = 10_800
MAX_CANDIDATE_RATIONALE = 240
#: A request body above this is refused before it is parsed: 16 bundles of up to ~160 KiB each, the documents and some slack.
MAX_AUTHORING_BODY_BYTES = 4 * 1024 * 1024
#: A published bundle belongs to the Studio namespace (retention-aware, `jarvis.domain.prefab.RETENTION_NAMESPACE`).
BUNDLE_NAMESPACE = "presentation-studio."
#: Marker prefix of a candidate variant's rationale: an exploratory candidate is a draft until the user picks it.
DRAFT_RATIONALE_PREFIX = "draft direction"

_LANGUAGE = re.compile(r"[a-z]{2,3}(?:-[A-Z]{2})?\Z")
PLACEHOLDER_SCENE_ID = "pss_" + "0" * 12
PLACEHOLDER_ITEM_ID = "psi_" + "0" * 12


class Workflow(StrEnum):
    ONE_SHOT = "one_shot"
    DIRECTED = "directed"
    EXPLORATORY = "exploratory"

    @property
    def serious(self) -> bool:
        """`require_art_direction(serious=...)`: a one-shot and a directed variant always resolve a DA; an exploratory one may be a bare draft."""

        return self is not Workflow.EXPLORATORY


class Speech(StrEnum):
    """Who speaks in the presentation, as the brief says it."""

    JARVIS = "jarvis"
    USER = "user"
    NONE = "none"


class SceneRole(StrEnum):
    OPENING = "opening"
    BODY = "body"
    CLOSING = "closing"
    #: A one-scene presentation (a report shown at once).
    SINGLE = "single"


class DaMode(StrEnum):
    PROFILE = "profile"
    SIGNALS = "signals"
    FALLBACK = "fallback"


# ------------------------------------------------------------------ small checks

def _line(where: str, value: object, limit: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise _fail(f"{where} must be a string")
    if not value:
        if allow_empty:
            return value
        raise _fail(f"{where} must not be empty")
    if value != value.strip() or not value.isprintable() or len(value) > limit:
        raise _fail(f"{where} must be one printable line of at most {limit} characters, without surrounding spaces")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise _fail(f"{where} holds a character that cannot be stored (lone surrogate)") from None
    return value


def _list(where: str, value: object, limit: int, low: int = 0) -> list[Any]:
    if not isinstance(value, list):
        raise _fail(f"{where} must be a list")
    if not low <= len(value) <= limit:
        raise _fail(f"{where} must hold {low}..{limit} entries")
    return value


def _slug(where: str, value: object) -> str:
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise _fail(f"{where} must match [a-z][a-z0-9_]{{0,39}}")
    return value


def _flag(where: str, value: object) -> bool:
    if type(value) is not bool:
        raise _fail(f"{where} must be true or false")
    return value


def _enum(kind: type[StrEnum], where: str, value: object) -> Any:
    try:
        return kind(value)
    except (ValueError, TypeError):
        raise _fail(f"{where} must be one of {', '.join(m.value for m in kind)}") from None


# ------------------------------------------------------------------ the brief

@dataclass(frozen=True, slots=True)
class AuthoringBrief:
    """What was asked, as the brain understood it after inspecting the project and asking what it had to. Untrusted text."""

    title: str
    workflow: Workflow
    purpose: str = ""
    audience: str = ""
    #: Intended length in seconds (the gate holds the soft targets of the score to +-35 % of it); `None`: not stated.
    duration_target_s: int | None = None
    tone: tuple[str, ...] = ()
    #: `fr`, `en`, `fr-CA`... : the language of what the audience reads and hears.
    language: str = ""
    speech: Speech = Speech.JARVIS
    #: References of what the draft was built from (provenance): stored on the Presentation, never a copied content.
    resources: tuple[ResourceReference, ...] = ()
    must_cover: tuple[str, ...] = ()
    max_scenes: int = MAX_DRAFT_SCENES

    def seed(self) -> SeedContext:
        """The context the deterministic DA fallback reads (title, audience, purpose, tone; clipped to its own bounds)."""

        clip = lambda text: text[:200]  # noqa: E731 - tiny local helper, the bound is the fallback's own
        return SeedContext(clip(self.title), clip(self.audience), clip(self.purpose),
                           tuple(word[:24] for word in self.tone[:8]))

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "workflow": self.workflow.value, "purpose": self.purpose, "audience": self.audience,
                "duration_target_s": self.duration_target_s, "tone": list(self.tone), "language": self.language,
                "speech": self.speech.value,
                "resources": [{"kind": r.kind.value, "locator": r.locator, "title": r.title} for r in self.resources],
                "must_cover": list(self.must_cover), "max_scenes": self.max_scenes}

    def digest_source(self) -> str:
        return canonical_json(self.to_dict())


_BRIEF_OPTIONAL = frozenset({"purpose", "audience", "duration_target_s", "tone", "language", "speech", "resources",
                             "must_cover", "max_scenes"})


def parse_brief(raw: object) -> AuthoringBrief:
    """Exact keys, bounded, untrusted text kept as text. A resource locator goes through the Slice 02 hygiene (`resource_from_dict`)."""

    data = _exact_keys(raw, "brief", {"title", "workflow"}, _BRIEF_OPTIONAL)
    title = _line("brief.title", data["title"], MAX_TITLE)
    workflow = _enum(Workflow, "brief.workflow", data["workflow"])
    duration = data.get("duration_target_s")
    if duration is not None:
        _check_int("brief.duration_target_s", duration, MIN_DURATION_S, MAX_DURATION_S)
    tone = tuple(_line("brief.tone[]", w, MAX_TONE_WORD) for w in _list("brief.tone", data.get("tone", []), MAX_BRIEF_LIST))
    language = data.get("language", "")
    if language != "" and (not isinstance(language, str) or not _LANGUAGE.fullmatch(language)):
        raise _fail("brief.language must look like fr, en or fr-CA")
    must = tuple(_line("brief.must_cover[]", w, 120) for w in _list("brief.must_cover", data.get("must_cover", []), MAX_BRIEF_LIST))
    resources = tuple(resource_from_dict(r, f"brief.resources[{i}]")
                      for i, r in enumerate(_list("brief.resources", data.get("resources", []), MAX_RESOURCES)))
    if len({(r.kind, r.locator) for r in resources}) != len(resources):
        raise _fail("brief.resources hold the same reference twice")
    max_scenes = data.get("max_scenes", MAX_DRAFT_SCENES)
    _check_int("brief.max_scenes", max_scenes, 1, MAX_DRAFT_SCENES)
    return AuthoringBrief(
        title, workflow, _line("brief.purpose", data.get("purpose", ""), MAX_BRIEF_LINE, allow_empty=True),
        _line("brief.audience", data.get("audience", ""), MAX_BRIEF_LINE, allow_empty=True), duration, tone, language,
        _enum(Speech, "brief.speech", data.get("speech", "jarvis")), resources, must, max_scenes)


# ------------------------------------------------------------------ the draft

@dataclass(frozen=True, slots=True)
class DraftBundle:
    """A new prefab source the draft publishes (a `PrefabService` candidate). `bundle` is its parsed form."""

    key: str
    candidate: Mapping[str, Any]
    bundle: PrefabBundle

    @property
    def prefab_id(self) -> str:
        return self.bundle.manifest.prefab_id


@dataclass(frozen=True, slots=True)
class DraftScene:
    """A logical scene. `scene` carries the Slice 04 content with a provisional id and, for a bundle, the candidate's own pin;
    Core replaces both when it allocates ids and publishes the bundle."""

    key: str
    role: SceneRole
    scene: StudioScene
    #: Key of the draft bundle this scene is rendered by, or `None` for an existing pin.
    bundle_key: str | None = None
    #: A full-read scene (a document): the text-density cap rises to the long-form cap and the report says so.
    long_form: bool = False
    #: The author attests that the hard cut INTO this scene is intended (no transition declared).
    cut: bool = False


@dataclass(frozen=True, slots=True)
class DraftAction:
    """A closed, reversible score action naming a logical scene (`scene` defaults to the item's own scene)."""

    action: ActionRef
    scene: str | None


@dataclass(frozen=True, slots=True)
class DraftCue:
    label: str
    predicate: CuePredicate
    armable: bool


@dataclass(frozen=True, slots=True)
class DraftItem:
    scene: str
    presenter: Presenter
    text: str = ""
    note: str = ""
    label: str = ""
    cue: DraftCue | None = None
    visual: tuple[DraftAction, ...] = ()
    motion: tuple[DraftAction, ...] = ()
    target_duration_ms: int | None = None
    interruption: Interruption = Interruption.ALLOW


@dataclass(frozen=True, slots=True)
class DraftDirection:
    """One variant of the submission. A serious draft has exactly one; an exploratory one has two to six, each a candidate."""

    title: str
    rationale: str
    profile: ArtDirectionProfile | None
    #: `{scene key: {title?, props?, data?}}` : what this direction changes in the shared scenes (kept light).
    patch: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PresentationDraft:
    bundles: tuple[DraftBundle, ...]
    scenes: tuple[DraftScene, ...]
    items: tuple[DraftItem, ...]
    directions: tuple[DraftDirection, ...]

    def scene(self, key: str) -> DraftScene | None:
        return next((s for s in self.scenes if s.key == key), None)


@dataclass(frozen=True, slots=True)
class Problem:
    """One schema problem. `code` is a gate rule code (`draft_schema`, `prefab_invalid`, `contrast_low`...)."""

    code: str
    where: str
    message: str


@dataclass(frozen=True, slots=True)
class ParsedDraft:
    """`draft` is `None` whenever `problems` is not empty: a half-understood submission is never judged or written."""

    draft: PresentationDraft | None
    problems: tuple[Problem, ...]


class _Collector:
    def __init__(self) -> None:
        self.problems: list[Problem] = []

    def add(self, code: str, where: str, message: str) -> None:
        if len(self.problems) < MAX_PROBLEMS:
            self.problems.append(Problem(code, where, message[:300]))

    def guard(self, where: str, work: Callable[[], Any], *, code: str = "draft_schema") -> Any:
        """Runs `work`; a coded refusal of the domain becomes a problem and `None`. Nothing else is caught."""

        try:
            return work()
        except PresentationStudioError as exc:
            self.add("contrast_low" if "contrast" in exc.message and code == "draft_schema" else code, where, exc.message)
        except PrefabDefinitionError as exc:
            self.add(code, where, "; ".join(exc.errors[:2]))
        return None


# ------------------------------------------------------------------ parsing the draft

def _action(raw: object, where: str, own_scene: str, *, track: str) -> DraftAction:
    data = _exact_keys(raw, where, {"kind"}, frozenset({"scene", "control_id", "anchor_id", "value"}))
    kind = _enum(ActionKind, f"{where}.kind", data["kind"])
    if kind is ActionKind.SEQUENCE:
        raise _fail(f"{where}: a locked sequence is not authored in a first draft (add it afterwards with the sequence tools)")
    scene = data.get("scene")
    if scene is not None:
        _slug(f"{where}.scene", scene)
    elif kind is ActionKind.SCENE_GOTO:
        raise _fail(f"{where}: scene_goto names its scene")
    fields = {name: data[name] for name in ("control_id", "anchor_id", "value") if name in data}
    # Validated now with a placeholder scene id: the shape, the closed kinds and the scalar value are the Slice 10 contract's.
    action = ActionRef(kind, scene_id=PLACEHOLDER_SCENE_ID, **fields)
    if track == "motion" and kind is not ActionKind.CONTROL_SET:
        raise _fail(f"{where}: the motion track holds control_set actions only")
    if kind is ActionKind.SCENE_GOTO and scene != own_scene:
        raise _fail(f"{where}: an item's own scene_goto names its scene ({own_scene!r})")
    return DraftAction(action, scene)


def _cue(raw: object, where: str) -> DraftCue:
    data = _exact_keys(raw, where, {"label", "armable"}, frozenset({"phrases", "semantics"}))
    predicate = CuePredicate(tuple(_list(f"{where}.phrases", data.get("phrases", []), 8)),
                             tuple(_list(f"{where}.semantics", data.get("semantics", []), 4)))
    cue = DraftCue(_line(f"{where}.label", data["label"], MAX_LABEL), predicate, _flag(f"{where}.armable", data["armable"]))
    if cue.armable and predicate.is_empty():
        raise _fail(f"{where} is armable but names no phrase and no semantic label")
    return cue


def _item(raw: object, where: str, scene_keys: set[str]) -> DraftItem:
    data = _exact_keys(raw, where, {"scene", "presenter"},
                       frozenset({"text", "note", "label", "cue", "visual", "motion", "target_duration_ms", "interruption"}))
    scene = _slug(f"{where}.scene", data["scene"])
    if scene not in scene_keys:
        raise _fail(f"{where}: scene {scene!r} is not a scene key of this draft")
    presenter = _enum(Presenter, f"{where}.presenter", data["presenter"])
    visual = tuple(_action(a, f"{where}.visual[{i}]", scene, track="visual")
                   for i, a in enumerate(_list(f"{where}.visual", data.get("visual", []), 4)))
    motion = tuple(_action(a, f"{where}.motion[{i}]", scene, track="motion")
                   for i, a in enumerate(_list(f"{where}.motion", data.get("motion", []), 4)))
    cue = _cue(data["cue"], f"{where}.cue") if data.get("cue") is not None else None
    target = data.get("target_duration_ms")
    interruption = _enum(Interruption, f"{where}.interruption", data.get("interruption", "allow"))
    item = DraftItem(scene, presenter, data.get("text", ""), data.get("note", ""), data.get("label", ""), cue, visual,
                     motion, target, interruption)
    # The Slice 10 item rules (speech xor note, silence is presenter none, bounds), checked on a placeholder-id item.
    ScoreItem(PLACEHOLDER_ITEM_ID, PLACEHOLDER_SCENE_ID, presenter, "silence" if presenter is Presenter.NONE else "speech",
              item.label, item.text, item.note, None, tuple(a.action for a in visual), tuple(a.action for a in motion),
              target, interruption=interruption)
    return item


def _scene(raw: object, where: str, bundles: Mapping[str, DraftBundle]) -> DraftScene:
    data = _exact_keys(raw, where, {"key", "role", "title", "prefab"},
                       frozenset({"section", "props", "data", "controls", "anchors", "alt", "long_form", "cut"}))
    key = _slug(f"{where}.key", data["key"])
    role = _enum(SceneRole, f"{where}.role", data["role"])
    ref = _exact_keys(data["prefab"], f"{where}.prefab", set(), frozenset({"bundle", "id", "version"}))
    bundle_key: str | None = None
    if "bundle" in ref:
        if set(ref) != {"bundle"}:
            raise _fail(f"{where}.prefab is either {{bundle}} or {{id, version}}")
        bundle_key = _slug(f"{where}.prefab.bundle", ref["bundle"])
        if bundle_key not in bundles:
            raise _fail(f"{where}.prefab.bundle {bundle_key!r} is not a bundle key of this draft")
        manifest = bundles[bundle_key].bundle.manifest
        pin = PrefabRef(manifest.prefab_id, manifest.version)
    else:
        if set(ref) != {"id", "version"}:
            raise _fail(f"{where}.prefab is either {{bundle}} or {{id, version}}")
        pin = PrefabRef.from_dict(ref, f"{where}.prefab")
    for name in ("props", "data"):
        if not isinstance(data.get(name, {}), dict):
            raise _fail(f"{where}.{name} must be an object")
    controls = _list(f"{where}.controls", data.get("controls", []), 32)
    anchors = _list(f"{where}.anchors", data.get("anchors", []), 16)
    alt = _line(f"{where}.alt", data.get("alt", ""), 200, allow_empty=True)
    title = _line(f"{where}.title", data["title"], MAX_TITLE)
    scene = StudioScene(
        PLACEHOLDER_SCENE_ID, pin, title, _line(f"{where}.section", data.get("section", ""), 40, allow_empty=True),
        data.get("props", {}), data.get("data", {}),
        tuple(StudioControl.from_dict(c, f"{where}.controls[{i}]") for i, c in enumerate(controls)),
        tuple(ScoreAnchor.from_dict(a, f"{where}.anchors[{i}]") for i, a in enumerate(anchors)),
        ScenePreview(title[:120], alt))
    return DraftScene(key, role, scene, bundle_key, _flag(f"{where}.long_form", data.get("long_form", False)),
                      _flag(f"{where}.cut", data.get("cut", False)))


def _profile(raw: object, where: str, brief: AuthoringBrief) -> ArtDirectionProfile:
    data = _exact_keys(raw, where, {"mode"}, frozenset({"profile", "signals"}))
    mode = _enum(DaMode, f"{where}.mode", data["mode"])
    needed = {"profile": "profile", "signals": "signals"}.get(mode.value)
    if needed is None:
        if len(data) != 1:
            raise _fail(f"{where}: mode fallback takes no other key (it reads the brief)")
        return generate_fallback_profile(brief.seed())
    if set(data) != {"mode", needed}:
        raise _fail(f"{where}: mode {mode.value} takes exactly {{mode, {needed}}}")
    if mode is DaMode.PROFILE:
        return parse_profile(data["profile"])
    return derive_from_signals(parse_design_signals(data["signals"]))


def _patch(raw: object, where: str, scene_keys: set[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict) or len(raw) > MAX_DRAFT_SCENES:
        raise _fail(f"{where} must be an object of at most {MAX_DRAFT_SCENES} scene patches")
    out: dict[str, dict[str, Any]] = {}
    for key, body in raw.items():
        _slug(f"{where} key", key)
        if key not in scene_keys:
            raise _fail(f"{where}: {key!r} is not a scene key of this draft")
        patch = _exact_keys(body, f"{where}.{key}", set(), frozenset({"title", "props", "data"}))
        if "title" in patch:
            _line(f"{where}.{key}.title", patch["title"], MAX_TITLE)
        for name in ("props", "data"):
            if name in patch and not isinstance(patch[name], dict):
                raise _fail(f"{where}.{key}.{name} must be an object")
        out[key] = patch
    return out


def _direction(raw: object, where: str, brief: AuthoringBrief, scene_keys: set[str]) -> DraftDirection:
    data = _exact_keys(raw, where, {"title", "rationale"}, frozenset({"art_direction", "scenes_patch"}))
    title = _line(f"{where}.title", data["title"], MAX_TITLE)
    rationale = _line(f"{where}.rationale", data["rationale"], MAX_CANDIDATE_RATIONALE)
    profile = _profile(data["art_direction"], f"{where}.art_direction", brief) if data.get("art_direction") is not None else None
    patch = _patch(data.get("scenes_patch", {}), f"{where}.scenes_patch", scene_keys)
    composed = f"{DRAFT_RATIONALE_PREFIX} 6/6: {rationale}"
    check_rationale(composed)
    if rationale_bytes(composed) > MAX_RATIONALE_BYTES:
        raise _fail(f"{where}.rationale is too heavy once encoded")
    return DraftDirection(title, rationale, profile, patch)


_DRAFT_KEYS = frozenset({"prefabs", "art_direction", "candidates"})


def _waits_on(entry: object, failed: set[str]) -> bool:
    ref = entry.get("prefab") if isinstance(entry, dict) else None
    return isinstance(ref, dict) and ref.get("bundle") in failed


def parse_draft(raw: object, brief: AuthoringBrief) -> ParsedDraft:
    """The whole submission, every problem collected (at most `MAX_PROBLEMS`). `draft` is set only when there is none."""

    c = _Collector()
    try:
        data = _exact_keys(raw, "draft", {"scenes", "score"}, _DRAFT_KEYS)
    except PresentationStudioError as exc:
        c.add("draft_schema", "draft", exc.message)
        return ParsedDraft(None, tuple(c.problems))

    bundles: dict[str, DraftBundle] = {}
    failed_bundles: set[str] = set()
    for i, entry in enumerate(c.guard("draft.prefabs", lambda: _list("draft.prefabs", data.get("prefabs", []), MAX_DRAFT_BUNDLES)) or []):
        where = f"bundle:{i + 1}"
        body = c.guard(where, lambda e=entry, w=where: _exact_keys(e, w, {"key", "candidate"}))
        if body is None:
            continue
        key = c.guard(where, lambda b=body, w=where: _slug(f"{w}.key", b["key"]))
        if key is None:
            continue
        if key in bundles:
            c.add("draft_schema", f"bundle:{key}", "the same bundle key appears twice")
            continue
        parsed = c.guard(f"bundle:{key}", lambda b=body: parse_candidate(b["candidate"]), code="prefab_invalid")
        if parsed is not None:
            bundles[key] = DraftBundle(key, body["candidate"], parsed)
        else:
            failed_bundles.add(key)

    scenes: list[DraftScene] = []
    scene_list = c.guard("draft.scenes", lambda: _list("draft.scenes", data["scenes"], MAX_DRAFT_SCENES, 1)) or []
    #: Keys of scenes that wait on a bundle which did not parse: already reported by the bundle, so no second error about them.
    blocked: set[str] = set()
    for i, entry in enumerate(scene_list):
        if _waits_on(entry, failed_bundles):
            if isinstance(entry.get("key"), str) and SLUG.fullmatch(entry["key"]):
                blocked.add(entry["key"])
            continue
        scene = c.guard(f"scene:{i + 1}", lambda e=entry, n=i: _scene(e, f"scenes[{n}]", bundles))
        if scene is None:
            continue
        if any(s.key == scene.key for s in scenes):
            c.add("draft_schema", f"scene:{scene.key}", "the same scene key appears twice")
            continue
        scenes.append(scene)
    if len(scene_list) > brief.max_scenes:
        c.add("draft_schema", "draft.scenes", f"the brief allows at most {brief.max_scenes} scenes")
    unused = sorted(set(bundles) - {s.bundle_key for s in scenes if s.bundle_key})
    if unused and len(scenes) + len(blocked) == len(scene_list):
        c.add("draft_schema", f"bundle:{unused[0]}", "a bundle is published but no scene uses it")

    keys = {s.key for s in scenes} | blocked
    items: list[DraftItem] = []
    score = c.guard("draft.score", lambda: _exact_keys(data["score"], "score", {"items"}))
    item_list = c.guard("score.items", lambda: _list("score.items", score["items"], MAX_DRAFT_ITEMS, 1)) if score else []
    for i, entry in enumerate(item_list or []):
        item = c.guard(f"item:{i + 1}", lambda e=entry, n=i: _item(e, f"score.items[{n}]", keys))
        if item is not None:
            items.append(item)

    directions = _directions(data, brief, keys, c)
    if c.problems:
        return ParsedDraft(None, tuple(c.problems))
    return ParsedDraft(PresentationDraft(tuple(bundles.values()), tuple(scenes), tuple(items), tuple(directions)), ())


def _directions(data: Mapping[str, Any], brief: AuthoringBrief, keys: set[str], c: _Collector) -> list[DraftDirection]:
    """Serious: one `art_direction` and no candidates. Exploratory: two to six `candidates` and no top-level `art_direction`."""

    if brief.workflow is Workflow.EXPLORATORY:
        if "art_direction" in data:
            c.add("draft_schema", "draft.art_direction", "an exploratory draft carries its art directions in candidates, not at the top")
        listed = c.guard("draft.candidates", lambda: _list("draft.candidates", data.get("candidates", []), MAX_CANDIDATES)) or []
        out = []
        for i, entry in enumerate(listed):
            direction = c.guard(f"candidate:{i + 1}", lambda e=entry, n=i: _direction(e, f"candidates[{n}]", brief, keys))
            if direction is not None:
                out.append(direction)
        return out
    if "candidates" in data:
        c.add("draft_schema", "draft.candidates", f"a {brief.workflow.value} draft is one direction: candidates belong to exploratory")
    if "art_direction" not in data:
        return [DraftDirection(brief.title, f"first draft ({brief.workflow.value})", None)]
    profile = c.guard("art_direction", lambda: _profile(data["art_direction"], "art_direction", brief))
    return [DraftDirection(brief.title, f"first draft ({brief.workflow.value})", profile)] if profile is not None else []
