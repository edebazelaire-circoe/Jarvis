from __future__ import annotations

from collections.abc import Iterable

from jarvis.domain.speaker import SpeakerVerification, VerificationStatus, VerifierAvailability

#: Pas de script : un nombre = fenêtre jugée avec ce score ; `None` = pas assez
#: de parole ; un statut = ce statut sans score ; un verdict = rendu tel quel ;
#: une exception = levée par `process`.
ScriptStep = float | None | VerificationStatus | SpeakerVerification | Exception


class ScriptedSpeakerVerifier:
    """`SpeakerVerifier` déterministe pour les tests : un verdict scripté par appel.

    Chaque appel à `process` consomme un pas du script, quel que soit
    l'audio reçu : le test décide ainsi d'une suite propriétaire, étranger ou
    ambiguë fenêtre par fenêtre. Script épuisé : `insufficient_audio`, comme un
    micro qui n'entend plus personne. `reset` ne rembobine pas le script — le
    flux continue — mais remet à zéro la preuve accumulée (`evidence_ms`), qui
    croît de la durée de chaque fenêtre jugée d'affilée.
    """

    def __init__(
        self,
        script: Iterable[ScriptStep] = (),
        *,
        threshold: float = 0.7,
        engine: str = "fake-speaker/1",
        profile_id: str | None = "owner-test",
        availability: VerifierAvailability = VerifierAvailability.READY,
        candidate_script: Iterable[ScriptStep] = (),
        short_threshold: float | None = None,
        short_evidence_ms: int = 700,
    ) -> None:
        self._script = tuple(script)
        self._next = 0
        self.threshold = threshold
        self.engine = engine
        self.profile_id = profile_id
        self.availability = availability
        self._evidence_ms = 0
        # Verdicts de fin de candidat (tâche 07) : un pas par appel à
        # `finish_candidate(judge=True)`, même grammaire que `script` ; épuisé,
        # `insufficient_audio`. Seuil durci : `short_threshold`, par défaut
        # `threshold + 0.1`.
        self._candidate_script = tuple(candidate_script)
        self._candidate_next = 0
        self.short_threshold = min(1.0, threshold + 0.1) if short_threshold is None else short_threshold
        self.short_evidence_ms = short_evidence_ms
        #: (octets, fréquence) de chaque appel à `process`.
        self.calls: list[tuple[int, int]] = []
        #: `judge` de chaque appel à `finish_candidate`.
        self.finish_calls: list[bool] = []
        self.resets = 0
        self.closed = False

    def reset(self) -> None:
        self.resets += 1
        self._evidence_ms = 0

    def process(self, pcm: bytes, sample_rate: int) -> SpeakerVerification:
        if self.closed:
            raise RuntimeError("verifier closed")
        self.calls.append((len(pcm), sample_rate))
        step = self._script[self._next] if self._next < len(self._script) else None
        self._next += 1
        if isinstance(step, Exception):
            raise step
        if isinstance(step, SpeakerVerification):
            return step
        if step is None or isinstance(step, VerificationStatus):
            self._evidence_ms = 0
            status = VerificationStatus.INSUFFICIENT_AUDIO if step is None else step
            return SpeakerVerification(status=status, engine=self.engine, profile_id=self.profile_id)
        self._evidence_ms += len(pcm) * 1000 // (int(sample_rate) * 2)
        score = float(step)
        return SpeakerVerification(
            status=VerificationStatus.OK,
            engine=self.engine,
            owner_score=score,
            owner_detected=score >= self.threshold,
            evidence_ms=self._evidence_ms,
            profile_id=self.profile_id,
        )

    def finish_candidate(self, *, judge: bool = True) -> SpeakerVerification:
        """Fin de candidat (`CandidateAwareVerifier`) : verdict bref scripté, puis preuve oubliée."""

        if self.closed:
            raise RuntimeError("verifier closed")
        self.finish_calls.append(judge)
        self._evidence_ms = 0
        insufficient = SpeakerVerification(
            status=VerificationStatus.INSUFFICIENT_AUDIO, engine=self.engine, profile_id=self.profile_id
        )
        if not judge:
            return insufficient
        step = self._candidate_script[self._candidate_next] if self._candidate_next < len(self._candidate_script) else None
        self._candidate_next += 1
        if isinstance(step, Exception):
            raise step
        if isinstance(step, SpeakerVerification):
            return step
        if step is None:
            return insufficient
        if isinstance(step, VerificationStatus):
            return SpeakerVerification(status=step, engine=self.engine, profile_id=self.profile_id)
        score = float(step)
        return SpeakerVerification(
            status=VerificationStatus.OK,
            engine=self.engine,
            owner_score=score,
            owner_detected=score >= self.short_threshold,
            evidence_ms=self.short_evidence_ms,
            profile_id=self.profile_id,
        )

    def close(self) -> None:
        self.closed = True
