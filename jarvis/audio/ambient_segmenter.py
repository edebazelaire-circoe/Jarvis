"""Découper la parole continue de la salle en énonciations bornées.

Pourquoi ce module existe alors que le dépôt a déjà de la détection d'énergie :
`jarvis.audio.duplex` et `jarvis.audio.owner_verifier` savent tous les deux
dire « cette trame contient de la parole », et c'est exactement ce qu'on leur
reprend — `frame_db` pour le niveau, `SpeechGate` pour le plancher adaptatif.
Ce qu'aucun des deux ne fait, et que la lane ambiante exige, c'est **une
frontière d'énonciation** : quand une phrase commence, quand elle finit, et
comment garantir qu'elle ne dure pas trois minutes.

Ce que ce module garantit
-------------------------

- **Rien n'est illimité.** Une énonciation est coupée d'office à
  `DEFAULT_MAX_UTTERANCE_MS` ; le segment porte alors `truncated=True` et la
  lane en fait une *révision* de la même énonciation plutôt qu'une phrase
  neuve. Sans cette coupe, un orateur qui ne respire pas ferait grossir un
  tampon sans borne — et la mémoire, ici, c'est de l'audio brut.
- **Rien n'est persisté.** Le PCM vit dans un `bytearray` borné et sort dans un
  `AmbientSegment`, dont le `repr` et le `to_payload` ne portent que des
  compteurs. Un `repr()` recopié dans un journal suffirait à faire fuir de
  l'audio brut dans un fichier, ce que ce dépôt interdit partout
  (`jarvis/audio/duplex.py`, `jarvis/runtime/realtime_audio.py`).
- **Aucune conversion de fréquence.** Le segmenteur travaille à la fréquence du
  hub, telle quelle. `docs/presentation-audio-capture.md` § 7 pose la règle :
  le rééchantillonneur du hub est une interpolation linéaire sans filtre
  anti-repliement, acceptable pour un moteur de mot d'éveil, **pas pour de la
  transcription**. La lane s'abonne donc à `sample_rate=None` et ce qui sort
  d'ici est du PCM d'origine.

Discipline : un segmenteur appartient à une seule lane et n'est appelé que
depuis la boucle qui vide sa file d'abonné — jamais depuis le thread PortAudio,
où aucun travail de ce poids n'a le droit d'entrer.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from jarvis.audio.duplex import frame_db
from jarvis.audio.owner_verifier import SpeechGate

_BYTES_PER_SAMPLE = 2  # int16 mono

#: Trame d'analyse. 20 ms, la même que `owner_verifier.GATE_FRAME_MS`, et pour
#: la même raison : assez court pour suivre les pauses entre les mots, assez
#: long pour qu'un clic isolé pèse peu.
FRAME_MS = 20

#: Sous cette durée de parole, ce n'est pas une énonciation : une porte de
#: chaise, un raclement de gorge, un « mm ». Transcrire 200 ms coûte un appel
#: fournisseur pour rendre du vide.
DEFAULT_MIN_UTTERANCE_MS = 500

#: Silence qui clôt une énonciation. 700 ms : au-dessus des pauses entre deux
#: mots d'une même phrase (~200-400 ms à l'oral soutenu), en dessous de la
#: pause entre deux phrases. C'est aussi l'ordre de grandeur du
#: `silence_duration_ms` par défaut du VAD serveur du fournisseur Realtime
#: (1500 ms), délibérément plus court ici : la lane ambiante préfère des
#: énonciations un peu trop découpées à un fil de séance en retard.
DEFAULT_SILENCE_HANGOVER_MS = 700

#: Coupe d'office. 12 s : au-delà, l'appel de transcription devient long, le
#: fil de séance prend du retard, et le tampon audio pèse
#: 12 x 24000 x 2 = 576 Ko. Un orateur qui enchaîne est donc transcrit par
#: tranches révisées, jamais gardé en attente.
DEFAULT_MAX_UTTERANCE_MS = 12000

#: Ce qu'on garde *avant* la première trame voisée, pour ne pas manger l'attaque
#: de la première syllabe (consonne sourde, montée d'énergie). Même idée, même
#: ordre de grandeur que `OWNER_REPLAY_MARGIN_MS` dans `duplex`.
DEFAULT_LEAD_IN_MS = 200


@dataclass(frozen=True, slots=True)
class AmbientSegment:
    """Une énonciation découpée, prête à transcrire. **Mémoire seulement.**

    `pcm` est exclu du `repr` et n'apparaît dans aucune forme journalisable :
    `to_payload()` ne rend que des compteurs, exactement comme
    `CommandPreRoll.to_payload()` (`jarvis/runtime/presentation_audio.py`).
    """

    sequence: int
    pcm: bytes = field(repr=False)
    sample_rate: int
    #: Décalage, en secondes de capture, du début de l'énonciation depuis
    #: l'ouverture du segmenteur. Compté en trames, jamais lu sur une horloge
    #: murale : un test doit pouvoir rejouer la même séquence deux fois.
    started_at_s: float
    duration_s: float
    #: La coupe de durée maximale a interrompu la phrase : la suite arrivera
    #: dans le segment suivant et la lane en fera une révision.
    truncated: bool = False

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("segment sequence must be a positive integer")
        if not isinstance(self.pcm, (bytes, bytearray)):
            raise TypeError("segment pcm must be bytes")
        if int(self.sample_rate) <= 0:
            raise ValueError("segment sample rate must be positive")

    @property
    def frames(self) -> int:
        return len(self.pcm) // _BYTES_PER_SAMPLE

    def __repr__(self) -> str:  # pragma: no cover - forme de trace
        return (
            f"AmbientSegment(sequence={self.sequence}, duration_s={self.duration_s:.2f}, "
            f"bytes={len(self.pcm)}, truncated={self.truncated})"
        )

    def to_payload(self) -> dict[str, Any]:
        """Journalisable : des compteurs, jamais un octet de PCM."""

        return {
            "sequence": self.sequence,
            "started_at_s": round(float(self.started_at_s), 3),
            "duration_s": round(float(self.duration_s), 3),
            "frames": self.frames,
            "bytes": len(self.pcm),
            "sample_rate": self.sample_rate,
            "truncated": self.truncated,
        }


class AmbientSegmenter:
    """Blocs PCM en entrée, énonciations bornées en sortie.

    Machine à deux états — silence, parole — plus un délai de retombée. Chaque
    transition est comptée, parce qu'un segmenteur qui ne rend jamais rien et
    un segmenteur qui n'entend rien se ressemblent beaucoup vus d'en haut.
    """

    def __init__(
        self,
        *,
        sample_rate: int,
        min_utterance_ms: int = DEFAULT_MIN_UTTERANCE_MS,
        silence_hangover_ms: int = DEFAULT_SILENCE_HANGOVER_MS,
        max_utterance_ms: int = DEFAULT_MAX_UTTERANCE_MS,
        lead_in_ms: int = DEFAULT_LEAD_IN_MS,
        gate: SpeechGate | None = None,
    ) -> None:
        sample_rate = int(sample_rate)
        if sample_rate <= 0:
            raise ValueError("sample rate must be positive")
        if int(max_utterance_ms) < int(min_utterance_ms):
            raise ValueError("max utterance must not be shorter than the minimum")
        self.sample_rate = sample_rate
        self.frame_bytes = max(2, (sample_rate * FRAME_MS // 1000) * _BYTES_PER_SAMPLE)
        self.min_frames = max(1, int(min_utterance_ms) // FRAME_MS)
        self.hangover_frames = max(1, int(silence_hangover_ms) // FRAME_MS)
        self.max_frames = max(self.min_frames, int(max_utterance_ms) // FRAME_MS)
        self.lead_in_frames = max(0, int(lead_in_ms) // FRAME_MS)
        self._gate = gate if gate is not None else SpeechGate()
        self._carry = bytearray()
        self._lead: deque[bytes] = deque(maxlen=self.lead_in_frames or 1)
        self._voice = bytearray()
        self._voiced_frames = 0
        self._silence_run = 0
        self._speaking = False
        self._sequence = 0
        #: Rang de la trame courante depuis l'ouverture : c'est l'horloge du
        #: segmenteur, et elle ne dépend d'aucune horloge murale.
        self._frame_index = 0
        self._segment_start_frame = 0
        #: Comptabilité observable. Une contre-pression, une coupe ou un rejet
        #: qu'on ne peut pas compter est une intention, pas une politique.
        self.blocks_in = 0
        self.frames_in = 0
        self.voiced_frames_total = 0
        self.segments_out = 0
        self.forced_cuts = 0
        self.discarded_short = 0

    # -- horloge interne ---------------------------------------------------

    @property
    def frame_s(self) -> float:
        return (self.frame_bytes // _BYTES_PER_SAMPLE) / self.sample_rate

    @property
    def speaking(self) -> bool:
        return self._speaking

    @property
    def pending_bytes(self) -> int:
        """Ce que le segmenteur retient en ce moment. Toujours borné."""

        return len(self._voice) + len(self._carry) + sum(len(item) for item in self._lead)

    # -- entrée ------------------------------------------------------------

    def push(self, block: bytes) -> tuple[AmbientSegment, ...]:
        """Absorber un bloc du hub, rendre les énonciations qu'il a closes.

        Un bloc du hub ne fait pas un nombre entier de trames de 20 ms (50 ms à
        24 kHz en fait deux et demie) : le reste est reporté, sinon une trame
        sur deux serait analysée à cheval et le plancher adaptatif suivrait du
        bruit de découpe plutôt que la salle.
        """

        if not isinstance(block, (bytes, bytearray)):
            raise TypeError("block must be bytes")
        self.blocks_in += 1
        self._carry.extend(block)
        out: list[AmbientSegment] = []
        while len(self._carry) >= self.frame_bytes:
            frame = bytes(self._carry[: self.frame_bytes])
            del self._carry[: self.frame_bytes]
            segment = self._consume_frame(frame)
            if segment is not None:
                out.append(segment)
        return tuple(out)

    def flush(self) -> tuple[AmbientSegment, ...]:
        """Clore ce qui est en cours. Appelé à l'arrêt de la lane.

        Une énonciation trop courte est **jetée et comptée**, pas rendue : la
        transcrire coûterait un appel fournisseur pour un raclement de gorge.
        """

        if not self._speaking:
            self._reset_voice()
            return ()
        segment = self._close(truncated=False)
        return (segment,) if segment is not None else ()

    def reset(self) -> None:
        """Repartir de zéro : nouvelle séance, ou capture reprise après perte."""

        self._carry.clear()
        self._lead.clear()
        self._reset_voice()
        self._gate.reset()

    # -- machine à états ---------------------------------------------------

    def _consume_frame(self, frame: bytes) -> AmbientSegment | None:
        self._frame_index += 1
        self.frames_in += 1
        voiced = self._gate.update(frame_db(frame))
        if voiced:
            self.voiced_frames_total += 1

        if not self._speaking:
            if not voiced:
                self._lead.append(frame)
                return None
            # Attaque : on repart du souffle gardé d'avance pour ne pas manger
            # la première syllabe.
            self._speaking = True
            self._silence_run = 0
            self._voiced_frames = 1
            lead = list(self._lead)
            self._lead.clear()
            self._voice = bytearray(b"".join(lead))
            self._voice.extend(frame)
            self._segment_start_frame = self._frame_index - len(lead)
            return None

        self._voice.extend(frame)
        if voiced:
            self._voiced_frames += 1
            self._silence_run = 0
        else:
            self._silence_run += 1

        held = len(self._voice) // self.frame_bytes
        if held >= self.max_frames:
            # Coupe d'office : la phrase continue, mais le tampon ne grossit
            # pas. La suite sera une révision de la même énonciation.
            self.forced_cuts += 1
            return self._close(truncated=True)
        if self._silence_run >= self.hangover_frames:
            return self._close(truncated=False)
        return None

    def _close(self, *, truncated: bool) -> AmbientSegment | None:
        pcm = bytes(self._voice)
        voiced = self._voiced_frames
        start_frame = self._segment_start_frame
        self._reset_voice()
        # Une coupe d'office n'est pas une fin de phrase : le segmenteur reste
        # « en parole », sinon le silence de retombée serait recompté et la
        # suite de la phrase commencerait par une attaque fantôme.
        if truncated:
            self._speaking = True
            self._segment_start_frame = self._frame_index
            self._voiced_frames = 0
        if voiced < self.min_frames:
            self.discarded_short += 1
            return None
        self._sequence += 1
        self.segments_out += 1
        return AmbientSegment(
            sequence=self._sequence,
            pcm=pcm,
            sample_rate=self.sample_rate,
            started_at_s=round(start_frame * self.frame_s, 6),
            duration_s=round(len(pcm) // _BYTES_PER_SAMPLE / self.sample_rate, 6),
            truncated=truncated,
        )

    def _reset_voice(self) -> None:
        self._voice = bytearray()
        self._voiced_frames = 0
        self._silence_run = 0
        self._speaking = False
        self._lead.clear()

    # -- observation -------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        return {
            "sample_rate": self.sample_rate,
            "frame_ms": FRAME_MS,
            "min_frames": self.min_frames,
            "hangover_frames": self.hangover_frames,
            "max_frames": self.max_frames,
            "speaking": self._speaking,
            "pending_bytes": self.pending_bytes,
            "blocks_in": self.blocks_in,
            "frames_in": self.frames_in,
            "voiced_frames": self.voiced_frames_total,
            "segments_out": self.segments_out,
            "forced_cuts": self.forced_cuts,
            "discarded_short": self.discarded_short,
        }


__all__ = [
    "DEFAULT_LEAD_IN_MS",
    "DEFAULT_MAX_UTTERANCE_MS",
    "DEFAULT_MIN_UTTERANCE_MS",
    "DEFAULT_SILENCE_HANGOVER_MS",
    "FRAME_MS",
    "AmbientSegment",
    "AmbientSegmenter",
]
