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

Rien n'est persisté : l'audio ne vit que dans des tampons bornés en mémoire.
"""

from __future__ import annotations

import math
import threading
from collections import deque
from typing import Protocol

import numpy as np

NEAR_END = "near_end"

FRAME_MS = 10
_BYTES_PER_SAMPLE = 2  # int16 mono
_SILENCE_DB = -120.0


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


class NearEndDetector:
    """Décide, trame par trame, si l'utilisateur parle par-dessus JARVIS.

    Toutes les énergies sont en dB pleine échelle, sur des trames de 10 ms.

    - `ref_env` : enveloppe de ce qui a été joué, maximum sur une fenêtre assez
      longue pour couvrir la latence du périphérique et la réverbération.
    - plancher : minimum glissant de l'énergie du micro, mesuré seulement quand
      JARVIS se tait ; une longue réponse ne peut donc pas le faire monter.
    - couplage : écart appris entre l'écho résiduel et `ref_env`. Il monte vite
      (un écho sous-estimé déclencherait un faux barge-in) et descend lentement.
      Un écho résiduel sous le plancher compte comme « au plancher », sans quoi
      un annuleur efficace laisserait le couplage figé à sa valeur initiale.

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
    ) -> None:
        self.coupling_db = float(initial_coupling_db)
        self.initial_coupling_db = float(initial_coupling_db)
        self.warmup_frames = warmup_frames
        # Écart micro − référence des dernières trames où JARVIS parlait : si
        # une parole supposée est récusée, c'est qu'il s'agissait d'écho, et
        # c'est ce niveau que le couplage doit rattraper.
        self._recent_excess: deque[float] = deque(maxlen=window_frames)
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

    @property
    def far_recent(self) -> bool:
        """Vrai tant que JARVIS parle, ou vient juste de se taire."""

        return self._frames_since_far <= self.tail_frames

    def release(self) -> None:
        """Lever le verrou : la parole supposée n'en était pas.

        C'était donc de l'écho que le couplage appris sous-estimait — après un
        passage du casque aux haut-parleurs, ou un annuleur qui décroche. Or le
        couplage n'apprend que sur des trames jugées « non proches » : sans
        correction, cet écho resterait proche pour toujours, et JARVIS se
        couperait lui-même en boucle. Le couplage remonte donc au niveau
        observé, juste assez pour que ce même écho ne franchisse plus la marge.
        """

        if self._recent_excess:
            observed = max(self._recent_excess) - self.echo_margin_db + 2.0
            self.coupling_db = min(20.0, max(self.coupling_db, observed))
        self.latched = False
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

        self._references.append(ref_db)
        ref_env = max(self._references)
        far_now = ref_env > self.REF_SILENCE_DB
        self._frames_since_far = 0 if far_now else self._frames_since_far + 1
        if not self.far_recent:
            self._update_floor(mic_db)
            self.latched = False
            self._reset_window()
            self._refractory = 0
            return False

        coupling = self.coupling_db
        if far_now:
            self._recent_excess.append(mic_db - ref_env)
        if far_now and ref_env > self.REF_LEARN_DB:
            self._far_frames += 1
        if self._far_frames < self.warmup_frames:
            coupling = max(coupling, self.warmup_coupling_db)
        predicted = ref_env + coupling if far_now else -math.inf
        near = mic_db > self.floor_db + self.floor_margin_db and mic_db > predicted + self.echo_margin_db
        recently_near = any(self._near)
        self._near.append(near)
        if ref_env > self.REF_LEARN_DB and not near and not recently_near and not self.latched:
            # Appris seulement quand JARVIS est nettement audible : dans ses
            # pauses, le micro ne contient que le bruit ambiant, et l'écart
            # mesuré ne dirait plus rien de l'écho.
            observed = mic_db - ref_env
            rate = 0.05 if observed > self.coupling_db else 0.02
            self.coupling_db = min(20.0, max(-60.0, self.coupling_db + rate * (observed - self.coupling_db)))
        if self._refractory > 0:
            self._refractory -= 1
            return False
        if (
            not self.latched
            and sum(self._near) >= self.min_frames
            and self._longest_run(self._near) >= self.min_run_frames
        ):
            self.latched = True
            return True
        return False

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
    détecteur ne sont touchés que par le thread de capture.
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
        self.detector = detector or NearEndDetector(initial_coupling_db=-15.0 if canceller is not None else 5.0)
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
        self._carry = b""
        self._gate_open = True
        self.canceller_failed = False

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

    def release_near_end(self) -> None:
        """Refermer la garde : le bridge n'a pas confirmé de parole."""

        with self._lock:
            self._release_requested = True

    def reset(self) -> None:
        """Repartir pour une nouvelle session vocale.

        Appelé à l'activation, avant l'ouverture du micro : aucun thread
        PortAudio ne tourne alors. Les tampons de la session précédente
        disparaissent ; l'annuleur convergé et le plancher de bruit restent. Le
        couplage, lui, ne redescend pas sous sa valeur prudente : entre deux
        réveils, le casque a pu laisser place aux haut-parleurs, et un couplage
        appris au casque ferait prendre leur écho pour l'utilisateur. Il
        réapprend en une seconde de parole de JARVIS.
        """

        with self._lock:
            self._reference.clear()
            self._release_requested = False
        self._carry = b""
        self._preroll.clear()
        self._gate_open = True
        detector = self.detector
        detector.latched = False
        detector._reset_window()
        detector._refractory = 0
        detector.coupling_db = max(detector.coupling_db, detector.initial_coupling_db)

    # -- état lu par la boucle ------------------------------------------------

    @property
    def gate_open(self) -> bool:
        """Le fournisseur entend-il le micro en ce moment ?"""

        return self._gate_open

    @property
    def near_end_active(self) -> bool:
        return self.detector.latched

    @property
    def far_recent(self) -> bool:
        return self.detector.far_recent

    # -- côté capture ---------------------------------------------------------

    def process(self, pcm: bytes) -> tuple[bytes, tuple[str, ...]]:
        """Traiter un bloc capturé ; rendre ce qu'il faut envoyer et les signaux."""

        data = self._carry + pcm
        size = self._capture_frame_bytes
        usable = len(data) - len(data) % size
        self._carry = data[usable:]
        with self._lock:
            release, self._release_requested = self._release_requested, False
        if release:
            self.detector.release()
        out = bytearray()
        signals: list[str] = []
        for offset in range(0, usable, size):
            frame = data[offset:offset + size]
            reference = self._pop_reference()
            frame = self._cancel_echo(frame, reference)
            confirmed = self.detector.update(frame_db(frame), frame_db(reference))
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
        return bytes(out), tuple(signals)

    def _pop_reference(self) -> bytes:
        size = self._render_frame_bytes
        with self._lock:
            chunk = bytes(self._reference[:size])
            del self._reference[:size]
        if len(chunk) < size:
            chunk += bytes(size - len(chunk))
        return chunk

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
