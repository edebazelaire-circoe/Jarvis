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
   `place` (handoff native-studio-playback-fix, Slice 07, contrat § 5) : le segment que le lecteur reçoit dans une lecture de
   présentateur. Une scène nouvellement entrée part de son image locale 0 jusqu'au `until` de l'élément (jamais de l'ancre) ; un retour ou
   un saut tient l'image d'arrêt de l'élément ; une reprise dans la même scène continue depuis l'image tenue.
3. `SegmentClock` : le temps **joué** (pauses exclues) du segment courant selon l'horloge de Core, et un compteur `seq` qui
   n'avance que lorsque le segment change (le navigateur distingue ainsi « aller au segment » de « reprendre »).

Horloge de composition (handoff jarvis-remotion-native-studio-playback-fix, Slice 04) : la position de la vidéo continue est l'image
de composition `f` de `composition_clock.py`, jamais `SegmentClock`. `SegmentClock` reste le temps joué d'un segment de PARTITION (lecture
de présentateur) ; la Slice 05 lui retire tout pouvoir d'avancer, couper ou recaler une scène vidéo (échéances de `presentation_studio_autoplay`,
recalage de dérive du suiveur), la Slice 07 le garde pour les seules ancres du présentateur.

Rien ici ne parle, n'appelle un outil ni ne déclenche une cue : le résultat est une **description** (`timeline` de la vue de
lecture) que le navigateur applique au lecteur Remotion. Le lecteur ne renvoie jamais rien à Core.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
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


def checked_composition(composition: Mapping[str, Any]) -> tuple[str, int, int]:
    """`(id, fps, duration_in_frames)` d'une composition déclarée, ou `TimelineError`. Seule validation des bornes d'une composition
    côté Core : la table d'ancres ci-dessous et l'horloge de composition (`composition_clock.py`) la partagent."""

    comp_id = composition.get("id")
    fps = composition.get("fps")
    duration = composition.get("duration_in_frames", composition.get("durationInFrames"))
    if not isinstance(comp_id, str) or not comp_id:
        raise TimelineError("the composition has no id")
    if type(fps) is not int or not 1 <= fps <= MAX_FPS:
        raise TimelineError(f"the composition fps must be an integer 1..{MAX_FPS}")
    if type(duration) is not int or not 1 <= duration <= MAX_DURATION_FRAMES:
        raise TimelineError(f"the composition duration must be an integer 1..{MAX_DURATION_FRAMES} frames")
    return comp_id, fps, duration


def build_frame_map(scene_id: str, composition: Mapping[str, Any], anchors: Sequence[Any], *, whole_scene: bool = False) -> FrameMap | None:
    """`composition` : `{id, fps, duration_in_frames}` du manifeste (ou `{id, fps, durationInFrames}` du descripteur).
    `anchors` : les `ScoreAnchor` de la scène (`anchor_id`, `at_ms`). `None` si la scène n'a aucune ancre : rien ne la pilote,
    elle se joue comme avant (Slice 10). `whole_scene` (lecture enchaînée, Slice 23) : une scène sans ancre a quand même une ligne de
    temps, d'un seul segment (de 0 à la dernière image) : elle se joue UNE fois et tient sa dernière image, au lieu de boucler, pour que
    l'enchaînement sache quand elle a fini."""

    if not anchors and not whole_scene:
        return None
    comp_id, fps, duration = checked_composition(composition)
    count = len(anchors)
    if not anchors:
        return FrameMap(scene_id, comp_id, fps, duration, ())
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
        if not ordered:
            return Segment(None, 0, last)   # a scene without anchor in a chained play: the whole composition, once
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


class Move(StrEnum):
    """Ce qui a amené la partition à son état (le service le nomme d'après la commande ; handoff native-studio-playback-fix, Slice 07)."""

    #: pause, reprise, détour, acquittement du cadre, changement d'orateur : la position n'a pas bougé
    NONE = "none"
    #: départ, `next`, une cue, un pas de séquence verrouillée, une révélation : la partition avance
    FORWARD = "forward"
    #: `previous`, `goto`, `hide`, un point de reprise : retour en arrière ou saut
    JUMP = "jump"
    #: une lecture enchaînée reprend la scène depuis son premier élément
    RESTART = "restart"
    #: un saut PENDANT une lecture enchaînée : le segment de l'élément visé se joue (une tenue y serait rythmée puis sautée, jamais vue)
    SEEK = "seek"


class Arrival(StrEnum):
    """Comment le lecteur arrive sur le segment de l'élément (`docs/presentation-studio.md` > *Presentation experience contract* § 5)."""

    #: scène nouvellement entrée : image locale 0, puis jusqu'au `until` de l'élément (l'entrée se joue, jamais prise en route)
    ENTER = "enter"
    #: même scène, la partition avance : le segment de l'élément, depuis son ancre
    PLAY = "play"
    #: retour ou saut : l'image d'arrêt de l'élément, tenue, sans rejouer les segments d'avant
    HOLD = "hold"


@dataclass(frozen=True, slots=True)
class Placement:
    """Où en est le lecteur d'une scène dans une lecture de présentateur : le segment que la partition vise (`target`, celui de l'ancre
    révélée la plus loin) et la façon d'y arriver (`arrival`). `segment` est ce que le navigateur reçoit."""

    scene_id: str
    target: Segment
    arrival: Arrival

    @property
    def segment(self) -> Segment:
        target = self.target
        if self.arrival is Arrival.ENTER:
            return Segment(target.anchor_id, 0, target.until)
        if self.arrival is Arrival.HOLD:
            return Segment(target.anchor_id, target.until, target.until)
        return target


def place(fmap: FrameMap, revealed: Collection[str], move: Move, previous: Placement | None, *, fresh: bool = False) -> Placement:
    """Slice 07 (§ 5) : le placement du lecteur pour l'état de la partition. Pur et idempotent (`move` NONE et le même état rendent le même
    placement). Les ancres bornent seulement l'arrêt (`until`) et la tenue, jamais le début d'une scène nouvellement entrée :

    - une scène nouvellement entrée (pas de placement précédent dans cette scène) part de son image locale 0 et joue jusqu'au `until` de
      l'élément, même quand l'élément d'entrée révèle une ancre à `at_ms > 0` (`ENTER`) ; entrée par un saut : tenue (`HOLD`) ;
    - même scène, même segment visé : le placement ne change pas (une reprise continue depuis l'image tenue, même `seq`) ;
    - même scène, la partition avance vers une ancre plus loin : son segment (`PLAY`) ; sauf si l'entrée n'a pas encore joué une image
      (`fresh` : le pas 0 d'une séquence verrouillée révèle une ancre à l'instant où la scène entre) : l'entrée part toujours de 0 et va
      jusqu'au nouveau `until` (`ENTER`), sinon l'animation d'entrée serait sautée ;
    - même scène, retour ou saut (ou une ancre plus tôt) : l'image d'arrêt de l'élément, tenue (`HOLD`) ;
    - `RESTART` (lecture enchaînée relancée) : la scène repart de 0 ;
    - `SEEK` (saut pendant une lecture enchaînée) : le segment de l'élément visé se joue, depuis son ancre (comportement de la Slice 05)."""

    target = target_segment(fmap, revealed)
    if move is Move.RESTART:
        return Placement(fmap.scene_id, target, Arrival.ENTER)
    if previous is None or previous.scene_id != fmap.scene_id:
        arrival = {Move.JUMP: Arrival.HOLD, Move.SEEK: Arrival.PLAY}.get(move, Arrival.ENTER)
        return Placement(fmap.scene_id, target, arrival)
    if target.anchor_id == previous.target.anchor_id or move is Move.NONE:
        return Placement(fmap.scene_id, target, previous.arrival)
    if move is Move.FORWARD and target.start > previous.target.start:
        return Placement(fmap.scene_id, target, Arrival.ENTER if fresh and previous.arrival is Arrival.ENTER else Arrival.PLAY)
    if move is Move.SEEK:
        return Placement(fmap.scene_id, target, Arrival.PLAY)
    return Placement(fmap.scene_id, target, Arrival.HOLD)


def timeline_wire(fmap: FrameMap, segment: Segment, *, playing: bool, seq: int, play_ms: int, prefab: str | None = None,
                  auto: bool = False) -> dict[str, Any]:
    """La ligne de temps de la vue de lecture. Entiers, booléen et identifiants seulement ; une vingtaine d'octets par champ.
    `prefab` (`id@version`) : la source que la scène montre, pour que le navigateur n'ordonne qu'au cadre de CETTE scène (Slice 23) ;
    `auto` : lecture enchaînée, le navigateur dit à Core quand le segment a vraiment fini."""

    wire = {"scene_id": fmap.scene_id, "composition_id": fmap.composition_id, "fps": fmap.fps,
            "duration_frames": fmap.duration_frames, "anchor_id": segment.anchor_id, "from_frame": segment.start,
            "until_frame": segment.until, "playing": bool(playing and segment.until > segment.start), "seq": seq,
            "play_ms": play_ms, "tolerance_ms": DRIFT_TOLERANCE_MS, "problems": list(fmap.problems), "auto": bool(auto)}
    if prefab:
        wire["prefab"] = prefab
    return wire


class SegmentClock:
    """Temps joué du segment courant, selon l'horloge de Core (`now_ms` est fourni : aucune horloge ici). `observe` est idempotent
    pour un même état ; il se rappelle à chaque transition (pause, reprise) et à chaque lecture de la vue."""

    __slots__ = ("_key", "_seq", "_acc", "_since")

    def __init__(self) -> None:
        self._key: object = None
        self._seq = 0
        self._acc = 0
        self._since: int | None = None

    @property
    def seq(self) -> int:
        """Le numéro du segment observé en dernier (0 avant le premier)."""

        return self._seq

    def reset(self) -> None:
        self._key, self._acc, self._since = None, 0, None

    def restart(self, now_ms: int, playing: bool) -> None:
        """Le navigateur dit que le segment COMMENCE (son cadre était à charger) : le temps joué repart de zéro à cet instant, sans changer
        `seq` (Slice 23)."""

        self._acc = 0
        self._since = now_ms if playing and self._key is not None else None

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
        return self._seq, max(0, min(cap_ms, self.played(now_ms)))

    def played(self, now_ms: int) -> int:
        """Le temps joué du segment observé, NON plafonné (pauses exclues) : combien de temps la page a eu pour le finir."""

        return self._acc + (max(0, now_ms - self._since) if self._since is not None else 0)
