"""Voice : le suiveur de cues du Studio (handoff jarvis-interactive-presentation-studio, Slice 13, R5).

Quand l'utilisateur présente, JARVIS entend la salle par la lane ambiante (`AmbientIngestionLane`) et peut, **à ces
seuls moments**, avancer sa présentation : une cue de la partition, déjà armée par Core, est satisfaite quand le
présentateur dit sa phrase. Ce module est le pont :

    énonciation ambiante -> (préemption par l'adresse explicite) -> `CueMatcher` pur -> `cue_satisfied` typé -> Core

## Ce qu'il ne fait jamais (structurel, testé par AST et par fermeture d'imports)

Il ne construit ni `BrainTurnInput`, ni appel d'outil, ni intention d'UI, ni requête d'`ActionBroker`. Sa seule sortie
vers Core est `presentation_studio_report_cue(run_id, generation, cue_id)` : trois valeurs, aucun texte. L'action liée
est résolue par Core depuis la partition stockée. Il ne lit ni ne crée de fenêtre d'adresse, ne change aucun mode.

## Vie privée

Le texte d'une énonciation n'existe ici que dans l'appel synchrone `on_utterance` : lu, apparié, oublié. Ni champ, ni
file, ni journal, ni trace. Le journal ne reçoit que des **comptes**, un `cue_id`, la règle et deux positions. Une
exception du gestionnaire est avalée ici (classe seule dans le journal) : la lane écrirait son *message*, qui pourrait
citer du texte.

## Quand il s'arrête de suivre

| Cause | Effet |
| --- | --- |
| séance PRESENTATION terminée / `stop()` | tâches annulées, consommateur débranché, rapport en vol abandonné |
| mode autre que PRESENTATION (`mode_ok`) | aucune énonciation n'est appariée |
| run terminé, pause, détour, autre rôle | Core remet un ensemble vide : rien n'est apparié |
| ensemble armé vide | rien n'est apparié (`unarmed` / `idle`) |
| autorité expirée (aucun tirage réussi depuis `expires_in_s`, 90 s) | ensemble oublié (`lapsed`), un nouveau tirage est tenté |
| **adresse explicite** : fenêtre vivante, vocatif (« Jarvis, ... »), tour adressé en cours ou fini depuis moins de `hold_s` | pause immédiate, l'énonciation est ignorée, le rapport non encore parti est abandonné |
| sondes d'adresse illisibles | tenu pour « adressé » (le côté sûr : l'automatisation se tait) et dit |

## Panne : visible, jamais une boucle muette

Core injoignable ou réponse illisible : attente exponentielle (1 s à 30 s), état `backoff` lisible (`status()`),
**une** ligne d'avertissement par panne et une ligne à la reprise. Une limite de débit (`rate_limited`) ou un rapport
refusé pour génération périmée ne se rejoue pas à l'aveugle : la cue redevient tirable, l'ensemble est retiré.
Côté Core, l'absence de tirage se lit `follower: absent` dans l'état de lecture (le bandeau le dit).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from jarvis.domain.presentation_addressed_turn import decide_turn_authority, is_vocative_address
from jarvis.domain.presentation_studio_armed_set import ARMED_CHANGED
from jarvis.domain.presentation_studio_cues import ArmedCues, CueMatch, CueMatcher, Verdict, parse_armed, phrase_tokens

KIND = "presentation.studio"
#: Réponses de Core après lesquelles l'ensemble tenu est périmé : on le retire et on le retire du serveur.
_MAX_REFUSAL_CODES = 16
_STALE_CODES = frozenset({"stale_run", "stale_generation", "armed_set_expired", "cue_not_armed"})


class FollowerState(StrEnum):
    STARTING = "starting"
    IDLE = "idle"  # no run
    UNARMED = "unarmed"  # a run, nothing armed (paused, detour, last item, role without cues...)
    FOLLOWING = "following"
    PAUSED_ADDRESS = "paused_address"  # explicit address preempts cue automation
    BACKOFF = "backoff"  # Core unreachable / rate limited: waiting, visibly
    LAPSED = "lapsed"  # authority expired: set dropped, pulling again
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class FollowerConfig:
    tick_s: float = 0.25
    #: How long cue automation stays paused after the last sign of an explicit address. The ambient transcript of an
    #: addressed utterance lands after the realtime stack already used the window: this covers that lag.
    hold_s: float = 4.0
    idle_poll_s: float = 5.0
    call_timeout_s: float = 5.0
    backoff_base_s: float = 1.0
    backoff_max_s: float = 30.0
    rate_backoff_s: float = 2.0
    repull_gap_s: float = 1.0


@dataclass(slots=True)
class FollowerCounters:
    """Only counts. No text, no phrase."""

    utterances: int = 0
    preempted_address: int = 0
    skipped_mode: int = 0
    skipped_backoff: int = 0
    no_armed: int = 0
    no_match: int = 0
    fired: int = 0
    ambiguous: int = 0
    vetoed: int = 0  # quoted, hedged, question, not anchored
    suppressed: int = 0  # already fired, cooldown, order
    pulls: int = 0
    pull_failures: int = 0
    lapses: int = 0
    reports_sent: int = 0
    reports_fired: int = 0
    reports_duplicate: int = 0
    reports_failed: int = 0
    reports_dropped_in_flight: int = 0
    reports_dropped_preempted: int = 0
    probe_errors: int = 0
    handler_errors: int = 0
    refused: dict[str, int] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


class PresentationStudioCueFollower:
    def __init__(
        self,
        *,
        core: Any,
        window_live: Callable[[], bool],
        turn_in_flight: Callable[[], bool] = lambda: False,
        mode_ok: Callable[[], bool] = lambda: True,
        address_marker: Callable[[], int] = lambda: 0,
        journal: Any | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        matcher: CueMatcher | None = None,
        config: FollowerConfig | None = None,
    ) -> None:
        self._core, self._window_live, self._turn_in_flight, self._mode_ok = core, window_live, turn_in_flight, mode_ok
        self._journal, self._now = journal, monotonic
        #: A counter that only grows each time an explicit address is ARMED (the addressed-turn service counts them). Reading it
        #: closes the sampling gap of the window probes: a window that opened and closed between two reads still moved it.
        self._address_marker = address_marker
        try:
            self._marker_seen = int(address_marker())
        except Exception:  # noqa: BLE001 - argued: the first utterance reads it again, fails closed and says so
            self._marker_seen = -1
        self._matcher = matcher or CueMatcher()
        self._config = config or FollowerConfig()
        self.counters = FollowerCounters()
        self._state = FollowerState.STARTING
        self._armed: ArmedCues | None = None
        self._run_live = False  # the last pull showed a run (armed or not)
        self._pulled_at: float | None = None
        self._next_pull_at = 0.0
        self._pull_requested = True
        self._last_pull_s = -1e9
        self._pulling = False
        self._failures = 0
        self._in_outage = False
        self._report_block_until = 0.0
        self._hold_until = -1e9
        self._probe_warned = False
        self._handler_warned = False
        self._lapsed = False
        self._report: asyncio.Task[None] | None = None
        self._report_sent = False
        self._report_match: CueMatch | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._wake = asyncio.Event()
        self._detach: Callable[[], None] | None = None
        self._started = self._stopped = False
        self._announced: tuple[Any, ...] | None = None

    # ------------------------------------------------------------------ wiring and lifecycle

    def attach(self, lane: Any) -> None:
        """Se brancher comme consommateur d'énonciations de la lane (`add_utterance_consumer`), sans toucher `on_utterance`."""

        self._detach = lane.add_utterance_consumer(self.on_utterance)

    async def start(self) -> None:
        if self._started or self._stopped:
            return
        self._started = True
        self._tasks = [asyncio.create_task(self._supervise(), name="studio-cue-follower"),
                       asyncio.create_task(self._events(), name="studio-cue-follower-events")]
        self._trace("follower_started", "Suiveur de cues du Studio ouvert sur la lane ambiante")

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        if self._detach is not None:
            self._detach()
            self._detach = None
        for task in (*self._tasks, *([self._report] if self._report is not None else [])):
            task.cancel()
        await asyncio.gather(*self._tasks, *([self._report] if self._report is not None else []), return_exceptions=True)
        self._matcher.arm(None)
        self._armed = None
        self._state = FollowerState.STOPPED
        self._trace("follower_stopped", "Suiveur de cues du Studio arrêté", data={"counters": self.counters.to_payload()})

    def status(self) -> dict[str, Any]:
        """Counts and state only. `armed` is how many cues are held, never which phrases."""

        armed = self._armed
        return {"state": self._state.value, "run_id": None if armed is None else armed.run_id,
                "generation": None if armed is None else armed.generation, "armed": 0 if armed is None else len(armed.cues),
                "failures": self._failures, "counters": self.counters.to_payload()}

    # ------------------------------------------------------------------ the utterance path (synchronous)

    def on_utterance(self, utterance: Any, analysis: Any = None) -> None:
        """Consommateur de la lane. Ne lève jamais : une exception ne citerait que de la parole."""

        del analysis  # `imperative` changes nothing here: the form of a sentence authorises nothing (D03)
        try:
            self._on_utterance(utterance)
        except Exception as exc:  # noqa: BLE001 - argued: the lane would write the exception message, which may quote speech
            self.counters.handler_errors += 1
            if not self._handler_warned:
                self._handler_warned = True
                self._trace("follower_handler_failed", f"Gestionnaire d'énonciation en échec : {type(exc).__name__}",
                            level="error", data={"code": "cue_follower_handler_failed", "exception_type": type(exc).__name__})

    def _on_utterance(self, utterance: Any) -> None:
        if self._stopped:
            return
        now = self._now()
        self.counters.utterances += 1
        if not self._safe_mode_ok():
            self.counters.skipped_mode += 1
            return
        text = utterance.text
        if self._addressed(text, now):
            self.counters.preempted_address += 1
            self._hold_until = max(self._hold_until, now + self._config.hold_s)
            self._cancel_unsent()
            self._refresh(now, "explicit_address")
            return
        if now < self._report_block_until or self._failures:
            self.counters.skipped_backoff += 1
            return
        decision = self._matcher.consider(utterance.utterance_id, text, now)
        del text
        verdict = decision.verdict
        if verdict is Verdict.FIRE:
            self.counters.fired += 1
            self._schedule(decision.match)
        elif verdict is Verdict.NO_ARMED:
            self.counters.no_armed += 1
        elif verdict is Verdict.NO_MATCH:
            self.counters.no_match += 1
        elif verdict is Verdict.AMBIGUOUS:
            self.counters.ambiguous += 1
            self._trace("cue_ambiguous", "Énonciation ambiguë : plusieurs cues armées touchées, aucune ne tire",
                        data={"code": "cue_ambiguous", "candidates": list(decision.candidates),
                              "utterance_id": utterance.utterance_id})
        elif verdict in (Verdict.QUOTED, Verdict.HEDGED, Verdict.QUESTION, Verdict.NOT_ANCHORED):
            self.counters.vetoed += 1
        else:
            self.counters.suppressed += 1

    def _marker_moved(self, now: float) -> bool:
        """An explicit address was armed since the last read (even if its window is already gone). Latches the hold."""

        seen = int(self._address_marker())  # may raise: the callers fail closed
        if seen == self._marker_seen:
            return False
        self._marker_seen = seen
        self._hold_until = max(self._hold_until, now + self._config.hold_s)
        self._cancel_unsent()
        return True

    def _addressed(self, text: str, now: float) -> bool:
        """Quelqu'un parle-t-il à JARVIS ? Fenêtre, vocatif, \"jarvis\" n'importe où, tour en cours ou à peine fini. Illisible = adressé."""

        try:
            moved = self._marker_moved(now)
            authority = decide_turn_authority(window_live=bool(self._window_live()), vocative=is_vocative_address(text))
            busy = bool(self._turn_in_flight())
            named = "jarvis" in phrase_tokens(text)
        except Exception as exc:  # noqa: BLE001 - fail closed: unreadable address probes silence the automation, and say so
            self.counters.probe_errors += 1
            if not self._probe_warned:
                self._probe_warned = True
                self._trace("follower_probe_failed", f"Sonde d'adresse illisible, suivi mis en pause : {type(exc).__name__}",
                            level="error", data={"code": "cue_follower_probe_failed", "exception_type": type(exc).__name__})
            return True
        return authority.admits_turn or busy or named or moved or now < self._hold_until

    def _safe_mode_ok(self) -> bool:
        try:
            return bool(self._mode_ok())
        except Exception:  # noqa: BLE001 - argued: an unreadable mode means "not PRESENTATION" for automation; counted as skipped
            return False

    # ------------------------------------------------------------------ the report (one in flight)

    def _schedule(self, match: CueMatch | None) -> None:
        armed = self._armed
        if match is None or armed is None or armed.run_id is None:
            return
        if self._report is not None and not self._report.done():
            self.counters.reports_dropped_in_flight += 1
            self._matcher.retract(match)
            return
        self._report_sent = False
        self._report_match = match
        self._report = asyncio.get_running_loop().create_task(self._send(armed.run_id, match), name="studio-cue-report")

    def _cancel_unsent(self) -> None:
        """Explicit address begins: a report not yet on the wire is dropped (its match is retracted). One sent stays sent."""

        if self._report is not None and not self._report.done() and not self._report_sent:
            self._report.cancel()
            if self._report_match is not None:
                self._matcher.retract(self._report_match)  # a task cancelled before its first step never reaches its own handler
            self.counters.reports_dropped_preempted += 1

    async def _send(self, run_id: str, match: CueMatch) -> None:
        now = self._now()
        try:
            if now < self._hold_until or self._window_busy():
                self.counters.reports_dropped_preempted += 1
                self._matcher.retract(match)
                return
            self._report_sent = True
            self.counters.reports_sent += 1
            answer = await asyncio.wait_for(
                self._core.presentation_studio_report_cue(run_id, match.generation, match.cue_id), self._config.call_timeout_s)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - recorded with its real cause (class and Core code), backoff set, cue retractable
            self._matcher.retract(match)
            self.counters.reports_failed += 1
            self._fail("report", exc)
            return
        self._settle(match, answer)

    def _window_busy(self) -> bool:
        try:
            return bool(self._window_live()) or bool(self._turn_in_flight())
        except Exception:  # noqa: BLE001 - argued: same fail-closed rule as `_addressed`, already counted there on the utterance path
            return True

    def _settle(self, match: CueMatch, answer: Any) -> None:
        now = self._now()
        status = answer.get("status") if isinstance(answer, dict) else None
        if status == "fired":
            self.counters.reports_fired += 1
            if answer.get("duplicate"):
                self.counters.reports_duplicate += 1
            self._ok()
            ev = match.evidence
            self._trace("cue_fired", "Cue satisfaite par la parole du présentateur : rapport accepté par Core",
                        data={"code": "cue_fired", "cue_id": match.cue_id, "generation": match.generation,
                              "rule": ev.rule.value, "start": ev.start, "end": ev.end, "utterance_id": ev.utterance_id,
                              "position": answer.get("position"), "duplicate": bool(answer.get("duplicate"))})
            return
        self._matcher.retract(match)
        code = str(answer.get("code")) if isinstance(answer, dict) and answer.get("code") else "malformed_answer"
        key = "other" if code not in self.counters.refused and len(self.counters.refused) >= _MAX_REFUSAL_CODES else code
        self.counters.refused[key] = self.counters.refused.get(key, 0) + 1  # a Core answer does not bound the table itself
        self._trace("cue_report_refused", f"Core a refusé le rapport de cue : {code}", level="warning" if code == "rate_limited" else "info",
                    data={"code": code, "cue_id": match.cue_id, "generation": match.generation})
        if code == "rate_limited":
            self._report_block_until = now + self._config.rate_backoff_s
        elif code in _STALE_CODES:
            self._matcher.arm(None)
            self._armed = None
            self._request_pull(now)
        self._refresh(now, code)

    # ------------------------------------------------------------------ pulling the armed set, supervising

    def on_armed_changed(self, payload: Any) -> None:
        """Bus `presentation_studio.armed.changed {run_id, generation, count}`: invalidate, then pull (never trust the payload)."""

        now = self._now()
        held = self._armed
        if isinstance(payload, dict) and held is not None and payload.get("run_id") == held.run_id \
                and payload.get("generation") == held.generation:
            return
        self._request_pull(now)

    def _on_connected(self) -> None:
        """The bus stream (re)opened: messages sent while it was down are lost, so pull once, unless a pull just happened."""

        now = self._now()
        if self._pulling or (self._pulled_at is not None and now - self._pulled_at < self._config.repull_gap_s):
            return
        self._request_pull(now)

    def _request_pull(self, now: float) -> None:
        self._pull_requested = True
        self._wake.set()

    async def _supervise(self) -> None:
        while True:
            try:
                now = self._now()
                self._watch_address(now)
                self._check_authority(now)
                if now >= self._next_pull_at or (self._pull_requested and not self._failures
                                                 and now - self._last_pull_s >= self._config.repull_gap_s):
                    await self._pull(now)
                self._refresh(self._now(), "tick")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the supervisor must not die: recorded, then the next tick
                self._fail("supervisor", exc)
            try:
                await asyncio.wait_for(self._wake.wait(), self._config.tick_s)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    def _watch_address(self, now: float) -> None:
        try:
            moved = self._marker_moved(now)
        except Exception:  # noqa: BLE001 - argued: unreadable means addressed (fail closed); `_addressed` counts and says it on the next utterance
            moved = True
        if moved or self._window_busy():
            self._hold_until = max(self._hold_until, now + self._config.hold_s)
            self._cancel_unsent()

    def _check_authority(self, now: float) -> None:
        armed = self._armed
        if armed is not None and self._pulled_at is not None and now - self._pulled_at > armed.expires_in_s:
            self._matcher.arm(None)
            self._armed, self._lapsed = None, True
            self.counters.lapses += 1
            self._request_pull(now)

    async def _pull(self, now: float) -> None:
        self._pull_requested = False
        self._last_pull_s = now
        self._pulling = True
        self.counters.pulls += 1
        try:
            raw = await asyncio.wait_for(self._core.presentation_studio_playback_armed(), self._config.call_timeout_s)
            armed = parse_armed(raw)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - Core unreachable or answer unreadable: backoff, visible, one line per outage
            self.counters.pull_failures += 1
            self._fail("pull", exc)
            return
        finally:
            self._pulling = False
        self._ok()
        self._pulled_at, self._lapsed = now, False
        self._armed = None if armed.empty else armed
        self._matcher.arm(armed)
        self._run_live = armed.run_id is not None
        self._next_pull_at = now + (self._config.idle_poll_s if armed.empty else armed.expires_in_s / 3.0)
        fingerprint = (armed.run_id, armed.generation, len(armed.cues))
        if fingerprint != self._announced:
            self._announced = fingerprint
            self._trace("armed_set_changed", "Ensemble de cues armées relu",
                        data={"code": "armed_set_pulled", "run_id": armed.run_id, "generation": armed.generation,
                              "count": len(armed.cues)})

    def _fail(self, what: str, exc: BaseException) -> None:
        self._failures += 1
        delay = min(self._config.backoff_base_s * 2 ** (self._failures - 1), self._config.backoff_max_s)
        now = self._now()
        self._next_pull_at = now + delay
        code = getattr(exc, "code", None) or getattr(exc, "status", None)
        if not self._in_outage:
            self._in_outage = True
            self._trace("follower_degraded", f"Suiveur de cues en attente ({what}) : {type(exc).__name__}, nouvel essai dans {delay:.0f} s",
                        level="warning", data={"code": "cue_follower_degraded", "step": what,
                                               "exception_type": type(exc).__name__, "core_code": None if code is None else str(code)})
        self._refresh(now, "failure")

    def _ok(self) -> None:
        if self._failures:
            self._failures = 0
        if self._in_outage:
            self._in_outage = False
            self._trace("follower_recovered", "Suiveur de cues rétabli : Core répond", data={"code": "cue_follower_recovered"})

    async def _events(self) -> None:
        """Le message `armed.changed` du bus de Core. Une panne du flux ne coupe pas le suivi : le tirage périodique rattrape."""

        events = getattr(self._core, "events", None)
        if not callable(events):
            self._trace("follower_events_unavailable", "Pas de flux d'évènements Core : l'ensemble est relu périodiquement seulement",
                        level="warning", data={"code": "cue_follower_events_unavailable"})
            return
        delay, warned = self._config.backoff_base_s, False
        while True:
            stream: Any = None
            opened = self._now()
            try:
                stream = events(on_connected=self._on_connected)
                async for envelope in stream:
                    if getattr(envelope, "message_type", None) == ARMED_CHANGED:
                        self.on_armed_changed(getattr(envelope, "payload", None))
                        self._wake.set()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a stream outage is a degraded (slower) follower, said once
                if not warned:
                    warned = True
                    self._trace("follower_events_lost", f"Flux d'évènements Core coupé : {type(exc).__name__} ; relecture périodique",
                                level="warning", data={"code": "cue_follower_events_lost", "exception_type": type(exc).__name__})
            finally:
                aclose = getattr(stream, "aclose", None)
                if aclose is not None:
                    try:
                        await aclose()
                    except Exception:  # noqa: BLE001 - intentional: closing an already dead stream must not stop the resubscription
                        pass
            if self._now() - opened > 30.0:
                delay = self._config.backoff_base_s  # it lived: not a tight loop
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._config.backoff_max_s)

    # ------------------------------------------------------------------ state, traces

    def _refresh(self, now: float, reason: str) -> None:
        if self._stopped:
            return
        if self._failures or now < self._report_block_until:
            state = FollowerState.BACKOFF
        elif self._lapsed:
            state = FollowerState.LAPSED
        elif now < self._hold_until:
            state = FollowerState.PAUSED_ADDRESS
        elif self._armed is None:
            state = FollowerState.UNARMED if self._run_live else FollowerState.IDLE
        else:
            state = FollowerState.FOLLOWING
        if state is not self._state:
            self._state = state
            self._trace("follower_state", f"Suiveur de cues : {state.value}", data={"code": "cue_follower_state", "state": state.value,
                                                                                    "reason": reason})

    def _trace(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        if self._journal is None:
            return
        try:
            self._journal.emit(f"{KIND}.{kind}", message, level=level, data=data or {})
        except Exception:  # noqa: BLE001 - intentional: same position as the ambient lane, a failing journal never stops the follower
            pass


__all__ = ["FollowerConfig", "FollowerCounters", "FollowerState", "PresentationStudioCueFollower"]
