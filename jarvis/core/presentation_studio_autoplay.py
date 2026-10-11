"""Lecture enchaînée du Studio de présentation (handoff jarvis-remotion-presentation-integration, Slice 23 ; contrat :
`docs/presentation-studio.md` > *Chained playback (scope)*).

Une lecture avance d'habitude au geste du présentateur (`next`) ou à une cue. Avec une **portée** (`Scope`), elle avance toute seule :

- `scene` : joue la scène courante d'un bout à l'autre (tous ses éléments, un segment après l'autre) puis **tient sa dernière image** ;
- `all`   : de scène en scène jusqu'au dernier élément, qui tient alors sa dernière image ;
- `manual` : jamais (défaut).

La portée est un état du **service** (mémoire, comme la ligne de temps), pas de la machine d'états : la machine ne change pas, l'avance
est un `next` ordinaire passé par la même porte (`_dispatch`), donc soumis à ses refus (séquence verrouillée, interruption refusée).

**Qui dit « le segment est fini ».** Le navigateur : son suiveur voit le lecteur Remotion s'arrêter PILE sur l'image d'arrêt après l'avoir
vu bouger, et la page le rend à Core (`advance {seq, event: done}`). Core n'en dépend pas pour rester vivant : chaque élément porte une
**échéance** (durée restante du segment selon l'horloge de Core + une marge ; plus un délai de chargement tant que le navigateur n'a
pas dit `started`), après laquelle Core avance seul (page fermée, scène qui ne charge pas). Un élément sans segment à jouer (scène HTML,
élément qui ne change pas le segment) reste `max(durée visée, minimum)` ou, à défaut, `DEFAULT_DWELL_MS`. La pause arrête tout : l'échéance
est recalculée à la reprise sur le TEMPS JOUÉ (pauses exclues). Un rapport d'un autre segment (`seq` périmé), ou venu trop tôt pour avoir
pu être vrai, est ignoré.

**À retirer pour la vidéo (handoff jarvis-remotion-native-studio-playback-fix, Slices 05 et 07).** La vidéo continue (« Lire ») n'a
plus d'échéance ni de portée : l'horloge de composition du lecteur de Variantes (`jarvis/domain/composition_clock.py`) est la seule
autorité de `f`, et Core n'en tient aucune copie. Les portées `scene`/`all`, leurs échéances (`GRACE_MS`, `LOAD_ALLOWANCE_MS`) et le
pas `DEFAULT_DWELL_MS` ne doivent plus jamais avancer une scène Remotion ; il ne reste, pour une lecture de présentateur, que le rythme
d'un élément SANS segment de média (scène HTML, silence). Contrat : `docs/presentation-studio.md` > *Composition clock (Level 3)*.

Un mixin, comme `presentation_studio_preview` : même verrou, même scène, même état ; dans son propre fichier pour que le service reste
une seule responsabilité.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from jarvis.domain.presentation_studio_playback import EventKind, Phase
from jarvis.domain.presentation_studio_playback_requests import Scope

#: Un élément sans segment à jouer reste au moins ceci, et par défaut ceci quand la partition ne vise aucune durée.
MIN_DWELL_MS = 1500
DEFAULT_DWELL_MS = 4000
#: Marge ajoutée à la durée restante d'un segment avant que Core avance seul (le rapport du navigateur arrive bien avant).
GRACE_MS = 3000
#: Tant que le navigateur n'a pas dit `started` pour ce segment : le temps de charger la scène (compilation à froid comprise).
LOAD_ALLOWANCE_MS = 45000
#: Un `done` n'est cru que si le segment a été joué au moins cette part de sa durée (moins une marge) : un rapport périmé n'en saute pas un.
MIN_PLAYED_RATIO = 0.75
MIN_PLAYED_SLACK_MS = 300


@dataclass(frozen=True, slots=True)
class AutoTimings:
    min_dwell_ms: int = MIN_DWELL_MS
    default_dwell_ms: int = DEFAULT_DWELL_MS
    grace_ms: int = GRACE_MS
    load_allowance_ms: int = LOAD_ALLOWANCE_MS


class AutoPlayMixin:
    """Methods of `PresentationStudioPlaybackService`. Expects `_lock`, `_state`, `_plan`, `_tasks`, `_tl_clock`, `_dispatch`,
    `_timeline_view`, `_ms`, `_wake` and `_trace` from the service."""

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
            frames = timeline["until_frame"] - timeline["from_frame"] + 1
            cap_ms = -(-frames * 1000 // timeline["fps"])
            remaining = max(0, cap_ms - timeline["play_ms"])
            loading = 0 if self._auto_started_seq == timeline["seq"] else timings.load_allowance_ms
            return (*base, timeline["seq"]), remaining + timings.grace_ms + loading
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
            self._trace("autoplay_deadline", "Echeance de la lecture enchainee : Core avance seul", data={
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

    def _played_enough(self, timeline: dict[str, Any]) -> bool:
        frames = timeline["until_frame"] - timeline["from_frame"] + 1
        cap_ms = -(-frames * 1000 // timeline["fps"])
        return timeline["play_ms"] >= cap_ms * MIN_PLAYED_RATIO - MIN_PLAYED_SLACK_MS

