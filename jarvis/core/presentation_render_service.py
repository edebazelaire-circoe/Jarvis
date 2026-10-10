"""Rendu d'un snapshot de présentation en MP4, image fixe ou PDF de pages-images (Remotion Slice 16 ; `docs/remotion-render.md`).

Ce service ne possède rien de neuf : le snapshot reste à `PresentationPackager` (paquet relu ET vérifié avant chaque rendu), l'Artifact dérivé à
`PresentationArtifacts.begin_render` (relation `rendered_from` posée dans la transaction de création) et à `ArtifactService` (spool, `finalize`,
`fail`), le processus et le disque au `RenderRunner`. Il apporte le **travail** : file d'attente (un seul rendu à la fois), états, progression,
annulation, reprise.

Règles :

- Un rendu ne part JAMAIS d'une édition, d'un rechargement à chaud ni d'une valeur de contrôle : seulement d'un snapshot `complete`, relu et
  vérifié (hash, empreintes de chaque membre) ; la source vivante n'est pas consultée.
- L'Artifact dérivé naît `pending` à la demande (le Board montre « en cours ») ; il ne devient `complete` qu'après un fichier vérifié
  (en-tête, dimensions, durée, images) copié par le spool (`.partial` puis renommage). Un échec, une annulation ou un arrêt le rend `failed`
  (code stable) : le `.partial` éventuel reste comme preuve, jamais promu. Un fichier final trouvé après un arrêt brutal (renommage fait, base
  pas à jour) devient `partial` (`artifact_recovered`) : complet mais non vérifié, et dit tel.
- Concurrence 1 : les autres demandes attendent (`queued`, 8 au plus, puis `queue_full`).
- Le processus de rendu tourne isolé (`docs/remotion-render.md` §4) ; l'annulation tue l'arbre entier après contrôle d'identité (`pid:heure`).
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Collection, Mapping
import threading
import time
from typing import Any

from jarvis.core.artifact_service import ArtifactService
from jarvis.domain.artifacts import Artifact, ArtifactError, ArtifactQuery, ArtifactState
from jarvis.domain.presentation_artifacts import RENDER_KINDS, RENDERS, RenderFormat, parse_render_format
from jarvis.domain.presentation_render import (
    CONCURRENCY_LIMIT, KEEP_FINISHED, MAX_QUEUED, JobState, RenderError, RenderErrorCode as C, ResolvedRender, clean_detail,
    parse_settings, resolve,
)
from jarvis.domain.presentation_render_plan import choose_scene, plan_files
from jarvis.domain.presentation_studio import PresentationStudioError
from jarvis.ports.remotion_render import BrowserInfo, RenderRunner
from jarvis.ports.v2 import DiagnosticSink

TRACE = "core.presentation_render"
STOP_WAIT_S = 15.0
SPOOL_PROGRESS_STEP = 8


class RenderJob:
    """Un travail de rendu, en mémoire ; l'Artifact dérivé est sa trace durable."""

    def __init__(self, job_id: str, artifact_id: str, snapshot_id: str, resolved: ResolvedRender, browser: BrowserInfo) -> None:
        self.job_id, self.artifact_id, self.snapshot_id = job_id, artifact_id, snapshot_id
        self.resolved, self.browser = resolved, browser
        self.state = JobState.QUEUED
        self.phase = "queued"
        self.frames_done = 0
        self.created = time.time()
        self.started: float | None = None
        self.finished: float | None = None
        self.error_code = ""
        self.error_detail = ""
        self.process_ref = ""
        self.cancel = threading.Event()
        self.egress: dict[str, Any] = {}
        self.log_tail: list[str] = []
        self.size_bytes: int | None = None
        self.verified_by = ""

    def view(self, *, position: int | None = None) -> dict[str, Any]:
        r = self.resolved
        total = r.frames_total
        end = self.finished or time.time()
        percent = 100 if self.state is JobState.COMPLETE else min(99, int(100 * self.frames_done / total)) if total else 0
        return {
            "job_id": self.job_id, "artifact_id": self.artifact_id, "snapshot_id": self.snapshot_id, "state": self.state.value,
            "phase": self.phase, "format": r.fmt.value, "scene_id": r.target.scene_id, "frames_done": self.frames_done,
            "frames_total": total, "percent": percent, "created_at": self.created, "started_at": self.started,
            "elapsed_s": round(end - self.started, 1) if self.started else 0.0, "timeout_s": int(r.timeout_s),
            "queue_position": position, "cancel_requested": self.cancel.is_set() and not self.state.terminal,
            "can_cancel": self.state in (JobState.QUEUED, JobState.RUNNING) and not self.cancel.is_set(),
            "error_code": self.error_code or None, "error_detail": self.error_detail or None, "size_bytes": self.size_bytes,
            "browser": self.browser.version, "settings": r.canonical(), "settings_sha256": r.settings_sha256,
            "egress_denied": int(self.egress.get("proxy_denied", 0) or 0) + int(self.egress.get("blocked_connect", self.egress.get("blockedConnect", 0)) or 0),
            "verified_by": self.verified_by or None, "log_tail": self.log_tail[-4:] if self.state is JobState.FAILED else [],
        }


class PresentationRenderService:
    def __init__(self, *, artifacts: ArtifactService, snapshots: Any, packager: Any, runner: RenderRunner,
                 installed_engine: Callable[[], Any | None], capability_status: Callable[[], str] = lambda: "ready",
                 diagnostics: DiagnosticSink | None = None, run_blocking: Callable[..., Any] = asyncio.to_thread,
                 new_job_id: Callable[[], str] | None = None) -> None:
        """`snapshots` = `PresentationArtifacts` ; `packager` = `PresentationPackager` ; `installed_engine` rend l'`InstalledEngine` réel
        de la capacité (ou `None`) ; `capability_status` rend le statut de la capacité locale (`ready`/`running` = utilisable)."""

        import secrets
        self._artifacts, self._snapshots, self._packager, self._runner = artifacts, snapshots, packager, runner
        self._installed, self._capability_status = installed_engine, capability_status
        self._diagnostics, self._run_blocking = diagnostics, run_blocking
        self._new_id = new_job_id or (lambda: "rj_" + secrets.token_hex(6))
        self._jobs: dict[str, RenderJob] = {}
        self._queue: deque[str] = deque()
        self._worker: asyncio.Task | None = None
        self._current: str | None = None
        self._stopping = False

    # ------------------------------------------------------------------ demander

    def availability(self) -> dict[str, Any]:
        """Pourquoi un rendu n'est pas possible maintenant, ou `ready: true` : lecture seule, ne lance rien."""

        status = self._capability_status()
        reason = None
        if status not in ("ready", "running"):
            reason = f"the Remotion capability is {status}: install or repair it first"
        else:
            reason = self._runner.runtime_ready()
        browser = self._runner.find_browser() if reason is None else None
        if reason is None and browser is None:
            reason = "no Chrome or Edge was found; install Chrome or set JARVIS_REMOTION_RENDER_BROWSER (a browser is never downloaded)"
        return {"ready": reason is None, "reason": reason, "browser": None if browser is None else browser.version,
                "concurrency": CONCURRENCY_LIMIT, "max_queued": MAX_QUEUED}

    async def export(self, *, presentation_id: str, variant_id: str, expected_presentation_revision: int, expected_variant_revision: int,
                     authorised_boards: Collection[str], render_format: str, settings: object = None,
                     jarvis_session_id: str | None = None, context_id: str | None = None) -> dict[str, Any]:
        """Fige la variante (rejouable : le même couple de révisions retombe sur le même snapshot) PUIS demande le rendu de CE snapshot.
        Le gel passe par `PresentationPackager.freeze` (liste blanche de Boards obligatoire, révisions exactes)."""

        fmt = parse_render_format(render_format)  # un format invalide est refusé avant tout gel
        parse_settings(fmt, settings)
        self._require_ready()
        frozen = await self._packager.freeze(
            presentation_id, variant_id, expected_presentation_revision=expected_presentation_revision,
            expected_variant_revision=expected_variant_revision, authorised_boards=authorised_boards,
            jarvis_session_id=jarvis_session_id, context_id=context_id)
        view = await self.submit(frozen["artifact_id"], fmt, settings, jarvis_session_id=jarvis_session_id, context_id=context_id)
        return {**view, "snapshot_replayed": bool(frozen.get("replayed")), "authorised_boards": frozen.get("authorised_boards", [])}

    async def submit(self, snapshot_id: str, render_format: RenderFormat | str, settings: object = None, *,
                     jarvis_session_id: str | None = None, context_id: str | None = None) -> dict[str, Any]:
        """Valide tout ce qui peut l'être AVANT de créer quoi que ce soit, crée l'Artifact `pending`, met le travail en file."""

        if self._stopping:
            raise RenderError(C.UNAVAILABLE, "Core is stopping")
        fmt = parse_render_format(render_format)
        parsed = parse_settings(fmt, settings)
        browser = self._require_ready()
        try:
            package = await self._packager.read_snapshot(snapshot_id)
        except (ArtifactError, PresentationStudioError) as exc:
            raise RenderError(C.SNAPSHOT_INVALID, f"{getattr(exc, 'code', type(exc).__name__)}: {str(exc)[:200]}") from None
        except Exception as exc:  # noqa: BLE001 - argued: a damaged package (LiveRefError) is the same refusal, with its code
            code = getattr(exc, "code", None)
            raise RenderError(C.SNAPSHOT_INVALID, f"{getattr(code, 'value', code) or type(exc).__name__}: {str(exc)[:200]}") from None
        target = choose_scene(package, parsed.scene_id)
        resolved = resolve(fmt, parsed, target)
        installed = self._installed()
        if installed is None or installed.remotion_version != target.engine_version:
            have = "unreadable" if installed is None else installed.remotion_version
            raise RenderError(C.ENGINE_MISMATCH, f"the snapshot was frozen for remotion {target.engine_version}, this machine has {have}: "
                                                 "a render is only made with the frozen engine version")
        if len(self._queue) >= MAX_QUEUED:
            raise RenderError(C.QUEUE_FULL, f"{MAX_QUEUED} renders are already waiting")
        job_id = self._new_id()
        meta = {**resolved.to_metadata(), "render_job_id": job_id, "render_engine_drift": installed.lock_sha256 != target.engine_lock_sha256}
        artifact = await self._snapshots.begin_render(snapshot_id, fmt, jarvis_session_id=jarvis_session_id, context_id=context_id,
                                                      metadata=meta)
        job = RenderJob(job_id, artifact.artifact_id, snapshot_id, resolved, browser)
        self._jobs[job_id] = job
        self._queue.append(job_id)
        await self._record(job)
        self._trace("queued", "Rendu de présentation mis en file", data={
            "job_id": job_id, "artifact_id": artifact.artifact_id, "snapshot_id": snapshot_id, "format": fmt.value,
            "frames": resolved.frames_total, "queued": len(self._queue)})
        self._ensure_worker()
        return job.view(position=self._position(job_id))

    def _require_ready(self) -> BrowserInfo:
        status = self._capability_status()
        if status not in ("ready", "running"):
            raise RenderError(C.RUNTIME_UNAVAILABLE, f"the Remotion capability is {status}: install or repair it first")
        problem = self._runner.runtime_ready()
        if problem is not None:
            raise RenderError(C.RUNTIME_UNAVAILABLE, problem)
        browser = self._runner.find_browser()
        if browser is None:
            raise RenderError(C.BROWSER_UNAVAILABLE, "no Chrome or Edge was found; install Chrome or set JARVIS_REMOTION_RENDER_BROWSER "
                                                     "(a browser is never downloaded)")
        return browser

    # ------------------------------------------------------------------ lire, annuler

    def get(self, job_id: str) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if job is None:
            raise RenderError(C.UNKNOWN_JOB, "no such render job in this Core run (finished jobs older than the last "
                                              f"{KEEP_FINISHED} are forgotten; the derivative Artifact is the durable record)")
        return job.view(position=self._position(job_id))

    def jobs(self) -> list[dict[str, Any]]:
        return [job.view(position=self._position(job.job_id)) for job in sorted(self._jobs.values(), key=lambda j: -j.created)]

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if job is None:
            raise RenderError(C.UNKNOWN_JOB, "no such render job in this Core run")
        if job.state.terminal or job.state is JobState.FINALIZING:
            raise RenderError(C.NOT_CANCELLABLE, f"the job is {job.state.value}")
        job.cancel.set()
        self._trace("cancel_requested", "Annulation de rendu demandée", level="warning", data={"job_id": job_id, "state": job.state.value})
        if job.state is JobState.QUEUED:
            try:
                self._queue.remove(job_id)
            except ValueError:
                pass
            asyncio.get_running_loop().create_task(self._finish_queued_cancel(job))
            job.state, job.phase = JobState.CANCELLED, "cancelled"  # visible at once; the Artifact is failed just after
            job.error_code = C.CANCELLED.value
            job.finished = time.time()
        return job.view(position=self._position(job_id))

    async def _finish_queued_cancel(self, job: RenderJob) -> None:
        await self._fail_artifact(job, C.CANCELLED.value)
        await self._record(job)

    # ------------------------------------------------------------------ travail

    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.get_running_loop().create_task(self._drain(), name="presentation-render-worker")

    async def _drain(self) -> None:
        while self._queue and not self._stopping:
            job = self._jobs.get(self._queue.popleft())
            if job is None or job.state is not JobState.QUEUED:
                continue
            self._current = job.job_id
            try:
                await self._execute(job)
            except asyncio.CancelledError:
                job.cancel.set()  # the render thread cannot be cancelled: this makes it kill the process tree
                await asyncio.shield(self._fail_job(job, C.INTERRUPTED.value, "Core stopped while the render was running"))
                raise
            except Exception as exc:  # noqa: BLE001 - argued: any defect becomes a typed failure of THIS job; the worker serves the next one
                self._trace("internal_error", "Défaut inattendu pendant un rendu", level="error",
                            data={"job_id": job.job_id, "exception": type(exc).__name__, "detail": clean_detail(exc)})
                await self._fail_job(job, C.INTERNAL.value, f"{type(exc).__name__}: {clean_detail(exc, 160)}")
            finally:
                self._current = None
                self._forget_old()

    async def _execute(self, job: RenderJob) -> None:
        job.state, job.phase, job.started = JobState.RUNNING, "preparing", time.time()
        self._trace("started", "Rendu de présentation démarré", data={"job_id": job.job_id, "artifact_id": job.artifact_id})
        try:
            package = await self._packager.read_snapshot(job.snapshot_id)  # relu et revérifié : le paquet n'a pas changé depuis la demande
            files, props = plan_files(package, job.resolved.target)
            await self._run_blocking(self._runner.prepare, job.job_id, files)
            r = job.resolved
            spec = {"format": r.fmt.value, "entry": "studio-root.tsx", "composition_id": r.target.composition_id,
                    "composition": {"width": r.target.width, "height": r.target.height, "fps": r.target.fps,
                                    "durationInFrames": r.target.duration_in_frames},
                    "props": props, "frames_total": r.frames_total, "frame_range": [r.frame_start, r.frame_end],
                    "frames": list(r.frames), "crf": r.settings.crf, "scale": r.settings.scale, "concurrency": r.settings.concurrency,
                    "jpeg_quality": 90}
            if job.cancel.is_set():
                raise RenderError(C.CANCELLED, "cancelled before the process started")
            loop = asyncio.get_running_loop()

            def on_start(ref: str) -> None:
                job.process_ref = ref
                self._runner.write_record(job.job_id, self._record_of(job))

            def on_progress(progress: Mapping[str, Any]) -> None:
                loop.call_soon_threadsafe(self._apply_progress, job, dict(progress))

            outcome = await self._run_blocking(self._runner.run, job.job_id, spec, browser=job.browser, cancel=job.cancel,
                                               timeout_s=r.timeout_s, on_start=on_start, on_progress=on_progress)
            job.egress, job.log_tail = dict(outcome.egress), list(outcome.log_tail)
            if not outcome.ok:
                raise RenderError(C.FAILED if outcome.code not in {c.value for c in C} else C(outcome.code), outcome.detail)
            await self._finalize(job)
        except RenderError as exc:
            await self._fail_job(job, exc.code.value, exc.detail)
        finally:
            await self._run_blocking(self._runner.cleanup, job.job_id)

    def _apply_progress(self, job: RenderJob, progress: dict[str, Any]) -> None:
        if job.state is not JobState.RUNNING:
            return
        job.phase = str(progress.get("phase") or job.phase)[:32]
        done = progress.get("frames_done")
        if isinstance(done, int) and 0 <= done <= job.resolved.frames_total:
            job.frames_done = done

    async def _finalize(self, job: RenderJob) -> None:
        """Fichier vérifié, copié dans le spool de l'Artifact (`.partial` puis renommage), métadonnées de fin, `complete`."""

        job.state, job.phase = JobState.FINALIZING, "verifying"
        r = job.resolved
        frames = r.frames_total if r.fmt is RenderFormat.MP4 else None
        pages = len(r.frames) if r.fmt is RenderFormat.PDF else None
        verified = await self._run_blocking(self._runner.verify, job.job_id, r.fmt.value, width=r.out_width, height=r.out_height,
                                            frames=frames, pages=pages)
        job.phase = "storing"
        artifact = await self._artifacts.get(job.artifact_id)
        spool = self._artifacts.open_spool(artifact)
        try:
            await self._run_blocking(self._runner.copy_output, job.job_id, verified, spool.write)
            size = await self._run_blocking(spool.finalize)
        except BaseException:
            spool.close()
            raise
        if size != verified.size_bytes:
            raise RenderError(C.OUTPUT_INVALID, f"the stored file is {size} bytes, the verified render was {verified.size_bytes}")
        duration_ms = verified.duration_ms if verified.duration_ms is not None else None
        if r.fmt is RenderFormat.MP4 and duration_ms is None:
            duration_ms = round(1000 * r.frames_total / r.target.fps)
        denied = int(job.egress.get("proxy_denied", 0) or 0) + int(job.egress.get("blocked_connect", job.egress.get("blockedConnect", 0)) or 0)
        extra: dict[str, Any] = {"render_output_sha256": verified.sha256, "render_verified_by": verified.verified_by,
                                 "render_browser": job.browser.version, "render_egress_denied": denied,
                                 "render_wall_ms": int(((job.finished or time.time()) - (job.started or time.time())) * 1000)}
        if verified.pages is not None:
            extra["render_pages"] = verified.pages
        await self._artifacts.update_pending(job.artifact_id, metadata=extra)
        done = await self._artifacts.finalize(job.artifact_id, duration_ms=duration_ms, width=verified.width, height=verified.height)
        job.state, job.phase, job.finished = JobState.COMPLETE, "complete", time.time()
        job.size_bytes, job.verified_by, job.frames_done = done.size_bytes, verified.verified_by, r.frames_total
        await self._record(job)
        self._trace("complete", "Rendu de présentation terminé", data={
            "job_id": job.job_id, "artifact_id": job.artifact_id, "size_bytes": done.size_bytes, "sha256": verified.sha256,
            "verified_by": verified.verified_by, "elapsed_s": round(job.finished - (job.started or job.finished), 1),
            "egress_denied": denied})

    async def _fail_job(self, job: RenderJob, code: str, detail: str) -> None:
        cancelled = code == C.CANCELLED.value
        job.state = JobState.CANCELLED if cancelled else JobState.FAILED
        job.phase, job.error_code, job.error_detail, job.finished = ("cancelled" if cancelled else "failed"), code, clean_detail(detail), time.time()
        await self._fail_artifact(job, code)
        await self._record(job)
        self._trace("cancelled" if cancelled else "failed", "Rendu de présentation annulé" if cancelled else "Rendu de présentation échoué",
                    level="warning" if cancelled else "error", data={"job_id": job.job_id, "artifact_id": job.artifact_id, "code": code,
                                                                     "detail": job.error_detail, "log_tail": job.log_tail[-3:]})

    async def _fail_artifact(self, job: RenderJob, code: str) -> None:
        try:
            await self._artifacts.fail(job.artifact_id, error_code=code)
        except ArtifactError as exc:
            self._trace("fail_artifact_refused", "L'Artifact dérivé n'a pas pu être marqué en échec", level="error",
                        data={"job_id": job.job_id, "artifact_id": job.artifact_id, "code": exc.code.value})

    # ------------------------------------------------------------------ reprise, arrêt

    @staticmethod
    def owns(artifact: Artifact) -> bool:
        """Pour `ArtifactService.recover_pending(owned=...)` : un rendu `pending` appartient à ce service (jamais promu à l'aveugle)."""

        return artifact.kind in RENDER_KINDS

    async def reconcile(self) -> dict[str, int]:
        """Au démarrage de Core, avant tout rendu : un processus de rendu resté vivant est tué (identité contrôlée), les dossiers de
        travail sont effacés, chaque dérivé `pending` d'une vie précédente devient `failed` (`presentation_render_interrupted`), ou
        `partial` (`artifact_recovered`) si son fichier final existe déjà. Ne lève pas."""

        report = {"killed": 0, "failed": 0, "partial": 0, "kept": 0}
        try:
            for record in await self._run_blocking(self._runner.records):
                ref = str(record.get("process_ref") or "")
                if ref and await self._run_blocking(self._runner.alive, ref):
                    if await self._run_blocking(self._runner.stop, ref):
                        report["killed"] += 1
                    else:
                        report["kept"] += 1
                        self._trace("orphan_unkillable", "Un processus de rendu orphelin n'a pas pu être arrêté", level="error",
                                    data={"job_id": record.get("job_id")})
                if record.get("job_id"):
                    await self._run_blocking(self._runner.cleanup, str(record["job_id"]))
            cursor = None
            for _ in range(10):
                page = await self._artifacts.query(ArtifactQuery(kinds=tuple(sorted(RENDER_KINDS, key=lambda k: k.value)),
                                                                 states=(ArtifactState.PENDING,), cursor=cursor, limit=200))
                for artifact in page.items:
                    info = self._artifacts.payload_info(artifact)
                    if info is not None and info.final_bytes is not None:
                        await self._artifacts.recover(artifact.artifact_id)
                        report["partial"] += 1
                    else:
                        await self._artifacts.fail(artifact.artifact_id, error_code=C.INTERRUPTED.value)
                        report["failed"] += 1
                if page.next_cursor is None:
                    break
                cursor = page.next_cursor
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - argued: Core keeps starting; the failure is journalled with its type
            self._trace("reconcile_failed", "Reprise des rendus interrompue", level="error",
                        data={"exception": type(exc).__name__, "detail": clean_detail(exc)})
        self._trace("reconciled", "Reprise des rendus", level="warning" if any(report.values()) else "info", data=report)
        return report

    async def stop(self) -> None:
        """Arrêt de Core : plus de demande, le rendu en cours est annulé (arbre tué), les travaux en file échouent `interrupted`."""

        self._stopping = True
        queued = [self._jobs[j] for j in list(self._queue) if j in self._jobs]
        self._queue.clear()
        for job in queued:
            job.cancel.set()
            await self._fail_job(job, C.INTERRUPTED.value, "Core stopped before this render started")
        current = self._jobs.get(self._current or "")
        if current is not None:
            current.cancel.set()
        worker = self._worker
        if worker is not None and not worker.done():
            try:
                await asyncio.wait_for(asyncio.shield(worker), STOP_WAIT_S)
            except asyncio.TimeoutError:
                worker.cancel()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - argued: the worker already journalled its own failure
                pass

    # ------------------------------------------------------------------ interne

    def _position(self, job_id: str) -> int | None:
        try:
            return list(self._queue).index(job_id) + 1
        except ValueError:
            return None

    def _forget_old(self) -> None:
        done = sorted((j for j in self._jobs.values() if j.state.terminal), key=lambda j: j.finished or 0.0)
        for job in done[: max(0, len(done) - KEEP_FINISHED)]:
            self._jobs.pop(job.job_id, None)

    @staticmethod
    def _record_of(job: RenderJob) -> dict[str, Any]:
        return {"job_id": job.job_id, "artifact_id": job.artifact_id, "snapshot_id": job.snapshot_id, "state": job.state.value,
                "process_ref": job.process_ref, "format": job.resolved.fmt.value, "created_at": job.created, "error_code": job.error_code}

    async def _record(self, job: RenderJob) -> None:
        try:
            await self._run_blocking(self._runner.write_record, job.job_id, self._record_of(job))
        except RenderError as exc:
            self._trace("record_failed", "L'enregistrement de reprise du rendu n'a pas pu être écrit", level="error",
                        data={"job_id": job.job_id, "code": exc.code.value})

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(f"{TRACE}.{kind}", message, level=level, data=dict(data or {}))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal must not undo a committed write
            pass


__all__ = ["PresentationRenderService", "RenderJob", "RENDERS"]
