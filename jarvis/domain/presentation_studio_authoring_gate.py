"""Presentation Studio: the first-draft quality gate (handoff jarvis-interactive-presentation-studio, Slice 11).

`check_first_draft(draft, brief, manifests=None, built=None) -> QualityReport` is **deterministic and explainable**: every
finding carries a rule `code`, a `severity` (`error` blocks delivery, `warning` does not), a `where` (logical keys:
`scene:intro`, `item:4`, `candidate:2`, `bundle:hero`, `art_direction`, `score`) and a message that says what to change.
A message never carries the author's free text: a placeholder finding names the *kind*, an unknown key is counted, a refused value is
replaced by `<value>` (`safe_text`); what does appear is a position (`item:4`), a validated slug (`scene:intro`), a code or a size.
The same draft always gives the same report (no clock, no randomness, no model).

**One rule table, three columns** (`RULES`, mirrored in `docs/presentation-studio.md`): the level of each rule is `error`,
`warning` or `off` for `one_shot`, `directed` and `exploratory`. A serious workflow (`one_shot`, `directed`) is refused when any
error remains, with the *whole* list so the brain fixes everything in one round. The exploratory column is the documented lighter
subset: what is objectively broken (an invalid prefab, a placeholder, a contrast failure, a score that does not resolve) and what
does not depend on lightness (an arc with an opening and a closing, every scene in the score, motion that honours reduced motion)
still refuses, the rest of the craft rules are warnings or off, and candidates are marked as drafts when stored. An exploratory
request over a briefed deck sets `brief.strict_content`: every rule then has its `directed` level (a candidate may be light, a deck
whose content is given may not). `finalize` re-gates a stored candidate as `directed` before it is adopted.

The gate is a FLOOR, not a judge of quality: it refuses empty, placeholder, repeated and unbounded content and the structural gaps.
`purpose`, `audience` and `tone` of the brief are untrusted prose with no deterministic check worth the name: they steer the model
through the prompt and seed the art direction fallback, nothing else.

What needs more than the draft is optional and its absence is *reported*, never silent: `manifests` (scene key -> the
`PrefabManifest` of its pin) enables the control-bounds and colour-contrast rules; `built` (the provisional documents from
`presentation_studio_authoring_build.build_presentation`) enables the cue rules (they reuse the Slice 10 `weak_cue_warnings` and
`ambiguous_phrases`) and the payload / document headroom rules. `QualityReport.skipped` lists the rules that could not run.

Pure: no I/O.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from jarvis.domain.prefab import InputType, PrefabManifest
from jarvis.domain.presentation_studio import MAX_DOCUMENT_BYTES
from jarvis.domain.presentation_studio_art_direction import ArtDirectionProfile, Origin
from jarvis.domain.presentation_studio_art_direction_authoring import MIN_DIVERGENCE, profile_distance
from jarvis.domain.presentation_studio_art_direction_vocab import GRAPHIC_RATIO, TransitionStyle, contrast_ratio
from jarvis.domain.presentation_studio_authoring import (
    MAX_CANDIDATES, MIN_CANDIDATES, AuthoringBrief, DraftScene, PresentationDraft, Problem, SceneRole, Speech, Workflow, safe_text,
)
from jarvis.domain.presentation_studio_authoring_text import (  # noqa: F401 - re-exported: the historical home of these names
    LANGUAGE_LEAD, MIN_LINE_WORDS, MIN_SCENE_WORDS, MUST_COVER_THRESHOLD, NUMERIC_FILLER_SCENES, NUMERIC_TITLE_SCENES, MIN_FILLER_CHARS,
    MIN_BODY_WORDS, count_words, covers, fold, guess_language, is_allowed, is_literal, is_motion_unguarded, label_meaningless, meaningful_words,
    normalise_filler, placeholder_hit, placeholder_hits, placeholder_kind, prose_leaves, risky_constructs, stems,
)
from jarvis.domain.presentation_studio_authoring_build import BuiltPresentation
from jarvis.domain.presentation_studio_checks import PresentationStudioError
from jarvis.domain.presentation_studio_playback import ARM_LOOKAHEAD
from jarvis.domain.presentation_studio_scene import effective_bounds, node_of, value_at
from jarvis.domain.presentation_studio_score import ActionKind, Presenter, ambiguous_phrases, normalise_phrase, phrase_weakness

# ------------------------------------------------------------------ thresholds (the rule table quotes them)

#: Controls one scene exposes (Slice 04 allows 32; a scene with more is not curated, it is a dump of the manifest).
MAX_CONTROLS_PER_SCENE = 12
#: Visible words of one scene: a slide that is read aloud over, not a page. Warning above 2/3 of it. A `long_form` scene (a
#: full-read document) has its own cap.
MAX_SCENE_WORDS = 120
LONG_FORM_WORDS = 600
#: Sum of the soft targets of the score against the brief's duration.
DURATION_TOLERANCE = 0.35
MIN_ITEM_MS = 500
MAX_ITEM_MS = 900_000
#: Used share of a cap above which there is no room left for edits (payload of a scene, document sizes).
HEADROOM = 0.75
#: Armable cues this close to each other (in score items) must not share a phrase: the armed set follows the playback position
#: (`ARM_LOOKAHEAD` ahead), a user who jumps lands in a neighbourhood, so the lint looks a little wider than the set.
CUE_WINDOW = ARM_LOOKAHEAD + 2
MAX_FINDINGS_PER_RULE = 5
MAX_FINDINGS = 60

ERROR, WARNING, OFF = "error", "warning", "off"


@dataclass(frozen=True, slots=True)
class Rule:
    code: str
    one_shot: str
    directed: str
    exploratory: str
    summary: str

    def level(self, workflow: Workflow, strict: bool = False) -> str:
        """`strict` (exploratory with `brief.strict_content`): the `directed` level wherever `directed` has one, the exploratory level
        for the rules only exploratory has (the candidate shape)."""

        if workflow is Workflow.EXPLORATORY and strict and self.directed != OFF:
            return self.directed
        return {Workflow.ONE_SHOT: self.one_shot, Workflow.DIRECTED: self.directed, Workflow.EXPLORATORY: self.exploratory}[workflow]


E, W, O = ERROR, WARNING, OFF
RULES: tuple[Rule, ...] = (
    # --- validation: the submission is understood and consistent with the prefabs (always blocking)
    Rule("brief_invalid", E, E, E, "the brief is an exact, bounded object"),
    Rule("draft_schema", E, E, E, "the draft is an exact, bounded object (every schema problem is listed)"),
    Rule("prefab_invalid", E, E, E, "a published source is a valid prefab candidate (`validate_candidate`)"),
    Rule("prefab_namespace", E, E, E, "a published source lives under `presentation-studio.`"),
    Rule("pin_unknown", E, E, E, "an existing pin names a healthy prefab version"),
    Rule("scene_incompatible", E, E, E, "controls and values of a scene fit the manifest of its pin"),
    Rule("score_incompatible", E, E, E, "every score reference resolves (scenes, controls, anchors, bounded values)"),
    Rule("document_invalid", E, E, E, "the Presentation, its variants and its index are consistent, every document fits its size cap"),
    # --- art direction
    Rule("da_missing", E, E, W, "every serious variant carries an art direction (Slice 09 `require_art_direction`)"),
    Rule("da_incoherent", E, E, W, "the provenance of the art direction is backed (provided or inferred needs references)"),
    Rule("da_fallback_ignored_sources", W, W, O, "a generated fallback while the brief lists sources to inspect"),
    Rule("contrast_low", E, E, E, "text and colour controls keep contrast on the art direction background"),
    # --- structure and narrative
    Rule("arc_incomplete", E, E, E, "opening, body and closing scenes, in that order"),
    Rule("scene_no_score", E, E, E, "every scene has at least one score item"),
    Rule("scene_unbound", E, E, E, "every scene declares a control or carries content values"),
    Rule("scene_no_controls", W, W, O, "a scene with no curated control cannot be tuned by voice or inspector"),
    Rule("transition_missing", E, E, O, "a transition style, or a motion on the entering item, or a declared cut"),
    # --- text
    Rule("placeholder_text", E, E, E, "no lorem, TODO, 'xxx', bracketed or generic placeholder text (colours, numbers and table cells are not text)"),
    Rule("placeholder_allowed", W, W, W, "a placeholder-looking term the brief declared legitimate (`literal_terms`) was allowed"),
    Rule("content_thin", E, E, W, f"a scene shows at least {MIN_SCENE_WORDS} meaningful words ({MIN_BODY_WORDS} outside its title) and a spoken line at least {MIN_LINE_WORDS}"),
    Rule("repeated_filler", E, E, W, "the same text is not repeated as filler across scenes"),
    Rule("filler_numeric_variants", E, E, W, "texts and titles that differ only by digits, case or spacing are not filler"),
    Rule("text_density", E, E, W, f"at most {MAX_SCENE_WORDS} visible words per scene ({LONG_FORM_WORDS} for a declared long_form scene)"),
    Rule("text_dense", W, W, O, "a scene past two thirds of the word cap"),
    # --- timing and speech
    Rule("duration_off", E, E, O, f"the soft targets add up to the brief's duration within +-{round(DURATION_TOLERANCE * 100)} %"),
    Rule("duration_missing", W, W, O, "speaking items carry a soft target duration"),
    Rule("duration_item_range", W, W, O, f"an item target is {MIN_ITEM_MS} ms to {MAX_ITEM_MS // 60_000} min"),
    Rule("presenter_mismatch", E, E, W, "presenters match who speaks in the brief; `none` is the explicit silence"),
    Rule("jarvis_line_missing", W, W, O, "an item Jarvis presents carries the line he says, not only an intention"),
    Rule("notes_missing", W, E, O, "every scene has speech or a speaker note (directed)"),
    Rule("must_cover_missing", W, E, O, f"every `brief.must_cover` item is found in the scene texts ({round(MUST_COVER_THRESHOLD * 100)} % of its significant words)"),
    Rule("language_mismatch", W, E, W, "the scene texts read as French or English like the brief's language says"),
    # --- cues
    Rule("cue_weak", E, E, W, "an armable cue has distinctive multi-word phrases (Slice 13 `weak_cue`)"),
    Rule("cue_stopword_phrase", E, E, W, "a multi-word armable phrase is not made only of stop-words and fillers"),
    Rule("cue_ambiguous", E, E, E, "no phrase names two armable cues among neighbouring items"),
    Rule("cue_nested", W, W, O, "an armable phrase is not contained in a neighbour's phrase"),
    Rule("cues_sparse", W, W, O, "a user-presented deck arms cues on half of its scenes"),
    # --- controls
    Rule("controls_too_many", E, E, W, f"at most {MAX_CONTROLS_PER_SCENE} controls per scene"),
    Rule("control_unlabelled", E, E, W, "a control has a human label, not its machine id"),
    Rule("control_label_meaningless", E, E, W, "a control label is words, not `???`, `x` or `ctrl1`"),
    Rule("control_no_meaning", W, W, O, "a control says what it is for"),
    Rule("control_unbounded", E, E, W, "a numeric control is bounded on both sides"),
    # --- motion and caps
    Rule("motion_unguarded", E, E, E, "an animated published source honours prefers-reduced-motion"),
    Rule("behavior_risky", E, E, W, "a published source has no network call, eval, dynamic import, javascript: or remote reference (a lint; the host sandbox is the wall)"),
    Rule("payload_headroom", E, E, W, f"a scene payload uses at most {round(HEADROOM * 100)} % of its cap"),
    Rule("document_headroom", E, E, W, f"a document uses at most {round(HEADROOM * 100)} % of its size cap"),
    # --- exploratory shape
    Rule("candidates_count", O, O, E, f"{MIN_CANDIDATES} to {MAX_CANDIDATES} candidates"),
    Rule("candidates_not_divergent", O, O, E, f"candidates differ by at least {MIN_DIVERGENCE} (Slice 09 distance)"),
)
RULE_BY_CODE: Mapping[str, Rule] = {rule.code: rule for rule in RULES}


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    severity: str
    where: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "where": self.where, "message": self.message}


@dataclass(frozen=True, slots=True)
class QualityReport:
    workflow: Workflow | None
    findings: tuple[Finding, ...]
    #: Rules that could not run for lack of an input (manifests, built documents), by code.
    skipped: tuple[str, ...] = ()
    stats: Mapping[str, Any] = field(default_factory=dict)
    #: Findings beyond the per-rule cap, by code: the report says how many it hid.
    suppressed: Mapping[str, int] = field(default_factory=dict)
    checked: int = 0
    #: How far the verdict went: `complete` (every stage ran), `partial` (the draft did not parse completely: the text, motion, source and
    #: control rules ran on what could be read, the structure rules wait for a parsable draft), `schema` (nothing could be read), `brief`
    #: (the brief was refused; `workflow` is then what the author declared, or `None`).
    stage: str = "complete"
    declared_workflow: str | None = None
    not_judged: tuple[str, ...] = ()

    @property
    def workflow_name(self) -> str | None:
        return self.workflow.value if self.workflow is not None else self.declared_workflow

    @property
    def failures(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == ERROR)

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == WARNING)

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "workflow": self.workflow_name,
                "stage": self.stage, "subset": "exploratory" if self.workflow is Workflow.EXPLORATORY else "full",
                "failures": [f.to_dict() for f in self.failures], "warnings": [f.to_dict() for f in self.warnings],
                "rules": {"checked": self.checked, "failed": len({f.code for f in self.failures}),
                          "warned": len({f.code for f in self.warnings})},
                "skipped": list(self.skipped), "not_judged": list(self.not_judged), "suppressed": dict(self.suppressed), "stats": dict(self.stats)}


class _Sink:
    """Collects findings at the level the rule table gives the workflow, with a cap per rule."""

    def __init__(self, workflow: Workflow, strict: bool = False, partial: bool = False,
                 not_judged: frozenset[str] = frozenset()) -> None:
        self.workflow = workflow
        self.strict = strict
        #: Rules the caller says it cannot judge (a stored variant keeps no brief): never run, never skipped silently, listed in the report.
        self.not_judged = not_judged
        #: The draft did not parse completely: rules that need every part of it do not run (and are not "skipped": the stage says why).
        self.partial = partial
        self.findings: list[Finding] = []
        self.suppressed: Counter[str] = Counter()
        self.checked: set[str] = set()
        self.skipped: list[str] = []

    def ran(self, code: str) -> bool:
        """True when the rule applies to this workflow (and so is worth computing)."""

        applies = code not in self.not_judged and RULE_BY_CODE[code].level(self.workflow, self.strict) != OFF
        if applies:
            self.checked.add(code)
        return applies

    def skip(self, code: str) -> None:
        self.checked.discard(code)
        if code not in self.skipped and RULE_BY_CODE[code].level(self.workflow, self.strict) != OFF:
            self.skipped.append(code)

    def add(self, code: str, where: str, message: str) -> None:
        level = RULE_BY_CODE[code].level(self.workflow, self.strict)
        if level == OFF or code in self.not_judged:
            return
        if sum(1 for f in self.findings if f.code == code) >= MAX_FINDINGS_PER_RULE or len(self.findings) >= MAX_FINDINGS:
            self.suppressed[code] += 1
            return
        self.findings.append(Finding(code, level, where, safe_text(message)))


def finding_from_problem(problem: Problem, workflow: Workflow, strict: bool = False) -> Finding | None:
    """A parse or validation `Problem` as a finding at its rule's level (`None`: the rule is off for this workflow)."""

    rule = RULE_BY_CODE.get(problem.code) or RULE_BY_CODE["draft_schema"]
    level = rule.level(workflow, strict)
    return None if level == OFF else Finding(rule.code, level, problem.where, safe_text(problem.message))


# ------------------------------------------------------------------ text helpers (the lexical ones live in presentation_studio_authoring_text)

def string_leaves(value: object, depth: int = 0) -> Iterator[str]:
    """Every string value (never a key) of a JSON value, bounded depth."""

    if isinstance(value, str):
        yield value
    elif depth < 8 and isinstance(value, dict):
        for item in value.values():
            yield from string_leaves(item, depth + 1)
    elif depth < 8 and isinstance(value, list):
        for item in value:
            yield from string_leaves(item, depth + 1)


def scene_prose(scene: DraftScene) -> list[str]:
    """The prose a scene shows: its title and the string leaves of its values that are text (not a colour, a URL or a number)."""

    return [scene.scene.title, *prose_leaves((*string_leaves(scene.scene.props), *string_leaves(scene.scene.data)))]


def visible_words(scene: DraftScene) -> int:
    """Words of the scene's content strings for the density cap (colours, URLs and numbers are not read aloud, a title counts; a CJK
    run counts one word per two characters, an underscore separates words)."""

    return sum(count_words(t) for t in scene_prose(scene))


def content_units(text: str) -> float:
    """Meaningful words, plus half a word per number: a table of figures is content, `...` and a row of emoji are not."""

    return meaningful_words(text) + 0.5 * len([t for t in text.split() if any(c.isdigit() for c in t)])


# ------------------------------------------------------------------ the gate

def check_first_draft(draft: PresentationDraft, brief: AuthoringBrief, manifests: Mapping[str, PrefabManifest] | None = None,
                      built: BuiltPresentation | None = None, *, problems: tuple[Problem, ...] = (), partial: bool = False,
                      not_judged: frozenset[str] = frozenset()) -> QualityReport:
    """Judges `draft` against `brief`. `problems` are earlier validation rows (resolution, build) merged in so the report is whole.
    `partial`: `draft` is only what could be read of a submission with schema problems; the structure, timing, cue and art direction
    rules (which need every part) do not run, the text, motion, source and control rules do, and `stage` says `partial`."""

    sink = _Sink(brief.workflow, brief.strict_content, partial, not_judged)
    for problem in problems:
        found = finding_from_problem(problem, brief.workflow, brief.strict_content)
        if found is not None:
            sink.checked.add(found.code)
            sink.add(found.code, found.where, found.message)
    checks = (_text, _controls, _motion_and_caps) if partial else (_da, _structure, _text, _timing_and_speech, _controls,
                                                                  _motion_and_caps, _exploratory)
    for check in checks:
        check(sink, draft, brief, manifests, built)
    if not partial:
        _cues(sink, draft, brief, built)
    else:
        sink.skipped.clear()
    return QualityReport(brief.workflow, tuple(sink.findings), tuple(sink.skipped), _stats(draft, brief, built),
                         dict(sink.suppressed), len(sink.checked), "partial" if partial else "complete",
                         not_judged=tuple(sorted(not_judged)))


def _stats(draft: PresentationDraft, brief: AuthoringBrief, built: BuiltPresentation | None) -> dict[str, Any]:
    total_ms = sum(item.target_duration_ms or 0 for item in draft.items)
    cues = [i.cue for i in draft.items if i.cue is not None]
    return {"scenes": len(draft.scenes), "items": len(draft.items), "cues": len(cues),
            "armable_cues": sum(1 for c in cues if c.armable), "variants": len(draft.directions),
            "estimated_duration_s": round(total_ms / 1000), "target_duration_s": brief.duration_target_s,
            "bundles": len(draft.bundles), "max_scene_words": max((visible_words(s) for s in draft.scenes), default=0)}


def _da(sink: _Sink, draft: PresentationDraft, brief: AuthoringBrief, *_: Any) -> None:
    exploratory = brief.workflow is Workflow.EXPLORATORY
    if sink.ran("da_missing"):
        for position, direction in enumerate(draft.directions, start=1):
            if direction.profile is None:
                sink.add("da_missing", f"candidate:{position}" if exploratory else "art_direction",
                         "no art direction: a serious presentation always carries one (provided, inferred from the project, "
                         "or the generated fallback `{\"mode\": \"fallback\"}`)")
    if sink.ran("da_incoherent"):
        for position, direction in enumerate(draft.directions, start=1):
            profile = direction.profile
            if profile is None:
                continue
            where = f"candidate:{position}" if exploratory else "art_direction"
            prov = profile.provenance
            if prov.origin in (Origin.PROVIDED, Origin.INFERRED) and not profile.references:
                sink.add("da_incoherent", where, f"provenance {prov.origin.value} names no reference: list what it was taken from, "
                                                 "or mark it generated")
    if sink.ran("da_fallback_ignored_sources") and brief.resources:
        for position, direction in enumerate(draft.directions, start=1):
            if direction.profile is not None and direction.profile.provenance.fallback:
                sink.add("da_fallback_ignored_sources", "art_direction",
                         "the DA is the generated fallback although the brief lists sources: inspect them and derive from signals")


def _structure(sink: _Sink, draft: PresentationDraft, brief: AuthoringBrief, manifests: Any, built: Any) -> None:
    scenes = draft.scenes
    if sink.ran("arc_incomplete") and len(scenes) > 1:
        roles = [s.role for s in scenes]
        if roles[0] is not SceneRole.OPENING:
            sink.add("arc_incomplete", f"scene:{scenes[0].key}", "the first scene is the opening (role opening)")
        if roles[-1] is not SceneRole.CLOSING:
            sink.add("arc_incomplete", f"scene:{scenes[-1].key}", "the last scene is the closing (role closing)")
        for scene in scenes[1:-1]:
            if scene.role is not SceneRole.BODY:
                sink.add("arc_incomplete", f"scene:{scene.key}", "scenes between the opening and the closing have role body")
        if len(scenes) > 2 and SceneRole.BODY not in roles:
            sink.add("arc_incomplete", "draft", "a presentation of three scenes or more has a body")
    elif sink.ran("arc_incomplete") and scenes and scenes[0].role not in (SceneRole.SINGLE, SceneRole.OPENING, SceneRole.CLOSING):
        sink.add("arc_incomplete", f"scene:{scenes[0].key}", "a one-scene presentation has role single")
    used = Counter(item.scene for item in draft.items)
    if sink.ran("scene_no_score"):
        for scene in scenes:
            if not used[scene.key]:
                sink.add("scene_no_score", f"scene:{scene.key}",
                         "no score item for this scene: add one (its line, or an explicit silence with presenter none)")
    for scene in scenes:
        if sink.ran("scene_unbound") and not scene.scene.controls and not scene.scene.props and not scene.scene.data:
            sink.add("scene_unbound", f"scene:{scene.key}", "no control and no content value: the scene shows nothing and cannot be edited")
        if sink.ran("scene_no_controls") and not scene.scene.controls:
            sink.add("scene_no_controls", f"scene:{scene.key}", "no curated control: nothing to tune by voice or in the inspector")
    if sink.ran("transition_missing") and len(scenes) > 1:
        declared = any(d.profile is not None and d.profile.motion.transition is not TransitionStyle.NONE for d in draft.directions)
        first_items: dict[str, Any] = {}
        for item in draft.items:
            first_items.setdefault(item.scene, item)
        if not declared:
            for scene in scenes[1:]:
                entering = first_items.get(scene.key)
                if not scene.cut and not (entering is not None and entering.motion):
                    sink.add("transition_missing", f"scene:{scene.key}",
                             "hard cut with no declared transition: set the art direction transition, give the entering item a "
                             "motion action, or declare `cut: true` when the cut is intended")


def _numbered(draft: PresentationDraft) -> list[tuple[int, Any]]:
    """`(position, item)` where position is the item's place in the author's list (a partial draft keeps the original numbers)."""

    return [(item.position or n, item) for n, item in enumerate(draft.items, start=1)]


def _texts(draft: PresentationDraft) -> Iterator[tuple[str, str, bool, str]]:
    """(where, text, is_title, owner) for every PROSE the brain wrote in the draft (a colour, a URL, a number is not prose).
    `owner` is the scene a text belongs to."""

    for scene in draft.scenes:
        where = f"scene:{scene.key}"
        yield where, scene.scene.title, True, scene.key
        yield where, scene.scene.section, False, scene.key
        yield where, scene.scene.preview.alt, False, scene.key
        for text in prose_leaves((*string_leaves(scene.scene.props), *string_leaves(scene.scene.data))):
            yield where, text, False, scene.key
    for number, item in _numbered(draft):
        for text in (item.text, item.note, item.label, item.cue.label if item.cue else ""):
            yield f"item:{number}", text, False, item.scene
    for number, direction in enumerate(draft.directions, start=1):
        yield f"candidate:{number}", direction.title, False, f"candidate:{number}"
        yield f"candidate:{number}", direction.rationale, False, f"candidate:{number}"


def _text(sink: _Sink, draft: PresentationDraft, brief: AuthoringBrief, *_: Any) -> None:
    if sink.ran("placeholder_text"):
        allowed_spans = 0
        for where, text, is_title, _owner in _texts(draft):
            hits = placeholder_hits(text, title=is_title) if text else []
            refused = [h for h in hits if not (brief.literal_terms and is_allowed(h[1], brief.literal_terms))]
            allowed_spans += len(hits) - len(refused)
            if refused:
                sink.add("placeholder_text", where, f"placeholder text ({refused[0][0]}): write the real content"
                         + (" (or list the word in brief.literal_terms if it is the subject)" if refused[0][0] in ("todo", "lorem", "blank", "xxx") else ""))
        if allowed_spans and sink.ran("placeholder_allowed"):
            sink.add("placeholder_allowed", "brief", f"{allowed_spans} placeholder-looking text(s) allowed by brief.literal_terms: check they are the subject")
    _filler(sink, draft)
    for scene in draft.scenes:
        words = visible_words(scene)
        cap = LONG_FORM_WORDS if scene.long_form else MAX_SCENE_WORDS
        if sink.ran("text_density") and words > cap:
            sink.add("text_density", f"scene:{scene.key}", f"{words} visible words, at most {cap}: split the scene or cut the text"
                                                           + ("" if scene.long_form else " (a full-read document declares long_form)"))
        elif sink.ran("text_dense") and words > cap * 2 // 3:
            sink.add("text_dense", f"scene:{scene.key}", f"{words} visible words, close to the {cap} cap")
        if sink.ran("content_thin"):
            prose = scene_prose(scene)
            body = sum(content_units(t) for t in prose[1:])
            units = content_units(prose[0]) + body
            if units < MIN_SCENE_WORDS or body < MIN_BODY_WORDS:
                sink.add("content_thin", f"scene:{scene.key}", f"{units:g} meaningful word(s) on screen ({body:g} outside the title), at least "
                                                              f"{MIN_SCENE_WORDS} ({MIN_BODY_WORDS} outside the title): punctuation, ellipsis, "
                                                              "emoji and single letters carry no content")
    if sink.ran("content_thin"):
        for number, item in _numbered(draft):
            if item.presenter is not Presenter.NONE and content_units(item.text or item.note) < MIN_LINE_WORDS:
                sink.add("content_thin", f"item:{number}", f"a spoken line or note of fewer than {MIN_LINE_WORDS} meaningful words")
    if not sink.partial:
        _must_cover_and_language(sink, draft, brief)


def _filler(sink: _Sink, draft: PresentationDraft) -> None:
    if sink.ran("repeated_filler"):
        owners: dict[str, set[str]] = {}
        for _, text, _, owner in _texts(draft):
            if len(text) >= 20:
                owners.setdefault(" ".join(text.casefold().split()), set()).add(owner)
        for text, who in owners.items():
            if len(who) >= 3:
                first = next(w for w, t, _, _ in _texts(draft) if " ".join(t.casefold().split()) == text)
                sink.add("repeated_filler", first, f"the same {len(text)}-character text appears in {len(who)} scenes: write each scene's own words")
    if sink.ran("filler_numeric_variants"):
        groups: dict[str, tuple[set[str], set[str], str]] = {}
        for where, text, is_title, owner in _texts(draft):
            norm = normalise_filler(text)
            minimum = 1 if is_title else MIN_FILLER_CHARS
            if len(norm) >= minimum and "#" in norm:
                who, raw, first = groups.setdefault(norm, (set(), set(), where))
                who.add(owner)
                raw.add(" ".join(text.casefold().split()))
        for norm, (who, raw, first) in groups.items():
            threshold = NUMERIC_TITLE_SCENES if len(norm) < MIN_FILLER_CHARS else NUMERIC_FILLER_SCENES
            if len(who) >= threshold and len(raw) >= 2:           # one raw form repeated is `repeated_filler`'s
                sink.add("filler_numeric_variants", first, f"{len(who)} scenes carry the same text that differs only by a number: "
                                                           "write each scene's own words")


def _must_cover_and_language(sink: _Sink, draft: PresentationDraft, brief: AuthoringBrief) -> None:
    texts = [t for _, t, _, _ in _texts(draft) if t]
    if sink.ran("must_cover_missing") and brief.must_cover:
        corpus = " ".join(texts)
        corpus_stems, corpus_folded = stems(corpus), fold(corpus)
        for index, item in enumerate(brief.must_cover, start=1):
            if not covers(item, corpus_stems, corpus_folded):
                sink.add("must_cover_missing", f"brief.must_cover[{index}]",
                         f"not found in the scene texts (at least {round(MUST_COVER_THRESHOLD * 100)} % of its significant words): "
                         "cover it or take it out of the brief")
    if sink.ran("language_mismatch") and brief.language:
        guess = guess_language(texts)
        wanted = brief.language.split("-")[0]
        if guess is not None and guess != wanted:
            sink.add("language_mismatch", "draft", f"the scene texts read as {guess}, the brief's language is {brief.language}")


def _timing_and_speech(sink: _Sink, draft: PresentationDraft, brief: AuthoringBrief, *_: Any) -> None:
    speaking = [(n, i) for n, i in _numbered(draft) if i.presenter is not Presenter.NONE]
    if sink.ran("duration_off") and brief.duration_target_s:
        total = sum(i.target_duration_ms or 0 for i in draft.items) / 1000
        wanted = brief.duration_target_s
        if abs(total - wanted) > wanted * DURATION_TOLERANCE:
            sink.add("duration_off", "score", f"the soft targets add up to {round(total)} s, the brief asks {wanted} s "
                                              f"(+-{round(DURATION_TOLERANCE * 100)} % = {round(wanted * (1 - DURATION_TOLERANCE))}"
                                              f"..{round(wanted * (1 + DURATION_TOLERANCE))} s): retime the items")
    if sink.ran("duration_missing"):
        for number, item in speaking:
            if item.target_duration_ms is None:
                sink.add("duration_missing", f"item:{number}", "no soft target duration on a speaking item")
    if sink.ran("duration_item_range"):
        for number, item in _numbered(draft):
            if item.target_duration_ms is not None and not MIN_ITEM_MS <= item.target_duration_ms <= MAX_ITEM_MS:
                sink.add("duration_item_range", f"item:{number}", f"target {item.target_duration_ms} ms is outside {MIN_ITEM_MS}..{MAX_ITEM_MS} ms")
    if sink.ran("presenter_mismatch"):
        for number, item in _numbered(draft):
            if brief.speech is Speech.NONE and item.presenter is not Presenter.NONE:
                sink.add("presenter_mismatch", f"item:{number}", "the brief says nobody speaks: every item is an explicit silence (presenter none)")
            elif brief.speech is Speech.JARVIS and item.presenter is Presenter.USER:
                sink.add("presenter_mismatch", f"item:{number}", "the brief has Jarvis present: a user item belongs to a user-presented deck")
            elif brief.speech is Speech.USER and item.presenter is Presenter.JARVIS:
                sink.add("presenter_mismatch", f"item:{number}", "the user presents: Jarvis stays silent here (presenter none)")
    if sink.ran("jarvis_line_missing"):
        for number, item in speaking:
            if item.presenter is Presenter.JARVIS and not item.text:
                sink.add("jarvis_line_missing", f"item:{number}", "Jarvis presents this item but no line is written (note only)")
    if sink.ran("notes_missing") and brief.speech is not Speech.NONE:
        spoken = {item.scene for _, item in speaking}
        for scene in draft.scenes:
            if scene.key not in spoken:
                sink.add("notes_missing", f"scene:{scene.key}", "no speech and no speaker note for this scene (text for what is said, note for the intention)")


def _cues(sink: _Sink, draft: PresentationDraft, brief: AuthoringBrief, built: BuiltPresentation | None) -> None:
    wanted = [c for c in ("cue_weak", "cue_stopword_phrase", "cue_ambiguous", "cue_nested", "cues_sparse") if sink.ran(c)]
    if "cue_weak" in wanted or "cue_stopword_phrase" in wanted:
        for number, item in _numbered(draft):
            if item.cue is None or not item.cue.armable:
                continue
            for index, phrase in enumerate(item.cue.predicate.phrases, start=1):
                reasons = phrase_weakness(phrase)
                if not reasons:
                    continue
                multi = len(phrase.split()) >= 2
                code = "cue_stopword_phrase" if multi and "only_stopwords" in reasons else "cue_weak"
                sink.add(code, f"item:{number}", f"phrase #{index} of this armable cue is weak ({', '.join(reasons)}): use a distinctive "
                                                 "multi-word phrase, or make the cue not armable")
    armable_scenes = {item.scene for item in draft.items if item.cue is not None and item.cue.armable}
    if "cues_sparse" in wanted:
        if brief.speech is Speech.USER and len(draft.scenes) > 1 and len(armable_scenes) * 2 < len(draft.scenes) - 1:
            sink.add("cues_sparse", "score", f"the user presents but only {len(armable_scenes)} of {len(draft.scenes)} scenes arm a cue")
    needs_score = [c for c in wanted if c in ("cue_ambiguous", "cue_nested")]
    if not needs_score:
        return
    if built is None or not built.variants:
        for code in needs_score:
            sink.skip(code)
        return
    score = built.variants[0].score
    position = {item.cue_id: n for n, item in enumerate(score.items, start=1) if item.cue_id}
    armable = [(n, item) for n, item in enumerate(score.items, start=1)
               if item.cue_id and next(c for c in score.cues if c.cue_id == item.cue_id).armable]
    reported: set[tuple[str, tuple[str, ...]]] = set()
    for index, (number, item) in enumerate(armable):
        near = [(n, i) for n, i in armable[index + 1:] if n - number <= CUE_WINDOW]
        if not near:
            continue
        ids = [item.cue_id, *(i.cue_id for _, i in near)]
        if "cue_ambiguous" in wanted:
            for phrase, cue_ids in ambiguous_phrases(score, ids).items():
                if (phrase, cue_ids) not in reported:
                    reported.add((phrase, cue_ids))
                    items = ", ".join(f"item:{position[c]}" for c in cue_ids)
                    sink.add("cue_ambiguous", items.split(", ")[0], f"one phrase names the cues of {items}: give each its own phrase")
        if "cue_nested" in wanted:
            cues = {c.cue_id: c for c in score.cues}
            mine = [f" {p} " for p in cues[item.cue_id].predicate.phrases]
            for n, other in near:
                for theirs in cues[other.cue_id].predicate.phrases:
                    padded = f" {normalise_phrase(theirs)} "
                    if any(m != padded and (m in padded or padded in m) for m in mine):
                        sink.add("cue_nested", f"item:{number}", f"a phrase here is contained in a phrase of item:{n}")


def _controls(sink: _Sink, draft: PresentationDraft, brief: AuthoringBrief, manifests: Mapping[str, PrefabManifest] | None,
              built: Any) -> None:
    backgrounds = [(position, d.profile.palette.background) for position, d in enumerate(draft.directions, start=1)
                   if d.profile is not None]
    set_values: dict[tuple[str, str], list[Any]] = {}
    for item in draft.items:
        for action in (*item.visual, *item.motion):
            if action.action.kind is ActionKind.CONTROL_SET:
                set_values.setdefault((action.scene or item.scene, action.action.control_id or ""), []).append(action.action.value)
    for scene in draft.scenes:
        controls = scene.scene.controls
        where = f"scene:{scene.key}"
        if sink.ran("controls_too_many") and len(controls) > MAX_CONTROLS_PER_SCENE:
            sink.add("controls_too_many", where, f"{len(controls)} controls, at most {MAX_CONTROLS_PER_SCENE}: curate what a person would actually change")
        for control in controls:
            leaf = control.path.rsplit(".", 1)[-1].casefold()
            if sink.ran("control_unlabelled") and (control.label.casefold() in (control.control_id, leaf, control.path.casefold())
                                                  or len(control.label) < 3):
                sink.add("control_unlabelled", where, f"control {control.control_id} has no human label (use the words a person would say)")
            if sink.ran("control_label_meaningless") and label_meaningless(control.label):
                sink.add("control_label_meaningless", where, f"control {control.control_id} has a label that is not words (a person must read it)")
            if sink.ran("control_no_meaning") and not control.meaning:
                sink.add("control_no_meaning", where, f"control {control.control_id} does not say what it is for")
        manifest = manifests.get(scene.key) if manifests is not None else None
        if manifest is None:
            for code in ("control_unbounded", "contrast_low"):
                if controls and sink.ran(code):
                    sink.skip(code)
            continue
        for control in controls:
            node = node_of(manifest, control)
            if node is None:
                continue  # reported by scene_incompatible
            if sink.ran("control_unbounded") and node.type in (InputType.INTEGER, InputType.NUMBER):
                bounds = effective_bounds(node, control.bounds)
                if "min" not in bounds or "max" not in bounds:
                    sink.add("control_unbounded", where, f"numeric control {control.control_id} is not bounded on both sides (curated bounds or the manifest's)")
            if sink.ran("contrast_low") and node.type is InputType.COLOR:
                # Only what the author SET is judged: a colour left at the prefab's default is drawn from the theme of the art
                # direction (`to_theme`), not a choice of this draft.
                present, current = value_at(scene.scene, control)
                values = [v for v in ([current] if present else []) + set_values.get((scene.key, control.control_id), [])
                          if isinstance(v, str)]
                for value in values:
                    for position, background in backgrounds:
                        try:
                            ratio = contrast_ratio(value, background)
                        except PresentationStudioError:  # contrast_ratio refuses a value that is not #rrggbb
                            continue  # the manifest validation reports it
                        if ratio < GRAPHIC_RATIO:
                            who = f"candidate:{position}/{where}" if len(backgrounds) > 1 else where
                            sink.add("contrast_low", who, f"colour control {control.control_id} gives {ratio:.1f}:1 on the art direction "
                                                          f"background, at least {GRAPHIC_RATIO:g}:1 is needed")


def _motion_and_caps(sink: _Sink, draft: PresentationDraft, brief: AuthoringBrief, manifests: Any,
                     built: BuiltPresentation | None) -> None:
    if sink.ran("behavior_risky"):
        for bundle in draft.bundles:
            kinds = risky_constructs(bundle.bundle.template, bundle.bundle.style, bundle.bundle.behavior)
            if kinds:
                sink.add("behavior_risky", f"bundle:{bundle.key}",
                         f"the source uses {', '.join(kinds)}: a slide needs none of it (the host sandbox is the wall, this is the lint in front)")
    if sink.ran("motion_unguarded"):
        for bundle in draft.bundles:
            if is_motion_unguarded(bundle.bundle.style, bundle.bundle.behavior):
                sink.add("motion_unguarded", f"bundle:{bundle.key}",
                         "the source animates but never mentions prefers-reduced-motion: add a @media (prefers-reduced-motion: reduce) "
                         "rule (or a matchMedia check) that stops the motion")
    caps = [c for c in ("payload_headroom", "document_headroom") if sink.ran(c)]
    if not caps:
        return
    if built is None:
        for code in caps:
            sink.skip(code)
        return
    sizes = built.sizes()
    if "payload_headroom" in caps:
        for key, budget in sizes["scene_payload"].items():
            if budget["bytes"] > budget["limit"] * HEADROOM:
                sink.add("payload_headroom", f"scene:{key}", f"payload {budget['bytes']} of {budget['limit']} bytes: leave room to edit (cut content or move it)")
    if "document_headroom" in caps:
        for name in ("manifest", "variant", "score"):
            if sizes[name] > MAX_DOCUMENT_BYTES:     # it could not even be stored: never a mere warning, whatever the workflow
                sink.add("document_invalid", "draft", f"the {name} document would be {sizes[name]} bytes, above the {MAX_DOCUMENT_BYTES} cap")
            elif sizes[name] > MAX_DOCUMENT_BYTES * HEADROOM:
                sink.add("document_headroom", "draft", f"the {name} document is {sizes[name]} of {MAX_DOCUMENT_BYTES} bytes")


def _exploratory(sink: _Sink, draft: PresentationDraft, brief: AuthoringBrief, *_: Any) -> None:
    if brief.workflow is not Workflow.EXPLORATORY:
        return
    if sink.ran("candidates_count") and not MIN_CANDIDATES <= len(draft.directions) <= MAX_CANDIDATES:
        sink.add("candidates_count", "draft", f"{len(draft.directions)} candidate(s): an exploratory draft offers {MIN_CANDIDATES} to {MAX_CANDIDATES} directions")
    if sink.ran("candidates_not_divergent"):
        profiles: list[tuple[int, ArtDirectionProfile]] = [(n, d.profile) for n, d in enumerate(draft.directions, start=1) if d.profile]
        for index, (a, left) in enumerate(profiles):
            for b, right in profiles[index + 1:]:
                distance = profile_distance(left, right)
                if distance < MIN_DIVERGENCE:
                    sink.add("candidates_not_divergent", f"candidate:{b}",
                             f"candidates {a} and {b} are {distance:.2f} apart, at least {MIN_DIVERGENCE} (change palette, type, shape or motion)")
