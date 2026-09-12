"""Vérification du propriétaire par empreinte vocale, indépendante du moteur.

Un moteur d'empreinte (`SpeakerEmbedder`) ne sait que transformer quelques
secondes de parole en vecteur. Tout le reste vit ici, identique pour tous les
moteurs comparés au banc d'essai (tâche 09) :

- `SpeechGate` : porte d'énergie adaptative qui écarte silence et souffle ;
- `EmbeddingSpeakerVerifier` : implémente le port `SpeakerVerifier` avec une
  fenêtre glissante bornée de parole voisée, un score normalisé et un seuil ;
- `enroll_embedding` : empreinte de référence du propriétaire à l'enrôlement.

Rien ici n'écrit l'audio ni l'empreinte vers un journal : les vecteurs restent
dans ce module et dans le fichier de profil.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Iterable, Protocol

import numpy as np

from jarvis.domain.speaker import SpeakerVerification, VerificationStatus, VerifierAvailability

#: Découpe interne de la porte de parole : assez court pour suivre les pauses
#: entre les mots, assez long pour qu'un clic isolé pèse peu.
GATE_FRAME_MS = 20
_SILENCE_DB = -120.0


class SpeakerEmbedder(Protocol):
    """Moteur d'empreinte vocale : audio mono flottant → vecteur.

    `embed` reçoit des échantillons float32 dans [-1, 1] déjà à
    `sample_rate` et rend un vecteur de `dim` valeurs (normalisé ou non).
    Il peut charger son modèle au premier appel ; `load` le fait d'avance.
    """

    @property
    def model_id(self) -> str: ...

    @property
    def dim(self) -> int: ...

    @property
    def sample_rate(self) -> int: ...

    def embed(self, samples: np.ndarray) -> np.ndarray: ...


class EnrollmentError(ValueError):
    """Enrôlement refusé, avec un code stable pour l'interface."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def pcm16_to_float(pcm: bytes) -> np.ndarray:
    """PCM int16 mono → float32 dans [-1, 1]."""

    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def level_db(samples: np.ndarray) -> float:
    """Énergie RMS en dB pleine échelle (même échelle que `duplex.frame_db`)."""

    if samples.size == 0:
        return _SILENCE_DB
    power = float(np.mean(np.square(samples, dtype=np.float64)))
    return 10.0 * math.log10(power) if power > 1e-12 else _SILENCE_DB


def resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Rééchantillonner une fenêtre complète (FFT, sans état).

    Appelé sur une fenêtre de preuve entière, pas trame par trame : le coût
    reste de l'ordre de la milliseconde et aucun filtre ne traîne d'état entre
    deux fenêtres non contiguës.
    """

    source_rate, target_rate = int(source_rate), int(target_rate)
    if source_rate == target_rate or samples.size == 0:
        return samples.astype(np.float32, copy=False)
    count = max(1, int(round(samples.size * target_rate / source_rate)))
    spectrum = np.fft.rfft(samples.astype(np.float64))
    bins = count // 2 + 1
    if bins <= spectrum.size:
        spectrum = spectrum[:bins]
    else:
        spectrum = np.concatenate([spectrum, np.zeros(bins - spectrum.size, dtype=spectrum.dtype)])
    out = np.fft.irfft(spectrum, n=count) * (count / samples.size)
    return out.astype(np.float32)


class SpeechGate:
    """Porte d'énergie adaptative : cette trame contient-elle de la parole ?

    Plancher = percentile bas des niveaux récents, borné comme celui du
    `NearEndDetector` ; une trame est voisée quand elle dépasse ce plancher de
    `margin_db` et un minimum absolu. Heuristique volontairement simple : elle
    ne décide que « assez de parole pour juger », jamais qui parle.
    """

    FLOOR_MIN_DB = -70.0
    FLOOR_MAX_DB = -35.0

    def __init__(self, *, margin_db: float = 10.0, absolute_min_db: float = -55.0, history_frames: int = 250) -> None:
        self.margin_db = float(margin_db)
        self.absolute_min_db = float(absolute_min_db)
        self._levels: deque[float] = deque(maxlen=max(10, int(history_frames)))
        self.floor_db = -60.0

    def reset(self) -> None:
        self._levels.clear()
        self.floor_db = -60.0

    def update(self, level: float) -> bool:
        self._levels.append(level)
        if len(self._levels) >= 10:
            low = float(np.percentile(np.fromiter(self._levels, dtype=np.float64), 10))
            self.floor_db = min(self.FLOOR_MAX_DB, max(self.FLOOR_MIN_DB, low + 3.0))
        return level > self.floor_db + self.margin_db and level > self.absolute_min_db


def voiced_samples(samples: np.ndarray, sample_rate: int, gate: SpeechGate | None = None) -> np.ndarray:
    """Ne garder que les trames voisées d'un enregistrement complet."""

    gate = gate or SpeechGate()
    frame = int(sample_rate) * GATE_FRAME_MS // 1000
    count = samples.size // frame
    if count == 0:
        return np.zeros(0, dtype=np.float32)
    frames = samples[: count * frame].reshape(count, frame)
    keep = [gate.update(level_db(row)) for row in frames]
    return frames[np.asarray(keep, dtype=bool)].reshape(-1).astype(np.float32, copy=False)


def _unit(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float64).reshape(-1)
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= 0.0:
        raise ValueError("embedding has no direction")
    return vector / norm


def owner_score_from_cosine(cosine: float) -> float:
    """Similarité cosinus → échelle commune [0, 1].

    Écrêtage simple : une similarité négative veut dire « certainement pas le
    propriétaire » (0) ; au-dessus, le score *est* la similarité cosinus, ce qui
    garde le seuil lisible dans les unités de la fiche du modèle.
    """

    if not math.isfinite(cosine):
        return 0.0
    return min(1.0, max(0.0, float(cosine)))


class EmbeddingSpeakerVerifier:
    """`SpeakerVerifier` pour tout moteur d'empreinte vocale.

    Par fenêtre reçue (100 ms en pratique, `SpeakerVerificationWorker`) :

    1. découpe en trames de 20 ms, porte de parole ;
    2. les trames voisées rejoignent une fenêtre glissante bornée à
       `evidence_ms` de parole ; silence et souffle n'y entrent pas ;
    3. un silence de `max_gap_ms` vide la fenêtre (le locuteur suivant ne
       doit pas hériter de la preuve du précédent) → `insufficient_audio` ;
    4. moins de `evidence_ms` de parole accumulée → `insufficient_audio` ;
    5. sinon l'empreinte de la fenêtre est recalculée tous les `stride_ms` de
       parole nouvelle, et comparée à celle du propriétaire (cosinus → score) ;
       entre deux calculs, le dernier verdict est rendu tel quel.

    Candidats acoustiques (tâche 07, `finish_candidate`), seulement avec
    `short_evidence_ms` :

    - réponse brève : un candidat refermé sans verdict, avec au moins
      `short_evidence_ms` de parole voisée, est jugé une fois sur ce qu'il
      contient, au seuil durci `threshold + short_margin` ; en dessous, rien ;
    - passage de relais : tant que la fenêtre reconnaît le propriétaire, ses
      `short_evidence_ms` les plus récentes sont aussi jugées à chaque
      recalcul ; sous `threshold − short_margin`, le verdict devient
      « pas le propriétaire ». Une autre voix qui enchaîne sans silence ne
      profite donc plus de la preuve du propriétaire que la fenêtre glissante
      garde encore (1,5 s) : environ `short_evidence_ms` + `stride_ms`.
      Coût : une seconde empreinte, courte, par recalcul où le propriétaire
      est reconnu.

    Tout candidat refermé efface la preuve : le suivant est jugé sur de
    l'audio neuf, jamais sur la voix du précédent.

    Mémoire bornée : au plus `evidence_ms` de parole (partagée par la fenêtre
    et le candidat) plus une trame partielle. Thread : un seul fil appelant
    (le port l'exige), aucun verrou ici.
    """

    def __init__(
        self,
        embedder: SpeakerEmbedder,
        owner_embedding: Iterable[float],
        *,
        engine: str,
        profile_id: str,
        threshold: float,
        evidence_ms: int = 1500,
        stride_ms: int = 500,
        max_gap_ms: int = 600,
        gate: SpeechGate | None = None,
        short_evidence_ms: int | None = None,
        short_margin: float = 0.0,
    ) -> None:
        if not 0.0 < float(threshold) <= 1.0:
            raise ValueError("threshold must lie in ]0, 1]")
        if int(evidence_ms) < GATE_FRAME_MS or int(stride_ms) < GATE_FRAME_MS or int(max_gap_ms) < GATE_FRAME_MS:
            raise ValueError("evidence_ms, stride_ms and max_gap_ms must cover at least one gate frame")
        if short_evidence_ms is not None and not GATE_FRAME_MS <= int(short_evidence_ms) < int(evidence_ms):
            raise ValueError("short_evidence_ms must cover a gate frame and stay below evidence_ms")
        if not 0.0 <= float(short_margin) <= 0.5:
            raise ValueError("short_margin must lie in [0, 0.5]")
        owner = _unit(np.fromiter((float(value) for value in owner_embedding), dtype=np.float64))
        if owner.size != int(embedder.dim):
            raise ValueError("owner embedding dimension does not match the engine")
        self._embedder = embedder
        self._owner = owner
        self.engine = engine
        self.profile_id = profile_id
        self.threshold = float(threshold)
        self.evidence_ms = int(evidence_ms)
        self.stride_ms = int(stride_ms)
        self.max_gap_ms = int(max_gap_ms)
        self.availability = VerifierAvailability.READY
        self._gate = gate or SpeechGate()
        self._rate = 0
        self._frame = 0
        self._carry = np.zeros(0, dtype=np.float32)
        self._voiced: deque[np.ndarray] = deque()
        self._voiced_count = 0
        self._gap_ms = 0
        self._fresh_ms = 0
        self._verdict: SpeakerVerification | None = None
        self.short_evidence_ms = None if short_evidence_ms is None else int(short_evidence_ms)
        self.short_margin = float(short_margin)
        #: Seuil d'un verdict bref, et plancher de la sous-fenêtre récente.
        self.short_threshold = min(1.0, self.threshold + self.short_margin)
        self.handover_floor = max(0.0, self.threshold - self.short_margin)
        # Parole voisée du candidat acoustique en cours : effacée seulement par
        # `finish_candidate` (ou `reset`), pas par un trou — un « oui » peut
        # finir avant que le candidat ne se referme. Mêmes trames que la
        # fenêtre glissante (aucune copie de plus), bornée comme elle.
        self._segment: deque[np.ndarray] = deque()
        self._segment_count = 0
        # Une empreinte a-t-elle déjà jugé ce candidat (fenêtre complète) ?
        self._segment_judged = False
        #: Nombre d'empreintes calculées (mesure CPU, tests), et de verdicts brefs.
        self.embeddings_computed = 0
        self.short_verdicts = 0
        #: Score de la fenêtre complète au dernier recalcul, avant la règle du
        #: passage de relais. Mesure seulement (banc d'essai, tâche 09) :
        #: aucune décision n'en dépend.
        self.last_window_score: float | None = None

    # -- cycle de vie ---------------------------------------------------------

    def reset(self) -> None:
        """Oublier l'audio et la preuve ; le profil et le modèle restent chargés."""

        self._clear_evidence()
        self._clear_segment()
        self._carry = np.zeros(0, dtype=np.float32)
        self._gate.reset()
        load = getattr(self._embedder, "load", None)
        if callable(load):
            # Premier réveil : charger le modèle ici, dans le fil du
            # vérificateur, plutôt qu'au premier verdict.
            load()

    def close(self) -> None:
        self._clear_evidence()
        self._clear_segment()
        close = getattr(self._embedder, "close", None)
        if callable(close):
            close()

    # -- flux -----------------------------------------------------------------

    @property
    def voiced_ms(self) -> int:
        """Parole voisée actuellement dans la fenêtre glissante."""

        return self._voiced_count * 1000 // self._rate if self._rate else 0

    def process(self, pcm: bytes, sample_rate: int) -> SpeakerVerification:
        rate = int(sample_rate)
        if rate <= 0:
            raise ValueError("sample_rate must be positive")
        if rate != self._rate:
            # Changement de fréquence : l'audio d'avant n'est plus comparable.
            self._rate = rate
            self._frame = rate * GATE_FRAME_MS // 1000
            self._carry = np.zeros(0, dtype=np.float32)
            self._clear_evidence()
            self._clear_segment()
        samples = pcm16_to_float(pcm)
        if self._carry.size:
            samples = np.concatenate([self._carry, samples])
        count = samples.size // self._frame
        self._carry = samples[count * self._frame :].copy()
        window = self._window_samples()
        for index in range(count):
            frame = samples[index * self._frame : (index + 1) * self._frame]
            if self._gate.update(level_db(frame)):
                voiced = frame.copy()
                self._voiced.append(voiced)
                self._voiced_count += frame.size
                self._fresh_ms += GATE_FRAME_MS
                self._gap_ms = 0
                while self._voiced_count - self._voiced[0].size >= window:
                    self._voiced_count -= self._voiced.popleft().size
                if self.short_evidence_ms is not None:
                    self._segment.append(voiced)
                    self._segment_count += frame.size
                    while self._segment_count - self._segment[0].size >= window:
                        self._segment_count -= self._segment.popleft().size
            else:
                self._gap_ms += GATE_FRAME_MS
                if self._gap_ms >= self.max_gap_ms:
                    self._clear_evidence()
        if self._voiced_count < window:
            return self._insufficient()
        if self._verdict is None or self._fresh_ms >= self.stride_ms:
            self._verdict = self._score()
        return self._verdict

    def finish_candidate(self, *, judge: bool = True) -> SpeakerVerification:
        """Le candidat acoustique vient de se refermer (tâche 07, capacité optionnelle du port).

        `judge` (aucun verdict n'a été rendu dans ce candidat) : la parole du
        candidat est jugée une fois si elle atteint `short_evidence_ms` sans
        avoir déjà été jugée — seuil durci `short_threshold`. Sinon, ou sans
        règle brève : `insufficient_audio`. Dans tous les cas la preuve est
        oubliée ensuite : le candidat suivant repart d'un audio neuf.
        """

        verdict = SpeakerVerification(
            status=VerificationStatus.INSUFFICIENT_AUDIO,
            engine=self.engine,
            evidence_ms=self._segment_ms(),
            profile_id=self.profile_id,
        )
        try:
            short = self.short_evidence_ms
            if judge and short is not None and not self._segment_judged and self._rate:
                if self._segment_count >= self._rate * short // 1000:
                    score = self._embed_score(list(self._segment))
                    self.short_verdicts += 1
                    verdict = SpeakerVerification(
                        status=VerificationStatus.OK,
                        engine=self.engine,
                        owner_score=score,
                        owner_detected=score >= self.short_threshold,
                        evidence_ms=self._segment_ms(),
                        profile_id=self.profile_id,
                    )
        finally:
            self._clear_evidence()
            self._clear_segment()
        return verdict

    # -- interne --------------------------------------------------------------

    def _window_samples(self) -> int:
        return self._rate * self.evidence_ms // 1000

    def _segment_ms(self) -> int:
        return self._segment_count * 1000 // self._rate if self._rate else 0

    def _clear_evidence(self) -> None:
        self._voiced.clear()
        self._voiced_count = 0
        self._gap_ms = 0
        self._fresh_ms = 0
        self._verdict = None

    def _clear_segment(self) -> None:
        self._segment.clear()
        self._segment_count = 0
        self._segment_judged = False

    def _insufficient(self) -> SpeakerVerification:
        return SpeakerVerification(
            status=VerificationStatus.INSUFFICIENT_AUDIO,
            engine=self.engine,
            evidence_ms=self.voiced_ms,
            profile_id=self.profile_id,
        )

    def _embed_score(self, frames: list[np.ndarray]) -> float:
        audio = resample(np.concatenate(frames), self._rate, int(self._embedder.sample_rate))
        embedding = _unit(self._embedder.embed(audio))
        if embedding.size != self._owner.size:
            raise ValueError("engine returned an embedding of unexpected dimension")
        self.embeddings_computed += 1
        return owner_score_from_cosine(float(np.dot(embedding, self._owner)))

    def _score(self) -> SpeakerVerification:
        voiced = list(self._voiced)
        score = self._embed_score(voiced)
        self.last_window_score = score
        self._fresh_ms = 0
        self._segment_judged = True
        detected = score >= self.threshold
        evidence_ms = self.voiced_ms
        short = self.short_evidence_ms
        if detected and short is not None:
            # Passage de relais sans silence : la fenêtre glissante garde
            # encore la voix du propriétaire, la plus récente parole peut déjà
            # être celle d'un autre. Elle seule, sous le plancher, suffit à
            # dire « pas le propriétaire ».
            recent = np.concatenate(voiced)[-(self._rate * short // 1000):]
            recent_score = self._embed_score([recent])
            if recent_score < self.handover_floor:
                score, detected, evidence_ms = recent_score, False, recent.size * 1000 // self._rate
        return SpeakerVerification(
            status=VerificationStatus.OK,
            engine=self.engine,
            owner_score=score,
            owner_detected=detected,
            evidence_ms=evidence_ms,
            profile_id=self.profile_id,
        )


# -- enrôlement -----------------------------------------------------------------

#: Parole voisée minimale pour enrôler : en dessous, l'empreinte de référence
#: dépend trop de la phrase lue. 20 à 30 s sont recommandées.
MIN_ENROLLMENT_VOICED_MS = 10_000
#: Découpe de l'enrôlement : des segments de la taille des fenêtres jugées en
#: direct rendent des scores comparables ; leur moyenne lisse la phrase lue.
ENROLLMENT_SEGMENT_MS = 3000
_MIN_SEGMENT_MS = 1000


@dataclass(frozen=True, slots=True)
class Enrollment:
    """Empreinte de référence et ce qui la justifie (sans audio)."""

    embedding: tuple[float, ...]
    voiced_ms: int
    segments: int
    #: Similarité minimale segment ↔ référence : basse, elle trahit plusieurs
    #: voix ou beaucoup de bruit dans l'enregistrement.
    consistency: float


def enroll_embedding(
    embedder: SpeakerEmbedder,
    clips: Iterable[tuple[np.ndarray, int]],
    *,
    min_voiced_ms: int = MIN_ENROLLMENT_VOICED_MS,
    segment_ms: int = ENROLLMENT_SEGMENT_MS,
) -> Enrollment:
    """Empreinte du propriétaire à partir d'enregistrements mono flottants.

    Chaque clip passe par la porte de parole puis est ramené à la fréquence du
    moteur ; la parole voisée est découpée en segments, dont les empreintes
    unitaires sont moyennées. Trop peu de parole : `EnrollmentError`.
    """

    target = int(embedder.sample_rate)
    voiced: list[np.ndarray] = []
    for samples, rate in clips:
        mono = np.asarray(samples, dtype=np.float32).reshape(-1)
        kept = voiced_samples(mono, int(rate))
        if kept.size:
            voiced.append(resample(kept, int(rate), target))
    audio = np.concatenate(voiced) if voiced else np.zeros(0, dtype=np.float32)
    voiced_ms = audio.size * 1000 // target
    if voiced_ms == 0:
        raise EnrollmentError("enrollment_no_speech", "Aucune parole détectée dans l'enregistrement.")
    if voiced_ms < int(min_voiced_ms):
        raise EnrollmentError(
            "enrollment_too_short",
            f"Seulement {voiced_ms / 1000:.1f} s de parole détectée ; il en faut au moins "
            f"{int(min_voiced_ms) / 1000:.0f} s (20 à 30 s recommandées).",
        )
    size = target * int(segment_ms) // 1000
    minimum = target * _MIN_SEGMENT_MS // 1000
    units = [
        _unit(embedder.embed(audio[start : start + size]))
        for start in range(0, audio.size, size)
        if audio[start : start + size].size >= minimum
    ]
    reference = _unit(np.mean(units, axis=0))
    consistency = min(float(np.dot(unit, reference)) for unit in units)
    return Enrollment(
        embedding=tuple(float(value) for value in reference),
        voiced_ms=int(voiced_ms),
        segments=len(units),
        consistency=round(consistency, 3),
    )
