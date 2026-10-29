"""Détection locale de parole pendant IDLE : « l'utilisateur est en train de me parler ».

En IDLE (`docs/voice-lifecycle.md`) la séance GPT-Live est fermée mais le micro
local reste ouvert pour le mot d'éveil. Ce module regarde ces mêmes trames et
décide, sans fournisseur, quand une parole humaine commence. Il ne décide
jamais si elle s'adresse à JARVIS : c'est l'adressage de la séance rouverte qui
tranche (une parole qui n'était pas pour lui laisse la séance retomber en IDLE).

Trois choses seulement :

1. **Détection** : une trame est voisée quand son niveau dépasse un plancher
   adaptatif (`SpeechGate`, déjà utilisé par le vérificateur de locuteur) ; la
   parole est confirmée quand `MIN_VOICED` trames voisées tombent dans les
   `WINDOW` dernières. Un claquement isolé ne suffit pas.
2. **Propriétaire** (Solo Owner) : si un `judge` est fourni, la parole n'est
   confirmée que lorsqu'il répond oui sur l'audio du candidat ; non, ou pas de
   réponse à temps, et le candidat est abandonné (`COOLDOWN`).
3. **Pré-roll** : les `LEAD_MS` d'audio d'avant la détection, puis tout ce qui
   suit jusqu'à `MAX_MS`, sont gardés en mémoire pour que la séance rouverte
   reçoive les premiers mots (`take_preroll`).

Rien n'est persisté : le PCM vit dans un tampon borné, en mémoire, et sort par
`take_preroll` une seule fois. Les compteurs et durées sont les seules données
qu'un journal reçoit. Appelé depuis un seul thread (le consommateur du
détecteur de mot d'éveil) ; `take_preroll`, `reset` et `enabled` peuvent venir
de la boucle asyncio, d'où le verrou.
"""

from __future__ import annotations

from collections import deque
import threading
from typing import Callable, Protocol

from jarvis.audio.owner_verifier import SpeechGate, level_db, pcm16_to_float

#: Audio gardé avant la première trame voisée : l'attaque de la première syllabe.
LEAD_MS = 1200
#: Borne du tampon après détection : le temps de rouvrir la séance (contexte
#: Core + connexion fournisseur), pas davantage.
MAX_MS = 6000
#: Parole confirmée : au moins `MIN_VOICED` trames voisées parmi les `WINDOW` dernières.
WINDOW = 8
MIN_VOICED = 4
#: Après un candidat abandonné (propriétaire non reconnu, ou verdict trop long).
COOLDOWN_MS = 2500
#: Un verdict du propriétaire qui tarde au-delà est un non.
JUDGE_PATIENCE_MS = 4000


class OwnerJudge(Protocol):
    """Qui parle ? `begin()` oublie le candidat précédent ; `feed()` rend True (propriétaire),
    False (autre voix) ou `None` (pas encore assez d'audio pour juger)."""

    def begin(self) -> None: ...

    def feed(self, frame: bytes, sample_rate: int) -> bool | None: ...


class VerifierOwnerJudge:
    """`OwnerJudge` branché sur le vérificateur de locuteur local (`EmbeddingSpeakerVerifier`)."""

    def __init__(self, verifier) -> None:  # noqa: ANN001 - SpeakerVerifier (duck-typed)
        self.verifier = verifier

    def begin(self) -> None:
        self.verifier.reset()

    def feed(self, frame: bytes, sample_rate: int) -> bool | None:
        from jarvis.domain.speaker import VerificationStatus

        result = self.verifier.process(frame, sample_rate)
        if result.status is VerificationStatus.OK:
            return bool(result.owner_detected)
        return None


class IdleSpeechDetector:
    """Machine à trois états : veille d'écoute, candidat, parole confirmée (en attente de reprise)."""

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        frame_ms: int = 80,
        judge: OwnerJudge | None = None,
        gate: SpeechGate | None = None,
        on_trace: Callable[[str, dict[str, object]], None] | None = None,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.frame_ms = int(frame_ms)
        self.judge = judge
        # Plancher plus haut que celui du vérificateur : on parle ici de déclencher un
        # coût fournisseur sur un bruit de pièce, pas de juger une phrase déjà captée.
        self.gate = gate or SpeechGate(margin_db=12.0, absolute_min_db=-45.0)
        self._trace = on_trace
        self._lead_frames = max(1, LEAD_MS // self.frame_ms)
        self._max_frames = max(self._lead_frames + 1, MAX_MS // self.frame_ms)
        self._cooldown_frames = max(1, COOLDOWN_MS // self.frame_ms)
        self._patience_frames = max(1, JUDGE_PATIENCE_MS // self.frame_ms)
        self._lock = threading.Lock()
        self._enabled = False
        self._ring: deque[bytes] = deque()
        self._recent: deque[bool] = deque(maxlen=WINDOW)
        self._confirmed = False
        self._candidate_frames = 0
        self._cooldown = 0
        #: Compteurs : les seules mesures qu'un journal reçoit.
        self.confirmed_count = 0
        self.abandoned_count = 0

    # -- armement -----------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Armer (IDLE) ou désarmer (SLEEP, séance ouverte). Désarmer oublie tout l'audio."""

        with self._lock:
            self._enabled = bool(enabled)
            self._clear()

    def reset(self) -> None:
        with self._lock:
            self._clear()

    def _clear(self) -> None:
        self._ring.clear()
        self._recent.clear()
        self._confirmed = False
        self._candidate_frames = 0
        self._cooldown = 0
        if self.judge is not None:
            self.judge.begin()

    # -- flux ---------------------------------------------------------------

    def feed(self, frame: bytes) -> bool:
        """Une trame de `frame_ms`. Rend True **une fois**, quand la parole est confirmée."""

        with self._lock:
            if not self._enabled or self._confirmed:
                if self._enabled and self._confirmed:
                    self._append(frame)  # le tampon suit la parole jusqu'à la reprise
                return False
            self._append(frame)
            voiced = self.gate.update(level_db(pcm16_to_float(frame)))
            self._recent.append(voiced)
            if self._cooldown > 0:
                self._cooldown -= 1
                return False
            if sum(self._recent) < MIN_VOICED:
                self._candidate_frames = 0
                return False
            if self.judge is None:
                return self._confirm()
            self._candidate_frames += 1
            if self._candidate_frames == 1:
                self.judge.begin()
                # Le jugement part des trames déjà voisées du tampon, pas du seul présent.
                for held in list(self._ring)[-WINDOW:]:
                    self._judge_frame(held)
            verdict = self._judge_frame(frame)
            if verdict is True:
                return self._confirm()
            if verdict is False or self._candidate_frames >= self._patience_frames:
                self._abandon("owner_not_recognized" if verdict is False else "owner_verdict_late")
            return False

    def take_preroll(self) -> tuple[bytes, int]:
        """L'audio gardé (de `LEAD_MS` avant la parole à maintenant), une seule fois, et le désarmement."""

        with self._lock:
            pcm = b"".join(self._ring)
            self._clear()
            self._enabled = False
            return pcm, self.sample_rate

    # -- interne ------------------------------------------------------------

    def _append(self, frame: bytes) -> None:
        self._ring.append(frame)
        limit = self._max_frames if self._confirmed else self._lead_frames + WINDOW
        while len(self._ring) > limit:
            self._ring.popleft()

    def _judge_frame(self, frame: bytes) -> bool | None:
        try:
            return self.judge.feed(frame, self.sample_rate)  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 - un vérificateur en panne ne déclenche rien
            return False

    def _confirm(self) -> bool:
        self._confirmed = True
        self.confirmed_count += 1
        # Le tampon garde désormais jusqu'à MAX_MS, mais jamais moins que le pré-roll déjà là.
        if self._trace is not None:
            self._trace("idle_speech_confirmed", {"buffered_ms": len(self._ring) * self.frame_ms})
        return True

    def _abandon(self, reason: str) -> None:
        self.abandoned_count += 1
        self._candidate_frames = 0
        self._cooldown = self._cooldown_frames
        self._recent.clear()
        if self._trace is not None:
            self._trace("idle_speech_abandoned", {"reason": reason})
