"""Vérification du locuteur en ombre : mesurer sans rien décider.

Avant que son verdict ne gouverne quoi que ce soit (Solo Owner), le
vérificateur écoute la capture duplex et journalise ce qu'il aurait décidé.
Ce qui part vers le fournisseur, la garde d'écho et le signal `near_end` ne
changent pas d'un octet : l'observateur reçoit une copie de chaque trame
nettoyée, et rien ne remonte de lui vers la capture.

Décision de concurrence : le vérificateur ne tourne **pas** dans le callback
PortAudio. Un modèle d'empreinte vocale coûte 10 à 50 ms par fenêtre ; dans le
callback, il retarderait la capture et l'annulation d'écho. Le callback ne fait
qu'assembler des fenêtres et les déposer dans une file bornée
(`SpeakerVerificationWorker.observe`) ; un fil dédié les passe au vérificateur,
dans l'ordre, tient l'état glissant du propriétaire (`OwnerStateMachine`) et la
télémétrie (`ShadowOwnerTelemetry`).

Vérification glissante (tâche 04) — décision « toutes les trames, écho masqué » :

- le vérificateur reçoit **chaque** trame, en fenêtres contiguës : sa porte
  d'énergie écarte déjà silence et bruit pour moins d'une milliseconde par
  fenêtre, et seule la parole voisée coûte une empreinte (90 à 135 ms toutes
  les 500 ms de parole, tâche 03). Ne le nourrir qu'à partir d'un candidat
  acoustique n'économiserait presque rien quand JARVIS se tait — sa porte et
  le candidat retiennent la même parole — mais retarderait la preuve de la
  latence du détecteur et perdrait le début de phrase ;
- pendant que JARVIS parle (`far_end`), une trame sans parole proche est
  remplacée par du silence numérique avant d'être assemblée : l'écho résiduel
  n'entre jamais dans la preuve du moteur (la fenêtre reste contiguë et datée,
  son trou de 600 ms la vide), et la lecture seule ne coûte aucune empreinte.
  Une trame proche garde les 300 ms suivantes telles quelles, pour ne pas
  hacher les syllabes ;
- l'état du propriétaire n'existe qu'à l'intérieur d'un candidat acoustique
  soutenu (la règle du verrou de `NearEndDetector`) : écho seul, clic de
  clavier ou choc bref ne deviennent jamais le propriétaire, quel que soit le
  verdict. Le détecteur reste un préfiltre (D03), l'identité vient du seul
  vérificateur (D05).

Fin de candidat (tâche 07) : quand un candidat se referme, le vérificateur qui
en a la capacité (`CandidateAwareVerifier`) oublie sa preuve — le candidat
suivant est jugé sur de l'audio neuf — et, si aucun verdict n'a été rendu,
juge une fois la parole brève du candidat (« oui, vas-y », « stop ») sous sa
règle durcie. Propriétaire reconnu : l'état publie `owner_confirmed` pour ce
candidat refermé, puis `idle` — le bridge rejoue alors tout le candidat.

Solo Owner appliqué (`enforce`) : un candidat refermé sans jamais avoir été
reconnu est de l'entrée écartée — rien n'en est parti vers le fournisseur —,
dit par `voice.input.non_owner_dropped` (durée, raison, meilleur score).

Journal : métadonnées seules — score arrondi, durées, moteur, profil, statut.
Jamais d'audio, jamais d'empreinte vocale.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from jarvis.audio.duplex import FRAME_MS, CaptureFrameContext
from jarvis.domain.speaker import (
    MAX_SPEAKER_ID_CHARS,
    OwnerState,
    OwnerStateSnapshot,
    SpeakerVerification,
    VerificationStatus,
    VerifierAvailability,
)
from jarvis.ports.speaker import SpeakerVerifier, supports_candidate_verdict
from jarvis.ports.v2 import DiagnosticSink

OWNER_CANDIDATE = "voice.owner.candidate"
OWNER_CONFIRMED = "voice.owner.confirmed"
OWNER_REJECTED = "voice.owner.rejected"
OWNER_UNAVAILABLE = "voice.owner.unavailable"
OWNER_OVERRUN = "voice.owner.overrun"
OWNER_LISTENER_FAILED = "voice.owner.listener_failed"
#: Solo Owner (tâche 07) : un candidat entier écarté, jamais transmis.
OWNER_INPUT_DROPPED = "voice.input.non_owner_dropped"

_BYTES_PER_SAMPLE = 2  # int16 mono
_BUDGET_WINDOW_MS = 60_000

#: Candidat acoustique : la règle du verrou de `NearEndDetector` — 12 trames
#: proches parmi les 40 dernières, dont 6 d'affilée. Une syllabe la remplit,
#: un clic ou un choc sur le bureau jamais.
CANDIDATE_WINDOW_FRAMES = 40
CANDIDATE_MIN_FRAMES = 12
CANDIDATE_MIN_RUN_FRAMES = 6
#: Fin du candidat : 600 ms sans trame proche — le trou qui vide aussi la
#: preuve de l'adaptateur (`EmbeddingSpeakerVerifier.max_gap_ms`).
CANDIDATE_RELEASE_FRAMES = 60
#: Pendant que JARVIS parle, une trame proche laisse passer les suivantes
#: telles quelles pendant ce temps ; au-delà, silence numérique.
FAR_END_HANGOVER_MS = 300
#: Consommateurs de l'état du propriétaire : barge-in (05), porte d'entrée
#: (07), Control Center (08), avec de la marge.
MAX_OWNER_LISTENERS = 4


@dataclass(slots=True)
class _Region:
    """Candidat acoustique en cours (fil du vérificateur seulement)."""

    onset_ms: int
    last_near_ms: int
    far_end: bool
    judged: int = 0
    best_score: float | None = None
    non_owner_seen: bool = False
    owner_onset_ms: int | None = None
    confirmed_ms: int | None = None
    first_confirmed_ms: int | None = None


@dataclass(frozen=True, slots=True)
class OwnerStep:
    """Ce qu'une fenêtre a changé : de quoi journaliser et publier."""

    state: OwnerState
    changed: bool
    region: _Region | None
    opened: _Region | None = None
    closed: _Region | None = None
    confirmed_first: bool = False


class OwnerStateMachine:
    """État glissant du propriétaire, fenêtre après fenêtre.

    Confiné au fil du vérificateur ; aucune E/S, mémoire bornée (40 booléens
    et un candidat). Deux entrées par fenêtre : le contexte acoustique de
    chacune de ses trames (`CaptureFrameContext`), puis le verdict.

    Candidat acoustique : ouvert quand la règle du verrou de `NearEndDetector`
    est remplie, daté de la première trame proche de la rafale ; fermé après
    `release_frames` trames sans parole proche. États :

    - `idle` : aucun candidat ; un verdict, même « propriétaire », est ignoré ;
    - `candidate` : candidat ouvert, pas (ou plus) de verdict jugé — début de
      phrase, ou preuve vidée par un trou ;
    - `owner_confirmed` / `rejected` : le **dernier** verdict jugé du
      candidat. Aucun verrou : les deux s'enchaînent dans les deux sens sans
      silence, un étranger puis le propriétaire comme l'inverse (D06).
      Chevauchement propriétaire + étranger : le verdict du moteur sur la
      fenêtre mêlée décide, fenêtre par fenêtre.

    À la confirmation : `confirmed_ms` = fin de la fenêtre ; début estimé de
    la parole du propriétaire = début du candidat, ou — si un verdict
    « étranger » a précédé dans ce candidat — `confirmed_ms - evidence_ms`,
    le début de la preuve qui l'a reconnu, jamais avant le candidat.
    """

    def __init__(
        self,
        *,
        window_frames: int = CANDIDATE_WINDOW_FRAMES,
        min_frames: int = CANDIDATE_MIN_FRAMES,
        min_run_frames: int = CANDIDATE_MIN_RUN_FRAMES,
        release_frames: int = CANDIDATE_RELEASE_FRAMES,
    ) -> None:
        self.min_frames = max(1, int(min_frames))
        self.min_run_frames = max(1, int(min_run_frames))
        self.release_frames = max(1, int(release_frames))
        self._near: deque[bool] = deque(maxlen=max(self.min_frames, int(window_frames)))
        self.reset()

    def reset(self) -> None:
        """Oublier le candidat et la fenêtre acoustique : état `idle`."""

        self._near.clear()
        self._near_count = 0
        self._pending_onset: int | None = None
        self._quiet = 0
        self.region: _Region | None = None
        self.state = OwnerState.IDLE

    def step(self, frames: Sequence[CaptureFrameContext], verdict: SpeakerVerification, end_ms: int) -> OwnerStep:
        """Intégrer une fenêtre : ses trames, puis son verdict (`ok` ou `insufficient_audio`)."""

        previous_state, previous_region = self.state, self.region
        opened = closed = None
        for context in frames:
            ended, started = self._acoustic(context)
            closed = ended or closed
            opened = started or opened
        region = self.region
        confirmed_first = False
        if region is None:
            state = OwnerState.IDLE
        elif verdict.status is VerificationStatus.OK:
            score = float(verdict.owner_score or 0.0)
            region.judged += 1
            region.best_score = score if region.best_score is None else max(region.best_score, score)
            if verdict.owner_detected:
                state = OwnerState.OWNER_CONFIRMED
                if previous_state is not OwnerState.OWNER_CONFIRMED or previous_region is not region:
                    region.confirmed_ms = end_ms
                    region.owner_onset_ms = (
                        max(region.onset_ms, end_ms - verdict.evidence_ms) if region.non_owner_seen else region.onset_ms
                    )
                    if region.first_confirmed_ms is None:
                        region.first_confirmed_ms = end_ms
                        confirmed_first = True
            else:
                state = OwnerState.REJECTED
                region.non_owner_seen = True
        else:
            state = OwnerState.CANDIDATE
        self.state = state
        changed = state is not previous_state or region is not previous_region
        return OwnerStep(state, changed, region, opened, closed, confirmed_first)

    def _acoustic(self, context: CaptureFrameContext) -> tuple[_Region | None, _Region | None]:
        near = bool(context.near_end)
        window = self._near
        if len(window) == window.maxlen and window[0]:
            self._near_count -= 1
        window.append(near)
        if near:
            self._near_count += 1
            self._quiet = 0
            if self._pending_onset is None:
                self._pending_onset = context.stream_ms
        else:
            self._quiet += 1
            if self._near_count == 0:
                self._pending_onset = None
        region = self.region
        if region is not None:
            region.far_end = region.far_end or context.far_end
            if near:
                region.last_near_ms = context.stream_ms + FRAME_MS
            elif self._quiet >= self.release_frames:
                self.region = None
                return region, None
            return None, None
        if near and self._near_count >= self.min_frames and self._longest_run() >= self.min_run_frames:
            onset = context.stream_ms if self._pending_onset is None else self._pending_onset
            self.region = _Region(onset_ms=onset, last_near_ms=context.stream_ms + FRAME_MS, far_end=context.far_end)
            return None, self.region
        return None, None

    def _longest_run(self) -> int:
        best = run = 0
        for value in self._near:
            run = run + 1 if value else 0
            best = max(best, run)
        return best


class OwnerStatePublisher:
    """Dernier état du propriétaire et ses consommateurs : la seule partie partagée.

    `publish` (fil du vérificateur) remplace l'état sous verrou puis appelle
    les consommateurs hors verrou ; `latest` et `add` se lisent ou s'appellent
    de n'importe quel fil. Aucun historique : l'état courant et un numéro de
    séquence suffisent, la mémoire ne grandit pas.
    """

    def __init__(self, *, max_listeners: int = MAX_OWNER_LISTENERS) -> None:
        self.max_listeners = max(1, int(max_listeners))
        self._lock = threading.Lock()
        self._latest = OwnerStateSnapshot()
        self._listeners: tuple[Callable[[OwnerStateSnapshot], None], ...] = ()

    @property
    def latest(self) -> OwnerStateSnapshot:
        with self._lock:
            return self._latest

    def add(self, listener: Callable[[OwnerStateSnapshot], None]) -> Callable[[], None]:
        with self._lock:
            if len(self._listeners) >= self.max_listeners:
                raise ValueError(f"at most {self.max_listeners} owner-state listeners")
            self._listeners = (*self._listeners, listener)

        def remove() -> None:
            self._remove(listener)

        return remove

    def publish(self, snapshot: OwnerStateSnapshot) -> list[Exception]:
        """Publier ; rendre les exceptions des consommateurs, qui sont retirés."""

        with self._lock:
            self._latest = snapshot
            listeners = self._listeners
        failures: list[Exception] = []
        for listener in listeners:
            try:
                listener(snapshot)
            except Exception as exc:
                # Un consommateur en panne ne doit ni tuer le fil ni priver
                # les autres de l'état : il est retiré, une trace suffit.
                self._remove(listener)
                failures.append(exc)
        return failures

    def _remove(self, listener: Callable[[OwnerStateSnapshot], None]) -> None:
        with self._lock:
            self._listeners = tuple(item for item in self._listeners if item is not listener)


class ShadowOwnerTelemetry:
    """Ce que le vérificateur aurait décidé, en journal borné.

    Confiné au fil du vérificateur, sauf `publisher` (état du propriétaire,
    lisible de partout). Deux horloges de flux, jamais l'horloge murale : les
    instants de l'état et des épisodes sont ceux de la capture
    (`CaptureFrameContext.stream_ms`, remis à zéro à chaque session) ; le
    budget du journal compte l'audio reçu depuis la création, sans retour en
    arrière. Les durées rapportées ne dépendent donc pas du retard du fil.

    Épisode = candidat acoustique (`OwnerStateMachine`). Son ouverture émet
    `voice.owner.candidate` ; la première confirmation du propriétaire
    `voice.owner.confirmed`, avec `confirm_ms` = latence de l'ombre, du début
    du candidat à la confirmation ; un candidat refermé sans confirmation
    `voice.owner.rejected` (`reason` : `non_owner` s'il a été jugé,
    `insufficient_audio` sinon). Les basculements suivants dans un même
    candidat ne sont pas journalisés : ils sont publiés (`owner_state`).

    Bornes : au plus deux évènements par épisode, un `unavailable` par
    changement d'état, un `overrun` par session, et `max_events_per_minute` en
    tout ; au-delà, les évènements sont comptés et le suivant porte
    `suppressed`.

    Pannes : une exception du vérificateur le met hors service (`failed`)
    jusqu'au prochain `reset()` — une trace par session, pas une par fenêtre.
    Un moteur qui n'est pas `ready` au début d'une session n'est pas consulté,
    et l'état du propriétaire reste `idle`. Tout changement de disponibilité
    est aussi publié (un état `idle`) : le bridge Solo Owner en est prévenu
    aussitôt et referme l'entrée (tâche 07).

    `availability` part de ce que le moteur déclare à la construction (lu
    une fois, comme `engine`) et y revient à chaque `reset()` : nouvelle
    chance à chaque session, que Voice lit avant d'ouvrir le micro.

    `enforce` (Solo Owner appliqué) ajoute `voice.input.non_owner_dropped` à
    la fermeture d'un candidat jamais reconnu.
    """

    def __init__(
        self,
        verifier: SpeakerVerifier,
        *,
        sample_rate: int,
        diagnostics: DiagnosticSink | None = None,
        max_events_per_minute: int = 30,
        enforce: bool = False,
    ) -> None:
        self.verifier = verifier
        self.sample_rate = int(sample_rate)
        self.diagnostics = diagnostics
        self.max_events_per_minute = max(1, int(max_events_per_minute))
        self.enforce = bool(enforce)
        try:
            engine = str(verifier.engine)[:MAX_SPEAKER_ID_CHARS]
        except Exception:
            engine = ""
        self.engine = engine or "unknown"
        try:
            declared = VerifierAvailability(verifier.availability)
        except Exception:
            declared = VerifierAvailability.FAILED
        #: Disponibilité déclarée par le moteur à la construction.
        self.declared_availability = declared
        #: État du vérificateur tel que la voix le voit ; lisible d'un autre fil.
        self.availability = declared
        self.machine = OwnerStateMachine()
        #: État du propriétaire publié ; seule partie lue par d'autres fils.
        self.publisher = OwnerStatePublisher()
        self._sequence = 0
        self._session = 0
        #: Fin de la dernière fenêtre reçue, horloge de la capture (session).
        self._last_end_ms = 0
        self._stream_ms = 0
        self._session_started = False
        self._consulted = False
        self._overrun_reported = False
        self._sent: deque[int] = deque()
        self._suppressed = 0

    # -- cycle de vie ---------------------------------------------------------

    def reset(self) -> None:
        """Nouvelle session vocale : oublier le candidat et la preuve accumulée."""

        self._session += 1
        self._last_end_ms = 0
        self.availability = self.declared_availability
        self._set_idle(force=True)
        self._session_started = False
        self._overrun_reported = False
        try:
            self.verifier.reset()
        except Exception as exc:
            self._session_started = True
            self._fail("verifier_reset_failed", exc)

    def skip(self, dropped_ms: int) -> None:
        """Le fil a jeté de l'audio : la fenêtre du moteur n'est plus contiguë."""

        self._stream_ms += max(0, int(dropped_ms))
        self._set_idle()
        if not self._overrun_reported:
            self._overrun_reported = True
            self._emit(
                OWNER_OVERRUN,
                "Vérification du locuteur en retard sur le temps réel : de l'audio a été sauté",
                level="warning",
                dropped_ms=int(dropped_ms),
                code="verifier_overrun",
            )
        if self._consulted:
            try:
                self.verifier.reset()
            except Exception as exc:
                self._fail("verifier_reset_failed", exc)

    def close(self) -> None:
        try:
            self.verifier.close()
        except Exception:
            # Fermer un moteur est au mieux best effort : la voix s'arrête de
            # toute façon.
            pass

    # -- flux -----------------------------------------------------------------

    def feed(self, pcm: bytes, frames: Sequence[CaptureFrameContext]) -> None:
        """Passer une fenêtre au vérificateur, faire avancer l'état, journaliser.

        `frames` : le contexte de chacune des trames de la fenêtre, dans l'ordre
        (au moins une) ; il porte la fréquence et l'horloge de la capture.
        """

        if not frames:
            raise ValueError("a window needs the context of its frames")
        rate = int(frames[0].sample_rate)
        if rate != self.sample_rate:
            self._change_rate(rate)
        duration_ms = len(pcm) * 1000 // (rate * _BYTES_PER_SAMPLE)
        end_ms = frames[0].stream_ms + duration_ms
        self._last_end_ms = end_ms
        self._stream_ms += duration_ms
        if not self._session_started:
            self._start_session()
        if not self._consulted:
            return
        try:
            result = self.verifier.process(pcm, rate)
            if not isinstance(result, SpeakerVerification):
                raise TypeError(f"expected SpeakerVerification, got {type(result).__name__}")
        except Exception as exc:
            self._fail("verifier_exception", exc)
            return
        self._observe(result, frames, end_ms)

    def _change_rate(self, rate: int) -> None:
        # Nouvelle fréquence : nouveau flux. L'état et la preuve d'avant ne
        # décrivent plus rien de comparable.
        self.sample_rate = rate
        self._session += 1
        self._last_end_ms = 0
        self._set_idle(force=True)
        if self._consulted:
            try:
                self.verifier.reset()
            except Exception as exc:
                self._fail("verifier_reset_failed", exc)

    def _start_session(self) -> None:
        self._session_started = True
        try:
            availability = VerifierAvailability(self.verifier.availability)
        except Exception as exc:
            self._fail("verifier_availability_failed", exc)
            return
        # Nouvelle chance à chaque session : un moteur tombé en panne la
        # précédente est de nouveau consulté s'il se dit prêt.
        self.availability = availability
        self._consulted = availability is VerifierAvailability.READY
        if not self._consulted:
            # Publié : un consommateur Solo Owner doit l'apprendre sans
            # attendre un autre évènement (tâche 07).
            self._set_idle(force=True)
            self._emit(
                OWNER_UNAVAILABLE,
                "Vérification du locuteur indisponible : rien n'est mesuré",
                level="warning",
                code="verifier_not_ready",
            )

    def _fail(self, code: str, exc: Exception) -> None:
        self._consulted = False
        # Disponibilité d'abord, publication ensuite : un consommateur prévenu
        # par l'état `idle` doit déjà lire `failed` (fermeture sûre, tâche 07).
        self.availability = VerifierAvailability.FAILED
        self._set_idle(force=True)
        self._emit(
            OWNER_UNAVAILABLE,
            "Vérificateur de locuteur en panne : la voix continue sans lui",
            level="warning",
            code=code,
            error=type(exc).__name__,
        )

    def _unavailable_verdict(self, result: SpeakerVerification) -> None:
        """Un verdict dit le moteur indisponible : candidat abandonné, changement publié."""

        availability = result.availability
        changed = availability is not self.availability
        self.availability = availability
        self._set_idle(force=changed)
        if changed:
            self._emit(
                OWNER_UNAVAILABLE,
                "Vérification du locuteur indisponible : rien n'est mesuré",
                level="warning",
                result=result,
                code=f"verifier_{result.status.value}",
            )

    def _observe(self, result: SpeakerVerification, frames: Sequence[CaptureFrameContext], end_ms: int) -> None:
        if result.availability is not VerifierAvailability.READY:
            self._unavailable_verdict(result)
            return
        self.availability = VerifierAvailability.READY
        step = self.machine.step(frames, result, end_ms)
        if step.closed is not None:
            if not self._finish_candidate(step.closed, frames, end_ms):
                # Le moteur a lâché en jugeant la fin du candidat : état déjà
                # rendu à `idle` et publié par la panne.
                return
        if step.opened is not None:
            self._emit(
                OWNER_CANDIDATE,
                "Parole candidate : le vérificateur la juge (ombre)",
                result=result,
                far_end=step.opened.far_end,
            )
        region = step.region
        if step.confirmed_first and region is not None and region.first_confirmed_ms is not None:
            self._emit(
                OWNER_CONFIRMED,
                "Propriétaire reconnu (ombre : l'audio n'en est pas changé)",
                result=result,
                confirm_ms=region.first_confirmed_ms - region.onset_ms,
                after_non_owner=region.non_owner_seen,
                far_end=region.far_end,
            )
        if step.changed:
            far_end = any(context.far_end for context in frames)
            self._publish(step.state, end_ms, region, result, far_end)

    def _finish_candidate(self, region: _Region, frames: Sequence[CaptureFrameContext], end_ms: int) -> bool:
        """Le candidat vient de se refermer : verdict bref éventuel, preuve oubliée, épisode clos.

        Rend False si le moteur a lâché (panne déjà traitée). Sans la capacité
        `finish_candidate`, seul l'épisode est clos, comme avant la tâche 07.
        """

        judge = region.judged == 0
        reason: str | None = None
        if supports_candidate_verdict(self.verifier):
            try:
                verdict = self.verifier.finish_candidate(judge=judge)  # type: ignore[attr-defined]
                if not isinstance(verdict, SpeakerVerification):
                    raise TypeError(f"expected SpeakerVerification, got {type(verdict).__name__}")
            except Exception as exc:
                self._fail("verifier_exception", exc)
                return False
            if verdict.availability is not VerifierAvailability.READY:
                self._unavailable_verdict(verdict)
                return False
            if judge and verdict.status is VerificationStatus.OK:
                score = float(verdict.owner_score or 0.0)
                region.judged += 1
                region.best_score = score if region.best_score is None else max(region.best_score, score)
                if verdict.owner_detected:
                    # Réponse brève reconnue : tout le candidat est au
                    # propriétaire, du début à la fin — le bridge le rejoue.
                    region.owner_onset_ms = region.onset_ms
                    region.confirmed_ms = region.first_confirmed_ms = end_ms
                    self._emit(
                        OWNER_CONFIRMED,
                        "Propriétaire reconnu sur une réponse brève, à la fin du candidat",
                        result=verdict,
                        confirm_ms=end_ms - region.onset_ms,
                        after_non_owner=False,
                        far_end=region.far_end,
                        verdict="candidate_end",
                    )
                    far_end = region.far_end or any(context.far_end for context in frames)
                    self._publish(OwnerState.OWNER_CONFIRMED, end_ms, region, verdict, far_end)
                    return True
                reason = "short_not_owner"
        self._close_episode(region, reason=reason)
        return True

    def _close_episode(self, region: _Region, *, reason: str | None = None) -> None:
        if region.first_confirmed_ms is not None:
            return
        reason = reason or ("non_owner" if region.judged else "insufficient_audio")
        best_score = None if region.best_score is None else round(region.best_score, 3)
        episode_ms = region.last_near_ms - region.onset_ms
        self._emit(
            OWNER_REJECTED,
            "Parole non attribuée au propriétaire (ombre)",
            best_score=best_score,
            episode_ms=episode_ms,
            reason=reason,
            far_end=region.far_end,
        )
        if self.enforce:
            # Solo Owner : la garde n'a jamais ouvert le flux pour ce
            # candidat, rien n'en a atteint le fournisseur.
            self._emit(
                OWNER_INPUT_DROPPED,
                "Parole écartée : pas reconnue comme celle du propriétaire, rien n'a été transmis",
                mode="enforce",
                source="capture",
                candidate_ms=episode_ms,
                reason=reason,
                best_score=best_score,
                far_end=region.far_end,
            )

    # -- état publié ----------------------------------------------------------

    def _set_idle(self, *, force: bool = False) -> None:
        """Abandonner le candidat en cours sans verdict (session, panne, trou)."""

        machine = self.machine
        if machine.state is OwnerState.IDLE and machine.region is None and not force:
            return
        machine.reset()
        self._publish(OwnerState.IDLE, self._last_end_ms, None, None, False)

    def _publish(
        self,
        state: OwnerState,
        stream_ms: int,
        region: _Region | None,
        result: SpeakerVerification | None,
        far_end: bool,
    ) -> None:
        self._sequence += 1
        snapshot = OwnerStateSnapshot(
            sequence=self._sequence,
            session=self._session,
            state=state,
            stream_ms=max(0, int(stream_ms)),
            candidate_onset_ms=None if region is None else region.onset_ms,
            owner_onset_ms=None if region is None else region.owner_onset_ms,
            confirmed_ms=None if region is None else region.confirmed_ms,
            owner_score=None if result is None or result.owner_score is None else round(float(result.owner_score), 3),
            evidence_ms=0 if result is None else result.evidence_ms,
            far_end=far_end,
        )
        for exc in self.publisher.publish(snapshot):
            self._emit(
                OWNER_LISTENER_FAILED,
                "Un consommateur de l'état du propriétaire a échoué : il est retiré",
                level="warning",
                code="owner_listener_failed",
                error=type(exc).__name__,
            )

    # -- journal --------------------------------------------------------------

    def _emit(
        self,
        kind: str,
        message: str,
        *,
        level: str = "info",
        result: SpeakerVerification | None = None,
        **extra: object,
    ) -> None:
        if self.diagnostics is None:
            return
        now = self._stream_ms
        while self._sent and now - self._sent[0] >= _BUDGET_WINDOW_MS:
            self._sent.popleft()
        if len(self._sent) >= self.max_events_per_minute:
            self._suppressed += 1
            return
        self._sent.append(now)
        data: dict[str, object] = {"mode": "shadow", "engine": self.engine, "availability": self.availability.value}
        if result is not None:
            data.update(
                engine=result.engine,
                status=result.status.value,
                owner_score=None if result.owner_score is None else round(float(result.owner_score), 3),
                owner_detected=result.owner_detected,
                evidence_ms=result.evidence_ms,
                profile_id=result.profile_id,
            )
        data.update(extra)
        if self._suppressed:
            data["suppressed"] = self._suppressed
            self._suppressed = 0
        try:
            self.diagnostics.emit(kind, message, level=level, data=data)
        except Exception:
            # Un journal qui refuse d'écrire ne doit pas arrêter la mesure.
            pass


class SpeakerVerificationWorker:
    """Fil du vérificateur, nourri par la capture sans jamais la freiner.

    Implémente `jarvis.audio.duplex.CaptureObserver` et
    `jarvis.ports.speaker.OwnerStateSource`.

    - `observe` (thread PortAudio) masque l'écho seul (trame sans parole
      proche pendant que JARVIS parle → silence numérique), assemble les
      trames de 10 ms en fenêtres de `hop_ms` avec leur contexte, et les
      dépose dans une file d'au plus `max_pending_ms`. File pleine : la plus
      ancienne fenêtre est jetée et comptée (`dropped_ms`), la capture
      n'attend jamais, et le vérificateur repart d'une fenêtre vide. Une
      nouvelle fréquence abandonne la fenêtre en cours d'assemblage.
    - `reset` (boucle asyncio, capture arrêtée) vide la file ; le fil remet le
      vérificateur et l'état du propriétaire à zéro avant la fenêtre suivante.
    - `close` arrête le fil ; c'est lui qui ferme le vérificateur.

    Tous les appels au vérificateur ont lieu dans ce fil. `availability`,
    `dropped_ms` et `owner_state` se lisent de n'importe où (Control Center,
    tâche 08 ; barge-in, tâche 05).
    """

    def __init__(
        self,
        verifier: SpeakerVerifier,
        *,
        sample_rate: int,
        diagnostics: DiagnosticSink | None = None,
        hop_ms: int = 100,
        max_pending_ms: int = 2000,
        max_events_per_minute: int = 30,
        far_end_hangover_ms: int = FAR_END_HANGOVER_MS,
        enforce: bool = False,
    ) -> None:
        self.telemetry = ShadowOwnerTelemetry(
            verifier,
            sample_rate=sample_rate,
            diagnostics=diagnostics,
            max_events_per_minute=max_events_per_minute,
            enforce=enforce,
        )
        self.hop_ms = max(10, int(hop_ms))
        self.max_pending = max(1, int(max_pending_ms) // self.hop_ms)
        # Thread de capture seulement : fenêtre en cours d'assemblage.
        self._rate = int(sample_rate)
        self._hop_bytes = self._rate * self.hop_ms // 1000 * _BYTES_PER_SAMPLE
        self._hop = bytearray()
        self._hop_frames: list[CaptureFrameContext] = []
        self._hangover_frames = max(0, int(far_end_hangover_ms)) // FRAME_MS
        self._hangover = 0
        self._pending: deque[tuple[bytes, tuple[CaptureFrameContext, ...]]] = deque()
        self._cond = threading.Condition()
        self._dropped_hops = 0
        self.dropped_ms = 0
        self._reset_requested = False
        self._busy = False
        self._closing = False
        self._thread = threading.Thread(target=self._run, name="jarvis-speaker-verifier", daemon=True)
        self._thread.start()

    @property
    def availability(self) -> VerifierAvailability:
        return self.telemetry.availability

    @property
    def pending(self) -> int:
        """Fenêtres en attente du vérificateur."""

        with self._cond:
            return len(self._pending)

    @property
    def owner_state(self) -> OwnerStateSnapshot:
        """Dernier état publié du propriétaire (`OwnerStateSource`)."""

        return self.telemetry.publisher.latest

    def add_owner_listener(self, listener: Callable[[OwnerStateSnapshot], None]) -> Callable[[], None]:
        """S'abonner aux changements d'état ; appelé dans le fil du vérificateur (`OwnerStateSource`)."""

        return self.telemetry.publisher.add(listener)

    # -- thread de capture ----------------------------------------------------

    def observe(self, frame: bytes, context: CaptureFrameContext) -> None:
        if context.sample_rate != self._rate:
            # Autre fréquence, autre flux : la fenêtre en cours n'est plus
            # comparable ; le fil remettra état et moteur à zéro en voyant la
            # nouvelle fréquence.
            self._rate = int(context.sample_rate)
            self._hop_bytes = self._rate * self.hop_ms // 1000 * _BYTES_PER_SAMPLE
            self._hop.clear()
            self._hop_frames = []
            self._hangover = 0
        if context.near_end:
            self._hangover = self._hangover_frames
            self._hop += frame
        elif self._hangover:
            self._hangover -= 1
            self._hop += frame
        elif context.far_end:
            # JARVIS parle et personne d'autre : écho résiduel, pas une voix
            # à juger. Silence numérique à sa place, même durée.
            self._hop += bytes(len(frame))
        else:
            self._hop += frame
        self._hop_frames.append(context)
        if len(self._hop) < self._hop_bytes:
            return
        hop = bytes(self._hop[: self._hop_bytes])
        del self._hop[: self._hop_bytes]
        frames = tuple(self._hop_frames)
        # Une trame à cheval sur deux fenêtres garde son contexte dans la suivante.
        self._hop_frames = [context] if self._hop else []
        with self._cond:
            if self._closing:
                return
            if len(self._pending) >= self.max_pending:
                self._pending.popleft()
                self._dropped_hops += 1
                self.dropped_ms += self.hop_ms
            self._pending.append((hop, frames))
            self._cond.notify()

    # -- boucle asyncio -------------------------------------------------------

    def reset(self) -> None:
        """Nouvelle session : appelé capture arrêtée, comme `CaptureProcessor.reset`.

        La disponibilité revient aussitôt à celle que le moteur déclare : Voice
        la lit juste après, avant d'ouvrir le micro, pour accepter ou refuser
        Solo Owner (tâche 07). Un moteur tombé en panne la session précédente
        a ainsi sa nouvelle chance ; s'il retombe, la session se referme.
        """

        self._hop.clear()
        self._hop_frames = []
        self._hangover = 0
        self.telemetry.availability = self.telemetry.declared_availability
        with self._cond:
            self._pending.clear()
            self._dropped_hops = 0
            self._reset_requested = True
            self._cond.notify()

    def flush(self, timeout: float | None = None) -> bool:
        """Attendre que le fil ait traité tout ce qui lui a été remis."""

        with self._cond:
            return self._cond.wait_for(
                lambda: self._closing or not (self._pending or self._reset_requested or self._busy), timeout
            )

    def close(self, timeout: float = 2.0) -> None:
        with self._cond:
            self._closing = True
            self._pending.clear()
            self._cond.notify_all()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout)

    # -- fil du vérificateur --------------------------------------------------

    def _run(self) -> None:
        telemetry = self.telemetry
        while True:
            with self._cond:
                while not (self._pending or self._reset_requested or self._closing):
                    self._busy = False
                    self._cond.notify_all()
                    self._cond.wait()
                if self._closing:
                    break
                reset, self._reset_requested = self._reset_requested, False
                dropped, self._dropped_hops = self._dropped_hops, 0
                hop = self._pending.popleft() if self._pending else None
                self._busy = True
            try:
                if reset:
                    telemetry.reset()
                if dropped:
                    telemetry.skip(dropped * self.hop_ms)
                if hop is not None:
                    telemetry.feed(*hop)
            except Exception as exc:
                # La télémétrie absorbe déjà les pannes du moteur ; ceci ne
                # garde que le fil en vie face à une erreur imprévue : mesure
                # suspendue jusqu'à la session suivante, état `idle`.
                telemetry.availability = VerifierAvailability.FAILED
                try:
                    telemetry._fail("shadow_exception", exc)
                except Exception:
                    pass
        telemetry.close()
        with self._cond:
            self._busy = False
            self._cond.notify_all()
