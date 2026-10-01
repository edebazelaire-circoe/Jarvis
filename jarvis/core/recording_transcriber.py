"""Transcription d'un enregistrement explicite depuis son spool durable (handoff session-context-recording, Slice 06).

D11, D17, D-AUDIO. Contrat : `docs/capture.md` › *Transcription*.

- **Source durable d'abord** : le transcripteur relit le payload WAV de
  l'Artifact `audio_recording` (le `.partial` pendant l'enregistrement, le
  fichier final ensuite), jamais un flux mémoire. Une transcription lente, en
  panne ou absente ne perd donc aucune preuve, et se rattrape plus tard.
- **Frontières** : `AmbientSegmenter` (énergie + plancher adaptatif, coupe
  d'office à 30 s), nourri trame par trame de 20 ms : la fin exacte de chaque
  segment est connue (`frames_in`), son début en découle.
- **Texte** : `TranscriptionBackend` (même port que la voie ambiante), une
  requête par segment, au plus `concurrency` appels simultanés tous
  enregistrements confondus, et **en ordre** par enregistrement (le curseur
  ne saute jamais un segment). Délai par essai, 3 essais avec attente
  croissante ; puis le segment reste **en attente** (`waiting_retry`,
  nouvel essai automatique à 30 s, 2 min puis 10 min) ou la transcription est
  `unavailable` (aucun fournisseur, refus non relançable) jusqu'à `retry()`.
- **Preuve immuable** : chaque segment accepté est un Artifact
  `transcript_segment` créé `complete` en une transaction (texte court dans
  la ligne, temps relatif à l'enregistrement et temps du mur,
  `transcribed_from` -> audio, `segment_of` -> projection,
  `transcript.segment.created`). Son identifiant est déterministe
  (`<audio>_seg<rang>`) : un rejeu après une mort de Core ne duplique rien.
- **Projection** : un Artifact `transcript` par enregistrement
  (`<audio>_transcript`), `pending` tant que la transcription n'est pas finie ;
  son `text` (queue lisible bornée) et ses métadonnées (curseur, état, erreur)
  sont réécrits à chaque segment (`transcript.projection.updated`, même
  transaction) — jamais les segments. À la fin : texte entier en payload
  `transcript.txt`, `complete` (ou `partial` si l'audio l'est).
- **Reprise** : au démarrage de Core, toute projection `pending` est reprise
  depuis son curseur (dernier échantillon traité, dans ses métadonnées), avant
  la reprise générique des Artifacts qui la laisse à son propriétaire.
- **Autorité** : rien n'entre dans `conversation_events` ; un texte de salle
  n'autorise jamais d'action (D17).

Miroir diagnostic `core.transcript.*` : identifiants, compteurs et codes,
jamais de texte ni d'audio.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from jarvis.audio.ambient_segmenter import DEFAULT_LEAD_IN_MS, AmbientSegment, AmbientSegmenter
from jarvis.audio.wav_pcm import WavFormat, WavFormatError, parse_wav_header, pcm16_wav
from jarvis.core.artifact_service import ArtifactService
from jarvis.domain.artifacts import (
    MAX_ARTIFACT_TEXT_CHARS, Artifact, ArtifactError, ArtifactErrorCode, ArtifactKind, ArtifactQuery,
    ArtifactRelationKind, ArtifactState,
)
from jarvis.domain.capture import CaptureChannel, CaptureError, CaptureErrorCode, CaptureRecord
from jarvis.domain.errors import ProviderError
from jarvis.domain.messages import AudioClip
from jarvis.domain.session_activity import ActivityKind
from jarvis.ports.artifacts import ArtifactPayloadError
from jarvis.ports.transcription import TranscriptionBackend
from jarvis.ports.v2 import DiagnosticSink

SOURCE = "stt.recording"
TRANSCRIPT_PAYLOAD = "transcript.txt"
DEFAULT_CONCURRENCY = 2
ATTEMPT_TIMEOUT_S = 60.0
ATTEMPTS = 3
ATTEMPT_BACKOFF_S = (2.0, 8.0)
#: Nouvel essai automatique d'un segment resté en attente (panne relançable).
RETRY_WAIT_S = (30.0, 120.0, 600.0)
POLL_S = 1.0
#: Audio lu par passe (secondes) : la boucle rend la main entre deux passes.
READ_CHUNK_S = 10
MAX_UTTERANCE_MS = 30_000
#: Curseur noté pendant un long silence (sans événement) au plus toutes les 30 s d'audio.
IDLE_CURSOR_S = 30
#: Réponse « vide » de l'adaptateur OpenAI : aucun mot, pas une panne.
EMPTY_RESPONSE = "Empty transcription response"
RECOVERY_PAGE = 200


class TranscriptionState(StrEnum):
    RUNNING = "running"
    #: Un segment a échoué après ses essais ; nouvel essai automatique programmé.
    WAITING_RETRY = "waiting_retry"
    #: Aucun fournisseur, ou refus non relançable : attend `retry()`.
    UNAVAILABLE = "unavailable"
    COMPLETE = "complete"
    PARTIAL = "partial"
    #: Abandon explicite (Slice 09) : projection finalisée `partial`, segments gardés, plus rien n'est tenté.
    ABANDONED = "abandoned"


#: `error_code` d'une projection abandonnée explicitement (Slice 09).
ABANDONED_CODE = "transcription_abandoned"
MAX_ABANDON_REASON_CHARS = 200


class _Pause(Exception):
    def __init__(self, code: CaptureErrorCode, detail: str, *, retryable: bool) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail[:200]
        self.retryable = retryable


def projection_id_of(audio_artifact_id: str) -> str:
    return f"{audio_artifact_id}_transcript"


def segment_id_of(audio_artifact_id: str, seq: int) -> str:
    return f"{audio_artifact_id}_seg{seq:06d}"


@dataclass(eq=False)
class _Job:
    capture_id: str
    audio_id: str
    projection: Artifact
    cursor_frame: int = 0
    next_seq: int = 1
    chars: int = 0
    state: TranscriptionState = TranscriptionState.RUNNING
    error_code: str | None = None
    last_error: str = ""
    retry_round: int = 0
    tail: str = ""
    truncated: bool = False
    # Lecture (mémoire de cette vie seulement ; le curseur durable est `cursor_frame`).
    fmt: WavFormat | None = None
    segmenter: AmbientSegmenter | None = None
    base_frame: int = 0
    read_frame: int = 0
    carry: bytes = b""
    queue: deque[tuple[int, AmbientSegment]] = field(default_factory=deque)
    persisted_idle: int = 0
    data_frames: int = 0
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None

    def snapshot(self) -> dict[str, Any]:
        rate = self.fmt.sample_rate if self.fmt is not None else None
        return {
            "capture_id": self.capture_id, "audio_artifact_id": self.audio_id,
            "transcript_artifact_id": self.projection.artifact_id, "state": self.state.value,
            "error_code": self.error_code, "last_error": self.last_error or None,
            "segments": self.next_seq - 1, "chars": self.chars,
            "cursor_ms": None if rate is None else self.cursor_frame * 1000 // rate,
            "lag_ms": None if rate is None else max(0, self.data_frames - self.cursor_frame) * 1000 // rate,
        }


class RecordingTranscriber:
    """Transcription durable des enregistrements audio explicites. Voir l'en-tête du module."""

    def __init__(
        self,
        artifacts: ArtifactService,
        capture_reader: Callable[[str], Awaitable[CaptureRecord]],
        backend: Callable[[], TranscriptionBackend | None],
        *,
        diagnostics: DiagnosticSink | None = None,
        concurrency: int = DEFAULT_CONCURRENCY,
        attempt_timeout_s: float = ATTEMPT_TIMEOUT_S,
        attempts: int = ATTEMPTS,
        attempt_backoff_s: tuple[float, ...] = ATTEMPT_BACKOFF_S,
        retry_wait_s: tuple[float, ...] = RETRY_WAIT_S,
        poll_s: float = POLL_S,
        max_utterance_ms: int = MAX_UTTERANCE_MS,
    ) -> None:
        self._artifacts = artifacts
        self._capture = capture_reader
        self._backend = backend
        self._diagnostics = diagnostics
        self._slots = asyncio.Semaphore(max(1, concurrency))
        self._attempt_timeout_s = attempt_timeout_s
        self._attempts = max(1, attempts)
        self._attempt_backoff_s = attempt_backoff_s
        self._retry_wait_s = retry_wait_s
        self._poll_s = poll_s
        self._max_utterance_ms = max_utterance_ms
        self._jobs: dict[str, _Job] = {}
        self._owned: set[str] = set()
        self._closing = False

    # ------------------------------------------------------------ lecture

    def owns(self, artifact: Artifact) -> bool:
        """Vrai pour une projection reprise ici (`ArtifactService.recover_pending(owned=...)`)."""

        return artifact.artifact_id in self._owned

    def status(self, capture_id: str | None = None) -> dict[str, Any] | list[dict[str, Any]] | None:
        """État de transcription d'un enregistrement (ou de tous ceux suivis dans cette vie de Core)."""

        if capture_id is None:
            return [job.snapshot() for job in self._jobs.values()]
        job = self._jobs.get(capture_id)
        return None if job is None else job.snapshot()

    # ------------------------------------------------------------ entrées

    async def on_capture_started(self, record: CaptureRecord) -> None:
        """Rappel de `CaptureService` après `capture.started` : projection créée, transcription lancée."""

        if record.channel is not CaptureChannel.AUDIO or record.artifact_id is None or self._closing:
            return
        if record.capture_id in self._jobs:
            return
        audio = await self._artifacts.get(record.artifact_id)
        job = await self._open_job(record.capture_id, audio)
        self._launch(job)

    async def recover(self, recovered_captures: tuple[str, ...] = ()) -> tuple[str, ...]:
        """Au démarrage de Core, après `CaptureService.recover()` et **avant**
        `ArtifactService.recover_pending(owned=self.owns)` : reprend chaque projection `pending`
        depuis son curseur, et ouvre celle d'un enregistrement réconcilié qui n'en avait pas (mort
        de Core juste après son démarrage). Ne lève pas ; rend les captures reprises."""

        resumed: list[str] = []
        try:
            cursor: str | None = None
            while True:
                page = await self._artifacts.query(ArtifactQuery(
                    kinds=(ArtifactKind.TRANSCRIPT,), states=(ArtifactState.PENDING,), cursor=cursor,
                    limit=RECOVERY_PAGE))
                for projection in page.items:
                    capture_id = projection.metadata.get("capture_id")
                    audio_id = projection.metadata.get("audio_artifact_id")
                    if projection.source != SOURCE or not capture_id or not audio_id or capture_id in self._jobs:
                        continue
                    self._owned.add(projection.artifact_id)
                    self._launch(self._job_from(str(capture_id), str(audio_id), projection))
                    resumed.append(str(capture_id))
                if page.next_cursor is None:
                    break
                cursor = page.next_cursor
            for capture_id in recovered_captures:
                if capture_id in self._jobs:
                    continue
                record = await self._capture(capture_id)
                if record.channel is not CaptureChannel.AUDIO or record.artifact_id is None:
                    continue
                audio = await self._artifacts.get(record.artifact_id)
                if audio.state is ArtifactState.FAILED or not audio.payload_ref:
                    continue
                try:
                    existing = await self._artifacts.get(projection_id_of(audio.artifact_id))
                except ArtifactError:
                    existing = None
                if existing is not None and not existing.is_pending:
                    continue
                self._launch(await self._open_job(capture_id, audio))
                resumed.append(capture_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - logged with its code; Core keeps starting, retry() stays possible
            self._trace("core.transcript.recovery_failed", f"Reprise des transcriptions interrompue : "
                        f"{type(exc).__name__}: {str(exc)[:200]}", level="error",
                        data={"code": str(getattr(exc, "code", "")), "exception_type": type(exc).__name__})
        self._trace("core.transcript.recovery", "Transcriptions d'enregistrements reprises",
                    level="warning" if resumed else "info", data={"resumed": len(resumed)})
        return tuple(resumed)

    async def retry(self, capture_id: str) -> dict[str, Any]:
        """Relance une transcription en attente (`waiting_retry`/`unavailable`) ; sinon rend son état.

        Idempotent : deux appels concurrents réveillent le même travail, qui
        ne recrée jamais un segment déjà enregistré. Inconnue de cette vie :
        `capture_not_found` (404) si la capture n'existe pas, sinon l'état
        lu de sa projection.
        """

        job = self._jobs.get(capture_id)
        if job is None:
            record = await self._capture(capture_id)
            if record.artifact_id is None:
                raise CaptureError(CaptureErrorCode.TRANSCRIPTION_UNAVAILABLE,
                                   f"capture {capture_id} has no audio to transcribe", capture_id=capture_id)
            try:
                projection = await self._artifacts.get(projection_id_of(record.artifact_id))
            except ArtifactError:
                raise CaptureError(CaptureErrorCode.TRANSCRIPTION_UNAVAILABLE,
                                   f"capture {capture_id} has no transcript", capture_id=capture_id) from None
            return {"capture_id": capture_id, "transcript_artifact_id": projection.artifact_id,
                    "state": projection.metadata.get("transcription_state"),
                    "error_code": projection.error_code}
        if job.state in (TranscriptionState.WAITING_RETRY, TranscriptionState.UNAVAILABLE):
            job.retry_round = 0
            self._trace("core.transcript.retry_requested", "Transcription relancée",
                        data={**self._ids(job), "from_state": job.state.value})
            job.wake.set()
            if job.task is None or job.task.done():
                job.state = TranscriptionState.RUNNING  # travail arrêté sur une erreur : relancé
                self._launch(job)
        return job.snapshot()

    async def abandon(self, capture_id: str, *, reason: str | None = None) -> dict[str, Any]:
        """Abandon **explicite** d'une transcription en attente (Slice 09, choix de l'utilisateur).

        La projection est finalisée `partial` (`error_code` `transcription_abandoned`,
        raison dans ses métadonnées), avec le texte des segments déjà acceptés ;
        les segments restent (preuve immuable), plus rien n'est envoyé au
        fournisseur. C'est ce qui rend supprimable un enregistrement dont la
        transcription resterait `pending` pour toujours (`artifact_still_pending`).

        Refus : `capture_still_open` (409) tant que l'enregistrement tourne ;
        `transcription_unavailable` sans audio ni projection. Projection déjà
        terminale : rendue telle quelle (idempotent).
        """

        reason = (reason or "").strip()[:MAX_ABANDON_REASON_CHARS] or None
        record = await self._capture(capture_id)
        if record.is_open:
            raise CaptureError(CaptureErrorCode.CAPTURE_STILL_OPEN,
                               f"capture {capture_id} is still recording: stop it before abandoning its transcription",
                               capture_id=capture_id)
        if record.artifact_id is None:
            raise CaptureError(CaptureErrorCode.TRANSCRIPTION_UNAVAILABLE,
                               f"capture {capture_id} has no audio to transcribe", capture_id=capture_id)
        job = self._jobs.get(capture_id)
        if job is None:
            try:
                projection = await self._artifacts.get(projection_id_of(record.artifact_id))
            except ArtifactError:
                raise CaptureError(CaptureErrorCode.TRANSCRIPTION_UNAVAILABLE,
                                   f"capture {capture_id} has no transcript", capture_id=capture_id) from None
            if not projection.is_pending:
                return self._settled(capture_id, projection)
            job = self._job_from(capture_id, record.artifact_id, projection)
        elif not job.projection.is_pending:
            return job.snapshot()
        task, job.task = job.task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        # Un segment écrit pendant l'annulation (transaction déjà partie) est adopté, jamais perdu.
        await self._adopt_replayed(job)
        await self._finish(job, abandoned=reason or "abandoned")
        return job.snapshot()

    @staticmethod
    def _settled(capture_id: str, projection: Artifact) -> dict[str, Any]:
        meta = projection.metadata
        return {"capture_id": capture_id, "audio_artifact_id": meta.get("audio_artifact_id"),
                "transcript_artifact_id": projection.artifact_id,
                "state": meta.get("transcription_state") or projection.state.value,
                "error_code": projection.error_code, "last_error": meta.get("last_error"),
                "segments": max(0, int(meta.get("next_seq") or 1) - 1), "chars": int(meta.get("chars") or 0),
                "cursor_ms": None, "lag_ms": None}

    async def close(self) -> None:
        """Arrêt de Core : les travaux s'arrêtent où ils sont (curseur durable, repris au démarrage)."""

        self._closing = True
        tasks = [job.task for job in self._jobs.values() if job.task is not None and not job.task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ------------------------------------------------------------ ouverture

    async def _open_job(self, capture_id: str, audio: Artifact) -> _Job:
        projection_id = projection_id_of(audio.artifact_id)
        try:
            projection = await self._artifacts.create(
                kind=ArtifactKind.TRANSCRIPT, source=SOURCE, jarvis_session_id=audio.jarvis_session_id,
                context_id=audio.context_id, payload_name=TRANSCRIPT_PAYLOAD, started_at=audio.started_at,
                mime_type="text/plain", artifact_id=projection_id, capture_id=capture_id,
                metadata={"capture_id": capture_id, "audio_artifact_id": audio.artifact_id, "cursor_frame": 0,
                          "next_seq": 1, "chars": 0, "transcription_state": TranscriptionState.RUNNING.value,
                          "error_code": None, "last_error": None},
                origins=((ArtifactRelationKind.TRANSCRIBED_FROM, audio.artifact_id),))
        except ArtifactError as exc:
            if exc.code is not ArtifactErrorCode.ARTIFACT_CONFLICT:
                raise
            projection = await self._artifacts.get(projection_id)  # déjà ouverte (rappel et reprise)
        self._owned.add(projection.artifact_id)
        return self._job_from(capture_id, audio.artifact_id, projection)

    def _job_from(self, capture_id: str, audio_id: str, projection: Artifact) -> _Job:
        meta = projection.metadata
        state = meta.get("transcription_state")
        job = _Job(capture_id=capture_id, audio_id=audio_id, projection=projection,
                   cursor_frame=int(meta.get("cursor_frame") or 0), next_seq=int(meta.get("next_seq") or 1),
                   chars=int(meta.get("chars") or 0), tail=projection.text or "",
                   truncated=bool(meta.get("projection_truncated")),
                   error_code=meta.get("error_code"), last_error=str(meta.get("last_error") or ""))
        if state == TranscriptionState.UNAVAILABLE.value:
            # Reprise : on réessaie une fois (une clé a pu être ajoutée entre-temps).
            job.state = TranscriptionState.RUNNING
        self._jobs[capture_id] = job
        return job

    def _launch(self, job: _Job) -> None:
        if job.projection.is_pending and (job.task is None or job.task.done()):
            job.task = asyncio.create_task(self._run(job), name=f"transcript-{job.capture_id}")

    # ------------------------------------------------------------ boucle

    async def _run(self, job: _Job) -> None:
        self._trace("core.transcript.started", "Transcription d'enregistrement en cours", data=self._ids(job))
        try:
            await self._adopt_replayed(job)
            check_provider = True
            while True:
                if job.state in (TranscriptionState.WAITING_RETRY, TranscriptionState.UNAVAILABLE):
                    await self._wait_retry(job)
                    check_provider = True
                    continue
                try:
                    if check_provider:
                        # Sans fournisseur, dit tout de suite (pas au premier segment).
                        check_provider = False
                        if self._backend() is None:
                            raise _Pause(CaptureErrorCode.TRANSCRIPTION_UNAVAILABLE,
                                         "no transcription provider configured (OpenAI key missing)",
                                         retryable=False)
                    if await self._advance(job):
                        await self._finish(job)
                        return
                except _Pause as pause:
                    await self._pause(job, pause)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - visible: state + journal; the cursor stays, retry() resumes
            self._trace("core.transcript.failed", f"Transcription arrêtée : {type(exc).__name__}: {str(exc)[:200]}",
                        level="error", data={**self._ids(job), "code": str(getattr(exc, "code", "")),
                                             "exception_type": type(exc).__name__})
            job.state = TranscriptionState.UNAVAILABLE
            job.error_code = CaptureErrorCode.TRANSCRIPTION_UNAVAILABLE.value
            job.last_error = f"{type(exc).__name__}: {str(exc)[:180]}"
            job.task = None

    async def _wait_retry(self, job: _Job) -> None:
        job.wake.clear()
        if job.state is TranscriptionState.WAITING_RETRY:
            delay = self._retry_wait_s[min(job.retry_round, len(self._retry_wait_s) - 1)]
            try:
                await asyncio.wait_for(job.wake.wait(), delay)
            except TimeoutError:
                pass
            job.retry_round += 1
        else:
            await job.wake.wait()
        job.state = TranscriptionState.RUNNING

    async def _advance(self, job: _Job) -> bool:
        """Une passe : segments en attente d'abord, puis nouvel audio. Vrai quand tout est transcrit."""

        while job.queue:
            await self._accept(job, *job.queue[0])
            job.queue.popleft()
        audio = await self._artifacts.get(job.audio_id)
        if job.fmt is None and not await self._read_format(job, audio):
            return await self._idle(job, audio, header_missing=True)
        assert job.fmt is not None and job.segmenter is not None
        info = await asyncio.to_thread(self._artifacts.payload_info, audio)
        size = 0 if info is None else (info.final_bytes if info.final_bytes is not None else info.partial_bytes or 0)
        job.data_frames = job.fmt.frames_in(job.fmt.data_bytes_on_disk(size))
        if job.read_frame < job.data_frames:
            frames = min(job.data_frames - job.read_frame, job.fmt.sample_rate * READ_CHUNK_S)
            offset = job.fmt.data_offset + job.read_frame * job.fmt.frame_bytes
            data = await asyncio.to_thread(self._artifacts.read_payload, audio, offset, frames * job.fmt.frame_bytes)
            job.read_frame += len(data) // job.fmt.frame_bytes
            await self._segment(job, data)
            return False
        return await self._idle(job, audio)

    async def _idle(self, job: _Job, audio: Artifact, *, header_missing: bool = False) -> bool:
        """Tout le spool est lu : fin si l'enregistrement est fini, sinon attendre la suite."""

        record = await self._capture(job.capture_id)
        if record.is_terminal and not audio.is_pending:
            if header_missing:
                return True  # aucun en-tête lisible : rien à transcrire
            assert job.segmenter is not None
            for segment in job.segmenter.flush():
                await self._enqueue(job, segment)
            while job.queue:
                await self._accept(job, *job.queue[0])
                job.queue.popleft()
            return True
        await self._note_idle_cursor(job)
        job.wake.clear()
        try:
            await asyncio.wait_for(job.wake.wait(), self._poll_s)
        except TimeoutError:
            pass
        return False

    async def _read_format(self, job: _Job, audio: Artifact) -> bool:
        prefix = await asyncio.to_thread(self._artifacts.read_payload, audio, 0, 4096)
        try:
            fmt = parse_wav_header(prefix)
        except WavFormatError as exc:
            if len(prefix) < 44:
                return False  # en-tête pas encore écrit
            raise _Pause(CaptureErrorCode.TRANSCRIPTION_UNAVAILABLE, f"unsupported recording: {exc}",
                         retryable=False) from exc
        if fmt.channels != 1:
            raise _Pause(CaptureErrorCode.TRANSCRIPTION_UNAVAILABLE,
                         f"unsupported recording: {fmt.channels} channels (mono expected)", retryable=False)
        job.fmt = fmt
        self._reset_reader(job)
        return True

    def _reset_reader(self, job: _Job) -> None:
        assert job.fmt is not None
        job.segmenter = AmbientSegmenter(sample_rate=job.fmt.sample_rate, max_utterance_ms=self._max_utterance_ms)
        job.base_frame = job.cursor_frame
        job.read_frame = job.cursor_frame
        job.carry = b""
        job.queue.clear()

    async def _segment(self, job: _Job, data: bytes) -> None:
        """Trame par trame : au plus un segment par trame, sa fin est exacte."""

        assert job.segmenter is not None
        segmenter = job.segmenter
        buffer = job.carry + data
        step = segmenter.frame_bytes
        usable = len(buffer) - len(buffer) % step
        for start in range(0, usable, step):
            for segment in segmenter.push(buffer[start:start + step]):
                await self._enqueue(job, segment)
        job.carry = buffer[usable:]
        while job.queue:
            await self._accept(job, *job.queue[0])
            job.queue.popleft()

    async def _enqueue(self, job: _Job, segment: AmbientSegment) -> None:
        assert job.segmenter is not None
        end = job.base_frame + job.segmenter.frames_in * (job.segmenter.frame_bytes // 2)
        job.queue.append((end - segment.frames, segment))

    # ------------------------------------------------------------ un segment

    async def _accept(self, job: _Job, start_frame: int, segment: AmbientSegment) -> None:
        """Transcrit puis enregistre un segment ; `_Pause` s'il doit attendre (le segment reste en tête)."""

        assert job.fmt is not None
        result, attempts = await self._transcribe(job, segment)
        end_frame = start_frame + segment.frames
        if result is None or not result.text.strip():
            job.cursor_frame = max(job.cursor_frame, end_frame)
            self._trace("core.transcript.segment_empty", "Segment sans parole transcrite",
                        data={**self._ids(job), "start_ms": job.fmt.ms_of(start_frame)})
            return
        await self._record(job, start_frame, end_frame, segment, result.text.strip(), result.provider,
                           result.model, attempts)

    async def _transcribe(self, job: _Job, segment: AmbientSegment) -> tuple[Any, int]:
        backend = self._backend()
        if backend is None:
            raise _Pause(CaptureErrorCode.TRANSCRIPTION_UNAVAILABLE,
                         "no transcription provider configured (OpenAI key missing)", retryable=False)
        clip = AudioClip(pcm16_wav(segment.pcm, sample_rate=segment.sample_rate), sample_rate=segment.sample_rate)
        last: _Pause | None = None
        for attempt in range(self._attempts):
            try:
                async with self._slots:
                    return await asyncio.wait_for(backend.transcribe(clip), self._attempt_timeout_s), attempt + 1
            except TimeoutError:
                last = _Pause(CaptureErrorCode.TRANSCRIPTION_TIMEOUT,
                              f"transcription took longer than {self._attempt_timeout_s:g} s", retryable=True)
            except ProviderError as exc:
                if str(exc) == EMPTY_RESPONSE:
                    return None, attempt + 1
                last = _Pause(CaptureErrorCode.TRANSCRIPTION_UNAVAILABLE,
                              f"{exc.provider} {exc.operation}: {exc}", retryable=bool(exc.retryable))
                if not exc.retryable:
                    break
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - provider adapter defect: said with its type, retried
                last = _Pause(CaptureErrorCode.TRANSCRIPTION_UNAVAILABLE,
                              f"{type(exc).__name__}: {str(exc)[:160]}", retryable=True)
            self._trace("core.transcript.attempt_failed", f"Essai de transcription en échec : {last.detail}",
                        level="warning", data={**self._ids(job), "code": last.code.value, "attempt": attempt + 1})
            if attempt + 1 < self._attempts:
                await asyncio.sleep(self._attempt_backoff_s[min(attempt, len(self._attempt_backoff_s) - 1)])
        assert last is not None
        raise last

    async def _record(self, job: _Job, start_frame: int, end_frame: int, segment: AmbientSegment, text: str,
                      provider: str, model: str, attempts: int) -> None:
        assert job.fmt is not None
        fmt = job.fmt
        seq = job.next_seq
        start_ms, end_ms = fmt.ms_of(start_frame), fmt.ms_of(end_frame)
        base = await self._wall_base(job)
        stored = text[:MAX_ARTIFACT_TEXT_CHARS]
        segment_id = segment_id_of(job.audio_id, seq)
        try:
            await self._artifacts.record_text(
                artifact_id=segment_id, kind=ArtifactKind.TRANSCRIPT_SEGMENT, source=SOURCE, text=stored,
                jarvis_session_id=job.projection.jarvis_session_id, context_id=job.projection.context_id,
                started_at=None if base is None else base + timedelta(milliseconds=start_ms),
                ended_at=None if base is None else base + timedelta(milliseconds=end_ms),
                duration_ms=end_ms - start_ms,
                metadata={"capture_id": job.capture_id, "audio_artifact_id": job.audio_id,
                          "transcript_artifact_id": job.projection.artifact_id, "seq": seq,
                          "start_ms": start_ms, "end_ms": end_ms, "start_frame": start_frame,
                          "end_frame": end_frame, "sample_rate": fmt.sample_rate, "provider": provider[:64],
                          "model": model[:128], "attempts": attempts, "forced_cut": segment.truncated,
                          "text_truncated": len(text) > len(stored), "speaker": None},
                origins=((ArtifactRelationKind.TRANSCRIBED_FROM, job.audio_id),
                         (ArtifactRelationKind.SEGMENT_OF, job.projection.artifact_id)),
                capture_id=job.capture_id,
                event=(ActivityKind.TRANSCRIPT_SEGMENT_CREATED,
                       {"seq": seq, "start_ms": start_ms, "end_ms": end_ms, "chars": len(stored),
                        "attempts": attempts}))
        except ArtifactError as exc:
            if exc.code is not ArtifactErrorCode.ARTIFACT_CONFLICT:
                raise
            # Rejeu (mort entre le segment et la projection) : le segment existe, il est adopté.
            existing = await self._artifacts.get(segment_id)
            stored = existing.text or ""
            end_frame = int(existing.metadata.get("end_frame") or end_frame)
        job.next_seq = seq + 1
        job.cursor_frame = max(job.cursor_frame, end_frame)
        self._append_tail(job, stored)
        await self._save(job, event=True)
        self._trace("core.transcript.segment", "Segment de transcription enregistré",
                    data={**self._ids(job), "seq": seq, "start_ms": start_ms, "end_ms": end_ms,
                          "chars": len(stored), "attempts": attempts})

    async def _adopt_replayed(self, job: _Job) -> None:
        """Segments créés par une vie précédente après son dernier curseur noté : adoptés, jamais refaits."""

        adopted = 0
        while True:
            try:
                existing = await self._artifacts.get(segment_id_of(job.audio_id, job.next_seq))
            except ArtifactError:
                break
            job.next_seq += 1
            job.cursor_frame = max(job.cursor_frame, int(existing.metadata.get("end_frame") or 0))
            self._append_tail(job, existing.text or "")
            adopted += 1
        if adopted:
            await self._save(job, event=True)
            self._trace("core.transcript.replay_adopted", "Segments déjà enregistrés adoptés",
                        level="warning", data={**self._ids(job), "adopted": adopted})

    # ------------------------------------------------------------ projection

    def _append_tail(self, job: _Job, text: str) -> None:
        job.chars += len(text)
        tail = f"{job.tail}\n{text}" if job.tail else text
        if len(tail) > MAX_ARTIFACT_TEXT_CHARS:
            cut = tail.find("\n", len(tail) - MAX_ARTIFACT_TEXT_CHARS)
            tail = tail[cut + 1:] if cut >= 0 else tail[-MAX_ARTIFACT_TEXT_CHARS:]
            job.truncated = True
        job.tail = tail

    def _projection_meta(self, job: _Job, state: TranscriptionState) -> dict[str, Any]:
        return {"cursor_frame": job.cursor_frame, "next_seq": job.next_seq, "chars": job.chars,
                "transcription_state": state.value, "error_code": job.error_code,
                "last_error": job.last_error[:200] or None, "projection_truncated": job.truncated,
                "sample_rate": None if job.fmt is None else job.fmt.sample_rate}

    async def _save(self, job: _Job, *, event: bool, state: TranscriptionState | None = None) -> None:
        state = state or job.state
        rate = job.fmt.sample_rate if job.fmt is not None else 1
        data = {"segments": job.next_seq - 1, "chars": job.chars, "cursor_ms": job.cursor_frame * 1000 // rate,
                "state": state.value, "error_code": job.error_code}
        job.projection = await self._artifacts.update_pending(
            job.projection.artifact_id, text=job.tail, metadata=self._projection_meta(job, state),
            event=(ActivityKind.TRANSCRIPT_PROJECTION_UPDATED, data) if event else None)

    async def _note_idle_cursor(self, job: _Job) -> None:
        """Long silence : curseur avancé (moins la marge d'attaque), noté sans événement."""

        if job.fmt is None or job.segmenter is None or job.segmenter.speaking or job.queue:
            return
        lead = job.fmt.sample_rate * DEFAULT_LEAD_IN_MS // 1000
        idle = max(job.cursor_frame, job.read_frame - lead - len(job.carry) // job.fmt.frame_bytes)
        if idle - job.persisted_idle >= job.fmt.sample_rate * IDLE_CURSOR_S and idle > job.cursor_frame:
            job.cursor_frame = idle
            job.persisted_idle = idle
            await self._save(job, event=False)

    async def _pause(self, job: _Job, pause: _Pause) -> None:
        job.state = TranscriptionState.WAITING_RETRY if pause.retryable else TranscriptionState.UNAVAILABLE
        job.error_code = pause.code.value
        job.last_error = pause.detail
        await self._save(job, event=True)
        self._trace("core.transcript.waiting", f"Transcription en attente : {pause.detail}", level="warning",
                    data={**self._ids(job), "state": job.state.value, "code": pause.code.value,
                          "pending_from_ms": None if job.fmt is None else job.fmt.ms_of(
                              job.queue[0][0] if job.queue else job.cursor_frame)})

    async def _finish(self, job: _Job, *, abandoned: str | None = None) -> None:
        """Projection finalisée. `abandoned` : abandon explicite (raison), `partial` quoi que dise l'audio."""

        audio = await self._artifacts.get(job.audio_id)
        whole = await self._whole_text(job)
        state = ArtifactState.COMPLETE if audio.state is ArtifactState.COMPLETE else ArtifactState.PARTIAL
        error = None if state is ArtifactState.COMPLETE else (audio.error_code or "source_partial")
        final = TranscriptionState.COMPLETE if state is ArtifactState.COMPLETE else TranscriptionState.PARTIAL
        job.error_code, job.last_error = None, ""
        if abandoned is not None:
            state, error, final = ArtifactState.PARTIAL, ABANDONED_CODE, TranscriptionState.ABANDONED
            job.error_code, job.last_error = ABANDONED_CODE, abandoned
        # L'état final n'est dit (`status`) qu'une fois la projection finalisée.
        await self._save(job, event=True, state=final)
        finalize: dict[str, Any] = {"state": state, "ended_at": audio.ended_at, "duration_ms": audio.duration_ms,
                                    "error_code": error,
                                    "text": whole if len(whole) <= MAX_ARTIFACT_TEXT_CHARS else None}
        try:
            info = self._artifacts.payload_info(job.projection)
            if info is not None and info.final_bytes is not None:
                job.projection = await self._artifacts.finalize(job.projection.artifact_id, **finalize)
            else:
                job.projection = await self._artifacts.store_payload(job.projection.artifact_id,
                                                                     whole.encode("utf-8"), **finalize)
        except ArtifactPayloadError as exc:
            self._trace("core.transcript.payload_failed", f"Texte entier non écrit : {str(exc)[:200]}",
                        level="error", data={**self._ids(job), "code": exc.code})
            job.projection = await self._artifacts.finalize(
                job.projection.artifact_id, state=ArtifactState.PARTIAL, ended_at=audio.ended_at,
                duration_ms=audio.duration_ms, error_code="transcript_payload_failed")
        job.state = final
        self._owned.discard(job.projection.artifact_id)
        self._trace("core.transcript.abandoned" if abandoned is not None else "core.transcript.finished",
                    "Transcription abandonnée sur demande" if abandoned is not None
                    else "Transcription d'enregistrement terminée",
                    level="info" if state is ArtifactState.COMPLETE else "warning",
                    data={**self._ids(job), "state": job.projection.state.value, "segments": job.next_seq - 1,
                          "chars": job.chars, **({"code": ABANDONED_CODE} if abandoned is not None else {})})

    async def _whole_text(self, job: _Job) -> str:
        parts: list[str] = []
        for seq in range(1, job.next_seq):
            try:
                parts.append((await self._artifacts.get(segment_id_of(job.audio_id, seq))).text or "")
            except ArtifactError:
                continue  # supprimé explicitement entre-temps : la projection dit ce qui reste
        return "\n".join(parts)

    async def _wall_base(self, job: _Job) -> datetime | None:
        """Temps du mur de l'échantillon 0 : activation de la capture (± un bloc), sinon début de l'audio."""

        try:
            record = await self._capture(job.capture_id)
            if record.activated_at is not None:
                return record.activated_at
        except CaptureError:
            pass
        return job.projection.started_at

    # ------------------------------------------------------------ interne

    @staticmethod
    def _ids(job: _Job) -> dict[str, Any]:
        return {"capture_id": job.capture_id, "audio_artifact_id": job.audio_id,
                "transcript_artifact_id": job.projection.artifact_id,
                "jarvis_session_id": job.projection.jarvis_session_id, "context_id": job.projection.context_id}

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data or {}))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal must not stop a transcription
            pass
