"""Presentation Studio : la partition (`Score`), ses cues et ses séquences verrouillées (handoff
jarvis-interactive-presentation-studio, Slice 10).

Une *partition* aligne parole, visuels, mouvements et silence sans jamais être une
ligne de temps à l'horloge : l'ordre est le **graphe d'items** (`next_item_id`), les
durées sont des **cibles souples**, seules les séquences verrouillées ont des
décalages relatifs exacts. Contrat : `docs/presentation-studio.md` › *Score and cue contract*.

Ce qui y vit :

- `ScoreItem` : une scène, un `Presenter` (user | jarvis | none), de la parole (`text`)
  OU une note d'intention (`note`), une cue, des actions visuelles/mouvement, une durée
  cible, une politique de timing (soft | locked), interruption, reprise, état suivant.
  `none` est le **silence explicite** : un item `kind=silence` sans parole.
- `CueDefinition` : `cue_id` (`psc_`), `armable`, prédicat = ensemble **fini** de phrases
  normalisées et d'étiquettes sémantiques (jamais une expression régulière, jamais une
  instruction d'outil). C'est la seule chose qu'un appariement ambiant peut nommer (R5).
- `ActionRef` : ensemble **clos** d'actions pré-écrites et réversibles (réglage de contrôle,
  navigation de scène, révéler/masquer une ancre, séquence verrouillée). Rien d'autre
  n'est exécutable : aucun champ de la partition ne porte une commande, un outil ou du
  texte libre exécuté (`FREE_TEXT_FIELDS` classe chaque champ texte ; un test l'impose).
- `LockedSequence` : étapes à décalages relatifs strictement croissants (ordre
  déterministe), politique d'interruption, point de reprise.
- `RecoveryPoint` : un point de reprise nommé sur un item.

Cycles : **refusés**. Chaque item a au plus un successeur et au plus un prédécesseur ;
la seule répétition admise est une boucle **déclarée** (`LoopSpec`, `max_repeats` borné),
et le développement total est borné (`MAX_EXPANDED_ITEMS`).

Pur : aucune E/S. Références aux scènes de la variante : `check_score` (pur) ; la
validation des valeurs contre les manifestes : `check_score_values` (pur, manifestes fournis).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
import math
import re
import secrets
import unicodedata
from typing import Any, ClassVar

from jarvis.domain.prefab import PrefabManifest, canonical_json
from jarvis.domain.presentation_studio import (
    PRESENTATION_ID, SCHEMA_SCORE, SCORE_ID, SCORE_SCHEMA_VERSION, VARIANT_ID, _check_stamp, new_score_id, stamp,
    upgrade_document,
)
from jarvis.domain.presentation_studio_checks import (
    PresentationStudioError, PresentationStudioErrorCode, _check_id, _check_int, _exact_keys, _fail, clip,
)
from jarvis.domain.presentation_studio_scene import (
    SLUG, ControlGroup, StudioScene, node_of, value_at, value_problem,
)

#: Bornes (toute collection est bornée).
MAX_ITEMS = 200
MAX_CUES = 200
MAX_SEQUENCES = 16
MAX_RECOVERY_POINTS = 32
MAX_STEPS = 32
MAX_ACTIONS = 4
MAX_PHRASES = 8
MAX_SEMANTICS = 4
MAX_TEXT_CHARS = 1200
MAX_NOTE_CHARS = 300
MAX_LABEL = 80
MAX_VALUE_CHARS = 200
MAX_PHRASE_CHARS = 60
MAX_PHRASE_WORDS = 8
MIN_PHRASE_CHARS = 2
MAX_DURATION_MS = 3_600_000
MAX_LOOP_REPEATS = 8
MAX_EXPANDED_ITEMS = 2000
MAX_CHECK_ERRORS = 20

ITEM_ID = re.compile(r"psi_[0-9a-f]{12}\Z")
CUE_ID = re.compile(r"psc_[0-9a-f]{12}\Z")


def new_score_item_id() -> str:
    return "psi_" + secrets.token_hex(6)


def new_cue_id() -> str:
    return "psc_" + secrets.token_hex(6)


class Track(StrEnum):
    USER_SPEECH = "user_speech"
    JARVIS_SPEECH = "jarvis_speech"
    VISUAL = "visual"
    MOTION = "motion"
    CUES = "cues"


class Presenter(StrEnum):
    USER = "user"
    JARVIS = "jarvis"
    NONE = "none"


class ItemKind(StrEnum):
    SPEECH = "speech"
    #: Silence explicite (D07) : `Presenter.NONE`, ni parole ni note.
    SILENCE = "silence"


class TimingPolicy(StrEnum):
    SOFT = "soft"
    LOCKED = "locked"


class Interruption(StrEnum):
    #: Un détour (question, ressource auxiliaire) peut commencer à tout instant.
    ALLOW = "allow"
    #: Le détour attend la fin de l'item (ou de l'étape en cours d'une séquence).
    AT_BOUNDARY = "at_boundary"
    #: Seul un arrêt explicite interrompt.
    REFUSE = "refuse"


class Recovery(StrEnum):
    """Où reprendre quand un détour s'achève."""

    CONTINUE_ITEM = "continue_item"
    RESTART_ITEM = "restart_item"
    SKIP_TO_NEXT = "skip_to_next"
    RECOVERY_POINT = "recovery_point"


class SequenceInterrupt(StrEnum):
    PAUSE_RESUME = "pause_resume"
    ABORT_TO_RECOVERY = "abort_to_recovery"


class ActionKind(StrEnum):
    CONTROL_SET = "control_set"
    SCENE_GOTO = "scene_goto"
    REVEAL = "reveal"
    HIDE = "hide"
    SEQUENCE = "sequence"


def _text(name: str, value: object, limit: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise _fail(f"{name} must be a string")
    if not value:
        if allow_empty:
            return value
        raise _fail(f"{name} must not be empty")
    if value != value.strip() or not value.isprintable() or len(value) > limit:
        raise _fail(f"{name} must be one printable line of at most {limit} characters, without surrounding spaces")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise _fail(f"{name} holds a character that cannot be stored (lone surrogate)") from None
    return value


def _slug(name: str, value: object) -> str:
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise _fail(f"{name} must match [a-z][a-z0-9_]{{0,39}}")
    return value


def _tuple(name: str, value: object, kind: type, limit: int) -> tuple[Any, ...]:
    if not isinstance(value, (list, tuple)):
        raise _fail(f"{name} must be a list")
    if len(value) > limit:
        raise _fail(f"{name} exceed {limit}")
    if not all(isinstance(item, kind) for item in value):
        raise _fail(f"{name} must hold {kind.__name__} values")
    return tuple(value)


def _enum(kind: type[StrEnum], name: str, value: object) -> Any:
    try:
        return kind(value)
    except ValueError:
        raise _fail(f"{name} must be one of {', '.join(m.value for m in kind)}") from None


def _duration(name: str, value: object) -> None:
    _check_int(name, value, 1, MAX_DURATION_MS)


def _listed(name: str, raw: object, limit: int) -> list[Any]:
    if not isinstance(raw, list):
        raise _fail(f"{name} must be a list")
    if len(raw) > limit:
        raise _fail(f"{name} exceed {limit}")
    return raw


# ------------------------------------------------------------------ cues

_APOSTROPHES = ("\u2018", "\u2019", "\u02bc")


def _is_latin_letter(ch: str) -> bool:
    return ch.isalpha() and unicodedata.name(ch, "").startswith("LATIN")


def normalise_phrase(text: object) -> str:
    """NFKC, minuscules (casefold), apostrophes typographiques (U+2018, U+2019, U+02BC) ramenées à `'`, espaces réduits.
    Pur et idempotent. L'écriture est vérifiée à part (`_check_phrase`) : latin seulement."""

    if not isinstance(text, str):
        raise _fail("a cue phrase must be a string")
    folded = unicodedata.normalize("NFKC", text).casefold()
    for variant in _APOSTROPHES:
        folded = folded.replace(variant, "'")
    return " ".join(folded.split())


def _check_phrase(phrase: str) -> None:
    if not MIN_PHRASE_CHARS <= len(phrase) <= MAX_PHRASE_CHARS or len(phrase.split(" ")) > MAX_PHRASE_WORDS:
        raise _fail(f"a cue phrase holds {MIN_PHRASE_CHARS}..{MAX_PHRASE_CHARS} characters and at most "
                    f"{MAX_PHRASE_WORDS} words")
    # Letters, digits, space, apostrophe, hyphen only: no regex metacharacter, no markup, no `key: value`, no JSON.
    # Latin-script letters (accents included), ASCII digits: a Cyrillic `а` or an Arabic-Indic digit would build a
    # phrase that looks identical to another and never collides with it.
    if not all(_is_latin_letter(ch) or (ch.isascii() and ch.isdigit()) or ch in " '-" for ch in phrase) \
            or not any(ch.isalnum() for ch in phrase):
        raise _fail("a cue phrase holds only Latin letters, ASCII digits, spaces, apostrophes and hyphens "
                    "(a cue is a finite phrase set, never a pattern or an instruction)")
    if normalise_phrase(phrase) != phrase:
        raise _fail("a cue phrase is not stable under normalisation")


@dataclass(frozen=True, slots=True)
class CuePredicate:
    """Ensemble **fini** : `phrases` (normalisées, triées, sans doublon) et `semantics` (étiquettes slug).

    La normalisation est faite à la construction : deux auteurs qui écrivent « Voilà  Le Plan » et
    « voilà le plan » obtiennent le même prédicat. Aucun motif, aucune expression régulière.
    """

    phrases: tuple[str, ...] = ()
    semantics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        phrases = _tuple("phrases", self.phrases, str, MAX_PHRASES)
        normalised = tuple(normalise_phrase(p) for p in phrases)
        for phrase in normalised:
            _check_phrase(phrase)
        if len(set(normalised)) != len(normalised):
            raise _fail("a cue predicate holds the same phrase twice (after normalisation)")
        semantics = _tuple("semantics", self.semantics, str, MAX_SEMANTICS)
        for label in semantics:
            _slug("semantic label", label)
        if len(set(semantics)) != len(semantics):
            raise _fail("a cue predicate holds the same semantic label twice")
        object.__setattr__(self, "phrases", tuple(sorted(normalised)))
        object.__setattr__(self, "semantics", tuple(sorted(semantics)))

    def is_empty(self) -> bool:
        return not self.phrases and not self.semantics

    def to_dict(self) -> dict[str, Any]:
        return {"phrases": list(self.phrases), "semantics": list(self.semantics)}

    @classmethod
    def from_dict(cls, raw: object, where: str = "predicate") -> CuePredicate:
        data = _exact_keys(raw, where, set(), frozenset({"phrases", "semantics"}))
        return cls(tuple(_listed(f"{where}.phrases", data.get("phrases", []), MAX_PHRASES)),
                   tuple(_listed(f"{where}.semantics", data.get("semantics", []), MAX_SEMANTICS)))


@dataclass(frozen=True, slots=True)
class CueDefinition:
    cue_id: str
    label: str
    predicate: CuePredicate
    #: `True` : le runtime peut l'armer et l'apparier à la parole ambiante. `False` : avance manuelle seulement.
    armable: bool

    def __post_init__(self) -> None:
        _check_id("cue_id", self.cue_id, CUE_ID)
        _text("label", self.label, MAX_LABEL)
        if not isinstance(self.predicate, CuePredicate):
            raise _fail("predicate must be a CuePredicate")
        if type(self.armable) is not bool:
            raise _fail("armable must be a boolean")
        if self.armable and self.predicate.is_empty():
            raise _fail(f"cue {self.cue_id} is armable but its predicate is empty")

    def to_dict(self) -> dict[str, Any]:
        return {"cue_id": self.cue_id, "label": self.label, "predicate": self.predicate.to_dict(),
                "armable": self.armable}

    @classmethod
    def from_dict(cls, raw: object, where: str = "cue") -> CueDefinition:
        data = _exact_keys(raw, where, {"cue_id", "label", "armable"}, frozenset({"predicate"}))
        predicate = CuePredicate.from_dict(data["predicate"], f"{where}.predicate") if "predicate" in data \
            else CuePredicate()
        return cls(data["cue_id"], data["label"], predicate, data["armable"])


# ------------------------------------------------------------------ actions

_SHAPE: dict[ActionKind, tuple[str, ...]] = {
    ActionKind.CONTROL_SET: ("scene_id", "control_id", "value"),
    ActionKind.SCENE_GOTO: ("scene_id",),
    ActionKind.REVEAL: ("scene_id", "anchor_id"),
    ActionKind.HIDE: ("scene_id", "anchor_id"),
    ActionKind.SEQUENCE: ("sequence_id",),
}
_SCENE_ID = re.compile(r"pss_[0-9a-f]{12}\Z")


@dataclass(frozen=True, slots=True)
class ActionRef:
    """Une action pré-écrite et réversible, nommée par ids : jamais un outil, une commande ni du texte exécuté.

    Ensemble clos (`ActionKind`). `value` n'existe que pour `control_set` : un scalaire borné
    (booléen, nombre fini ou texte <= 200) qu'une valeur de contrôle accepte ; il est vérifié
    contre les bornes du contrôle (`check_score`) et contre le manifeste (`check_score_values`).
    Réversibilité : `reveal` <-> `hide`, `control_set` rend la valeur précédente, `scene_goto` revient
    à la scène précédente, une séquence se quitte par son point de reprise.
    """

    reversible: ClassVar[bool] = True

    kind: ActionKind
    scene_id: str | None = None
    control_id: str | None = None
    anchor_id: str | None = None
    sequence_id: str | None = None
    value: Any = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _enum(ActionKind, "action kind", self.kind))
        shape = _SHAPE[self.kind]
        for name in ("scene_id", "control_id", "anchor_id", "sequence_id", "value"):
            present = getattr(self, name) is not None
            if present and name not in shape:
                raise _fail(f"action {self.kind.value} takes no {name}")
            if not present and name in shape:
                raise _fail(f"action {self.kind.value} needs {name}")
        if self.scene_id is not None:
            _check_id("scene_id", self.scene_id, _SCENE_ID)
        for name in ("control_id", "anchor_id", "sequence_id"):
            if getattr(self, name) is not None:
                _slug(name, getattr(self, name))
        if self.kind is ActionKind.CONTROL_SET:
            value = self.value
            if isinstance(value, str):
                _text("value", value, MAX_VALUE_CHARS)
            elif type(value) not in (bool, int, float) or (type(value) is float and not math.isfinite(value)):
                raise _fail("a control value is a boolean, a finite number or a short text (never a list or an object)")

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, **{name: getattr(self, name) for name in _SHAPE[self.kind]}}

    def key(self) -> str:
        """Identité d'une action : JSON canonique (jamais `==`, qui confond `1`, `1.0` et `true`)."""

        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, raw: object, where: str = "action") -> ActionRef:
        data = _exact_keys(raw, where, {"kind"},
                           frozenset({"scene_id", "control_id", "anchor_id", "sequence_id", "value"}))
        return cls(**data)


def _actions(name: str, value: object, *, allow_sequence: bool) -> tuple[ActionRef, ...]:
    items = _tuple(name, value, ActionRef, MAX_ACTIONS)
    keys = [item.key() for item in items]
    if len(set(keys)) != len(keys):
        raise _fail(f"{name} holds the same action twice")
    if not allow_sequence and any(a.kind is ActionKind.SEQUENCE for a in items):
        raise _fail(f"{name} cannot start a locked sequence here")
    return items


def _action_list(raw: object, where: str) -> tuple[ActionRef, ...]:
    return tuple(ActionRef.from_dict(a, f"{where}[{i}]") for i, a in enumerate(_listed(where, raw, MAX_ACTIONS)))


# ------------------------------------------------------------------ séquences verrouillées

@dataclass(frozen=True, slots=True)
class SequenceStep:
    """Une étape à `offset_ms` **relatif** au début du segment. `speaker` : `jarvis` ou `none` ; l'étape dit ce qui se passe, pas quand dans le monde."""

    step_id: str
    offset_ms: int
    speaker: Presenter = Presenter.NONE
    text: str = ""
    visual: tuple[ActionRef, ...] = ()
    motion: tuple[ActionRef, ...] = ()

    def __post_init__(self) -> None:
        _slug("step_id", self.step_id)
        _check_int("offset_ms", self.offset_ms, 0, MAX_DURATION_MS)
        speaker = _enum(Presenter, "speaker", self.speaker)
        if speaker is Presenter.USER:
            raise _fail(f"step {self.step_id}: a locked sequence is Jarvis speech or silence, never the user")
        object.__setattr__(self, "speaker", speaker)
        _text("text", self.text, MAX_TEXT_CHARS, allow_empty=True)
        if (speaker is Presenter.JARVIS) != bool(self.text):
            raise _fail(f"step {self.step_id}: text is required for a Jarvis step and forbidden for a silent one")
        object.__setattr__(self, "visual", _actions("visual", self.visual, allow_sequence=False))
        object.__setattr__(self, "motion", _actions("motion", self.motion, allow_sequence=False))
        if speaker is Presenter.NONE and not self.visual and not self.motion:
            raise _fail(f"step {self.step_id} does nothing: give it speech or an action")

    def to_dict(self) -> dict[str, Any]:
        return {"step_id": self.step_id, "offset_ms": self.offset_ms, "speaker": self.speaker.value, "text": self.text,
                "visual": [a.to_dict() for a in self.visual], "motion": [a.to_dict() for a in self.motion]}

    @classmethod
    def from_dict(cls, raw: object, where: str = "step") -> SequenceStep:
        data = _exact_keys(raw, where, {"step_id", "offset_ms"},
                           frozenset({"speaker", "text", "visual", "motion"}))
        return cls(data["step_id"], data["offset_ms"], data.get("speaker", "none"), data.get("text", ""),
                   _action_list(data.get("visual", []), f"{where}.visual"),
                   _action_list(data.get("motion", []), f"{where}.motion"))


@dataclass(frozen=True, slots=True)
class LockedSequence:
    """Segment verrouillé : étapes dans l'ordre d'écriture, décalages relatifs strictement croissants dès 0.

    Mêmes données -> mêmes décalages (`timeline`). Bornes : le segment commence et finit avec son item
    hôte (`ScoreItem` portant `ActionRef(sequence)`), qui doit avoir `target_duration_ms == duration_ms`.
    """

    sequence_id: str
    label: str
    steps: tuple[SequenceStep, ...]
    duration_ms: int
    on_interrupt: SequenceInterrupt = SequenceInterrupt.PAUSE_RESUME
    #: Point de reprise (`RecoveryPoint`) : exigé par `abort_to_recovery`, refusé sinon.
    recovery_id: str | None = None

    def __post_init__(self) -> None:
        _slug("sequence_id", self.sequence_id)
        _text("label", self.label, MAX_LABEL)
        steps = _tuple("steps", self.steps, SequenceStep, MAX_STEPS)
        if not steps:
            raise _fail(f"sequence {self.sequence_id} has no step")
        ids = [s.step_id for s in steps]
        if len(set(ids)) != len(ids):
            raise _fail(f"sequence {self.sequence_id}: the same step_id appears twice")
        offsets = [s.offset_ms for s in steps]
        if offsets[0] != 0 or any(b <= a for a, b in zip(offsets, offsets[1:])):
            raise _fail(f"sequence {self.sequence_id}: step offsets start at 0 and strictly increase")
        _duration("duration_ms", self.duration_ms)
        if self.duration_ms <= offsets[-1]:
            raise _fail(f"sequence {self.sequence_id}: duration_ms must exceed the last step offset")
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "on_interrupt", _enum(SequenceInterrupt, "on_interrupt", self.on_interrupt))
        if self.recovery_id is not None:
            _slug("recovery_id", self.recovery_id)
        if (self.on_interrupt is SequenceInterrupt.ABORT_TO_RECOVERY) != (self.recovery_id is not None):
            raise _fail(f"sequence {self.sequence_id}: abort_to_recovery needs a recovery_id, pause_resume forbids one")

    def timeline(self) -> tuple[tuple[int, str], ...]:
        """`((offset_ms, step_id), ...)` : déterministe, trié par décalage (= l'ordre d'écriture)."""

        return tuple((s.offset_ms, s.step_id) for s in self.steps)

    def speaks(self) -> bool:
        return any(s.speaker is Presenter.JARVIS for s in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {"sequence_id": self.sequence_id, "label": self.label, "steps": [s.to_dict() for s in self.steps],
                "duration_ms": self.duration_ms, "on_interrupt": self.on_interrupt.value,
                "recovery_id": self.recovery_id}

    @classmethod
    def from_dict(cls, raw: object, where: str = "sequence") -> LockedSequence:
        data = _exact_keys(raw, where, {"sequence_id", "label", "steps", "duration_ms"},
                           frozenset({"on_interrupt", "recovery_id"}))
        return cls(data["sequence_id"], data["label"],
                   tuple(SequenceStep.from_dict(s, f"{where}.steps[{i}]")
                         for i, s in enumerate(_listed(f"{where}.steps", data["steps"], MAX_STEPS))),
                   data["duration_ms"], data.get("on_interrupt", "pause_resume"), data.get("recovery_id"))


@dataclass(frozen=True, slots=True)
class RecoveryPoint:
    recovery_id: str
    label: str
    item_id: str

    def __post_init__(self) -> None:
        _slug("recovery_id", self.recovery_id)
        _text("label", self.label, MAX_LABEL)
        _check_id("item_id", self.item_id, ITEM_ID)

    def to_dict(self) -> dict[str, Any]:
        return {"recovery_id": self.recovery_id, "label": self.label, "item_id": self.item_id}

    @classmethod
    def from_dict(cls, raw: object, where: str = "recovery point") -> RecoveryPoint:
        data = _exact_keys(raw, where, {"recovery_id", "label", "item_id"})
        return cls(data["recovery_id"], data["label"], data["item_id"])


# ------------------------------------------------------------------ items

@dataclass(frozen=True, slots=True)
class LoopSpec:
    """Boucle **déclarée** : après cet item, retour à `to_item_id` au plus `max_repeats` fois. Seule répétition admise."""

    to_item_id: str
    max_repeats: int

    def __post_init__(self) -> None:
        _check_id("to_item_id", self.to_item_id, ITEM_ID)
        _check_int("max_repeats", self.max_repeats, 1, MAX_LOOP_REPEATS)

    def to_dict(self) -> dict[str, Any]:
        return {"to_item_id": self.to_item_id, "max_repeats": self.max_repeats}

    @classmethod
    def from_dict(cls, raw: object, where: str = "loop") -> LoopSpec:
        data = _exact_keys(raw, where, {"to_item_id", "max_repeats"})
        return cls(data["to_item_id"], data["max_repeats"])


@dataclass(frozen=True, slots=True)
class ScoreItem:
    """Un temps de la partition. Voir l'en-tête du module et le contrat.

    Parole : `presenter` user/jarvis -> exactement un de `text` (dite telle quelle) ou `note`
    (intention : le locuteur improvise). `presenter=none` -> silence explicite : ni `text` ni `note`.
    Item hôte d'une séquence verrouillée (`ActionRef(sequence)` dans `visual`) : `timing=locked`,
    `text` interdit (la parole est dans les étapes), jarvis exige une étape Jarvis, user exige une `note`.
    """

    item_id: str
    scene_id: str
    presenter: Presenter
    kind: ItemKind
    label: str = ""
    text: str = ""
    note: str = ""
    cue_id: str | None = None
    visual: tuple[ActionRef, ...] = ()
    motion: tuple[ActionRef, ...] = ()
    target_duration_ms: int | None = None
    timing: TimingPolicy = TimingPolicy.SOFT
    interruption: Interruption = Interruption.ALLOW
    recovery: Recovery = Recovery.CONTINUE_ITEM
    recovery_point_id: str | None = None
    next_item_id: str | None = None
    loop: LoopSpec | None = None

    def __post_init__(self) -> None:
        _check_id("item_id", self.item_id, ITEM_ID)
        _check_id("scene_id", self.scene_id, _SCENE_ID)
        object.__setattr__(self, "presenter", _enum(Presenter, "presenter", self.presenter))
        object.__setattr__(self, "kind", _enum(ItemKind, "kind", self.kind))
        object.__setattr__(self, "timing", _enum(TimingPolicy, "timing", self.timing))
        object.__setattr__(self, "interruption", _enum(Interruption, "interruption", self.interruption))
        object.__setattr__(self, "recovery", _enum(Recovery, "recovery", self.recovery))
        _text("label", self.label, MAX_LABEL, allow_empty=True)
        _text("text", self.text, MAX_TEXT_CHARS, allow_empty=True)
        _text("note", self.note, MAX_NOTE_CHARS, allow_empty=True)
        if self.cue_id is not None:
            _check_id("cue_id", self.cue_id, CUE_ID)
        object.__setattr__(self, "visual", _actions("visual", self.visual, allow_sequence=True))
        object.__setattr__(self, "motion", _actions("motion", self.motion, allow_sequence=False))
        if self.target_duration_ms is not None:
            _duration("target_duration_ms", self.target_duration_ms)
        if self.recovery_point_id is not None:
            _slug("recovery_point_id", self.recovery_point_id)
        if (self.recovery is Recovery.RECOVERY_POINT) != (self.recovery_point_id is not None):
            raise _fail(f"item {self.item_id}: recovery_point needs a recovery_point_id, other behaviours forbid one")
        if self.next_item_id is not None:
            _check_id("next_item_id", self.next_item_id, ITEM_ID)
            if self.next_item_id == self.item_id:
                raise _fail(f"item {self.item_id} cannot be its own next item (declare a loop instead)")
        if self.loop is not None and not isinstance(self.loop, LoopSpec):
            raise _fail("loop must be a LoopSpec")
        for action in self.visual:
            if action.kind is ActionKind.SCENE_GOTO and action.scene_id != self.scene_id:
                raise _fail(f"item {self.item_id} belongs to scene {self.scene_id} but goes to scene "
                            f"{action.scene_id}: an item's own scene_goto names its scene")
        self._check_speech()
        self._check_timing()

    def sequence_refs(self) -> tuple[str, ...]:
        return tuple(a.sequence_id for a in self.visual if a.kind is ActionKind.SEQUENCE)  # type: ignore[misc]

    def _check_speech(self) -> None:
        silent = self.presenter is Presenter.NONE
        if silent != (self.kind is ItemKind.SILENCE):
            raise _fail(f"item {self.item_id}: kind silence is exactly presenter none")
        refs = self.sequence_refs()
        if len(refs) > 1:
            raise _fail(f"item {self.item_id} starts more than one locked sequence")
        if silent:
            if self.text or self.note:
                raise _fail(f"item {self.item_id}: a silence item carries no speech and no note")
        elif refs:
            if self.text:
                raise _fail(f"item {self.item_id}: a locked-sequence host speaks through its steps, not text")
            if self.presenter is Presenter.USER and not self.note:
                raise _fail(f"item {self.item_id}: a user presenter needs a note (the intention) over a locked sequence")
        elif bool(self.text) == bool(self.note):
            raise _fail(f"item {self.item_id}: a speaking item needs exactly one of text or note")

    def _check_timing(self) -> None:
        hosts = bool(self.sequence_refs())
        if hosts != (self.timing is TimingPolicy.LOCKED):
            raise _fail(f"item {self.item_id}: timing locked is exactly an item that starts a locked sequence")
        if hosts:
            if self.target_duration_ms is None:
                raise _fail(f"item {self.item_id}: a locked item needs target_duration_ms")
            if self.interruption is Interruption.ALLOW:
                raise _fail(f"item {self.item_id}: a locked item cannot allow interruption (at_boundary or refuse)")

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id, "scene_id": self.scene_id, "presenter": self.presenter.value,
            "kind": self.kind.value, "label": self.label, "text": self.text, "note": self.note, "cue_id": self.cue_id,
            "visual": [a.to_dict() for a in self.visual], "motion": [a.to_dict() for a in self.motion],
            "target_duration_ms": self.target_duration_ms, "timing": self.timing.value,
            "interruption": self.interruption.value, "recovery": self.recovery.value,
            "recovery_point_id": self.recovery_point_id, "next_item_id": self.next_item_id,
            "loop": self.loop.to_dict() if self.loop else None,
        }

    @classmethod
    def from_dict(cls, raw: object, where: str = "item") -> ScoreItem:
        data = _exact_keys(raw, where, {"item_id", "scene_id", "presenter", "kind"},
                           frozenset({"label", "text", "note", "cue_id", "visual", "motion", "target_duration_ms",
                                      "timing", "interruption", "recovery", "recovery_point_id", "next_item_id",
                                      "loop"}))
        loop = data.get("loop")
        return cls(
            data["item_id"], data["scene_id"], data["presenter"], data["kind"], data.get("label", ""),
            data.get("text", ""), data.get("note", ""), data.get("cue_id"),
            _action_list(data.get("visual", []), f"{where}.visual"),
            _action_list(data.get("motion", []), f"{where}.motion"), data.get("target_duration_ms"),
            data.get("timing", "soft"), data.get("interruption", "allow"), data.get("recovery", "continue_item"),
            data.get("recovery_point_id"), data.get("next_item_id"),
            LoopSpec.from_dict(loop, f"{where}.loop") if loop is not None else None)


# ------------------------------------------------------------------ classement structurel des champs texte

#: Tout champ `str` de ce module est soit un identifiant/énumération (validé par motif ou énumération fermée),
#: soit un texte de `FREE_TEXT_FIELDS` : dit, affiché, apparié ou écrit comme valeur de contrôle, **jamais exécuté**.
#: `tests/unit/test_presentation_studio_score.py` impose que chaque champ `str` soit dans l'un des deux classements.
FREE_TEXT_FIELDS: Mapping[str, frozenset[str]] = {
    "ScoreItem": frozenset({"label", "text", "note"}),
    "CueDefinition": frozenset({"label"}),
    "CuePredicate": frozenset({"phrases"}),
    "SequenceStep": frozenset({"text"}),
    "LockedSequence": frozenset({"label"}),
    "RecoveryPoint": frozenset({"label"}),
    "ActionRef": frozenset({"value"}),
}
#: Champs non textuels : entiers, booléens et collections de classes du modèle. Un champ de modèle qui n'est dans aucun
#: des trois classements fait échouer `test_every_model_field_is_classified`, quelle que soit son annotation.
STRUCTURE_FIELDS: Mapping[str, frozenset[str]] = {
    "ScoreItem": frozenset({"visual", "motion", "target_duration_ms", "loop"}),
    "CueDefinition": frozenset({"predicate", "armable"}),
    "CuePredicate": frozenset(),
    "SequenceStep": frozenset({"offset_ms", "visual", "motion"}),
    "LockedSequence": frozenset({"steps", "duration_ms"}),
    "RecoveryPoint": frozenset(),
    "ActionRef": frozenset(),
    "LoopSpec": frozenset({"max_repeats"}),
    "Score": frozenset({"items", "cues", "sequences", "recovery_points", "revision"}),
}
ID_FIELDS: Mapping[str, frozenset[str]] = {
    "ScoreItem": frozenset({"item_id", "scene_id", "presenter", "kind", "cue_id", "timing", "interruption", "recovery",
                            "recovery_point_id", "next_item_id"}),
    "CueDefinition": frozenset({"cue_id"}),
    "CuePredicate": frozenset({"semantics"}),
    "SequenceStep": frozenset({"step_id", "speaker"}),
    "LockedSequence": frozenset({"sequence_id", "on_interrupt", "recovery_id"}),
    "RecoveryPoint": frozenset({"recovery_id", "item_id"}),
    "ActionRef": frozenset({"kind", "scene_id", "control_id", "anchor_id", "sequence_id"}),
    "LoopSpec": frozenset({"to_item_id"}),
    "Score": frozenset({"score_id", "presentation_id", "variant_id", "start_item_id", "created_at", "updated_at"}),
}


# ------------------------------------------------------------------ la partition

def _expand(chain: list[ScoreItem]) -> list[str]:
    """Ordre de lecture développé (boucles déclarées comprises), borné par `MAX_EXPANDED_ITEMS`."""

    index = {item.item_id: i for i, item in enumerate(chain)}
    counters = [0] * len(chain)
    order: list[str] = []
    position = 0
    while position < len(chain):
        item = chain[position]
        order.append(item.item_id)
        if len(order) > MAX_EXPANDED_ITEMS:
            raise _fail(f"the declared loops expand beyond {MAX_EXPANDED_ITEMS} items")
        if item.loop is not None and counters[position] < item.loop.max_repeats:
            counters[position] += 1
            target = index[item.loop.to_item_id]
            for inner in range(target, position):
                counters[inner] = 0  # an inner loop repeats afresh each time the outer one comes back to it
            position = target
        else:
            position += 1
    return order


@dataclass(frozen=True, slots=True)
class Score:
    score_id: str
    presentation_id: str
    variant_id: str
    start_item_id: str | None
    items: tuple[ScoreItem, ...]
    cues: tuple[CueDefinition, ...]
    sequences: tuple[LockedSequence, ...]
    recovery_points: tuple[RecoveryPoint, ...]
    revision: int
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        _check_id("score_id", self.score_id, SCORE_ID)
        _check_id("presentation_id", self.presentation_id, PRESENTATION_ID)
        _check_id("variant_id", self.variant_id, VARIANT_ID)
        _check_id("start_item_id", self.start_item_id, ITEM_ID, optional=True)
        object.__setattr__(self, "items", _tuple("items", self.items, ScoreItem, MAX_ITEMS))
        object.__setattr__(self, "cues", _tuple("cues", self.cues, CueDefinition, MAX_CUES))
        object.__setattr__(self, "sequences", _tuple("sequences", self.sequences, LockedSequence, MAX_SEQUENCES))
        object.__setattr__(self, "recovery_points",
                           _tuple("recovery_points", self.recovery_points, RecoveryPoint, MAX_RECOVERY_POINTS))
        _check_int("revision", self.revision, 1, 2**31 - 1)
        _check_stamp("created_at", self.created_at)
        _check_stamp("updated_at", self.updated_at)
        self._check_graph()
        self._check_references()
        self._check_sequences()

    # -- structure ---------------------------------------------------------

    def _unique(self, label: str, values: list[str]) -> None:
        if len(set(values)) != len(values):
            raise _fail(f"the same {label} appears twice")

    def _check_graph(self) -> None:
        ids = [i.item_id for i in self.items]
        self._unique("item_id", ids)
        known = set(ids)
        if not self.items:
            if self.start_item_id is not None:
                raise _fail("start_item_id names no item (the score is empty)")
            return
        if self.start_item_id not in known:
            raise _fail("start_item_id must name an item of the score")
        targets: list[str] = []
        for item in self.items:
            if item.next_item_id is not None:
                if item.next_item_id not in known:
                    raise _fail(f"item {item.item_id}: next_item_id {item.next_item_id} is not an item of the score")
                targets.append(item.next_item_id)
            if item.loop is not None and item.loop.to_item_id not in known:
                raise _fail(f"item {item.item_id}: loop target {item.loop.to_item_id} is not an item of the score")
        if len(set(targets)) != len(targets):
            raise _fail("two items lead to the same next item: the score is one chain")
        if self.start_item_id in targets and not self._chain_from_start_is_acyclic():
            raise _fail("the next-item graph holds a cycle: only a declared loop (loop.max_repeats) may repeat")
        chain = self.chain()
        if len(chain) != len(self.items):
            left = sorted(known - {i.item_id for i in chain})
            raise _fail(f"items not reachable from the start through next_item_id (or in an undeclared cycle): "
                        f"{', '.join(left[:4])}")
        position = {item.item_id: i for i, item in enumerate(chain)}
        for i, item in enumerate(chain):
            if item.loop is not None and position[item.loop.to_item_id] > i:
                raise _fail(f"item {item.item_id}: a loop returns to an earlier (or the same) item, never forward")
        spans = sorted((position[i.loop.to_item_id], position[i.item_id]) for i in chain if i.loop is not None)
        for (a_start, a_end), (b_start, b_end) in zip(spans, spans[1:]):
            if a_start < b_start <= a_end < b_end:
                raise _fail("declared loops may nest or follow one another, never overlap partially")
        _expand(chain)

    def _chain_from_start_is_acyclic(self) -> bool:
        by_id = {i.item_id: i for i in self.items}
        seen: set[str] = set()
        current = self.start_item_id
        while current is not None:
            if current in seen:
                return False
            seen.add(current)
            current = by_id[current].next_item_id
        return True

    def _check_references(self) -> None:
        self._unique("cue_id", [c.cue_id for c in self.cues])
        self._unique("recovery_id", [r.recovery_id for r in self.recovery_points])
        cue_ids = {c.cue_id for c in self.cues}
        used = [i.cue_id for i in self.items if i.cue_id is not None]
        for cue in used:
            if cue not in cue_ids:
                raise _fail(f"cue {cue} is not defined by the score")
        self._unique("cue use (a cue names exactly one item)", used)
        if set(used) != cue_ids:
            raise _fail("a defined cue is used by no item: " + ", ".join(sorted(cue_ids - set(used))[:4]))
        item_ids = {i.item_id for i in self.items}
        for point in self.recovery_points:
            if point.item_id not in item_ids:
                raise _fail(f"recovery point {point.recovery_id} names an item the score does not hold")
        points = {r.recovery_id for r in self.recovery_points}
        for item in self.items:
            if item.recovery_point_id is not None and item.recovery_point_id not in points:
                raise _fail(f"item {item.item_id}: unknown recovery point {item.recovery_point_id}")

    def _check_sequences(self) -> None:
        self._unique("sequence_id", [s.sequence_id for s in self.sequences])
        by_id = {s.sequence_id: s for s in self.sequences}
        points = {r.recovery_id for r in self.recovery_points}
        hosts: dict[str, ScoreItem] = {}
        for item in self.items:
            for ref in item.sequence_refs():
                if ref not in by_id:
                    raise _fail(f"item {item.item_id}: unknown locked sequence {ref}")
                if ref in hosts:
                    raise _fail(f"locked sequence {ref} is started by two items")
                hosts[ref] = item
        for sequence in self.sequences:
            host = hosts.get(sequence.sequence_id)
            if host is None:
                raise _fail(f"locked sequence {sequence.sequence_id} is started by no item")
            if host.target_duration_ms != sequence.duration_ms:
                raise _fail(f"item {host.item_id}: target_duration_ms must equal its sequence duration_ms "
                            f"({sequence.duration_ms}): a locked segment has one exact length")
            if sequence.speaks() and host.presenter is not Presenter.JARVIS:
                raise _fail(f"sequence {sequence.sequence_id} has Jarvis speech but its item's presenter is "
                            f"{host.presenter.value}: only a jarvis presenter speaks as Jarvis")
            if host.presenter is Presenter.JARVIS and not sequence.speaks():
                raise _fail(f"item {host.item_id}: a jarvis presenter over a locked sequence needs a Jarvis step")
            if sequence.recovery_id is not None and sequence.recovery_id not in points:
                raise _fail(f"sequence {sequence.sequence_id}: unknown recovery point {sequence.recovery_id}")

    # -- lecture -----------------------------------------------------------

    def chain(self) -> tuple[ScoreItem, ...]:
        """Les items dans l'ordre du graphe (départ puis `next_item_id`), une fois chacun : l'ordre de la partition."""

        by_id = {i.item_id: i for i in self.items}
        order: list[ScoreItem] = []
        current = self.start_item_id
        seen: set[str] = set()
        while current is not None and current not in seen:
            seen.add(current)
            order.append(by_id[current])
            current = by_id[current].next_item_id
        return tuple(order)

    def playback_order(self) -> tuple[str, ...]:
        """L'ordre de lecture développé avec les boucles déclarées (borné). Pas d'horloge."""

        return tuple(_expand(list(self.chain())))

    def estimated_duration_ms(self) -> int:
        """Somme **souple** des durées cibles sur l'ordre développé (un item sans cible compte 0)."""

        by_id = {i.item_id: i for i in self.items}
        return sum(by_id[i].target_duration_ms or 0 for i in self.playback_order())

    def item(self, item_id: str) -> ScoreItem | None:
        return next((i for i in self.items if i.item_id == item_id), None)

    def resolve_cue(self, cue_id: str) -> ScoreItem | None:
        """L'item qu'une cue satisfaite déclenche, résolu depuis l'état canonique (R5) ; `None` si la cue est inconnue."""

        return next((i for i in self.items if i.cue_id == cue_id), None)

    def sequence(self, sequence_id: str) -> LockedSequence | None:
        return next((s for s in self.sequences if s.sequence_id == sequence_id), None)

    def track(self, track: Track) -> tuple[dict[str, Any], ...]:
        """Une piste, vue inspectable dans l'ordre de la partition. Le silence de Jarvis y est une entrée explicite."""

        entries: list[dict[str, Any]] = []
        for item in self.chain():
            base = {"item_id": item.item_id, "scene_id": item.scene_id}
            speech = {"text": item.text} if item.text else {"note": item.note} if item.note else {}
            host = item.sequence_refs()
            if track is Track.USER_SPEECH and item.presenter is Presenter.USER:
                entries.append({**base, **speech})
            elif track is Track.JARVIS_SPEECH:
                if item.presenter is Presenter.JARVIS:
                    entries.append({**base, **speech, **({"sequence_id": host[0]} if host else {})})
                elif item.presenter is Presenter.NONE:
                    entries.append({**base, "silence": True})
            elif track is Track.VISUAL and item.visual:
                entries.append({**base, "actions": [a.to_dict() for a in item.visual]})
            elif track is Track.MOTION and item.motion:
                entries.append({**base, "actions": [a.to_dict() for a in item.motion]})
            elif track is Track.CUES and item.cue_id is not None:
                cue = next(c for c in self.cues if c.cue_id == item.cue_id)
                entries.append({**base, "cue_id": cue.cue_id, "armable": cue.armable})
        return tuple(entries)

    # -- documents ---------------------------------------------------------

    def content(self) -> dict[str, Any]:
        return {"start_item_id": self.start_item_id, "items": [i.to_dict() for i in self.items],
                "cues": [c.to_dict() for c in self.cues], "sequences": [s.to_dict() for s in self.sequences],
                "recovery_points": [r.to_dict() for r in self.recovery_points]}

    def to_document(self) -> dict[str, Any]:
        return {"schema": SCHEMA_SCORE, "schema_version": SCORE_SCHEMA_VERSION, "score_id": self.score_id,
                "presentation_id": self.presentation_id, "variant_id": self.variant_id, **self.content(),
                "revision": self.revision, "created_at": self.created_at, "updated_at": self.updated_at}

    def canonical(self) -> str:
        """JSON canonique (clés triées) : l'identité de contenu d'une partition, pour comparer sans `==`."""

        return canonical_json(self.to_document())

    def content_key(self) -> str:
        return canonical_json(self.content())


def phrase_index(score: Score, *, armable_only: bool = False) -> dict[str, tuple[str, ...]]:
    """Phrase normalisée -> `cue_id` triés. Pur. Le même mot peut légitimement revenir sur des cues différentes du
    score : aucune collision n'est refusée ici, c'est l'ensemble **armé** qui doit être sans ambiguïté (`ambiguous_phrases`)."""

    index: dict[str, list[str]] = {}
    for cue in score.cues:
        if armable_only and not cue.armable:
            continue
        for phrase in cue.predicate.phrases:
            index.setdefault(phrase, []).append(cue.cue_id)
    return {phrase: tuple(sorted(ids)) for phrase, ids in sorted(index.items())}


def semantic_index(score: Score, *, armable_only: bool = False) -> dict[str, tuple[str, ...]]:
    """Étiquette sémantique -> `cue_id` triés (même contrat que `phrase_index`)."""

    index: dict[str, list[str]] = {}
    for cue in score.cues:
        if armable_only and not cue.armable:
            continue
        for label in cue.predicate.semantics:
            index.setdefault(label, []).append(cue.cue_id)
    return {label: tuple(sorted(ids)) for label, ids in sorted(index.items())}


def ambiguous_phrases(score: Score, cue_ids: Iterable[str] | None = None) -> dict[str, tuple[str, ...]]:
    """Phrases (et étiquettes sémantiques, préfixées `semantic:`) qui nomment plus d'une cue parmi `cue_ids`.

    `cue_ids` : l'ensemble armé que la Slice 13 s'apprête à surveiller ; par défaut, toutes les cues armables du score.
    Une cue non armable n'est jamais comptée (elle n'est jamais appariée)."""

    armable = {c.cue_id for c in score.cues if c.armable}
    wanted = armable if cue_ids is None else armable & set(cue_ids)
    found: dict[str, tuple[str, ...]] = {}
    for phrase, ids in phrase_index(score, armable_only=True).items():
        hit = tuple(i for i in ids if i in wanted)
        if len(hit) > 1:
            found[phrase] = hit
    for label, ids in semantic_index(score, armable_only=True).items():
        hit = tuple(i for i in ids if i in wanted)
        if len(hit) > 1:
            found["semantic:" + label] = hit
    return found


CONTENT_KEYS = frozenset({"start_item_id", "items", "cues", "sequences", "recovery_points"})


def parse_content(data: Mapping[str, Any]) -> dict[str, Any]:
    """Les champs de contenu d'un corps ou d'un document (`CONTENT_KEYS`) -> arguments de `Score`. Refuse tout le reste en amont."""

    return {
        "start_item_id": data["start_item_id"],
        "items": tuple(ScoreItem.from_dict(i, f"items[{n}]") for n, i in enumerate(_listed("items", data["items"], MAX_ITEMS))),
        "cues": tuple(CueDefinition.from_dict(c, f"cues[{n}]") for n, c in enumerate(_listed("cues", data["cues"], MAX_CUES))),
        "sequences": tuple(LockedSequence.from_dict(s, f"sequences[{n}]")
                           for n, s in enumerate(_listed("sequences", data["sequences"], MAX_SEQUENCES))),
        "recovery_points": tuple(RecoveryPoint.from_dict(r, f"recovery_points[{n}]") for n, r in
                                 enumerate(_listed("recovery_points", data["recovery_points"], MAX_RECOVERY_POINTS))),
    }


def parse_score(raw: object) -> Score:
    """Document au format disque -> `Score`. Version plus récente : refus ; clé inconnue : refus."""

    data = _exact_keys(upgrade_document(raw, SCHEMA_SCORE), "score",
                       {"schema", "schema_version", "score_id", "presentation_id", "variant_id", *CONTENT_KEYS,
                        "revision", "created_at", "updated_at"})
    return Score(data["score_id"], data["presentation_id"], data["variant_id"], **parse_content(data),
                 revision=data["revision"], created_at=data["created_at"], updated_at=data["updated_at"])


@dataclass(frozen=True, slots=True)
class ScoreUpdate:
    """Corps d'un `PUT` : `expected_revision` + le contenu entier (remplacement)."""

    expected_revision: int
    content: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ScoreCreate:
    """Corps d'un `POST` : `expected_variant_revision` (la variante reçoit son `score_id`) + le contenu."""

    expected_variant_revision: int
    content: Mapping[str, Any]


def parse_score_update(raw: object) -> ScoreUpdate:
    data = _exact_keys(raw, "score update", {"expected_revision", *CONTENT_KEYS})
    _check_int("expected_revision", data["expected_revision"], 1, 2**31 - 1)
    return ScoreUpdate(data["expected_revision"], parse_content(data))


def parse_score_create(raw: object) -> ScoreCreate:
    data = _exact_keys(raw, "score create", {"expected_variant_revision", *CONTENT_KEYS})
    _check_int("expected_variant_revision", data["expected_variant_revision"], 1, 2**31 - 1)
    return ScoreCreate(data["expected_variant_revision"], parse_content(data))


def new_score(presentation_id: str, variant_id: str, content: Mapping[str, Any], now: Any, *,
              score_id: str | None = None) -> Score:
    at = stamp(now)
    return Score(score_id or new_score_id(), presentation_id, variant_id, **content, revision=1,
                 created_at=at, updated_at=at)


# ------------------------------------------------------------------ validation contre la variante

def _actions_of(score: Score) -> list[tuple[str, str, ActionRef]]:
    """`(où, piste, action)` pour chaque action d'un item ou d'une étape ; `piste` : `visual` ou `motion`."""

    found: list[tuple[str, str, ActionRef]] = []
    for item in score.items:
        found += [(f"item {item.item_id}", "visual", a) for a in item.visual]
        found += [(f"item {item.item_id}", "motion", a) for a in item.motion]
    for sequence in score.sequences:
        for step in sequence.steps:
            found += [(f"sequence {sequence.sequence_id} step {step.step_id}", "visual", a) for a in step.visual]
            found += [(f"sequence {sequence.sequence_id} step {step.step_id}", "motion", a) for a in step.motion]
    return found


def _bounds_problem(scene: StudioScene, action: ActionRef) -> str | None:
    """Sans manifeste : type et bornes curées du contrôle. (Le manifeste complet : `check_score_values`.)"""

    control = scene.control(action.control_id or "")
    if control is None:
        return f"control {action.control_id} is not declared by scene {scene.scene_id}"
    value, bounds = action.value, control.bounds
    kind = bool if type(value) is bool else str if isinstance(value, str) else float if type(value) is float else int
    reference = control.default
    if reference is None:
        present, current = value_at(scene, control)
        reference = current if present else None
    if reference is not None:
        wanted = bool if type(reference) is bool else str if isinstance(reference, str) else (int, float)
        if not (kind is wanted if wanted in (bool, str) else kind in wanted):
            return f"the value of control {control.control_id} must be of the control's own type"
    if kind in (int, float):
        if bounds.min is not None and value < bounds.min:
            return f"control {control.control_id}: value is below the curated minimum {bounds.min}"
        if bounds.max is not None and value > bounds.max:
            return f"control {control.control_id}: value is above the curated maximum {bounds.max}"
    if kind is str:
        if bounds.max_length is not None and len(value) > bounds.max_length:
            return f"control {control.control_id}: value exceeds {bounds.max_length} characters"
        if bounds.choices and value not in bounds.choices:
            return f"control {control.control_id}: value is not one of the curated choices"
    return None


def check_score(score: Score, scenes: tuple[StudioScene, ...]) -> list[str]:
    """Chaque référence se résout dans la variante : scènes, contrôles, ancres, groupe de piste, valeurs bornées.

    Liste vide : compatible. Bornée à `MAX_CHECK_ERRORS`. Pur."""

    by_id = {scene.scene_id: scene for scene in scenes}
    errors: list[str] = []
    for item in score.items:
        if item.scene_id not in by_id:
            errors.append(f"item {item.item_id}: scene {item.scene_id} is not a scene of this variant")
    for where, track, action in _actions_of(score):
        if action.kind is ActionKind.SEQUENCE:
            continue  # resolved structurally by the score itself
        scene = by_id.get(action.scene_id or "")
        if scene is None:
            errors.append(f"{where}: scene {action.scene_id} is not a scene of this variant")
            continue
        if action.kind in (ActionKind.REVEAL, ActionKind.HIDE):
            if not any(a.anchor_id == action.anchor_id for a in scene.anchors):
                errors.append(f"{where}: anchor {action.anchor_id} is not declared by scene {scene.scene_id}")
        elif action.kind is ActionKind.CONTROL_SET:
            control = scene.control(action.control_id or "")
            if control is None:
                errors.append(f"{where}: control {action.control_id} is not declared by scene {scene.scene_id}")
                continue
            if (control.group is ControlGroup.MOTION) != (track == "motion"):
                errors.append(f"{where}: control {control.control_id} (group {control.group.value}) "
                              f"belongs on the {'motion' if control.group is ControlGroup.MOTION else 'visual'} track")
                continue
            problem = _bounds_problem(scene, action)
            if problem:
                errors.append(f"{where}: {problem}")
    return [clip(e, 200) for e in errors[:MAX_CHECK_ERRORS]]


def check_score_values(score: Score, scenes: tuple[StudioScene, ...],
                       manifests: Mapping[str, PrefabManifest]) -> list[str]:
    """Chaque valeur de `control_set` contre le **manifeste** de la scène (`value_problem` : type, bornes du manifeste et
    bornes curées). `manifests` : `scene_id` -> manifeste du pin. Une scène sans manifeste fourni est une erreur, pas un passe-droit."""

    by_id = {scene.scene_id: scene for scene in scenes}
    errors: list[str] = []
    for where, _track, action in _actions_of(score):
        if action.kind is not ActionKind.CONTROL_SET:
            continue
        scene = by_id.get(action.scene_id or "")
        control = scene.control(action.control_id or "") if scene else None
        if scene is None or control is None:
            continue  # reported by check_score
        manifest = manifests.get(scene.scene_id)
        node = node_of(manifest, control) if manifest is not None else None
        if node is None:
            errors.append(f"{where}: no manifest input for control {control.control_id}")
            continue
        problem = value_problem(node, control.bounds, action.value, control.path)
        if problem:
            errors.append(f"{where}: {problem}")
    return [clip(e, 200) for e in errors[:MAX_CHECK_ERRORS]]


def raise_if_incompatible(problems: list[str]) -> None:
    if problems:
        raise PresentationStudioError(PresentationStudioErrorCode.SCORE_INCOMPATIBLE, "; ".join(problems[:4]))


#: Re-export pour les tests : les dataclasses du modèle, dans l'ordre de lecture.
MODEL_CLASSES = (ScoreItem, CueDefinition, CuePredicate, ActionRef, SequenceStep, LockedSequence, RecoveryPoint,
                 LoopSpec, Score)