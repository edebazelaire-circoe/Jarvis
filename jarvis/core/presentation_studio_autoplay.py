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
Le chemin du présentateur (portée `manual`, Slice 07) n'a jamais eu d'échéance : inchangé.

Un mixin, comme `presentation_studio_preview` : même verrou, même scène, même état ; dans son propre fichier pour que le service reste
une seule responsabilité.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from jarvis.domain.presentation_studio_playback import EventKind, Phase
from jarvis.domain.presentation_studio_playback_requests import Scope

#: Un élément SANS segment de média reste au moins ceci, et par défaut ceci quand la partition ne vise aucune durée. Jamais une scène Remotion.
MIN_DWELL_MS = 1500
DEFAULT_DWELL_MS = 4000


@dataclass(frozen=True, slots=True)
class AutoTimings:
    min_dwell_ms: int = MIN_DWELL_MS
    default_dwell_ms: int = DEFAULT_DWELL_MS


class AutoPlayMixin:
    """Methods of `PresentationStudioPlaybackService`. Expects `_lock`, `_state`, `_plan`, `_tasks`, `_dispatch`, `_timeline_view`,
    `_shows_video`, `_wake` and `_trace` from the service."""

    def _init_autoplay(self, timings: AutoTimings | None) -> None:
        self._timings = timings or AutoTimings()
        self._scope: Scope = Scope.MANUAL
        self._auto_handle: asyncio.TimerHandle | None = None
        self._auto_key: tuple[Any, ...] | None = None
        #: `seq` of the segment the chained play has just finished: an element that does not change the segment does not wait for it again.
        self._auto_done_seq: int | None = None
        #: `seq` of the segment the browser said it began (its scene had loaded and the Player was ordered).
        self._auto_started_seq: int | None = None

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

