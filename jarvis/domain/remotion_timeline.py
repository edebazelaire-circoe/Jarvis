"""Ligne de temps d'une scène Remotion pour la partition (handoff jarvis-remotion-presentation-integration, Slice 12 ;
`docs/presentation-studio.md` > *Remotion timeline bridge*, `docs/remotion-isolation.md` § 11).

C'est un **adaptateur pur**, sans E/S ni horloge : la partition (`Score`, `ScoreItem`, `LockedSequence`), la table de lecture
(`presentation_studio_playback`) et l'horloge des séquences restent les seuls maîtres. Ici, trois choses seulement :

1. `build_frame_map` : où tombe chaque ancre d'une scène (`ScoreAnchor`) dans la composition Remotion, en **images** (cadence,
   durée et identifiant de composition viennent du manifeste de la source, jamais du code de la scène). Déterministe et borné :
   `at_ms` posé -> image arrondie puis bornée à `0..durée-1` ; sinon l'ancre `i` sur `n` tombe à l'image `i * durée // n`.
2. `segment_for` / `target_segment` : la ligne de temps est découpée par les ancres en segments `[de, jusqu'à]`. Révéler une ancre
   = jouer son segment (aller à `de`, jouer, **s'arrêter sur `jusqu'à`** = l'image avant l'ancre suivante) ; rien de révélé = le
   segment d'entrée (de 0 à l'image avant la première ancre). Le repère de lecture est l'ancre révélée la plus loin ; **masquer**
   les ancres suivantes ramène en arrière (réversible, comme tout le dépliement de la partition).
3. `SegmentClock` : le temps **joué** (pauses exclues) du segment courant selon l'horloge de Core, et un compteur `seq` qui
   n'avance que lorsque le segment change (le navigateur distingue ainsi « aller au segment » de « reprendre »).

Rien ici ne parle, n'appelle un outil ni ne déclenche une cue : le résultat est une **description** (`timeline` de la vue de
lecture) que le navigateur applique au lecteur Remotion. Le lecteur ne renvoie jamais rien à Core.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: Bornes de la composition (celles du manifeste de source, `remotion_source`).
MAX_FPS = 120
MAX_DURATION_FRAMES = 108_000
#: Écart toléré entre le lecteur et l'horloge de Core avant que le navigateur corrige (en ms ; envoyé avec la ligne de temps).
DRIFT_TOLERANCE_MS = 500
#: Codes de constat (affichés par la bande de lecture, jamais une phrase libre).
ANCHOR_CLAMPED = "timeline_anchor_clamped"
ANCHORS_SHARE_FRAME = "timeline_anchors_share_frame"
ANCHORS_PARTLY_TIMED = "timeline_anchors_partly_timed"
UNRESOLVED = "timeline_unresolved"


class TimelineError(ValueError):
    """La composition déclarée n'est pas une composition Remotion valide (le manifeste l'a déjà refusée : défense en profondeur)."""


@dataclass(frozen=True, slots=True)
class Mark:
    anchor_id: str
    frame: int
    #: `at_ms` dépassait la durée : l'image a été ramenée à la dernière.
    clamped: bool = False


@dataclass(frozen=True, slots=True)
class FrameMap:
    scene_id: str
    composition_id: str
    fps: int
    duration_frames: int
    #: Dans l'ordre d'écriture des ancres de la scène.
    marks: tuple[Mark, ...]
    #: Codes de constat (ci-dessus), triés, sans doublon.
    problems: tuple[str, ...] = ()

    def mark(self, anchor_id: str) -> Mark | None:
        return next((m for m in self.marks if m.anchor_id == anchor_id), None)

    def frame_of(self, anchor_id: str) -> int | None:
        found = self.mark(anchor_id)
        return None if found is None else found.frame


@dataclass(frozen=True, slots=True)
class Segment:
    """Un tronçon à jouer : de l'image `start` à l'image `until` (comprise). `until == start` : tenir cette image."""

    anchor_id: str | None
    start: int
    until: int


def frame_of_ms(ms: int, fps: int, duration_frames: int) -> int:
    """Image d'un instant : arrondi à l'image la plus proche (demi vers le haut), borné à `0..durée-1`. Entiers seulement."""

    return max(0, min(duration_frames - 1, (ms * fps + 500) // 1000))


def build_frame_map(scene_id: str, composition: Mapping[str, Any], anchors: Sequence[Any]) -> FrameMap | None:
    """`composition` : `{id, fps, duration_in_frames}` du manifeste (ou `{id, fps, durationInFrames}` du descripteur).
    `anchors` : les `ScoreAnchor` de la scène (`anchor_id`, `at_ms`). `None` si la scène n'a aucune ancre : rien ne la pilote,
    elle se joue comme avant (Slice 10)."""

    if not anchors:
        return None
    comp_id = composition.get("id")
    fps = composition.get("fps")
    duration = composition.get("duration_in_frames", composition.get("durationInFrames"))
    if not isinstance(comp_id, str) or not comp_id:
        raise TimelineError("the composition has no id")
    if type(fps) is not int or not 1 <= fps <= MAX_FPS:
        raise TimelineError(f"the composition fps must be an integer 1..{MAX_FPS}")
    if type(duration) is not int or not 1 <= duration <= MAX_DURATION_FRAMES:
        raise TimelineError(f"the composition duration must be an integer 1..{MAX_DURATION_FRAMES} frames")
    count = len(anchors)
    marks: list[Mark] = []
    problems: set[str] = set()
    for index, anchor in enumerate(anchors):
        at_ms = getattr(anchor, "at_ms", None)
        if at_ms is None:
            marks.append(Mark(anchor.anchor_id, index * duration // count))
            continue
        raw = (at_ms * fps + 500) // 1000
        clamped = raw > duration - 1
        if clamped:
            problems.add(ANCHOR_CLAMPED)
        marks.append(Mark(anchor.anchor_id, frame_of_ms(at_ms, fps, duration), clamped))
    if len({getattr(a, "at_ms", None) is None for a in anchors}) > 1:
        problems.add(ANCHORS_PARTLY_TIMED)
    if len({m.frame for m in marks}) < len(marks):
        problems.add(ANCHORS_SHARE_FRAME)
    return FrameMap(scene_id, comp_id, fps, duration, tuple(marks), tuple(sorted(problems)))


def _ordered(fmap: FrameMap) -> list[tuple[int, int, Mark]]:
    return sorted(((m.frame, i, m) for i, m in enumerate(fmap.marks)), key=lambda t: (t[0], t[1]))


def segment_for(fmap: FrameMap, anchor_id: str | None) -> Segment:
    """Le segment d'une ancre (`None` : l'entrée, avant toute ancre). Inconnue : `KeyError` (l'appelant ne passe que des ancres
    de la scène)."""

    ordered = _ordered(fmap)
    last = fmap.duration_frames - 1
    if anchor_id is None:
        first = ordered[0][0]
        return Segment(None, 0, max(0, first - 1))
    start = fmap.frame_of(anchor_id)
    if start is None:
        raise KeyError(anchor_id)
    following = next((frame for frame, _i, _m in ordered if frame > start), None)
    return Segment(anchor_id, start, last if following is None else max(start, following - 1))


def target_segment(fmap: FrameMap, revealed: Collection[str]) -> Segment:
    """Le segment que la partition demande : celui de l'ancre révélée la plus loin dans la ligne de temps (égalité : la dernière
    écrite) ; aucune ancre de cette scène révélée : le segment d'entrée. Les ancres inconnues sont ignorées (jamais une erreur :
    la partition a pu changer sous la lecture)."""

    best: tuple[int, int, str] | None = None
    for index, mark in enumerate(fmap.marks):
        if mark.anchor_id in revealed and (best is None or (mark.frame, index) > best[:2]):
            best = (mark.frame, index, mark.anchor_id)
    return segment_for(fmap, None if best is None else best[2])


def timeline_wire(fmap: FrameMap, segment: Segment, *, playing: bool, seq: int, play_ms: int) -> dict[str, Any]:
    """La ligne de temps de la vue de lecture. Entiers, booléen et identifiants seulement ; une vingtaine d'octets par champ."""

    return {"scene_id": fmap.scene_id, "composition_id": fmap.composition_id, "fps": fmap.fps,
            "duration_frames": fmap.duration_frames, "anchor_id": segment.anchor_id, "from_frame": segment.start,
            "until_frame": segment.until, "playing": bool(playing and segment.until > segment.start), "seq": seq,
            "play_ms": play_ms, "tolerance_ms": DRIFT_TOLERANCE_MS, "problems": list(fmap.problems)}


class SegmentClock:
    """Temps joué du segment courant, selon l'horloge de Core (`now_ms` est fourni : aucune horloge ici). `observe` est idempotent
    pour un même état ; il se rappelle à chaque transition (pause, reprise) et à chaque lecture de la vue."""

    __slots__ = ("_key", "_seq", "_acc", "_since")

    def __init__(self) -> None:
        self._key: object = None
        self._seq = 0
        self._acc = 0
        self._since: int | None = None

    def reset(self) -> None:
        self._key, self._acc, self._since = None, 0, None

    def observe(self, key: object, playing: bool, now_ms: int, cap_ms: int) -> tuple[int, int]:
        """`(seq, play_ms)`. `key` identifie le segment (scène, ancre, images) : un autre `key` ouvre un nouveau segment."""

        if key != self._key:
            self._key, self._seq, self._acc = key, self._seq + 1, 0
            self._since = now_ms if playing else None
        elif playing and self._since is None:
            self._since = now_ms
        elif not playing and self._since is not None:
            self._acc += max(0, now_ms - self._since)
            self._since = None
        live = self._acc + (max(0, now_ms - self._since) if self._since is not None else 0)
        return self._seq, max(0, min(cap_ms, live))
