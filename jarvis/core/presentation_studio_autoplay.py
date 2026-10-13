"""Lecture enchaînée du Studio de présentation (handoff jarvis-remotion-presentation-integration, Slice 23 ; contrat :
`docs/presentation-studio.md` > *Chained playback (scope)*).

Une lecture avance d'habitude au geste du présentateur (`next`) ou à une cue. Avec une **portée** (`Scope`), elle avance toute seule :

- `scene` : joue la scène courante d'un bout à l'autre (tous ses éléments, un segment après l'autre) puis **tient sa dernière image** ;
- `all`   : de scène en scène jusqu'au dernier élément, qui tient alors sa dernière image ;
- `manual` : jamais (défaut).

La portée est un état du **service** (mémoire, comme la ligne de temps), pas de la machine d'états : la machine ne change pas, l'avance
est un `next` ordinaire passé par la même porte (`_dispatch`), donc soumis à ses refus (séquence verrouillée, interruption refusée).

**Qui dit « le segment est fini ».** Le navigateur, seul : son suiveur voit le lecteur Remotion s'arrêter PILE sur l'image d'arrêt après
l'avoir vu bouger, et la page le rend à Core (`advance {seq, event: done}`). Un `done` est cru pour le segment où Core se trouve (`seq`)
dès que la page a dit `started` pour ce segment ; un rapport d'un autre segment, ou sans `started`, est ignoré.

**Aucune échéance ne déplace une scène Remotion** (handoff jarvis-remotion-native-studio-playback-fix, Slice 05 ; contrat
`docs/presentation-studio.md` > *Presentation experience contract* § 3 et *Composition clock (Level 3)*). Avant, chaque segment portait
une échéance de Core (durée restante + 3 s de marge + 45 s de chargement), après laquelle Core avançait seul : une scène qui chargeait
lentement, ou dont le cadre avait été perdu, était SAUTÉE (Slice 03, défaut A). Désormais :
- un segment de média (scène Remotion) n'a pas d'échéance : il avance quand son Player a fini (`done`). Page fermée, scène qui ne charge
  pas ou qui ne compile pas : la lecture RESTE sur la scène, et la page dit pourquoi (échec typé de la scène, nommée) ; jamais un saut ;
- une scène Remotion dont la ligne de temps n'est pas (encore) résolue est tenue de même, jamais avancée au jugé ;
- seul un élément SANS segment de média à jouer (scène HTML, élément qui ne change pas le segment, segment d'une image) garde un rythme :
  `max(durée visée, MIN_DWELL_MS)` ou, à défaut, `DEFAULT_DWELL_MS`. La pause l'arrête ; il est réarmé à la reprise.
Le chemin du présentateur (portée `manual`, Slice 07) n'a jamais eu d'échéance : inchangé. Dans une course que Jarvis rythme (Slice 07), la
page dit aussi `started` / `done` (`_page_reports`) : Core l'apprend sans avancer (`media_segment`), et le silence explicite du présentateur
dure le média au lieu de sa cible (`target_duration_ms` ne coupe jamais une composition).

**Une attente se voit** (Slice 05 rework, P1). Un `done` perdu, un `started` jamais dit (un `done` sans lui est ignoré) ou une page fermée
tiennent la lecture sans que rien ne bouge. Quand un segment de média reste sans nouvelle de la page au-delà de sa propre durée + une
marge (temps JOUÉ, pauses exclues ; plus une marge de chargement tant que `started` n'est pas venu), la vue le dit (`page_wait`) et la
bande l'affiche. C'est un constat, jamais une avance : la lecture reste sur la scène, `next` et `stop` marchent comme toujours.

Un mixin, comme `presentation_studio_preview` : même verrou, même scène, même état ; dans son propre fichier pour que le service reste
une seule responsabilité.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from jarvis.core.presentation_studio_presenter import SILENCE_DEFAULT_MS
from jarvis.domain.presentation_studio_playback import EventKind, Phase, stage_scene_id
from jarvis.domain.presentation_studio_playback_requests import Scope
from jarvis.domain.presentation_studio_score import ItemKind

#: Un élément SANS segment de média reste au moins ceci, et par défaut ceci quand la partition ne vise aucune durée. Jamais une scène Remotion.
MIN_DWELL_MS = 1500
DEFAULT_DWELL_MS = 4000
#: Un segment de média sans nouvelle de la page au-delà de sa durée + ceci (+ `PAGE_SILENCE_BEFORE_START_MS` avant `started`) est dit, jamais avancé.
PAGE_SILENCE_MARGIN_MS = 15_000
PAGE_SILENCE_BEFORE_START_MS = 60_000


@dataclass(frozen=True, slots=True)
class AutoTimings:
    min_dwell_ms: int = MIN_DWELL_MS
    default_dwell_ms: int = DEFAULT_DWELL_MS


class AutoPlayMixin:
    """Methods of `PresentationStudioPlaybackService`. Expects `_lock`, `_state`, `_plan`, `_tasks`, `_dispatch`, `_timeline_view`,
    `_tl_clock`, `_ms`, `_shows_video`, `_stage_video`, `_tl_failed`, `_wake` and `_trace` from the service."""

    def _init_autoplay(self, timings: AutoTimings | None) -> None:
        self._timings = timings or AutoTimings()
        self._scope: Scope = Scope.MANUAL
        self._auto_handle: asyncio.TimerHandle | None = None
        self._auto_key: tuple[Any, ...] | None = None
        #: `seq` of the segment the chained play has just finished: an element that does not change the segment does not wait for it again.
        self._auto_done_seq: int | None = None
        #: `seq` of the segment the browser said it began (its scene had loaded and the Player was ordered).
        self._auto_started_seq: int | None = None
        #: `seq` of the segment whose silent page has already been traced (once per segment).
        self._page_wait_seq: int | None = None
        #: `(run_id, position, epoch)` of the item whose unresolved-timeline hold has already been traced (Slice 07 rework, I1).
        self._timeline_wait_key: tuple[Any, ...] | None = None

    # ------------------------------------------------------------------ scope

    @property
    def scope(self) -> Scope:
        return self._scope

    def _set_scope(self, scope: Scope, why: str) -> None:
        if scope is self._scope:
            return
        self._trace("autoplay_scope", "Portee de la lecture enchainee changee", data={
            "from": self._scope.value, "to": scope.value, "why": why, "run_id": self._state.run_id})
        self._scope = scope
        self._auto_done_seq = self._auto_started_seq = None
        if scope is Scope.MANUAL:
            self._cancel_auto()
        self._wake()

    # ------------------------------------------------------------------ timer

    def _cancel_auto(self) -> None:
        if self._auto_handle is not None:
            self._auto_handle.cancel()
        self._auto_handle, self._auto_key = None, None

    def _auto_eligible(self) -> bool:
        state = self._state
        return (self._scope is not Scope.MANUAL and self._plan is not None and state.phase is Phase.PLAYING
                and state.sequence is None and not state.aux and not state.jarvis_speaks and state.pending is None)

    def _page_reports(self) -> bool:
        """Does the page say when a media segment started and ended (`timeline.auto`)? In a chained play, and (Slice 07) in a run Jarvis
        paces: his silence items wait for the media instead of their soft target. A scene without anchors then gets one whole segment."""

        return self._scope is not Scope.MANUAL or self._state.jarvis_speaks

    def _waits_for_media(self) -> bool:
        """Slice 07: the Jarvis presenter holds the current item on its media segment (an explicit silence of a run he paces, playing)."""

        state, plan = self._state, self._plan
        return (state.jarvis_speaks and plan is not None and state.phase is Phase.PLAYING and state.sequence is None and not state.aux
                and state.pending is None and 0 <= state.position < len(plan) and plan.item_at(state.position).kind is ItemKind.SILENCE)

    def media_segment(self) -> str | None:
        """Slice 07, for the Jarvis presenter: `None` when the scene on the stage has no media segment to play (an HTML scene, a hold,
        no Remotion source: a soft pace may apply); `"playing"` while its Player has not said it reached the stop frame (a Remotion scene
        whose timeline is not resolved is held the same way, never paced); `"done"` once the page said so for this segment;
        `"pending"` while the kind of the scene now on the stage is not known yet (its stage sync is under way and wakes the presenter
        when it lands: Slice 07 rework, B1). Always answered for the CURRENT item, never from the scene before it."""

        if self._plan is None or not self._state.active:
            return None
        timeline = self._timeline_view()
        if timeline is None:
            video = self._stage_video()
            return "pending" if video is None else "playing" if video else None
        if timeline["until_frame"] <= timeline["from_frame"]:
            return None
        return "done" if timeline["seq"] == self._auto_done_seq else "playing"

    def _auto_plan(self) -> tuple[tuple[Any, ...], int] | None:
        """`(identité de ce qui joue, délai en ms avant que Core avance seul)`, ou `None` quand rien n'avance seul."""

        if not self._auto_eligible():
            return None
        state, plan, timings = self._state, self._plan, self._timings
        item = plan.item_at(state.position)
        base = (state.run_id, state.position, state.epoch)
        timeline = self._timeline_view()
        if timeline is not None and timeline["until_frame"] > timeline["from_frame"] and timeline["seq"] != self._auto_done_seq:
            return None   # a media segment: only its Player's end (`done`) moves on, never a deadline (Slice 05)
        if timeline is None and self._shows_video():
            return None   # a Remotion scene without a resolved timeline is held, never skipped on a guess
        dwell = max(timings.min_dwell_ms, item.target_duration_ms or timings.default_dwell_ms)
        return (*base, "dwell"), dwell

    def _rearm_auto(self) -> None:
        """Called after every state change and every stage sync (synchronous, never awaits): re-reads what is playing and re-arms the
        one deadline. The previous one is always dropped."""

        self._cancel_auto()
        planned = self._auto_plan()
        if planned is None:
            return
        key, delay_ms = planned
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # no running loop (a pure unit test of the state): nothing can fire
            return
        self._auto_key = key
        self._auto_handle = loop.call_later(max(0, delay_ms) / 1000, self._on_auto_deadline, key)

    def _on_auto_deadline(self, key: tuple[Any, ...]) -> None:
        if key != self._auto_key:
            return
        self._auto_handle = None
        task = asyncio.get_running_loop().create_task(self._auto_deadline(key))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _auto_deadline(self, key: tuple[Any, ...]) -> None:
        async with self._lock:
            if key != self._auto_key or not self._auto_eligible():
                return
            self._trace("autoplay_deadline", "Rythme d'un element sans media echu : Core avance", data={
                "run_id": self._state.run_id, "position": self._state.position + 1})
            try:
                await self._guarded("autoplay", self._auto_advance("deadline"))
            except Exception:  # noqa: BLE001 - `_guarded` ended the run cleanly and traced the real cause; a timer task has nobody to raise to
                return

    def _page_wait(self) -> dict[str, Any] | None:
        """`{seq, started, waited_ms}` when the media segment of a chained play has had its own length + a margin (played time) without its
        page saying it finished; `None` otherwise. A description for the view, never an advance (Slice 05 rework, P1)."""

        if not (self._auto_eligible() or self._waits_for_media()):
            return None
        timeline = self._timeline_view()
        if timeline is None:
            return self._timeline_wait()
        if timeline["until_frame"] <= timeline["from_frame"] or timeline["seq"] == self._auto_done_seq:
            return None
        seq = timeline["seq"]
        started = self._auto_started_seq == seq
        segment_ms = -(-(timeline["until_frame"] - timeline["from_frame"] + 1) * 1000 // timeline["fps"])
        limit = segment_ms + PAGE_SILENCE_MARGIN_MS + (0 if started else PAGE_SILENCE_BEFORE_START_MS)
        waited = self._tl_clock.played(self._ms())
        if waited < limit:
            return None
        if self._page_wait_seq != seq:
            self._page_wait_seq = seq
            self._trace("autoplay_page_silent", "Segment de media sans nouvelle de la page : la lecture reste sur la scene", level="warning",
                        data={"run_id": self._state.run_id, "seq": seq, "started": started, "waited_ms": waited})
        return {"seq": seq, "started": started, "waited_ms": waited}

    def _timeline_wait(self) -> dict[str, Any] | None:
        """Slice 07 rework (I1): a Jarvis silence held on a Remotion scene whose timeline could not be resolved. The contract holds (the
        motion is never cut, `target_duration_ms` never paces it) but never silently: once the item's soft target + `PAGE_SILENCE_MARGIN_MS`
        has passed (pauses excluded), the view says it (`page_wait` with `reason: timeline_unresolved`) and the band says the scene is held
        and that « Suivant » / « Arrêter » work. Traced once per item entry."""

        state, plan = self._state, self._plan
        if not self._waits_for_media() or self._tl_failed is None or self._tl_failed != stage_scene_id(plan, state):
            return None
        item = plan.item_at(state.position)
        target = item.target_duration_ms if item.target_duration_ms is not None else SILENCE_DEFAULT_MS
        held = max(0, self._ms() - state.item_started_ms - state.item_paused_ms)
        if held < target + PAGE_SILENCE_MARGIN_MS:
            return None
        key = (state.run_id, state.position, state.epoch)
        if self._timeline_wait_key != key:
            self._timeline_wait_key = key
            self._trace("timeline_unresolved_held", "Silence tenu sur une scene Remotion sans ligne de temps : dit, jamais coupe",
                        level="warning", data={"run_id": state.run_id, "position": state.position + 1, "held_ms": held})
        return {"seq": None, "started": False, "waited_ms": held, "reason": "timeline_unresolved"}

    # ------------------------------------------------------------------ advance

    async def _auto_advance(self, why: str) -> Any:
        """One step of the chained play, under the lock: finish the scope on the last element it covers, otherwise `next`."""

        state, plan = self._state, self._plan
        timeline = self._timeline_view()
        if timeline is not None:
            self._auto_done_seq = timeline["seq"]
        here = plan.item_at(state.position).scene_id
        following = state.position + 1
        if following >= len(plan) or (self._scope is Scope.SCENE and plan.item_at(following).scene_id != here):
            self._trace("autoplay_finished", "Lecture enchainee terminee : la derniere image est tenue", data={
                "run_id": state.run_id, "scope": self._scope.value, "why": why})
            self._set_scope(Scope.MANUAL, "finished")
            return None
        result = await self._dispatch("next", EventKind.NEXT)
        if getattr(result.status, "value", result.status) == "refused":
            self._set_scope(Scope.MANUAL, "refused")
        return result

