"""Horloge de composition d'une variante Remotion (handoff jarvis-remotion-native-studio-playback-fix, Slice 04 ;
`docs/presentation-studio.md` > *Presentation experience contract* > *Composition clock (Level 3)*).

Module **pur** (ni E/S, ni horloge, ni état mutable) : la seule implémentation de l'arithmétique de la composition côté Core. Le
navigateur en a un portage direct, `jarvis/runtime/control_center_composition_clock.js`, tenu identique par une table de vecteurs
commune (`tests/unit/test_composition_clock_conformance_js.py`).

- **Composition** : les scènes ordonnées de la variante, chacune avec sa composition déclarée (`fps`, `duration_in_frames`, lues
  dans le manifeste du pin, jamais dans le code de la scène). Un lecteur Remotion bac-à-sablé PAR scène (décision de la Slice 04) :
  ce module ne génère aucune racine `<Series>` ; il est la carte d'intervalles posée sur ces compositions.
- **Base de temps** : `fps` maître = le plus grand `fps` des scènes (entier, 1..120). Une scène native à `fps_k` pour `d_k` images
  dure `len_k = ceil(d_k * F / fps_k)` images maîtres. Image maître locale `m` -> image native `floor(m * fps_k / F)` ; image native
  `n` -> image maître locale `ceil(n * F / fps_k)`. Comme `fps_k <= F`, chaque image native a au moins une image maître et l'aller-retour
  natif -> maître -> natif est l'identité (testé). Entiers seulement : aucune virgule flottante dans une position.
- **Image de composition `f`** : un entier `0..L-1`, la seule position. La scène `k` occupe `[start_k, start_k + len_k)`,
  `start_0 = 0`, `start_k = start_(k-1) + len_(k-1) - transition_k`. `transition_k` (images maîtres, 0 par défaut : aucune transition
  n'existe aujourd'hui) est le recouvrement d'entrée de la scène `k` ; pendant un recouvrement, la scène « courante » est l'entrante.
- **Transport** (`Transport`, valeur) : `frame`, `playing`, `ended`. Les commandes gardent l'état de lecture ; la fin tient la dernière
  image (`ended`), ne boucle jamais ; seul `REPLAY` repart de 0.

La position de la **partition** (une lecture de présentateur, `presentation_studio_playback`) n'est pas ici : elle ne rejoint une image
de média que par des ancres explicites (`remotion_timeline.build_frame_map`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from jarvis.domain.remotion_timeline import TimelineError, checked_composition

#: Version du format servi (`to_wire`) ; le portage JS refuse une autre version.
WIRE_VERSION = 1

EMPTY = "composition_empty"
SCENE_INVALID = "composition_scene_invalid"
TRANSITION_INVALID = "composition_transition_invalid"
FRAME_OUT_OF_RANGE = "composition_frame_out_of_range"
SCENE_OUT_OF_RANGE = "composition_scene_out_of_range"
WIRE_MISMATCH = "composition_wire_mismatch"
#: `fromWire` (JS) sans la clé attendue : la vérification de carte périmée ne peut pas être sautée.
KEY_REQUIRED = "composition_key_required"


class CompositionError(ValueError):
    """Une composition ou une position refusée, avec un code stable (jamais une valeur par défaut silencieuse)."""

    def __init__(self, code: str, message: str, *, scene_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.scene_id = scene_id


@dataclass(frozen=True, slots=True)
class SceneManifest:
    """L'entrée d'une scène : sa composition déclarée (native)."""

    scene_id: str
    composition_id: str
    fps: int
    duration_in_frames: int


@dataclass(frozen=True, slots=True)
class SceneSpan:
    """Une scène posée dans la composition. `start`/`length`/`transition_in` en images maîtres ; `fps`/`duration_in_frames` natifs."""

    index: int
    scene_id: str
    composition_id: str
    fps: int
    duration_in_frames: int
    start: int
    length: int
    transition_in: int

    @property
    def end(self) -> int:
        """Première image maître après la scène (exclue)."""

        return self.start + self.length


@dataclass(frozen=True, slots=True)
class Position:
    frame: int
    scene_index: int
    scene_id: str
    #: Image maître locale (`frame - start`).
    local_frame: int
    #: L'image que le lecteur de la scène montre, à sa cadence native.
    native_frame: int
    #: `local_frame / length`, dans `[0, 1)`.
    local_progress: float


def scene_manifest(scene_id: str, composition: Mapping[str, Any]) -> SceneManifest:
    """Une scène depuis la composition de son manifeste (`PrefabService.remotion_composition`). Bornes de `checked_composition`."""

    if not isinstance(scene_id, str) or not scene_id:
        raise CompositionError(SCENE_INVALID, "a scene has no id")
    try:
        comp_id, fps, duration = checked_composition(composition)
    except TimelineError as exc:
        raise CompositionError(SCENE_INVALID, f"{scene_id}: {exc}", scene_id=scene_id) from exc
    return SceneManifest(scene_id, comp_id, fps, duration)


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


@dataclass(frozen=True, slots=True)
class CompositionMap:
    fps: int
    scenes: tuple[SceneSpan, ...]
    total_frames: int

    @property
    def last_frame(self) -> int:
        return self.total_frames - 1

    def _frame(self, frame: object) -> int:
        if type(frame) is not int or not 0 <= frame < self.total_frames:
            raise CompositionError(FRAME_OUT_OF_RANGE, f"frame must be an integer 0..{self.total_frames - 1}")
        return frame

    def _scene(self, index: object) -> SceneSpan:
        if type(index) is not int or not 0 <= index < len(self.scenes):
            raise CompositionError(SCENE_OUT_OF_RANGE, f"scene index must be an integer 0..{len(self.scenes) - 1}")
        return self.scenes[index]

    def clamp(self, frame: int) -> int:
        """Explicite : ramène un entier quelconque dans `0..L-1` (une édition qui raccourcit la composition, § 4.9)."""

        if type(frame) is not int:
            raise CompositionError(FRAME_OUT_OF_RANGE, "frame must be an integer")
        return max(0, min(self.last_frame, frame))

    def locate(self, frame: int) -> Position:
        """La scène qui contient `f` (pendant un recouvrement : l'entrante = le plus grand `start <= f`), son image locale et native."""

        f = self._frame(frame)
        lo, hi = 0, len(self.scenes) - 1
        while lo < hi:   # the last span whose start <= f
            mid = (lo + hi + 1) // 2
            if self.scenes[mid].start <= f:
                lo = mid
            else:
                hi = mid - 1
        span = self.scenes[lo]
        local = f - span.start
        return Position(f, span.index, span.scene_id, local, local * span.fps // self.fps, local / span.length)

    def start_of(self, index: int) -> int:
        return self._scene(index).start

    def frame_of(self, index: int, native_frame: int) -> int:
        """L'image de composition d'une image native du lecteur de la scène `index` (le conseil de son horloge)."""

        span = self._scene(index)
        if type(native_frame) is not int or not 0 <= native_frame < span.duration_in_frames:
            raise CompositionError(FRAME_OUT_OF_RANGE, f"native frame must be an integer 0..{span.duration_in_frames - 1}",
                                   scene_id=span.scene_id)
        return span.start + _ceil_div(native_frame * self.fps, span.fps)

    def next_start(self, frame: int) -> int | None:
        """Début de la scène suivante ; `None` sur la dernière scène (« Dernière scène », bouton désactivé)."""

        index = self.locate(frame).scene_index
        return None if index + 1 >= len(self.scenes) else self.scenes[index + 1].start

    def previous_start(self, frame: int) -> int:
        """Début de la scène précédente ; depuis la première scène, l'image 0."""

        index = self.locate(frame).scene_index
        return 0 if index == 0 else self.scenes[index - 1].start


def build_composition(manifests: Sequence[SceneManifest], transitions: Sequence[int] | None = None) -> CompositionMap:
    """La carte d'une composition. `transitions[k]` : recouvrement d'entrée de la scène `k` en images maîtres (`transitions[0]` vaut 0 ;
    absent : 0 partout). Chaque scène garde au moins une image où elle est seule (`in_k + in_(k+1) < len_k`)."""

    if not manifests:
        raise CompositionError(EMPTY, "the composition has no scene")
    ids = [m.scene_id for m in manifests]
    if len(set(ids)) != len(ids):
        raise CompositionError(SCENE_INVALID, "a scene appears twice in the composition")
    for m in manifests:
        scene_manifest(m.scene_id, {"id": m.composition_id, "fps": m.fps, "duration_in_frames": m.duration_in_frames})
    master = max(m.fps for m in manifests)
    lengths = [_ceil_div(m.duration_in_frames * master, m.fps) for m in manifests]
    overlaps = [0] * len(manifests) if transitions is None else list(transitions)
    if len(overlaps) != len(manifests):
        raise CompositionError(TRANSITION_INVALID, "one transition per scene is required")
    if any(type(t) is not int or t < 0 for t in overlaps) or overlaps[0] != 0:
        raise CompositionError(TRANSITION_INVALID, "transitions are integers >= 0 and the first scene has none")
    for k, length in enumerate(lengths):
        following = overlaps[k + 1] if k + 1 < len(overlaps) else 0
        if overlaps[k] + following >= length:
            raise CompositionError(TRANSITION_INVALID, f"{manifests[k].scene_id}: transitions leave no frame of its own",
                                   scene_id=manifests[k].scene_id)
    spans: list[SceneSpan] = []
    for k, (m, length) in enumerate(zip(manifests, lengths)):
        start = 0 if k == 0 else spans[-1].end - overlaps[k]
        spans.append(SceneSpan(k, m.scene_id, m.composition_id, m.fps, m.duration_in_frames, start, length, overlaps[k]))
    return CompositionMap(master, tuple(spans), spans[-1].end)


# ------------------------------------------------------------------ transport (valeur pure)


class Seek(str, Enum):
    NEXT = "next"
    PREVIOUS = "previous"
    #: Clic sur une vignette : début de la scène `value`.
    SCENE = "scene"
    #: Glissière : exactement l'image `value`.
    SCRUB = "scrub"
    HOME = "home"
    END = "end"
    #: `,` / `.` en pause : `value` = -1 ou +1.
    STEP = "step"
    #: « Rejouer » : image 0, lecture.
    REPLAY = "replay"


@dataclass(frozen=True, slots=True)
class Transport:
    """L'horloge de média : l'image `f`, lecture ou pause, fin atteinte. Rien d'autre (ni partition, ni minuterie)."""

    frame: int = 0
    playing: bool = False
    ended: bool = False


def _settle(cmap: CompositionMap, state: Transport) -> Transport:
    """Lire sur la dernière image = la fin : la dernière image est tenue, en pause, `ended`. Jamais de bouclage."""

    if state.playing and state.frame == cmap.last_frame:
        return Transport(cmap.last_frame, False, True)
    return state


def play(cmap: CompositionMap, state: Transport) -> Transport:
    """Lecture depuis `f`. À la fin, rien (« Rejouer » est un geste explicite : `Seek.REPLAY`)."""

    cmap._frame(state.frame)
    return state if state.ended else _settle(cmap, replace(state, playing=True))


def pause(cmap: CompositionMap, state: Transport) -> Transport:
    """Tient exactement `f`."""

    cmap._frame(state.frame)
    return replace(state, playing=False)


def seek(cmap: CompositionMap, state: Transport, kind: Seek, value: int | None = None) -> Transport:
    """Une commande de navigation : l'état de lecture est gardé (sauf `REPLAY`), `ended` est levé par tout déplacement."""

    f = cmap._frame(state.frame)
    if kind is Seek.NEXT:
        target = cmap.next_start(f)
        if target is None:
            return state   # last scene: next is disabled, nothing moves
    elif kind is Seek.PREVIOUS:
        target = cmap.previous_start(f)
    elif kind is Seek.SCENE:
        target = cmap.start_of(value)  # type: ignore[arg-type] - validated by start_of
    elif kind is Seek.SCRUB:
        target = cmap._frame(value)
    elif kind is Seek.HOME:
        target = 0
    elif kind is Seek.END:
        target = cmap.last_frame
    elif kind is Seek.STEP:
        if type(value) is not int or value not in (-1, 1):
            raise CompositionError(FRAME_OUT_OF_RANGE, "a step is -1 or +1")
        if state.playing:
            return state   # frame steps act while paused only (§ 4.15)
        target = cmap.clamp(f + value)
    elif kind is Seek.REPLAY:
        return _settle(cmap, Transport(0, True, False))
    else:  # pragma: no cover - closed enum
        raise CompositionError(FRAME_OUT_OF_RANGE, f"unknown seek {kind!r}")
    return _settle(cmap, Transport(target, state.playing, False))


def tick(cmap: CompositionMap, state: Transport, scene_index: int, native_frame: int, *, scene_ended: bool = False) -> Transport:
    """Le conseil de l'horloge du lecteur de la scène `scene_index` -> `f`. Seul le lecteur de la scène **courante** (celle qui
    contient `f` ; pendant un recouvrement, l'entrante) est écouté : le tic d'un autre lecteur (le sortant d'un recouvrement, un
    lecteur périmé après une navigation) ne change rien. `scene_ended` : ce lecteur a atteint sa dernière image ; la scène suivante
    commence alors à son image locale 0, jamais en arrière de `f` ; la dernière scène tient sa dernière image (`ended`). Une pause
    reste une pause : un tic ne relance jamais la lecture."""

    frame = cmap.frame_of(scene_index, native_frame)   # validated first: a malformed tick is an error, not a no-op
    if scene_index != cmap.locate(state.frame).scene_index:
        return state
    if scene_ended:
        if scene_index + 1 < len(cmap.scenes):
            return Transport(max(state.frame, cmap.scenes[scene_index + 1].start), state.playing, False)
        return Transport(cmap.last_frame, False, True)
    return Transport(frame, state.playing, False)


# ------------------------------------------------------------------ clé et format servi


def composition_key(presentation_id: str, variant_id: str, pins: Sequence[tuple[str, str, int]]) -> str:
    """Clé d'une carte : Presentation, variante et pins ordonnés `(scene_id, prefab_id, version)`. Une version de prefab est immuable,
    donc la composition d'un pin aussi : même clé = même carte ; une autre variante ou un autre pin donne une autre clé."""

    canonical = json.dumps([presentation_id, variant_id, [list(p) for p in pins]], separators=(",", ":"), ensure_ascii=True)
    return "cmp_" + hashlib.sha256(canonical.encode("ascii")).hexdigest()[:24]


def to_wire(cmap: CompositionMap, *, key: str) -> dict[str, Any]:
    """Ce que le navigateur reçoit (données seulement ; il refait le calcul et refuse un écart : `fromWire`)."""

    return {"version": WIRE_VERSION, "key": key, "fps": cmap.fps, "total_frames": cmap.total_frames,
            "scenes": [{"scene_id": s.scene_id, "composition_id": s.composition_id, "fps": s.fps,
                        "duration_in_frames": s.duration_in_frames, "start": s.start, "length": s.length,
                        "transition_in": s.transition_in} for s in cmap.scenes]}
