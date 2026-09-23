"""Rééchantillonnage PCM16 **continu**, avec état entre deux blocs.

Pourquoi un troisième rééchantillonneur dans ce dépôt, et pas l'un des deux
existants :

- `jarvis.audio.owner_verifier.resample` travaille par FFT et sa propre
  docstring pose la limite : « appelé sur une fenêtre de preuve entière, pas
  trame par trame […] aucun filtre ne traîne d'état entre deux fenêtres non
  contiguës ». Appliqué bloc par bloc à un flux continu, il recolle des
  fenêtres traitées indépendamment : la discontinuité au raccord est un clic à
  50 Hz, exactement dans la bande où un détecteur de mot d'éveil cherche de
  l'énergie.
- `jarvis.testlab.audio.fixtures.resample_pcm16` fait la bonne interpolation,
  mais sans état et depuis `testlab`, que le code de production n'importe pas.

Ce module garde donc le **dernier échantillon du bloc précédent** et la
**position fractionnaire** courante, si bien qu'un flux découpé en blocs rend
exactement ce que rendrait le même flux passé d'un coup (à l'arrondi entier
près). C'est l'invariant que fixe `test_presentation_audio_capture.py`.

Interpolation linéaire, pas de filtre anti-repliement. Limite assumée et
écrite : à la descente (24 kHz vers 16 kHz), le contenu entre 8 et 12 kHz se
replie. C'est acceptable pour un détecteur de mot d'éveil — Porcupine est
entraîné sur des micros qui bornent déjà cette bande — et ce ne l'est pas pour
de la transcription. Un abonné qui transcrit doit demander la fréquence du hub
et ne pas passer par ici.

Rien n'est persisté : l'état tient en un entier et un flottant.
"""

from __future__ import annotations

import array
import math

_BYTES_PER_SAMPLE = 2  # int16 mono


class StreamingPcm16Resampler:
    """Interpolation linéaire mono int16, continue d'un bloc au suivant.

    Non thread-safe par construction : un rééchantillonneur appartient à un seul
    abonné et n'est appelé que depuis la boucle qui vide sa file — jamais depuis
    le thread PortAudio, où aucun travail de ce poids n'a le droit d'entrer.
    """

    def __init__(self, *, source_rate: int, target_rate: int) -> None:
        source_rate, target_rate = int(source_rate), int(target_rate)
        if source_rate <= 0 or target_rate <= 0:
            raise ValueError("sample rates must be positive")
        self.source_rate = source_rate
        self.target_rate = target_rate
        self.ratio = source_rate / target_rate
        #: Dernier échantillon du bloc précédent : le point de gauche de la
        #: première interpolation du bloc suivant. Sans lui, chaque bloc
        #: repartirait de son propre premier échantillon et le raccord
        #: sauterait.
        self._previous: int | None = None
        #: Position du prochain échantillon de sortie, exprimée dans l'index des
        #: échantillons d'entrée du bloc courant. Reportée d'un bloc à l'autre.
        self._position = 0.0
        #: Compteurs observables : une conversion silencieusement inactive est
        #: un défaut qu'il faut pouvoir constater depuis un test.
        self.frames_in = 0
        self.frames_out = 0

    @property
    def passthrough(self) -> bool:
        return self.source_rate == self.target_rate

    def reset(self) -> None:
        """Repartir d'un flux neuf (nouvelle capture, abonnement réattaché)."""

        self._previous = None
        self._position = 0.0

    def process(self, pcm: bytes) -> bytes:
        """Convertir un bloc, en gardant la continuité avec le précédent."""

        if self.passthrough:
            self.frames_in += len(pcm) // _BYTES_PER_SAMPLE
            self.frames_out += len(pcm) // _BYTES_PER_SAMPLE
            return pcm
        if len(pcm) % _BYTES_PER_SAMPLE:
            # Un bloc tronqué au milieu d'un échantillon vient d'un mauvais
            # découpage en amont : le dire plutôt que rendre du bruit.
            raise ValueError("PCM16 block size must be a multiple of two bytes")
        source = array.array("h")
        source.frombytes(pcm)
        if not source:
            return b""
        self.frames_in += len(source)

        # Index virtuel -1 : l'échantillon reporté du bloc précédent. La
        # position reportée est toujours > -1 (voir la sortie de boucle), donc
        # `previous` est consulté exactement quand il existe.
        previous = self._previous if self._previous is not None else source[0]
        position = self._position
        out = array.array("h")
        last_index = len(source) - 1
        while position <= last_index:
            left_index = math.floor(position)
            fraction = position - left_index
            left = previous if left_index < 0 else source[left_index]
            right_index = left_index + 1
            # `position <= last_index` garantit `right_index <= last_index` dès
            # que `fraction > 0` : on interpole toujours, on n'extrapole jamais.
            right = source[right_index] if right_index <= last_index else left
            out.append(_clamp16(left + (right - left) * fraction))
            position += self.ratio

        self._previous = source[last_index]
        # Reporter la position dans le repère du bloc suivant : l'échantillon
        # reporté y vaut -1, donc on retranche la longueur du bloc consommé.
        self._position = position - len(source)
        self.frames_out += len(out)
        return out.tobytes()


def _clamp16(value: float) -> int:
    rounded = int(round(value))
    if rounded > 32767:
        return 32767
    if rounded < -32768:
        return -32768
    return rounded
