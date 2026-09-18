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
      entend le micro.
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

    def diagnostics(self, *, guard_open: bool) -> NearEndDiagnostics:
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

        self._references.append(ref_db)
        ref_env = max(self._references)
        self.last_mic_db, self.last_ref_env_db = mic_db, ref_env
        far_now = ref_env > self.REF_SILENCE_DB
        self._frames_since_far = 0 if far_now else self._frames_since_far + 1
        if not self.far_recent:
            self.last_margin_db = mic_db - (self.floor_db + self.floor_margin_db)
            self._update_floor(mic_db)
            self.last_near = mic_db > self.floor_db + self.floor_margin_db
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
        self.last_near = near
        # Ce qui manque à la trame pour franchir la plus contraignante des deux
        # bornes : positif, elle est proche. Diagnostic seul.
        self.last_margin_db = min(
            mic_db - (self.floor_db + self.floor_margin_db),
            mic_db - (predicted + self.echo_margin_db) if far_now else math.inf,
        )
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
            self.latched_excess_db = max(self._recent_excess) if self._recent_excess else None
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

    def near_end_diagnostics(self) -> NearEndDiagnostics:
        """Niveaux de la dernière trame traitée, pour la trace du bridge.

        Lecture depuis la boucle asyncio de scalaires écrits par le thread de
        capture : une valeur peut dater d'une trame, aucune décision n'en
        dépend, et rien n'est pris sous `_lock` — la capture ne doit jamais
        attendre la trace.
        """

        return self.detector.diagnostics(guard_open=self._gate_open)

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
            frame = self._cancel_echo(frame, reference)
            confirmed = self.detector.update(frame_db(frame), frame_db(reference))
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
