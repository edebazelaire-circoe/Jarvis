"""Mode PRESENTATION : un seul propriétaire du micro, et il est nommé.

Ce module est l'endroit où la contrainte centrale de la Slice 05 est
**appliquée**, pas seulement décrite : `docs/03-implementation-strategy.md` dit
« Presentation activation fails loudly if microphone ownership cannot be
established; never silently create two competing streams », et c'est ici que
« fails loudly » devient un `PresentationAudioError` nommé plutôt qu'un second
flux ouvert dans le dos de l'utilisateur.

Ce que la session possède
-------------------------

- un `AudioCaptureHub` — **le** flux physique, inscrit une fois dans
  `jarvis.audio.input_ownership` ;
- une `ExplicitAddressLane` — le fan-in typé du mot d'éveil et de la touche
  manuelle (D05), indépendant de tout travail ambiant (D04) ;
- un `SharedPcmWakeWordBackend` qui n'ouvre rien et lit le PCM du hub ;
- le `KeyboardWakeWordBackend` **existant**, inchangé, parce que la touche
  manuelle n'a jamais eu de périphérique audio à partager.

Ce qu'elle ne fait pas, délibérément
------------------------------------

Elle ne touche pas à SIMPLE (D14). Le chemin Porcupine autonome reste en place
pour SIMPLE, tel quel, et son second flux est désormais **compté** plutôt que
tacite : `physical_input_owners()` vaut 1 en PRESENTATION et 2 en SIMPLE quand
Porcupine est armé, et c'est un test qui le compte, pas une phrase.

Elle ne transcrit rien, ne segmente rien, n'appelle aucun cerveau : la lane
ambiante est la Slice 06, le tour adressé prioritaire la Slice 10.

Rien n'est persisté : le pré-roll et les files du hub sont des `deque` bornées
en mémoire, et `CommandPreRoll` ne s'écrit nulle part — son `repr` le dit.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from jarvis.adapters.wakeword_shared_pcm import SharedPcmWakeWordBackend, WakeWordEngine
from jarvis.audio.capture_hub import (
    DEFAULT_PREROLL_MS,
    AudioCaptureHub,
    AudioCaptureHubError,
)
from jarvis.audio.input_ownership import open_input_stream_count, open_input_streams
from jarvis.domain.explicit_address import ExplicitAddressSource, ExplicitAddressTrigger
from jarvis.runtime.explicit_address_lane import ExplicitAddressLane


class PresentationAudioError(RuntimeError):
    """Refus nommé de l'activation audio de PRESENTATION.

    `code` est stable et anglais ; le message est lu par un humain francophone
    et cite la panne réelle plutôt qu'une formule générique.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CommandPreRoll:
    """Le début de phrase déjà capté au moment où JARVIS a été adressé.

    En mémoire seulement, et son `repr` ne montre **jamais** le PCM : un
    `repr()` dans un journal ou un message d'erreur suffirait à faire fuir de
    l'audio brut dans un fichier, ce que ce dépôt interdit partout
    (`jarvis/audio/duplex.py`, `jarvis/runtime/realtime_audio.py`).
    """

    trigger: ExplicitAddressTrigger
    pcm: bytes = field(repr=False)
    sample_rate: int
    truncated: bool

    @property
    def duration_ms(self) -> int:
        if self.sample_rate <= 0:
            return 0
        return int(len(self.pcm) / 2 * 1000 / self.sample_rate)

    def __repr__(self) -> str:  # pragma: no cover - forme de trace
        return (
            f"CommandPreRoll(source={self.trigger.source.value}, "
            f"duration_ms={self.duration_ms}, bytes={len(self.pcm)})"
        )

    def to_payload(self) -> dict[str, object]:
        """Journalisable : des compteurs, jamais un octet de PCM."""

        return {
            **self.trigger.to_payload(),
            "preroll_ms": self.duration_ms,
            "preroll_bytes": len(self.pcm),
            "sample_rate": self.sample_rate,
            "truncated": self.truncated,
        }


class PresentationAudioSession:
    """La propriété du micro en PRESENTATION : établie, comptée, ou refusée."""

    def __init__(
        self,
        *,
        hub: AudioCaptureHub,
        lane: ExplicitAddressLane,
        wake: SharedPcmWakeWordBackend | None = None,
        journal: object | None = None,
        on_device_lost: Callable[[str], None] | None = None,
    ) -> None:
        self.hub = hub
        self.lane = lane
        self.wake = wake
        self.journal = journal
        self._on_device_lost = on_device_lost
        self.started = False
        self.device_lost = False
        hub.on_device_lost = self._device_lost

    # -- construction -----------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        manual_backend: object,
        wake_engine_factory: Callable[[], WakeWordEngine] | None = None,
        keyword: str = "jarvis",
        sample_rate: int = 24000,
        block_frames: int = 1200,
        device: int | str | None = None,
        preroll_ms: int = DEFAULT_PREROLL_MS,
        stream_factory: object | None = None,
        journal: object | None = None,
        on_device_lost: Callable[[str], None] | None = None,
    ) -> "PresentationAudioSession":
        """Composer la session. La touche manuelle est obligatoire ; le mot
        d'éveil est facultatif — sans clé Porcupine, JARVIS reste adressable."""

        hub = AudioCaptureHub(
            sample_rate=sample_rate, block_frames=block_frames, device=device,
            preroll_ms=preroll_ms, stream_factory=stream_factory,  # type: ignore[arg-type]
            journal=journal,
        )
        lane = ExplicitAddressLane(journal=journal)
        lane.add_source(ExplicitAddressSource.MANUAL_KEY, manual_backend)
        wake = None
        if wake_engine_factory is not None:
            wake = SharedPcmWakeWordBackend(
                hub=hub, engine_factory=wake_engine_factory, keyword=keyword, journal=journal,
            )
            lane.add_source(ExplicitAddressSource.WAKE_WORD, wake)
        return cls(hub=hub, lane=lane, wake=wake, journal=journal, on_device_lost=on_device_lost)

    # -- traces -----------------------------------------------------------

    def _trace(self, kind: str, message: str, *, level: str = "info", **data: object) -> None:
        if self.journal is not None:
            self.journal.emit(kind, message, level=level, data=dict(data))

    def _device_lost(self, code: str) -> None:
        self.device_lost = True
        if self._on_device_lost is not None:
            self._on_device_lost(code)

    # -- cycle de vie -----------------------------------------------------

    def physical_input_owners(self) -> int:
        """Combien de flux d'entrée physiques vivent dans ce processus.

        La contrainte se **compte**. En PRESENTATION établie la réponse est 1 ;
        toute autre valeur est un défaut, et `start()` refuse plutôt que de la
        laisser s'installer.
        """

        return open_input_stream_count()

    async def start(self) -> None:
        """Prendre le micro pour PRESENTATION, ou refuser en le disant.

        Idempotent : une session déjà démarrée ne rouvre rien.
        """

        if self.started:
            return
        # Un flux d'entrée déjà ouvert par quelqu'un d'autre — une session
        # SIMPLE encore vivante, un Porcupine autonome armé — est exactement la
        # concurrence que D04/D12 interdisent. On refuse **avant** d'ouvrir,
        # parce qu'après il serait trop tard : le second flux existerait.
        existing = open_input_streams()
        if existing:
            owners = sorted({entry.owner for entry in existing})
            self._trace(
                "presentation.audio.owner_conflict",
                "Activation PRESENTATION refusée : le micro est déjà tenu par "
                + ", ".join(owners),
                level="error", code="presentation_second_microphone_owner", owners=owners,
                open_input_streams=len(existing),
            )
            raise PresentationAudioError(
                "presentation_second_microphone_owner",
                "Impossible d'activer PRESENTATION : le micro est déjà tenu par "
                + ", ".join(owners)
                + ". Arrêtez la session en cours avant de passer en PRESENTATION.",
            )
        try:
            await self.hub.open()
        except AudioCaptureHubError as exc:
            # Ne jamais retomber sur « un second flux, tant pis » : l'échec
            # d'ouverture est l'échec de l'activation, et il porte le code du
            # hub tel quel plutôt qu'un code générique de plus.
            raise PresentationAudioError(
                exc.code,
                f"Impossible d'activer PRESENTATION : {exc}",
            ) from exc
        owners = self.physical_input_owners()
        if owners != 1:
            # Invariante centrale, vérifiée et non supposée. Si elle est
            # fausse, on rend le micro plutôt que de continuer à deux.
            await self.hub.close()
            self._trace(
                "presentation.audio.owner_ambiguous",
                f"Activation PRESENTATION annulée : {owners} propriétaires du micro au lieu d'un",
                level="error", code="presentation_input_owner_ambiguous", owners=owners,
            )
            raise PresentationAudioError(
                "presentation_input_owner_ambiguous",
                f"Impossible d'activer PRESENTATION : {owners} flux d'entrée ouverts au lieu d'un seul.",
            )
        await self.lane.start()
        if self.wake is not None:
            await self.wake.start()
        self.started = True
        self.device_lost = False
        self._trace(
            "presentation.audio.started",
            "Capture PRESENTATION active : un seul propriétaire du micro",
            input_owners=owners, sample_rate=self.hub.sample_rate,
            wake_word=self.wake is not None,
            wake_available=bool(self.wake is not None and not self.wake.engine_failed),
            sources=[source.value for source in self.lane.live_sources],
        )

    async def stop(self) -> None:
        """Rendre le micro. Idempotent, et la session reste redémarrable."""

        if not self.started and self.hub.open_input_streams == 0:
            return
        self.started = False
        await self.lane.close()
        if self.wake is not None:
            await self.wake.close()
        await self.hub.close()
        self._trace(
            "presentation.audio.stopped", "Capture PRESENTATION arrêtée : micro rendu",
            input_owners=self.physical_input_owners(),
        )

    # -- seams pour les Slices suivantes ----------------------------------

    def realtime_input_source(self) -> Callable[[Callable[..., None]], object]:
        """L'`input_source` de `SoundDeviceRealtimeAudio`.

        Passé au bridge interactif, il fait que le tour adressé consomme la
        capture **partagée** au lieu d'ouvrir un second micro. C'est l'adaptateur
        que demande SLICE.md ; il ne change rien au reste du bridge, qui
        continue de posséder la sortie et sa comptabilité de lecture.
        """

        if not self.started:
            raise PresentationAudioError(
                "presentation_capture_not_started",
                "La capture PRESENTATION n'est pas démarrée : rien à partager avec le chemin interactif.",
            )
        return self.hub.attach_input

    def command_preroll(self, trigger: ExplicitAddressTrigger) -> CommandPreRoll:
        """Le pré-roll borné associé à un déclencheur. Mémoire seulement."""

        ring = self.hub.preroll
        return CommandPreRoll(
            trigger=trigger,
            pcm=ring.snapshot(),
            sample_rate=self.hub.sample_rate,
            truncated=ring.evicted_bytes > 0,
        )

    def stats(self) -> dict[str, object]:
        return {
            "started": self.started,
            "device_lost": self.device_lost,
            "physical_input_owners": self.physical_input_owners(),
            "input_owners": [
                {"owner": entry.owner, "label": entry.label} for entry in open_input_streams()
            ],
            "hub": self.hub.stats(),
            "lane": self.lane.stats(),
            "wake": self.wake.stats() if self.wake is not None else None,
        }
