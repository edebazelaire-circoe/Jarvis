"""Capture en duplex : garde d'écho et détection locale de la parole de l'utilisateur.

Le mode continu garde le micro ouvert pendant que les haut-parleurs jouent.
Sans traitement, le fournisseur entend JARVIS se parler à lui-même : son VAD
ouvre un tour sur l'écho, la transcription rend « Entendu. », et ce faux tour
part au cerveau comme une demande. C'est la boucle observée sur poste réel le
11 septembre 2026 (voir `docs/fixes/voice-duplex/`).

Trois étages, tous exécutés dans le thread de capture PortAudio :

1. **Annulation d'écho** (optionnelle) : chaque trame de 10 ms du micro passe
   par un `EchoCanceller`, nourri en parallèle de ce qui a été réellement joué.
   Les deux flux avancent au même pas — une trame de référence consommée par
   trame capturée — si bien que la référence précède toujours l'écho, ce dont
   l'annuleur a besoin pour converger.
2. **Détection de parole proche** (`NearEndDetector`) : pendant que JARVIS
   parle, une trame n'est comptée comme parole de l'utilisateur que si elle
   dépasse à la fois le plancher de bruit et l'écho attendu d'une marge nette.
   L'écho attendu est appris en continu : très bas derrière l'annuleur, élevé
   sans lui.
3. **Garde** : tant que JARVIS parle et qu'aucune parole proche n'est
   confirmée, le fournisseur reçoit du silence à la place du micro. À la
   confirmation, la garde s'ouvre en envoyant d'abord les dernières centaines de
   millisecondes captées, pour que le début de la phrase ne soit pas perdu, et
   un signal `near_end` part vers le bridge, qui décide du barge-in.

Un observateur (`CaptureObserver`) peut en outre recevoir chaque trame nettoyée
— la vérification du locuteur en ombre, `jarvis/audio/speaker_shadow.py` —
avec ce que la capture savait d'elle (`CaptureFrameContext` : parole proche,
JARVIS audible, garde, temps du flux), sans rien changer à ce qui part ni aux
signaux.

Solo Owner (tâches 06 et 07) : avec un tampon de vérification du propriétaire
(`owner_buffer_ms`) et la garde confiée au propriétaire (`set_owner_gate`),
le micro n'atteint plus le fournisseur que par le flux que le propriétaire
ouvre — que JARVIS parle ou se taise : le verrou acoustique n'ouvre plus rien,
et le silence de JARVIS non plus. C'est la confirmation du propriétaire
(`open_owner_flow`) qui ouvre le flux : le préfixe jamais envoyé depuis le
début estimé de sa parole part d'abord, une seule fois et dans l'ordre, puis
le direct (`OwnerReplay`). C'est le point de filtrage le plus tôt possible :
une autre voix n'y devient ni transcript, ni `speech_started`, ni réponse.

Rien n'est persisté : l'audio ne vit que dans des tampons bornés en mémoire.
"""

from __future__ import annotations

import math
import os
import threading
from collections import deque
from dataclasses import dataclass
from itertools import islice
from typing import Protocol

import numpy as np

NEAR_END = "near_end"
#: Signal de la capture : un préfixe du propriétaire vient d'être rejoué
#: (`CaptureProcessor.take_owner_replays`).
OWNER_REPLAY = "owner_replay"
#: Marge rejouée avant le début estimé de la parole du propriétaire : la
#: première trame « proche » du détecteur suit l'attaque réelle de la syllabe
#: (consonne sourde, montée d'énergie). Jamais appliquée quand un étranger
#: parlait juste avant dans le même candidat.
OWNER_REPLAY_MARGIN_MS = 150

FRAME_MS = 10
_BYTES_PER_SAMPLE = 2  # int16 mono
_SILENCE_DB = -120.0
#: Avance maximale de la référence sur l'écho que l'estimateur CHERCHE : au
#: delà, le pic de corrélation ne désigne plus un trajet acoustique.
MAX_ECHO_LEAD_FRAMES = 100
#: Avance maximale qu'on RETARDE réellement la référence du détecteur. Une
#: liaison Bluetooth ajoute 150 à 300 ms au tampon du périphérique, jamais six
#: cents : au-delà, une mesure aberrante ferait croire à JARVIS qu'il parle
#: encore, et la garde resterait fermée sur l'utilisateur.
MAX_APPLIED_LEAD_FRAMES = 60


def _env_float(name: str, default: float, *, minimum: float = 0.0, maximum: float | None = None) -> float:
    """Seuil réglable par l'environnement, borné, sans jamais lever.

    Une valeur illisible ou hors bornes retombe sur le défaut : un `.env` mal
    tapé ne doit pas rendre le micro sourd.
    """

    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip().replace(",", "."))
    except ValueError:
        return default
    if value != value or value < minimum:  # NaN inclus
        return default
    return value if maximum is None or value <= maximum else default


def _env_flag(name: str, default: bool) -> bool:
    """Interrupteur d'environnement tolérant : `0`, `non`, `false` coupent."""

    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in {"0", "no", "non", "false", "off"}


def frame_db(frame: bytes) -> float:
    """Énergie RMS d'une trame int16, en dB par rapport à la pleine échelle."""

    if not frame:
        return _SILENCE_DB
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float64)
    power = float(np.mean(samples * samples)) / (32768.0 * 32768.0)
    return 10.0 * math.log10(power) if power > 1e-12 else _SILENCE_DB


class EchoCanceller(Protocol):
    """Annuleur d'écho travaillant par trames de 10 ms.

    `process_render` reçoit ce qui part vers les haut-parleurs, `process_capture`
    ce qui vient du micro, et rend la capture nettoyée. Les deux sont appelés
    depuis le même thread, dans cet ordre, une fois par trame capturée.
    """

    def process_render(self, frame: bytes) -> None: ...

    def process_capture(self, frame: bytes) -> bytes: ...


@dataclass(frozen=True, slots=True)
class CaptureFrameContext:
    """Ce que la capture savait d'une trame au moment de la traiter.

    Calculé dans le thread PortAudio, sans E/S ni copie d'audio : quelques
    booléens déjà connus de la garde. Immuable, l'observateur peut le garder.

    - `stream_ms` : début de la trame, en millisecondes d'audio capté depuis
      le dernier `CaptureProcessor.reset()` (horloge du flux, pas l'horloge
      murale) ;
    - `sample_rate` : fréquence de la trame ;
    - `near_end` : la trame, prise seule, dépasse le plancher de bruit — et,
      quand JARVIS parle, l'écho attendu — de la marge du `NearEndDetector`.
      Candidat acoustique, jamais une identité (D03) ;
    - `far_end` : JARVIS parle ou vient de se taire (`far_recent`) : un écho
      résiduel est possible dans cette trame ;
    - `near_end_latched` : parole proche confirmée (verrou du détecteur) ;
    - `gate_open` : le fournisseur entend le micro après cette trame.
    """

    stream_ms: int
    sample_rate: int
    near_end: bool
    far_end: bool
    near_end_latched: bool
    gate_open: bool


@dataclass(frozen=True, slots=True)
class NearEndDiagnostics:
    """Ce que le détecteur savait à la dernière trame. Scalaires seulement.

    Construit à la demande, depuis la boucle asyncio, pour la trace du bridge :
    sans ces chiffres, un faux barge-in sur haut-parleurs ne se diagnostique
    qu'en devinant (poste réel, 18/09/2026). Jamais d'audio, jamais d'empreinte.

    - `mic_db` / `ref_env_db` : énergie de la trame nettoyée, et enveloppe de
      la référence sur la fenêtre de maintien ;
    - `floor_db` : plancher de bruit appris dans les silences de JARVIS ;
    - `coupling_db` : écart appris entre l'écho résiduel et la référence ;
    - `excess_db` : `mic_db - ref_env_db` de la trame ;
    - `margin_db` : de combien la trame dépasse la plus contraignante de ses
      deux bornes — plancher plus `floor_margin_db`, écho attendu plus
      `echo_margin_db`. Positif, la trame est « proche » ; c'est le chiffre qui
      dit de combien l'écho d'une pièce a franchi la marge ;
    - `far_frames` : trames où JARVIS était nettement audible depuis le début
      de la session ; `warming_up` : moins que `warmup_frames`, le couplage est
      donc tenu à son plancher de chauffe ;
    - `latched` : parole proche confirmée ; `guard_open` : le fournisseur
      entend le micro ;
    - `echo_lead_ms` / `echo_lead_confidence` : avance mesurée de la référence
      sur l'écho, et la corrélation qui l'a établie (`EchoDelayEstimator`).
      C'est le paramètre dont dépend toute l'annulation : sous 25 ms, AEC3
      passe de 50 dB d'atténuation à 10 dB. Zéro veut dire « jamais mesurée ».
    """

    mic_db: float
    ref_env_db: float
    floor_db: float
    coupling_db: float
    excess_db: float
    margin_db: float
    far_frames: int
    warming_up: bool
    latched: bool
    guard_open: bool
    echo_lead_ms: int = 0
    echo_lead_confidence: float = 0.0

    def as_data(self) -> dict[str, object]:
        """Forme journalisable : arrondie au dixième de dB, prête pour la trace."""

        return {
            "mic_db": round(self.mic_db, 1),
            "ref_env_db": round(self.ref_env_db, 1),
            "floor_db": round(self.floor_db, 1),
            "coupling_db": round(self.coupling_db, 1),
            "excess_db": round(self.excess_db, 1),
            "margin_db": round(self.margin_db, 1),
            "far_frames": self.far_frames,
            "warming_up": self.warming_up,
            "latched": self.latched,
            "guard_open": self.guard_open,
            "echo_lead_ms": self.echo_lead_ms,
            "echo_lead_confidence": round(self.echo_lead_confidence, 2),
        }


@dataclass(frozen=True, slots=True)
class OwnerReplay:
    """Ce qu'une ouverture du flux par le propriétaire a rejoué (tâche 06).

    Scalaires seulement, en millisecondes de l'horloge du flux de capture
    (`CaptureProcessor.stream_ms`) : jamais d'audio.

    - `owner_onset_ms` : début estimé de la parole du propriétaire, tel que
      reçu ; `requested_from_ms` : ce début moins la marge éventuelle
      (`margin_ms`) ;
    - `from_ms` / `until_ms` : premier instant rejoué et fin du rejeu — l'instant
      où le direct reprend ; `replay_ms` = `until_ms - from_ms` ;
    - `already_sent_ms` : partie de l'intervalle demandé que le fournisseur
      avait déjà reçue (pré-roll, garde ouverte) ou qui précède de l'audio déjà
      envoyé — jamais renvoyée, l'ordre du flux primant ;
    - `clamped_ms` : début demandé plus ancien que le tampon, perdu ;
    - `buffer_ms` : capacité du tampon.
    """

    owner_onset_ms: int
    requested_from_ms: int
    from_ms: int
    until_ms: int
    replay_ms: int
    margin_ms: int
    already_sent_ms: int
    clamped_ms: int
    buffer_ms: int


class CaptureObserver(Protocol):
    """Observateur passif de la capture nettoyée (vérification du locuteur).

    `observe` est appelé dans le thread PortAudio, une fois par trame de 10 ms,
    après l'annulation d'écho et la garde, avec le contexte de la trame : il
    rend la main aussitôt — une file bornée, pas de calcul lourd, pas d'E/S —
    et ne peut rien changer à ce qui part. `reset` suit
    `CaptureProcessor.reset` (capture arrêtée), `close` sa fermeture.
    """

    def observe(self, frame: bytes, context: CaptureFrameContext) -> None: ...

    def reset(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class EchoAlignment:
    """Un réalignement de la référence du détecteur sur la pièce, pour la trace.

    Scalaires seulement : l'avance retenue, celle qu'elle remplace, la
    corrélation qui l'a établie, et l'instant du flux de capture.
    """

    lead_ms: int
    previous_lead_ms: int
    confidence: float
    stream_ms: int

    def as_data(self) -> dict[str, object]:
        return {
            "lead_ms": self.lead_ms,
            "previous_lead_ms": self.previous_lead_ms,
            "confidence": round(self.confidence, 2),
            "stream_ms": self.stream_ms,
        }


class EchoDelayEstimator:
    """Mesure l'avance de la référence sur l'écho, par corrélation d'enveloppes.

    Le couple (référence remise à l'annuleur, micro brut) donne une mesure
    directe du trajet haut-parleurs → micro : la même montée d'énergie
    apparaît dans les deux, décalée du temps que met le son à sortir du tampon
    du périphérique, à traverser la liaison — une enceinte Bluetooth ajoute
    150 à 300 ms — et à revenir. Seules les enveloppes en dB sont gardées :
    500 flottants par flux, jamais d'audio, jamais rien de persisté.

    Pourquoi cette mesure existe (poste réel, 19/09/2026). L'avance de la
    référence est le paramètre dont dépend toute l'annulation : mesurée sur
    AEC3 par `docs/fixes/voice-duplex-bluetooth/`, elle vaut 50 dB
    d'atténuation au-dessus de 25 ms et 4 à 10 dB en dessous. Elle n'était ni
    réglée, ni mesurée, ni visible : la file de référence avançait au rythme
    que le tampon du périphérique avait laissé, et personne ne pouvait dire
    lequel.

    Elle sert ici à une chose : le détecteur compare le micro à la référence
    **telle qu'elle est audible**, donc retardée de cette avance. Sans cela la
    référence se tait pendant que la pièce résonne encore, la fin de chaque
    phrase est jugée contre le seul plancher de bruit, et JARVIS se coupe
    lui-même à chaque phrase. L'annuleur, lui, garde la référence en avance :
    c'est ce dont il a besoin.

    Appelé depuis le thread de capture, une fois par trame. Le tri et la
    corrélation ne tournent qu'une fois par seconde, sur 500 points.
    """

    #: 5 s d'historique : assez pour couvrir plusieurs syllabes de JARVIS.
    HISTORY_FRAMES = 500
    #: Une mesure par seconde au plus.
    PROBE_EVERY_FRAMES = 100
    #: Sans 1,2 s de JARVIS nettement audible dans la fenêtre, il n'y a rien à
    #: corréler : la mesure précédente tient.
    MIN_FAR_FRAMES = 120
    #: Sous cette corrélation, le pic ne désigne rien : la mesure est écartée.
    MIN_CONFIDENCE = 0.4
    #: Les enveloppes sont écrêtées : une trame numériquement nulle (-120 dB)
    #: pèserait autant qu'une syllabe dans la corrélation.
    FLOOR_DB = -85.0

    def __init__(self, *, max_lead_frames: int = MAX_ECHO_LEAD_FRAMES) -> None:
        self.max_lead_frames = max(1, int(max_lead_frames))
        self._mic: deque[float] = deque(maxlen=self.HISTORY_FRAMES)
        self._ref: deque[float] = deque(maxlen=self.HISTORY_FRAMES)
        self._since_probe = 0
        #: Avance retenue, en trames de 10 ms. Négative, l'écho précède sa
        #: propre référence et aucun annuleur ne peut rien : c'est un défaut
        #: de la chaîne, pas du détecteur, et il doit se voir dans la trace.
        self.lead_frames = 0
        self.confidence = 0.0
        #: Faux tant qu'aucune corrélation n'a abouti : `lead_frames` est alors
        #: un défaut, pas une mesure.
        self.measured = False

    @property
    def lead_ms(self) -> int:
        return self.lead_frames * FRAME_MS

    def reset(self) -> None:
        """Nouvelle session : l'historique ne vaut plus, la mesure si.

        Le périphérique n'a pas changé entre deux réveils ; la mesure reste
        donc le meilleur point de départ, et la première corrélation de la
        session suivante la confirmera ou la corrigera.
        """

        self._mic.clear()
        self._ref.clear()
        self._since_probe = 0

    def observe(self, mic_db: float, ref_db: float) -> bool:
        """Intégrer une trame ; rend True quand une mesure vient d'aboutir."""

        self._mic.append(max(self.FLOOR_DB, mic_db))
        self._ref.append(max(self.FLOOR_DB, ref_db))
        self._since_probe += 1
        if self._since_probe < self.PROBE_EVERY_FRAMES or len(self._mic) < self.HISTORY_FRAMES:
            return False
        self._since_probe = 0
        if sum(1 for value in self._ref if value > NearEndDetector.REF_LEARN_DB) < self.MIN_FAR_FRAMES:
            return False
        return self._correlate()

    def _correlate(self) -> bool:
        mic = np.fromiter(self._mic, dtype=np.float64, count=len(self._mic))
        ref = np.fromiter(self._ref, dtype=np.float64, count=len(self._ref))
        mic -= mic.mean()
        ref -= ref.mean()
        norm = float(np.linalg.norm(mic) * np.linalg.norm(ref))
        if norm < 1e-9:
            return False
        centre = len(ref) - 1
        full = np.correlate(mic, ref, mode="full") / norm
        window = full[centre - self.max_lead_frames:centre + self.max_lead_frames + 1]
        index = int(np.argmax(window))
        peak = float(window[index])
        if peak < self.MIN_CONFIDENCE:
            return False
        self.lead_frames = index - self.max_lead_frames
        self.confidence = peak
        self.measured = True
        return True


class NearEndDetector:
    """Décide, trame par trame, si l'utilisateur parle par-dessus JARVIS.

    Toutes les énergies sont en dB pleine échelle, sur des trames de 10 ms.

    - `ref_env` : enveloppe de ce qui a été joué, maximum sur une fenêtre assez
      longue pour couvrir la latence du périphérique et la réverbération.
    - plancher : minimum glissant de l'énergie du micro, mesuré seulement quand
      JARVIS se tait ; une longue réponse ne peut donc pas le faire monter.
    - couplage : écart appris entre l'écho résiduel et `ref_env`. C'est un
      percentile haut des résidus récents, pas leur moyenne : voir
      `_learn_coupling`. Il monte immédiatement — un écho sous-estimé
      déclencherait un faux barge-in — et ne redescend qu'à
      `coupling_decay_db` par trame.

    Une trame est « proche » quand elle dépasse le plancher de `floor_margin_db`
    et l'écho attendu de `echo_margin_db`. La parole est confirmée — et le
    détecteur verrouillé — quand `min_frames` trames proches tombent dans les
    `window_frames` dernières, dont au moins `min_run_frames` d'affilée : une
    syllabe dure bien plus longtemps qu'un clic de clavier ou qu'un choc sur le
    bureau. Le verrou tombe quand JARVIS s'est tu, ou sur `release()` quand le
    bridge juge que ce n'était pas de la parole.

    Le plancher est un percentile bas, borné à `FLOOR_MIN_DB` : la suppression
    de bruit rend des trames quasi nulles pendant sa convergence, et un minimum
    brut ferait passer le moindre souffle pour de la parole.

    Chauffe : un annuleur d'écho a besoin de quelques secondes de parole de
    JARVIS pour converger, et laisse passer des bouffées d'écho entre-temps.
    Pendant les `warmup_frames` premières trames où JARVIS est audible, le
    couplage retenu ne descend pas sous `warmup_coupling_db` : il faut alors
    parler plus fort pour couper JARVIS, mais son propre écho ne le coupe pas.
    """

    REF_SILENCE_DB = -60.0
    REF_LEARN_DB = -40.0
    FLOOR_MIN_DB = -70.0
    FLOOR_MAX_DB = -35.0
    #: Résidus retenus pour le percentile : 6 s de JARVIS nettement audible.
    #: C'est là qu'est la mémoire d'une bouffée — elle pèse sur le percentile
    #: tant qu'elle n'est pas sortie de la fenêtre.
    COUPLING_WINDOW_FRAMES = 600
    #: Tant que la fenêtre n'en contient pas autant, le percentile ne décide
    #: de rien : la valeur initiale, prudente, tient. Une seconde d'écho ne se
    #: résume pas à une trame — et sans ce seuil, la première syllabe de
    #: l'utilisateur suffirait à enseigner au détecteur que la pièce lui
    #: renvoie une voix, donc à le rendre sourd.
    COUPLING_MIN_FRAMES = 100
    #: Le percentile n'est retrié qu'une trame sur cinq : 600 flottants triés
    #: toutes les 50 ms dans le thread PortAudio, soit quelques dizaines de µs.
    COUPLING_REFRESH_FRAMES = 5

    def __init__(
        self,
        *,
        initial_coupling_db: float,
        floor_margin_db: float = 12.0,
        echo_margin_db: float = 10.0,
        window_frames: int = 40,
        min_frames: int = 12,
        min_run_frames: int = 6,
        reference_hold_frames: int = 35,
        tail_frames: int = 25,
        floor_window_frames: int = 200,
        refractory_frames: int = 50,
        warmup_frames: int = 300,
        warmup_coupling_db: float = -15.0,
        coupling_percentile: float = 90.0,
        release_decay_db: float = 0.002,
    ) -> None:
        self.coupling_db = float(initial_coupling_db)
        self.initial_coupling_db = float(initial_coupling_db)
        #: Trames intégrées depuis la création, proches ou non. Sert au bridge
        #: à distinguer « le micro se tait » de « la capture ne tourne plus » :
        #: sans trame, il n'a aucune preuve à exiger.
        self.frames = 0
        #: Compteur cumulé des trames « proches » depuis la création.
        #: Monotone, jamais remis à zéro par `release()` : le bridge en prend
        #: deux instantanés (début et fin de sa fenêtre de confirmation) et la
        #: différence lui dit combien de millisecondes de voix locale ont
        #: réellement été entendues pendant qu'il baissait le volume. Sans lui,
        #: la « parole soutenue » se réduisait à l'état verrouillé du VAD du
        #: fournisseur, que l'écho de JARVIS suffit à tenir ouvert.
        self.voiced_frames = 0
        self.warmup_frames = warmup_frames
        # Écart micro − référence des dernières trames où JARVIS parlait : si
        # une parole supposée est récusée, c'est qu'il s'agissait d'écho, et
        # c'est ce niveau que le couplage doit rattraper.
        self._recent_excess: deque[float] = deque(maxlen=window_frames)
        # Résidus des trames apprenables, pour le percentile (`_learn_coupling`).
        self.coupling_percentile = float(coupling_percentile)
        self._excess_history: deque[float] = deque(maxlen=self.COUPLING_WINDOW_FRAMES)
        self._percentile_db: float | None = None
        self._since_percentile = 0
        # Plancher posé par une preuve : un candidat récusé était de l'écho, et
        # ce niveau-là a été ENTENDU. Il ne redescend qu'avec la parole de
        # JARVIS (`release_decay_db` par trame où il est audible), jamais avec
        # l'horloge : une pièce ne se réapprend qu'en l'écoutant. Le défaut,
        # 0,2 dB par seconde de parole, tient la preuve plusieurs minutes — le
        # temps que le percentile décrive la pièce à son tour — et laisse
        # quand même le passage au casque se rattraper dans la séance.
        self.release_decay_db = float(release_decay_db)
        self._released_db = -math.inf
        self.warmup_coupling_db = warmup_coupling_db
        self._far_frames = 0
        self.floor_db = -60.0
        self.floor_margin_db = floor_margin_db
        self.echo_margin_db = echo_margin_db
        self.min_frames = min_frames
        self.min_run_frames = min_run_frames
        self.tail_frames = tail_frames
        self.refractory_frames = refractory_frames
        self._references: deque[float] = deque(maxlen=reference_hold_frames)
        self._near: deque[bool] = deque(maxlen=window_frames)
        self._quiet_levels: deque[float] = deque(maxlen=floor_window_frames)
        self._frames_since_far = 1 << 30
        self._refractory = 0
        self.latched = False
        #: Verdict brut de la dernière trame (candidat acoustique), lu par
        #: l'observateur de la capture. Informatif : aucune décision du
        #: détecteur n'en dépend. JARVIS silencieux, seule la marge au
        #: plancher compte.
        self.last_near = False
        #: Dernière trame intégrée, pour la trace (`diagnostics()`).
        self.last_mic_db = _SILENCE_DB
        self.last_ref_env_db = _SILENCE_DB
        self.last_margin_db = 0.0
        #: Écart maximal observé à l'instant du verrou. Survit à la remise à
        #: zéro de la fenêtre, donc à la fin de la parole de JARVIS : c'est ce
        #: que `release(learn=True)` rattrape quand la preuve que ce candidat
        #: était de l'écho n'arrive qu'après (transcript écarté, 18/09/2026).
        self.latched_excess_db: float | None = None

    def diagnostics(self, *, guard_open: bool, echo_lead_ms: int = 0,
                    echo_lead_confidence: float = 0.0) -> NearEndDiagnostics:
        """Instantané des niveaux de la dernière trame, pour la trace du bridge."""

        return NearEndDiagnostics(
            mic_db=self.last_mic_db,
            ref_env_db=self.last_ref_env_db,
            floor_db=self.floor_db,
            coupling_db=self.coupling_db,
            excess_db=self.last_mic_db - self.last_ref_env_db,
            margin_db=self.last_margin_db,
            far_frames=self._far_frames,
            warming_up=self._far_frames < self.warmup_frames,
            latched=self.latched,
            guard_open=guard_open,
            echo_lead_ms=echo_lead_ms,
            echo_lead_confidence=echo_lead_confidence,
        )

    @property
    def far_recent(self) -> bool:
        """Vrai tant que JARVIS parle, ou vient juste de se taire."""

        return self._frames_since_far <= self.tail_frames

    def release(self, *, learn: bool = True) -> None:
        """Lever le verrou : la parole supposée n'en était pas.

        C'était donc de l'écho que le couplage appris sous-estimait — après un
        passage du casque aux haut-parleurs, ou un annuleur qui décroche. Or le
        couplage n'apprend que sur des trames jugées « non proches » : sans
        correction, cet écho resterait proche pour toujours, et JARVIS se
        couperait lui-même en boucle. Le couplage remonte donc au niveau
        observé, juste assez pour que ce même écho ne franchisse plus la marge.

        `learn=False` lève le verrou sans rien apprendre : le fournisseur a pu
        confirmer trop tard une vraie voix (17/09/2026, confirmation 140 ms
        après la fenêtre). Apprendre cette voix comme de l'écho rendait JARVIS
        de plus en plus dur à couper, rejet après rejet.

        La preuve arrive parfois bien après le verrou : un barge-in confirmé
        puis coupé, dont le transcript se révèle une hallucination sur l'écho
        (18/09/2026). JARVIS s'est tu entre-temps, la fenêtre est vide, et
        `latched_excess_db` porte alors le niveau à rattraper.
        """

        excess = max(self._recent_excess) if self._recent_excess else self.latched_excess_db
        if learn and excess is not None:
            observed = excess - self.echo_margin_db + 2.0
            self.coupling_db = min(20.0, max(self.coupling_db, observed))
            # La preuve entre aussi dans la fenêtre du percentile : cette
            # bouffée-là avait été jugée « proche », donc écartée de
            # l'apprentissage continu, et c'est précisément celle qu'il faut
            # décrire.
            self._released_db = max(self._released_db, observed)
            self._excess_history.append(excess)
            self._percentile_db = None
        self.latched = False
        self.latched_excess_db = None
        self._reset_window()
        self._refractory = self.refractory_frames

    def _reset_window(self) -> None:
        self._near.clear()
        self._recent_excess.clear()

    def _update_floor(self, mic_db: float) -> None:
        self._quiet_levels.append(mic_db)
        ordered = sorted(self._quiet_levels)
        low = ordered[len(ordered) // 5]
        self.floor_db = min(self.FLOOR_MAX_DB, max(self.FLOOR_MIN_DB, low + 3.0))

    def update(self, mic_db: float, ref_db: float) -> bool:
        """Intégrer une trame ; rend True à l'instant où la parole est confirmée."""

        self.frames += 1
        self._references.append(ref_db)
        ref_env = max(self._references)
        self.last_mic_db, self.last_ref_env_db = mic_db, ref_env
        far_now = ref_env > self.REF_SILENCE_DB
        self._frames_since_far = 0 if far_now else self._frames_since_far + 1
        if not self.far_recent:
            self.last_margin_db = mic_db - (self.floor_db + self.floor_margin_db)
            self._update_floor(mic_db)
            self.last_near = mic_db > self.floor_db + self.floor_margin_db
            self.voiced_frames += 1 if self.last_near else 0
            self.latched = False
            self._reset_window()
            self._refractory = 0
            return False

        coupling = self.coupling_db
        if far_now:
            self._recent_excess.append(mic_db - ref_env)
        if far_now and ref_env > self.REF_LEARN_DB:
            self._far_frames += 1
            if self._released_db > -math.inf:
                self._released_db = max(-60.0, self._released_db - self.release_decay_db)
        if self._far_frames < self.warmup_frames:
            coupling = max(coupling, self.warmup_coupling_db)
        predicted = ref_env + coupling if far_now else -math.inf
        near = mic_db > self.floor_db + self.floor_margin_db and mic_db > predicted + self.echo_margin_db
        self.last_near = near
        self.voiced_frames += 1 if near else 0
        # Ce qui manque à la trame pour franchir la plus contraignante des deux
        # bornes : positif, elle est proche. Diagnostic seul.
        self.last_margin_db = min(
            mic_db - (self.floor_db + self.floor_margin_db),
            mic_db - (predicted + self.echo_margin_db) if far_now else math.inf,
        )
        recently_near = any(self._near)
        self._near.append(near)
        if ref_env > self.REF_LEARN_DB and not self.latched:
            # Appris seulement quand JARVIS est nettement audible : dans ses
            # pauses, le micro ne contient que le bruit ambiant, et l'écart
            # mesuré ne dirait plus rien de l'écho. Une trame « proche » compte
            # comme les autres tant que rien n'est verrouillé : écarter les
            # bouffées de l'apprentissage sous prétexte qu'elles ressemblent à
            # de la parole est précisément ce qui empêchait de les apprendre.
            self._learn_coupling(mic_db - ref_env)
        if self._refractory > 0:
            self._refractory -= 1
            return False
        if (
            not self.latched
            and sum(self._near) >= self.min_frames
            and self._longest_run(self._near) >= self.min_run_frames
        ):
            self.latched = True
            self.latched_excess_db = max(self._recent_excess) if self._recent_excess else None
            return True
        return False

    def _learn_coupling(self, observed: float) -> None:
        """Rapprocher le couplage du niveau que l'écho atteint VRAIMENT.

        Un annuleur d'écho ne laisse pas un résidu constant : il tient
        cinquante décibels la plupart du temps et lâche par bouffées, à chaque
        fois que son alignement se perd — une liaison Bluetooth en produit une
        à chaque réajustement de sa gigue. La moyenne glissante d'avant
        apprenait le résidu TYPIQUE ; sur le poste réel du 19/09/2026 elle
        s'établissait à −59,5 dB pendant que les bouffées, elles, montaient à
        −6 dB de ce qui était joué. Chaque bouffée franchissait la marge de
        trente décibels, devenait « l'utilisateur parle », et JARVIS se coupait
        lui-même phrase après phrase.

        Le couplage suit donc un percentile haut des résidus récents : il
        décrit la bouffée, pas le calme entre deux bouffées. Il monte dès
        qu'une bouffée entre dans la fenêtre — un écho sous-estimé coûte une
        fausse interruption — et ne retombe que lorsqu'elle en sort, six
        secondes de parole de JARVIS plus tard. La mémoire ordinaire est la
        fenêtre elle-même.

        Une preuve vaut plus qu'une statistique : le plancher posé par un
        candidat récusé (`release`) n'est pas soumis au percentile, et ne
        s'efface qu'au rythme de la parole de JARVIS. C'est ce qui manquait le
        18/09 — la moyenne ramenait le couplage sous ce niveau en deux
        secondes, et la bouffée suivante rouvrait la garde.

        Ce que cela change quand l'annulation fonctionne : le percentile des
        résidus est alors lui aussi très bas (−45 dB mesurés sur AEC3 aligné),
        la marge reste large, et couper JARVIS demande la même voix qu'avant.
        Quand elle ne fonctionne pas, JARVIS devient dur à interrompre au lieu
        de s'interrompre tout seul — c'est le bon sens de l'échec.
        """

        self._excess_history.append(observed)
        if len(self._excess_history) < self.COUPLING_MIN_FRAMES:
            # La pièce n'est pas encore décrite : seule une preuve peut bouger
            # le couplage, la valeur initiale tient pour le reste.
            self.coupling_db = min(20.0, max(self.coupling_db, self._released_db))
            return
        self._since_percentile += 1
        if self._percentile_db is None or self._since_percentile >= self.COUPLING_REFRESH_FRAMES:
            self._since_percentile = 0
            ordered = sorted(self._excess_history)
            index = min(len(ordered) - 1, int(self.coupling_percentile / 100.0 * len(ordered)))
            self._percentile_db = ordered[index]
        self.coupling_db = min(20.0, max(-60.0, self._percentile_db, self._released_db))

    @staticmethod
    def _longest_run(values) -> int:  # noqa: ANN001 - itérable de booléens
        best = run = 0
        for value in values:
            run = run + 1 if value else 0
            best = max(best, run)
        return best


class CaptureProcessor:
    """Traitement du micro en mode continu, appelé depuis le thread PortAudio.

    Concurrence : `process()` est appelé par le thread de capture,
    `push_reference()` par le thread d'écriture de la sortie, `clear_reference()`
    et `release_near_end()` par la boucle asyncio. Seule la file de référence et
    la demande de libération sont partagées, sous `_lock` ; l'annuleur et le
    détecteur ne sont touchés que par le thread de capture. L'observateur
    reçoit sa copie depuis le thread de capture et fait lui-même passer le
    travail lourd dans son propre fil.

    Tampon de vérification du propriétaire (Solo Owner, tâche 06), présent
    seulement si `owner_buffer_ms` est donné — la salle ouverte n'en a pas :

    - distinct du pré-roll : le pré-roll (400 ms) sert l'ouverture acoustique
      rapide ; ce tampon garde les `owner_buffer_ms` dernières millisecondes
      de trames nettoyées (après l'annuleur, donc sans toucher à l'ordre de la
      référence), le temps que le vérificateur reconnaisse la voix (D07, D08).
      Mémoire bornée : `owner_buffer_ms / 10` trames de 10 ms, soit
      `owner_buffer_ms × fréquence × 2 / 1000` octets (240 Ko à 48 kHz et
      2,5 s). Jamais persisté, jamais journalisé ;
    - indexé sur l'horloge du flux : la trame `i` commence à `i × 10` ms,
      l'horloge de `OwnerStateSnapshot` ; `owner_onset_ms` désigne donc une
      trame du tampon ;
    - envoyé / pas envoyé : un seul repère, `_sent_until`, l'indice qui suit
      la dernière trame réelle remise au fournisseur (direct, pré-roll ou
      rejeu). Toute trame d'indice inférieur est envoyée ou abandonnée : le
      rejeu ne remet jamais une trame derrière de l'audio déjà envoyé, donc
      ni doublon ni désordre ;
    - vidé par `reset()` (session, fréquence d'une nouvelle capture).

    Les commandes du propriétaire (`set_owner_gate`, `open_owner_flow`,
    `close_owner_flow`) viennent de la boucle asyncio : elles sont déposées
    sous `_lock` et appliquées par le thread de capture au début du bloc
    suivant, avant ses trames — c'est ce qui rend le rejeu unique et exact
    face aux trames qui continuent d'arriver.
    """

    #: Durée de référence gardée au plus : au-delà, c'est une dérive d'horloge
    #: ou une sortie jamais consommée, pas une latence réelle.
    MAX_REFERENCE_S = 3.0

    def __init__(
        self,
        *,
        capture_rate: int,
        render_rate: int,
        canceller: EchoCanceller | None = None,
        preroll_ms: int | None = None,
        detector: NearEndDetector | None = None,
        observer: CaptureObserver | None = None,
        owner_buffer_ms: int | None = None,
        owner_replay_margin_ms: int = OWNER_REPLAY_MARGIN_MS,
    ) -> None:
        self.capture_rate = int(capture_rate)
        self.render_rate = int(render_rate)
        self.canceller = canceller
        self._capture_frame_bytes = self.capture_rate // 100 * _BYTES_PER_SAMPLE
        self._render_frame_bytes = self.render_rate // 100 * _BYTES_PER_SAMPLE
        self._max_reference_bytes = int(self.render_rate * self.MAX_REFERENCE_S) * _BYTES_PER_SAMPLE
        # Derrière un annuleur, l'écho résiduel est faible : une valeur initiale
        # prudente suffit, l'apprentissage fait le reste. Sans annuleur, l'écho
        # peut égaler ce qui est joué ; partir plus bas ferait prendre JARVIS
        # pour l'utilisateur dès la première phrase.
        self.detector = detector or NearEndDetector(
            initial_coupling_db=-15.0 if canceller is not None else 5.0,
            # Barre du détecteur, réglable sans toucher au code (18/09/2026) :
            # sur un poste où les haut-parleurs reviennent fort dans le micro,
            # la monter de quelques dB suffit à ce que l'écho de JARVIS n'ouvre
            # plus de candidat. Défauts inchangés.
            floor_margin_db=_env_float("JARVIS_NEAR_END_FLOOR_MARGIN_DB", 12.0, minimum=0.0, maximum=60.0),
            echo_margin_db=_env_float("JARVIS_NEAR_END_ECHO_MARGIN_DB", 10.0, minimum=0.0, maximum=60.0),
            min_run_frames=max(1, round(_env_float("JARVIS_NEAR_END_MIN_RUN_MS", 60.0, minimum=10.0, maximum=1000.0) / FRAME_MS)),
            # Percentile des résidus et vitesse de retour (`_learn_coupling`).
            coupling_percentile=_env_float("JARVIS_NEAR_END_COUPLING_PERCENTILE", 90.0, minimum=50.0, maximum=100.0),
            release_decay_db=_env_float("JARVIS_NEAR_END_RELEASE_DECAY_DB_S", 0.2, minimum=0.0, maximum=60.0) * FRAME_MS / 1000.0,
        )
        # Sans annuleur, le pré-roll est surtout de l'écho : on n'en garde que
        # le strict nécessaire pour ne pas couper la première syllabe.
        default_preroll = 400 if canceller is not None else 150
        # (trame, déjà envoyée) : seules les trames remplacées par du silence
        # sont rejouées à l'ouverture, sinon le fournisseur entendrait deux fois
        # les syllabes prononcées avant que JARVIS ne se mette à parler.
        self._preroll: deque[tuple[bytes, bool]] = deque(maxlen=max(1, (preroll_ms or default_preroll) // FRAME_MS))
        self._lock = threading.Lock()
        self._reference = bytearray()
        self._release_requested = False
        self._release_learn = False
        self._carry = b""
        self._gate_open = True
        self.canceller_failed = False
        # Trames traitées depuis le dernier `reset()` : l'horloge du flux,
        # partagée avec l'observateur (`CaptureFrameContext.stream_ms`).
        self._stream_frames = 0
        # Vérification du locuteur en ombre ; absent, rien ne change.
        self.observer = observer
        self.observer_failed = False
        # Tampon de vérification du propriétaire (voir la docstring) : thread
        # de capture seulement, sauf les commandes et rapports sous `_lock`.
        self._owner_ring: deque[bytes] | None = None
        self.owner_buffer_ms = 0
        if owner_buffer_ms is not None:
            frames = max(1, int(owner_buffer_ms) // FRAME_MS)
            self._owner_ring = deque(maxlen=frames)
            self.owner_buffer_ms = frames * FRAME_MS
        self.owner_replay_margin_ms = max(0, int(owner_replay_margin_ms))
        self._sent_until = 0
        self._owner_gate = False
        self._owner_flow = False
        self._owner_gate_wanted = False
        # Dernière commande de flux non appliquée : (ouvrir, début, candidat,
        # refermer aussitôt après le rejeu).
        self._owner_flow_request: tuple[bool, int, int | None, bool] | None = None
        self._owner_replays: deque[OwnerReplay] = deque(maxlen=4)
        # Alignement de la référence du détecteur sur la pièce : la mesure vit
        # dans le thread de capture, les rapports partent sous `_lock`.
        self.delay_estimator = EchoDelayEstimator() if _env_flag("JARVIS_ECHO_ALIGN", True) else None
        # Historique des niveaux de référence : sa tête est la référence telle
        # qu'elle est AUDIBLE maintenant, c'est-à-dire celle d'il y a
        # `lead` trames. Longueur 1 tant qu'aucune avance n'est mesurée.
        self._ref_db_history: deque[float] = deque([_SILENCE_DB], maxlen=1)
        self._alignments: deque[EchoAlignment] = deque(maxlen=4)

    # -- côté sortie ----------------------------------------------------------

    def push_reference(self, pcm: bytes) -> None:
        """Enregistrer un bloc effectivement remis au périphérique de sortie."""

        if not pcm:
            return
        with self._lock:
            self._reference += pcm
            overflow = len(self._reference) - self._max_reference_bytes
            if overflow > 0:
                del self._reference[:overflow]

    def clear_reference(self) -> None:
        """La sortie a été coupée : ce qui restait ne sera jamais joué."""

        with self._lock:
            self._reference.clear()

    def release_near_end(self, *, learn: bool = True) -> None:
        """Refermer la garde : le bridge n'a pas confirmé de parole.

        `learn` : le détecteur remonte-t-il son couplage au niveau entendu ?
        Deux demandes avant la trame suivante apprennent si l'une l'exige.
        """

        with self._lock:
            self._release_requested = True
            self._release_learn = self._release_learn or learn

    def reset(self) -> None:
        """Repartir pour une nouvelle session vocale.

        Appelé à l'activation, avant l'ouverture du micro, et au retour au fond
        une fois le micro fermé : aucun thread PortAudio ne tourne alors.
        L'horloge du flux repart de zéro. Les tampons de la session précédente
        disparaissent ; l'annuleur convergé et le plancher de bruit restent. Le
        couplage, lui, ne redescend pas sous sa valeur prudente : entre deux
        réveils, le casque a pu laisser place aux haut-parleurs, et un couplage
        appris au casque ferait prendre leur écho pour l'utilisateur. Il
        réapprend en une seconde de parole de JARVIS.

        Le tampon du propriétaire est vidé, la garde rendue à la règle
        acoustique et toute commande en attente oubliée : aucun rejeu ne peut
        désigner une trame d'une autre session. Le bridge suivant rend la
        garde au propriétaire s'il en a l'autorité.
        """

        with self._lock:
            self._reference.clear()
            self._release_requested = False
            self._release_learn = False
            self._owner_gate_wanted = False
            self._owner_flow_request = None
            self._owner_replays.clear()
            self._alignments.clear()
        self._carry = b""
        self._preroll.clear()
        self._gate_open = True
        self._stream_frames = 0
        if self._owner_ring is not None:
            self._owner_ring.clear()
        self._sent_until = 0
        self._owner_gate = False
        self._owner_flow = False
        detector = self.detector
        detector.latched = False
        detector.latched_excess_db = None
        detector._reset_window()
        detector._refractory = 0
        detector.coupling_db = max(detector.coupling_db, detector.initial_coupling_db)
        if self.delay_estimator is not None:
            # L'historique d'une session close ne vaut plus ; l'avance mesurée,
            # elle, décrit le périphérique, qui n'a pas changé.
            self.delay_estimator.reset()
        observer = self.observer
        if observer is not None and not self.observer_failed:
            try:
                observer.reset()
            except Exception:
                self.observer_failed = True

    def close(self) -> None:
        """Libérer l'observateur : cette capture ne servira plus."""

        observer, self.observer = self.observer, None
        if observer is not None:
            try:
                observer.close()
            except Exception:
                # Fermeture best effort : Voice s'arrête de toute façon.
                pass

    # -- état lu par la boucle ------------------------------------------------

    @property
    def gate_open(self) -> bool:
        """Le fournisseur entend-il le micro en ce moment ?"""

        return self._gate_open

    @property
    def near_end_active(self) -> bool:
        return self.detector.latched

    @property
    def near_end_observed(self) -> bool:
        """Latest classified frame or the detector's bounded speech latch."""
        return self.detector.last_near or self.detector.latched

    @property
    def far_recent(self) -> bool:
        return self.detector.far_recent

    @property
    def processed_frames(self) -> int:
        """Trames de 10 ms intégrées par le détecteur depuis sa création.

        Compteur monotone : figé, il dit que la capture ne tourne pas, et non
        que l'utilisateur se tait.
        """

        return self.detector.frames

    @property
    def voiced_frames(self) -> int:
        """Trames de 10 ms jugées « proches » depuis la création du détecteur.

        Compteur monotone, lu depuis la boucle asyncio sans verrou (entier
        écrit par le thread de capture) : le bridge en fait la différence entre
        deux instants pour savoir si la voix locale a vraiment duré. Voir
        `NearEndDetector.voiced_frames`.
        """

        return self.detector.voiced_frames

    @property
    def echo_lead_ms(self) -> int:
        """Avance mesurée de la référence sur l'écho, en millisecondes.

        Zéro tant qu'aucune corrélation n'a abouti — et zéro aussi quand la
        mesure dit zéro : `EchoDelayEstimator.measured` distingue les deux.
        """

        estimator = self.delay_estimator
        return estimator.lead_ms if estimator is not None else 0

    def take_alignments(self) -> tuple[EchoAlignment, ...]:
        """Réalignements faits depuis le dernier appel (au plus 4), pour la trace."""

        with self._lock:
            alignments = tuple(self._alignments)
            self._alignments.clear()
        return alignments

    def near_end_diagnostics(self) -> NearEndDiagnostics:
        """Niveaux de la dernière trame traitée, pour la trace du bridge.

        Lecture depuis la boucle asyncio de scalaires écrits par le thread de
        capture : une valeur peut dater d'une trame, aucune décision n'en
        dépend, et rien n'est pris sous `_lock` — la capture ne doit jamais
        attendre la trace.
        """

        estimator = self.delay_estimator
        return self.detector.diagnostics(
            guard_open=self._gate_open,
            echo_lead_ms=estimator.lead_ms if estimator is not None else 0,
            echo_lead_confidence=estimator.confidence if estimator is not None else 0.0,
        )

    @property
    def stream_ms(self) -> int:
        """Audio capté et traité depuis le dernier `reset()`, en millisecondes.

        Même horloge que `CaptureFrameContext.stream_ms` et que les instants de
        l'état du propriétaire (`OwnerStateSnapshot`). Écrit par le thread de
        capture ; une lecture d'ailleurs peut retarder d'un bloc.
        """

        return self._stream_frames * FRAME_MS

    # -- Solo Owner : flux ouvert par le propriétaire (boucle asyncio) -------

    @property
    def owner_gate(self) -> bool:
        """La garde appartient-elle au propriétaire (dernière commande appliquée) ?"""

        return self._owner_gate

    def set_owner_gate(self, enabled: bool) -> bool:
        """Confier la garde au propriétaire (Solo Owner) ou la rendre à la règle acoustique.

        Confiée, le fournisseur reçoit du silence jusqu'à `open_owner_flow`,
        que JARVIS parle ou se taise (tâche 07) : le verrou de parole proche
        ne fait plus que signaler un candidat. Rend False — et rien ne change —
        sans tampon du propriétaire : fermer la garde sans pouvoir rejouer
        perdrait le début de phrase.
        """

        if enabled and self._owner_ring is None:
            return False
        with self._lock:
            self._owner_gate_wanted = bool(enabled)
            if not enabled:
                self._owner_flow_request = None
        return True

    def open_owner_flow(self, owner_onset_ms: int, *, candidate_onset_ms: int | None = None) -> None:
        """Le propriétaire est confirmé : rejouer son préfixe non envoyé, puis le direct.

        Appliqué au début du bloc suivant, dans le thread de capture ; sans
        effet si le flux est déjà ouvert ou la garde acoustique.
        `candidate_onset_ms` : début du candidat acoustique ; s'il précède
        `owner_onset_ms`, un étranger parlait avant, et la marge n'est pas
        appliquée.
        """

        with self._lock:
            self._owner_flow_request = (True, max(0, int(owner_onset_ms)), candidate_onset_ms, False)

    def close_owner_flow(self) -> None:
        """Le propriétaire a fini (ou un étranger a repris) : garde refermée.

        Une ouverture encore en attente n'est pas perdue : elle rejoue son
        préfixe au bloc suivant, puis le flux se referme aussitôt. C'est le cas
        d'une réponse brève reconnue à la fin de son candidat (tâche 07) :
        confirmation et fin arrivent ensemble, tout le candidat part au rejeu.
        """

        with self._lock:
            pending = self._owner_flow_request
            if pending is not None and pending[0]:
                self._owner_flow_request = (True, pending[1], pending[2], True)
            else:
                self._owner_flow_request = (False, 0, None, False)

    def take_owner_replays(self) -> tuple[OwnerReplay, ...]:
        """Rapports des rejeux faits depuis le dernier appel (au plus 4), pour la trace."""

        with self._lock:
            replays = tuple(self._owner_replays)
            self._owner_replays.clear()
        return replays

    # -- côté capture ---------------------------------------------------------

    def process(self, pcm: bytes) -> tuple[bytes, tuple[str, ...]]:
        """Traiter un bloc capturé ; rendre ce qu'il faut envoyer et les signaux."""

        data = self._carry + pcm
        size = self._capture_frame_bytes
        usable = len(data) - len(data) % size
        self._carry = data[usable:]
        with self._lock:
            release, self._release_requested = self._release_requested, False
            learn, self._release_learn = self._release_learn, False
            owner_gate = self._owner_gate_wanted
            flow_request, self._owner_flow_request = self._owner_flow_request, None
        if release:
            self.detector.release(learn=learn)
        out = bytearray()
        signals: list[str] = []
        ring = self._owner_ring
        if ring is not None:
            self._apply_owner_commands(owner_gate, flow_request, out, signals)
        for offset in range(0, usable, size):
            frame = data[offset:offset + size]
            reference = self._pop_reference()
            reference_db = frame_db(reference)
            estimator = self.delay_estimator
            # Le micro BRUT : c'est lui qui porte l'écho, donc lui qui se
            # corrèle à la référence. Après l'annuleur il n'en resterait rien
            # à corréler, précisément quand l'annulation marche.
            raw_mic_db = frame_db(frame) if estimator is not None else 0.0
            frame = self._cancel_echo(frame, reference)
            if estimator is not None and estimator.observe(raw_mic_db, reference_db):
                self._align_reference(estimator)
            self._ref_db_history.append(reference_db)
            # L'annuleur reçoit la référence en avance — il lui en faut une ;
            # le détecteur la reçoit retardée de cette avance, donc telle
            # qu'elle est audible dans la pièce à cet instant.
            confirmed = self.detector.update(frame_db(frame), self._ref_db_history[0])
            if self._owner_gate:
                # Solo Owner : seul le propriétaire ouvre le flux, que JARVIS
                # parle ou se taise (tâche 07) — une autre voix n'atteint
                # jamais le fournisseur. Le verrou acoustique ne fait plus que
                # signaler un candidat au bridge ; son pré-roll ne part pas.
                should_open = self._owner_flow
                if should_open:
                    out += frame
                else:
                    out += bytes(len(frame))
                self._preroll.append((frame, should_open))
            else:
                should_open = self.detector.latched or not self.detector.far_recent
                if confirmed and not self._gate_open:
                    # Ouverture sur parole confirmée : le fournisseur reçoit d'abord
                    # ce qu'il n'a pas entendu juste avant, trame courante comprise,
                    # puis le direct.
                    self._preroll.append((frame, False))
                    out += b"".join(item for item, sent in self._preroll if not sent)
                    self._preroll = deque(((item, True) for item, _sent in self._preroll), maxlen=self._preroll.maxlen)
                elif should_open:
                    out += frame
                    self._preroll.append((frame, True))
                else:
                    out += bytes(len(frame))
                    self._preroll.append((frame, False))
            if confirmed:
                signals.append(NEAR_END)
            self._gate_open = should_open
            if ring is not None:
                # Trame nettoyée, telle qu'elle serait partie ; envoyée si la
                # garde était ouverte (direct, ou pré-roll vidé jusqu'à elle).
                ring.append(frame)
                if should_open:
                    self._sent_until = self._stream_frames + 1
            # Après la garde : l'observateur reçoit la trame nettoyée et ce que
            # la garde en a conclu. Rien de ce qui précède n'en dépend.
            self._observe(frame)
            self._stream_frames += 1
        return bytes(out), tuple(signals)

    def _align_reference(self, estimator: EchoDelayEstimator) -> None:
        """Retarder la référence du détecteur de l'avance qui vient d'être mesurée.

        Thread de capture. Une avance négative — l'écho précède sa propre
        référence — ne se rattrape pas en retardant quoi que ce soit : elle
        est reportée telle quelle dans la trace, et le détecteur garde la
        référence à l'instant.

        L'allongement est comblé par la plus ancienne valeur connue, jamais par
        du silence : pendant les quelques trames où l'historique se remplit, un
        silence inventé ferait juger l'écho contre le seul plancher de bruit —
        exactement le faux barge-in que cet alignement existe pour empêcher.
        """

        lead = max(0, min(MAX_APPLIED_LEAD_FRAMES, estimator.lead_frames))
        previous = (self._ref_db_history.maxlen or 1) - 1
        if lead == previous:
            return
        oldest = self._ref_db_history[0] if self._ref_db_history else _SILENCE_DB
        aligned: deque[float] = deque(self._ref_db_history, maxlen=lead + 1)
        while len(aligned) < lead + 1:
            aligned.appendleft(oldest)
        self._ref_db_history = aligned
        with self._lock:
            self._alignments.append(EchoAlignment(
                lead_ms=lead * FRAME_MS,
                previous_lead_ms=previous * FRAME_MS,
                confidence=estimator.confidence,
                stream_ms=self._stream_frames * FRAME_MS,
            ))

    def _apply_owner_commands(
        self,
        owner_gate: bool,
        flow_request: tuple[bool, int, int | None, bool] | None,
        out: bytearray,
        signals: list[str],
    ) -> None:
        """Appliquer, avant les trames du bloc, ce que la boucle a demandé."""

        self._owner_gate = owner_gate
        if not owner_gate:
            self._owner_flow = False
            return
        if flow_request is None:
            return
        opening, owner_onset_ms, candidate_onset_ms, close_after = flow_request
        if not opening:
            self._owner_flow = False
            return
        if not self._owner_flow:
            # Sinon, déjà ouvert : tout ce qui a suivi l'ouverture est parti
            # en direct.
            self._owner_flow = True
            replay = self._replay_owner_prefix(owner_onset_ms, candidate_onset_ms, out)
            with self._lock:
                self._owner_replays.append(replay)
            signals.append(OWNER_REPLAY)
        if close_after:
            self._owner_flow = False

    def _replay_owner_prefix(self, owner_onset_ms: int, candidate_onset_ms: int | None, out: bytearray) -> OwnerReplay:
        """Remettre au fournisseur, une fois, les trames jamais envoyées depuis le début du propriétaire.

        Thread de capture. Intervalle demandé : `owner_onset_ms` moins la marge
        (seulement si aucun étranger ne parlait avant dans ce candidat), jusqu'à
        la dernière trame traitée. N'en part que ce qui suit `_sent_until` —
        l'ordre du flux prime sur l'exhaustivité — et que le tampon garde
        encore ; le reste est compté (`already_sent_ms`, `clamped_ms`).
        """

        ring = self._owner_ring
        assert ring is not None
        end = self._stream_frames
        oldest = end - len(ring)
        after_non_owner = candidate_onset_ms is not None and owner_onset_ms > candidate_onset_ms
        margin = 0 if after_non_owner else self.owner_replay_margin_ms // FRAME_MS
        requested = max(0, owner_onset_ms // FRAME_MS - margin)
        needed = max(requested, self._sent_until)
        first = min(end, max(needed, oldest))
        if first < end:
            out += b"".join(islice(ring, first - oldest, None))
        # Tout ce qui précède est désormais envoyé ou abandonné : ni le
        # pré-roll acoustique ni un rejeu suivant ne le renverront.
        self._sent_until = end
        self._preroll = deque(((item, True) for item, _sent in self._preroll), maxlen=self._preroll.maxlen)
        return OwnerReplay(
            owner_onset_ms=owner_onset_ms,
            requested_from_ms=requested * FRAME_MS,
            from_ms=first * FRAME_MS,
            until_ms=end * FRAME_MS,
            replay_ms=(end - first) * FRAME_MS,
            margin_ms=margin * FRAME_MS,
            already_sent_ms=max(0, min(needed, end) - requested) * FRAME_MS,
            clamped_ms=max(0, min(oldest, end) - needed) * FRAME_MS,
            buffer_ms=self.owner_buffer_ms,
        )

    def _pop_reference(self) -> bytes:
        size = self._render_frame_bytes
        with self._lock:
            chunk = bytes(self._reference[:size])
            del self._reference[:size]
        if len(chunk) < size:
            chunk += bytes(size - len(chunk))
        return chunk

    def _observe(self, frame: bytes) -> None:
        observer = self.observer
        if observer is None or self.observer_failed:
            return
        detector = self.detector
        context = CaptureFrameContext(
            stream_ms=self._stream_frames * FRAME_MS,
            sample_rate=self.capture_rate,
            near_end=detector.last_near,
            far_end=detector.far_recent,
            near_end_latched=detector.latched,
            gate_open=self._gate_open,
        )
        try:
            observer.observe(frame, context)
        except Exception:
            # Une exception ici ferait repartir le micro brut depuis le
            # callback PortAudio (`SoundDeviceRealtimeAudio`) : l'observateur
            # est écarté, la capture continue à l'identique.
            self.observer_failed = True

    def _cancel_echo(self, frame: bytes, reference: bytes) -> bytes:
        canceller = self.canceller
        if canceller is None or self.canceller_failed:
            return frame
        try:
            canceller.process_render(reference)
            return canceller.process_capture(frame)
        except Exception:
            # Une panne de l'annuleur ne doit ni tuer le flux PortAudio ni
            # couper le micro : on continue sans lui, avec la garde seule —
            # et avec le couplage prudent d'une capture sans annuleur, sinon
            # l'écho brut passerait pour l'utilisateur.
            self.canceller_failed = True
            self.detector.coupling_db = max(self.detector.coupling_db, 5.0)
            self.detector._far_frames = 0
            return frame
