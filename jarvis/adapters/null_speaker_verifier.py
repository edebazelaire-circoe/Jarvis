from __future__ import annotations

from jarvis.domain.speaker import SpeakerVerification, VerificationStatus, VerifierAvailability


class NullSpeakerVerifier:
    """`SpeakerVerifier` sans moteur : « aucun vérificateur installé ».

    Il ne fait semblant de rien — aucun score, jamais de propriétaire reconnu —
    et annonce `not_installed`, pour que Solo Owner soit refusé et que
    l'observation se déclare dégradée au lieu de mesurer du vide.
    """

    engine = "none"
    availability = VerifierAvailability.NOT_INSTALLED

    def reset(self) -> None:
        return None

    def process(self, pcm: bytes, sample_rate: int) -> SpeakerVerification:
        del pcm, sample_rate
        return SpeakerVerification(status=VerificationStatus.UNAVAILABLE, engine=self.engine)

    def close(self) -> None:
        return None
