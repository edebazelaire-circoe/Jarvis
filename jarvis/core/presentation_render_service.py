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
- Concurrence 1 : les autres demandes attendent (`queued`). Au plus `MAX_ACTIVE_JOBS` (8) travaux non terminés, **créations en vol comprises** : la place est
  réservée avant le premier `await` (une rafale de 40 demandes en accepte 8, jamais plus), puis `queue_full`.
- Un même (snapshot, réglages résolus) n'est pas rendu deux fois : la demande rend le travail en cours ou le rendu `complete` existant (`deduplicated`).
- Un seul Core vivant par racine de données lance, reprend ou tue des rendus (`render/core.lock`).
- Le processus de rendu tourne isolé (`docs/remotion-render.md` §4) ; l'annulation tue l'arbre entier après contrôle d'identité (`pid:heure`).
- Portée `master` (`settings.scope`, jarvis-remotion-master-project-studio-export Slice 06, `docs/remotion-master-project.md` §10) : la
  composition maître de toute la variante figée, par le même hôte, le même navigateur, la même file ; plan `incompatible` -> 409
  `presentation_render_master_incompatible` avant toute création ; une scène qui lève -> `presentation_render_master_scene_failed`.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import replace
import hashlib
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from pathlib import Path
import shutil
import threading
import time
from typing import Any

from jarvis.core.artifact_service import ArtifactService
from jarvis.domain.artifacts import Artifact, ArtifactError, ArtifactQuery, ArtifactRelationKind, ArtifactState
from jarvis.domain.presentation_artifacts import RENDER_KINDS, RENDERS, RenderFormat, parse_render_format
from jarvis.domain.presentation_render import (
    CONCURRENCY_LIMIT, KEEP_FINISHED, KEEP_RENDERS_PER_SNAPSHOT, MAX_ACTIVE_JOBS, SCOPE_MASTER, JobState, MasterTarget, RenderError,
    RenderErrorCode as C, ResolvedRender, clean_detail, master_scene_failure, parse_settings, resolve,
)
from jarvis.domain.presentation_render_master import choose_master, frozen_plan, master_files, master_target
from jarvis.domain.presentation_render_plan import choose_scene, plan_files, representative_frame, still_scenes
from jarvis.domain.presentation_studio import PresentationStudioError
from jarvis.ports.artifacts import RelationDirection
from jarvis.ports.remotion_render import BrowserInfo, RenderRunner
from jarvis.ports.v2 import DiagnosticSink

TRACE = "core.presentation_render"
#: Native preview (Slice 13 of native-studio-playback-fix): frames per request, output scales, time bound, folders kept.
MAX_PREVIEW_FRAMES = 6
PREVIEW_SCALES = (0.25, 0.5, 1.0)
DEFAULT_PREVIEW_SCALE = 0.5
PREVIEW_TIMEOUT_S = 150.0
KEEP_PREVIEWS = 40
#: Slice 13 rework (QA B2): previews never pile up. At most this many previews wait (preparing or queued for the browser) while one renders;
#: any other is refused at once (`presentation_render_preview_busy`).
MAX_WAITING_PREVIEWS = 1
#: How long a preview waits for the browser (a running export or preview) before `presentation_render_preview_busy`.
PREVIEW_SLOT_WAIT_S = 60.0
#: How often a waiting or running preview checks that its HTTP caller is still there (a caller that left cancels it).
PREVIEW_POLL_S = 0.25


def default_preview_frames(duration_in_frames: int) -> tuple[int, ...]:
    """Three moments of a scene: after the entrances, the middle of the story, the held last frame."""

    last = max(0, duration_in_frames - 1)
    return tuple(sorted({min(last, round(last * 0.3)), min(last, round(last * 0.65)), last}))
STOP_WAIT_S = 15.0
SPOOL_PROGRESS_STEP = 8


class BrowserSlot:
    """One browser at a time on this host (memory), shared by exports and native previews. An export that wants the browser always goes
    before a waiting preview (exports keep priority); a preview waits with a deadline and gives up when its caller left. Single event loop:
    no check-then-set race between two coroutines."""

    def __init__(self) -> None:
        self.busy = False
        #: Exports between the worker's pick and the browser (counted before their first `await`, see `_execute`).
        self.exports_waiting = 0
        self._changed = asyncio.Event()

    def _kick(self) -> None:
        self._changed.set()  # wakes every current waiter once; the next ones wait on a fresh event
        self._changed = asyncio.Event()

    def want_export(self) -> None:
        self.exports_waiting += 1

    def withdraw_export(self) -> None:
        """An export that wanted the browser left before taking it (cancelled, failed in preparation)."""

        self.exports_waiting -= 1
        self._kick()

    async def take_export(self) -> None:
        while self.busy:
            await self._changed.wait()
        self.busy = True
        self.exports_waiting -= 1

    async def take_preview(self, *, exports_queued: Callable[[], bool], deadline: float, gone: Callable[[], bool]) -> None:
        """Raises `presentation_render_cancelled` when the caller left, `presentation_render_preview_busy` at the deadline."""

        while True:
            if gone():
                raise RenderError(C.CANCELLED, "the caller left before the preview started: nothing was rendered")
            if not self.busy and not self.exports_waiting and not exports_queued():
                self.busy = True
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RenderError(C.PREVIEW_BUSY, "the browser stayed busy (an export or another preview) for the whole wait: nothing was "
                                                  "rendered; retry once it is done")
            try:
                await asyncio.wait_for(self._changed.wait(), min(PREVIEW_POLL_S, remaining))
            except TimeoutError:
                pass  # intentional: a periodic look at the caller and the deadline, not a failure

    def release(self) -> None:
        self.busy = False
        self._kick()


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
        self.purge_payload = False

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
            "sandbox": self.egress.get("sandbox"), "deduplicated": False, **_scope_view(r),
        }


def _scope_view(resolved: ResolvedRender) -> dict[str, Any]:
    """The master fields of a job view (absent for a scene render: its view is unchanged)."""

    t = resolved.target
    if not isinstance(t, MasterTarget):
        return {}
    return {"scope": SCOPE_MASTER, "project_key": t.project_key, "scene_count": len(t.scene_ids)}


class PresentationRenderService:
    def __init__(self, *, artifacts: ArtifactService, snapshots: Any, packager: Any, runner: RenderRunner,
                 installed_engine: Callable[[], Any | None], capability_status: Callable[[], str] = lambda: "ready",
                 diagnostics: DiagnosticSink | None = None, run_blocking: Callable[..., Any] = asyncio.to_thread,
                 new_job_id: Callable[[], str] | None = None, preview_root: Callable[[], Path] | None = None,
                 preview_wait_s: float = PREVIEW_SLOT_WAIT_S,
                 live_master: Callable[[str, str], Awaitable[Any]] | None = None) -> None:
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
        self._reserved = 0  # creations in flight: counted against MAX_ACTIVE_JOBS from the moment they are accepted
        self._key_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._lock_holder: str | None = None  # another live Core holds the render lock
        self._lock_checked = False
        #: One browser at a time on this host (memory): a preview waits for a running export and the other way round; exports first.
        self._browser_slot = BrowserSlot()
        #: Previews admitted and not yet holding the browser (`MAX_WAITING_PREVIEWS`), and how long one may wait for it.
        self._previews_waiting = 0
        self._preview_wait_s = float(preview_wait_s)
        #: Where previews land (`<runtime>/render/previews`); `None`: this Core offers no preview.
        self._preview_root = preview_root
        #: `MasterProjectReader.live_plan`: an `export` with `scope: "master"` plans the LIVE variant first and refuses an incompatible one
        #: before anything is frozen (the frozen re-plan stays the authority once frozen). `None`: no pre-check (tests, old wiring).
        self._live_master = live_master

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
        if reason is None and self._lock_holder:
            reason = "another running Core holds the render lock of this data root"
        return {"ready": reason is None, "reason": reason, "browser": None if browser is None else browser.version,
                "concurrency": CONCURRENCY_LIMIT, "max_jobs": MAX_ACTIVE_JOBS, "active_jobs": self._active_count() + self._reserved}

    async def export(self, *, presentation_id: str, variant_id: str, expected_presentation_revision: int, expected_variant_revision: int,
                     authorised_boards: Collection[str], render_format: str, settings: object = None,
                     jarvis_session_id: str | None = None, context_id: str | None = None) -> dict[str, Any]:
        """Fige la variante (rejouable : le même couple de révisions retombe sur le même snapshot) PUIS demande le rendu de CE snapshot.
        Le gel passe par `PresentationPackager.freeze` (liste blanche de Boards obligatoire, révisions exactes)."""

        fmt = parse_render_format(render_format)  # un format invalide est refusé avant tout gel
        parsed = parse_settings(fmt, settings)
        self._require_ready()
        self._require_capacity()
        await self._require_engine_for(presentation_id, variant_id)  # nothing is frozen for a render this machine cannot make
        if parsed.scope == SCOPE_MASTER and self._live_master is not None:
            # nothing is frozen for a whole video the live variant cannot make; once frozen, the package's own plan decides (submit)
            master_target(await self._live_master(presentation_id, variant_id))
        frozen = await self._packager.freeze(
            presentation_id, variant_id, expected_presentation_revision=expected_presentation_revision,
            expected_variant_revision=expected_variant_revision, authorised_boards=authorised_boards,
            jarvis_session_id=jarvis_session_id, context_id=context_id)
        view = await self.submit(frozen["artifact_id"], fmt, settings, jarvis_session_id=jarvis_session_id, context_id=context_id)
        return {**view, "snapshot_replayed": bool(frozen.get("replayed")), "authorised_boards": frozen.get("authorised_boards", [])}

    async def submit(self, snapshot_id: str, render_format: RenderFormat | str, settings: object = None, *,
                     jarvis_session_id: str | None = None, context_id: str | None = None, deduplicate: bool = True) -> dict[str, Any]:
        """Valide tout ce qui peut l'être AVANT de créer quoi que ce soit, réserve une place, crée l'Artifact `pending`, met le travail en file.

        `deduplicate` (vrai par défaut) : un même (snapshot, réglages résolus) rend le travail en cours ou le rendu `complete` existant."""

        if self._stopping:
            raise RenderError(C.UNAVAILABLE, "Core is stopping")
        self._require_lock()
        fmt = parse_render_format(render_format)
        parsed = parse_settings(fmt, settings)
        browser = self._require_ready()
        package = await self._read_package(snapshot_id)
        if parsed.scope == SCOPE_MASTER:
            try:
                target: Any = choose_master(package)
            except RenderError as exc:
                if exc.code is C.MASTER_INCOMPATIBLE:
                    self._trace("master_incompatible", "Rendu de la vidéo entière refusé : variante figée non compatible", level="warning",
                                data={"snapshot_id": snapshot_id, **exc.extra})
                raise
        else:
            target = choose_scene(package, parsed.scene_id)
            # No frame named: the scene's representative still, never frame 0 (a scene that fades in is blank there; Slice 09 PM decision).
            if fmt is RenderFormat.STILL and parsed.frame is None:
                parsed = replace(parsed, frame=representative_frame(package, target))
            elif fmt is RenderFormat.PDF and parsed.frames is None:
                parsed = replace(parsed, frames=(representative_frame(package, target),))
        resolved = resolve(fmt, parsed, target)
        installed = self._installed()
        if installed is None or installed.remotion_version != target.engine_version:
            have = "unreadable" if installed is None else installed.remotion_version
            raise RenderError(C.ENGINE_MISMATCH, f"the snapshot was frozen for remotion {target.engine_version}, this machine has {have}: "
                                                 "a render is only made with the frozen engine version")
        key = (snapshot_id, resolved.settings_sha256)
        lock = self._key_locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:  # two identical requests at once: the second one finds the first one's job
                if deduplicate:
                    same = self._same_job(key) or await self._same_render(snapshot_id, resolved)
                    if same is not None:
                        self._trace("deduplicated", "Demande identique : rendu existant ou en cours rendu tel quel",
                                    data={"snapshot_id": snapshot_id, "settings_sha256": resolved.settings_sha256, "state": same.get("state")})
                        return same
                self._require_capacity()
                self._reserved += 1  # BEFORE the first await below: a burst of requests cannot all pass the check
                try:
                    job_id = self._new_id()
                    meta = {**resolved.to_metadata(), "render_job_id": job_id,
                            "render_engine_drift": installed.lock_sha256 != target.engine_lock_sha256}
                    artifact = await self._snapshots.begin_render(snapshot_id, fmt, jarvis_session_id=jarvis_session_id, context_id=context_id,
                                                                  metadata=meta)
                    job = RenderJob(job_id, artifact.artifact_id, snapshot_id, resolved, browser)
                    self._jobs[job_id] = job  # from here the job itself is counted (same loop turn: no gap)
                    self._queue.append(job_id)
                finally:
                    self._reserved -= 1
        finally:
            if not lock.locked() and not getattr(lock, "_waiters", None):
                self._key_locks.pop(key, None)
        await self._record(job)
        self._trace("queued", "Rendu de présentation mis en file", data={
            "job_id": job_id, "artifact_id": artifact.artifact_id, "snapshot_id": snapshot_id, "format": fmt.value,
            "frames": resolved.frames_total, "queued": len(self._queue), **_scope_view(resolved)})
        self._ensure_worker()
        return job.view(position=self._position(job_id))

    async def _read_package(self, snapshot_id: str) -> Any:
        """The snapshot package, re-read AND verified; any refusal is `presentation_render_snapshot_invalid` with the registry's code."""

        try:
            return await self._packager.read_snapshot(snapshot_id)
        except (ArtifactError, PresentationStudioError) as exc:
            raise RenderError(C.SNAPSHOT_INVALID, f"{getattr(exc, 'code', type(exc).__name__)}: {str(exc)[:200]}") from None
        except Exception as exc:  # noqa: BLE001 - argued: a damaged package (LiveRefError) is the same refusal, with its code
            code = getattr(exc, "code", None)
            raise RenderError(C.SNAPSHOT_INVALID, f"{getattr(code, 'value', code) or type(exc).__name__}: {str(exc)[:200]}") from None

    async def master_readiness(self, snapshot_id: str) -> dict[str, Any]:
        """Read only (`GET .../render/master?snapshot_id=`): the master plan view (§ 2) of a frozen snapshot, ready or incompatible.
        Starts nothing, needs no browser; an unreadable snapshot is `presentation_render_snapshot_invalid`."""

        package = await self._read_package(snapshot_id)
        plan = frozen_plan(package)
        self._trace("master_readiness", "Vidéo entière d'un snapshot : plan lu", data={
            "snapshot_id": snapshot_id, "status": plan.status.value, "reason": plan.reason.value if plan.reason else None,
            "project_key": plan.project_key, "scenes": len(plan.scenes)})
        # `stills` (Slice 09): the scenes an image or PDF export can name, with their titles, so a page offers the choice `RENDERS` asks for.
        return {**plan.to_wire(), "stills": still_scenes(package)}

    # ------------------------------------------------------------------ aperçu natif (Slice 13 native-studio-playback-fix)

    async def preview(self, *, presentation_id: str, variant_id: str, scene_id: str, frames: Sequence[int] | None = None,
                      scale: float = DEFAULT_PREVIEW_SCALE, gone: Callable[[], bool] = lambda: False) -> dict[str, Any]:
        """Render a few frames of ONE scene of the CURRENT variant, for the author to look at (an agent's `npx remotion still`).

        Same package assembler as an export (`assemble_preview`: in memory, no Board read), same guarded render host and browser, but no
        freeze, no Artifact, no queue entry: the JPEG frames land in `<runtime>/render/previews/<job>/` (the last `KEEP_PREVIEWS` folders
        are kept) and their paths are returned. Synchronous. Bounds (Slice 13 rework, QA B2): one browser at a time with the exports, which
        always go first; at most `MAX_WAITING_PREVIEWS` preview waits (preparing or queued for the browser), any other is refused at once
        (`presentation_render_preview_busy`); the wait for the browser ends at `preview_wait_s` (same code); the render at
        `PREVIEW_TIMEOUT_S`. `gone()` says the HTTP caller left: checked while waiting and every `PREVIEW_POLL_S` while rendering, it
        cancels the preview (the render process is stopped)."""

        if self._preview_root is None:
            raise RenderError(C.UNAVAILABLE, "this Core offers no preview (no render folder)")
        if self._stopping:
            raise RenderError(C.UNAVAILABLE, "Core is stopping")
        if not isinstance(scale, (int, float)) or isinstance(scale, bool) or float(scale) not in PREVIEW_SCALES:
            raise RenderError(C.INVALID, f"scale must be one of {list(PREVIEW_SCALES)}")
        if frames is not None and (not isinstance(frames, (list, tuple)) or not 1 <= len(frames) <= MAX_PREVIEW_FRAMES):
            raise RenderError(C.INVALID, f"frames must be a list of 1..{MAX_PREVIEW_FRAMES} frame numbers")
        self._require_lock()
        browser = self._require_ready()
        if self._previews_waiting >= MAX_WAITING_PREVIEWS:
            self._trace("preview_refused_busy", "Apercu natif refuse : un autre attend deja le navigateur", level="warning",
                        data={"presentation_id": presentation_id, "scene_id": scene_id, "waiting": self._previews_waiting})
            raise RenderError(C.PREVIEW_BUSY, "another preview is already waiting for the browser: nothing was rendered; retry once it is done")
        self._previews_waiting += 1  # BEFORE the first await: a burst of previews cannot all pass the check
        holding = False  # set right after `take_preview` returns (no await between): the outer `finally` releases what was taken
        try:
            try:
                await self._require_engine_for(presentation_id, variant_id)
                started = time.monotonic()
                package = await self._packager.assemble_preview(presentation_id, variant_id)
                target = choose_scene(package, scene_id)
                chosen = tuple(frames) if frames is not None else default_preview_frames(target.duration_in_frames)
                resolved = resolve(RenderFormat.PDF, parse_settings(RenderFormat.PDF, {"scene_id": scene_id, "frames": list(chosen),
                                                                                       "scale": float(scale)}), target)
                installed = self._installed()
                if installed is None or installed.remotion_version != target.engine_version:
                    have = "unreadable" if installed is None else installed.remotion_version
                    raise RenderError(C.ENGINE_MISMATCH, f"the scene declares remotion {target.engine_version}, this machine has {have}")
                files, props = plan_files(package, target)
                job_id = self._new_id()
                spec = {"format": RenderFormat.PDF.value, "entry": "studio-root.tsx", "composition_id": target.composition_id,
                        "composition": {"width": target.width, "height": target.height, "fps": target.fps, "durationInFrames": target.duration_in_frames},
                        "props": props, "frames_total": len(resolved.frames), "frame_range": [resolved.frame_start, resolved.frame_end],
                        "frames": list(resolved.frames), "crf": resolved.settings.crf, "scale": resolved.settings.scale, "concurrency": 1,
                        "jpeg_quality": 85}
                self._trace("preview_started", "Apercu natif d'une scene demande", data={
                    "job_id": job_id, "presentation_id": presentation_id, "variant_id": variant_id, "scene_id": scene_id,
                    "prefab": f"{target.prefab_id}@{target.version}", "frames": list(resolved.frames)})
                try:
                    await self._browser_slot.take_preview(exports_queued=lambda: bool(self._queue), gone=gone,
                                                          deadline=time.monotonic() + self._preview_wait_s)
                except RenderError as exc:
                    kind = "preview_abandoned" if exc.code is C.CANCELLED else "preview_wait_timeout"
                    self._trace(kind, "Apercu natif abandonne avant le navigateur", level="warning",
                                data={"job_id": job_id, "scene_id": scene_id, "code": exc.code.value, "wait_s": self._preview_wait_s})
                    raise
                holding = True
            finally:
                self._previews_waiting -= 1  # holding the browser, refused or failed: this preview no longer waits
            kept: list[dict[str, Any]] = []
            cancel = threading.Event()
            watcher = asyncio.get_running_loop().create_task(self._watch_caller(gone, cancel, job_id), name=f"preview-caller-{job_id}")
            try:
                await self._run_blocking(self._runner.prepare, job_id, files)
                if cancel.is_set():
                    raise RenderError(C.CANCELLED, "the caller left: the preview was cancelled")
                outcome = await self._run_blocking(self._runner.run, job_id, spec, browser=browser, cancel=cancel,
                                                   timeout_s=min(resolved.timeout_s, PREVIEW_TIMEOUT_S), on_start=lambda ref: None,
                                                   on_progress=lambda progress: None)
                if not outcome.ok:
                    raise RenderError(C.FAILED if outcome.code not in {c.value for c in C} else C(outcome.code), outcome.detail)
                outputs = list(outcome.outputs)
                if len(outputs) != len(resolved.frames):
                    raise RenderError(C.OUTPUT_INVALID, f"{len(outputs)} image(s) for {len(resolved.frames)} frame(s)")
                kept = await self._run_blocking(self._keep_preview, job_id, resolved.frames, outputs)
            except RenderError as exc:
                self._trace("preview_failed", "Apercu natif en echec", level="warning",
                            data={"job_id": job_id, "scene_id": scene_id, "code": exc.code.value, "detail": clean_detail(exc.detail)})
                raise
            finally:
                watcher.cancel()
        finally:
            # Slice 13 rework: the take is inside this `try`, so a cancellation or an error anywhere after it (the watcher, a future
            # `await`) can never leak the browser slot.
            if holding:
                self._browser_slot.release()
                await self._run_blocking(self._runner.cleanup, job_id)
        elapsed_ms = round((time.monotonic() - started) * 1000)
        self._trace("preview_done", "Apercu natif rendu", data={"job_id": job_id, "scene_id": scene_id, "frames": len(kept),
                                                                "elapsed_ms": elapsed_ms})
        return {"presentation_id": presentation_id, "variant_id": variant_id, "scene_id": scene_id,
                "prefab": {"id": target.prefab_id, "version": target.version},
                "composition": {"width": target.width, "height": target.height, "fps": target.fps,
                                "duration_in_frames": target.duration_in_frames},
                "scale": resolved.settings.scale, "frames": kept, "elapsed_ms": elapsed_ms}

    async def _watch_caller(self, gone: Callable[[], bool], cancel: threading.Event, job_id: str) -> None:
        """While a preview renders: the caller that left sets `cancel`, which stops the render process (as for an export's cancel)."""

        while not cancel.is_set():
            if gone():
                cancel.set()
                self._trace("preview_abandoned", "Apercu natif annule : l'appelant est parti", level="warning", data={"job_id": job_id})
                return
            await asyncio.sleep(PREVIEW_POLL_S)

    def _keep_preview(self, job_id: str, frames: Sequence[int], outputs: Sequence[Path]) -> list[dict[str, Any]]:
        assert self._preview_root is not None
        root = Path(self._preview_root())
        folder = root / job_id
        try:
            folder.mkdir(parents=True, exist_ok=True)
            kept = []
            for frame, source in zip(frames, outputs):
                target = folder / f"frame-{int(frame):05d}.jpg"
                shutil.copyfile(source, target)
                kept.append({"frame": int(frame), "path": str(target), "bytes": target.stat().st_size})
            older = sorted((p for p in root.iterdir() if p.is_dir() and p.name != job_id), key=lambda p: p.stat().st_mtime)
            for stale in older[: max(0, len(older) - KEEP_PREVIEWS + 1)]:
                shutil.rmtree(stale, ignore_errors=True)  # intentional: an old preview folder that resists removal is retried next time
            return kept
        except OSError as exc:
            raise RenderError(C.STORE_FAILED, f"{type(exc).__name__}: the preview frames could not be kept") from None

    # ------------------------------------------------------------------ capacité, doublons, verrou

    def _active_count(self) -> int:
        return sum(1 for job in self._jobs.values() if not job.state.terminal)

    def _require_capacity(self) -> None:
        if self._active_count() + self._reserved >= MAX_ACTIVE_JOBS:
            raise RenderError(C.QUEUE_FULL, f"{MAX_ACTIVE_JOBS} renders are already running or waiting")

    def _require_lock(self) -> None:
        if self._lock_holder:
            raise RenderError(C.LOCKED, "another running Core holds the render lock of this data root: this Core renders nothing "
                                        "(two Cores must not share one render folder)")

    def _same_job(self, key: tuple[str, str]) -> dict[str, Any] | None:
        for job in self._jobs.values():
            if (job.snapshot_id, job.resolved.settings_sha256) == key and not job.state.terminal:
                return {**job.view(position=self._position(job.job_id)), "deduplicated": True}
        return None

    async def _same_render(self, snapshot_id: str, resolved: ResolvedRender) -> dict[str, Any] | None:
        """Le rendu `complete` de CE snapshot avec ces réglages résolus, s'il existe déjà dans le registre (hors mémoire de ce Core)."""

        dependents = await self._artifacts.relations(snapshot_id, RelationDirection.DEPENDENTS)
        for relation in dependents:
            if relation.relation is not ArtifactRelationKind.RENDERED_FROM:
                continue
            artifact = await self._artifacts.get(relation.artifact_id)
            if (artifact.state is ArtifactState.COMPLETE and artifact.kind in RENDER_KINDS
                    and artifact.metadata.get("render_settings_sha256") == resolved.settings_sha256):
                return {"job_id": artifact.metadata.get("render_job_id"), "artifact_id": artifact.artifact_id, "snapshot_id": snapshot_id,
                        "state": "complete", "phase": "complete", "format": resolved.fmt.value, "scene_id": resolved.target.scene_id,
                        "frames_done": resolved.frames_total, "frames_total": resolved.frames_total, "percent": 100, "can_cancel": False,
                        "cancel_requested": False, "error_code": None, "error_detail": None, "size_bytes": artifact.size_bytes,
                        "settings": resolved.canonical(), "settings_sha256": resolved.settings_sha256, "deduplicated": True,
                        "queue_position": None, "elapsed_s": 0.0, "timeout_s": int(resolved.timeout_s), "started_at": None,
                        "created_at": artifact.created_at.timestamp(), "browser": artifact.metadata.get("render_browser"),
                        "egress_denied": artifact.metadata.get("render_egress_denied", 0), "verified_by": artifact.metadata.get("render_verified_by"),
                        "log_tail": [], "sandbox": artifact.metadata.get("render_sandbox"), **_scope_view(resolved)}
        return None

    async def _require_engine_for(self, presentation_id: str, variant_id: str) -> None:
        """Avant de FIGER (export) : le moteur installé est celui que les scènes Remotion de la variante demandent."""

        installed = self._installed()
        for version in await self._packager.remotion_engines(presentation_id, variant_id):
            if installed is None or installed.remotion_version != version:
                have = "unreadable" if installed is None else installed.remotion_version
                raise RenderError(C.ENGINE_MISMATCH, f"the scenes need remotion {version}, this machine has {have}: nothing was frozen")

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

    async def cancel(self, job_id: str) -> dict[str, Any]:
        """File d'attente : le travail est retiré, son dérivé `failed` (`presentation_render_cancelled`) AVANT de répondre. En cours : le
        signal est posé, la vue dit `cancel_requested` et le processus (arbre entier) est tué dans la seconde ; l'état terminal n'apparaît
        qu'une fois le dérivé lui-même terminal."""

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
            await self._fail_job(job, C.CANCELLED.value, "cancelled before it started")
        return job.view(position=self._position(job_id))

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
                if not job.state.terminal:  # a job that already completed is never turned into a failure by the shutdown
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
        self._browser_slot.want_export()  # before the first await: a waiting preview sees this export ahead of it (exports first)
        wants_browser = True
        job.state, job.phase, job.started = JobState.RUNNING, "preparing", time.time()
        self._trace("started", "Rendu de présentation démarré", data={"job_id": job.job_id, "artifact_id": job.artifact_id})
        try:
            package = await self._packager.read_snapshot(job.snapshot_id)  # relu et revérifié : le paquet n'a pas changé depuis la demande
            r = job.resolved
            if isinstance(r.target, MasterTarget):
                # the master composition takes no input props: each scene's merged props are inlined in the generated Presentation.tsx
                files, props = master_files(package, r.target), {}
            else:
                files, props = plan_files(package, r.target)
            await self._run_blocking(self._runner.prepare, job.job_id, files)
            spec = {"format": r.fmt.value, "entry": "studio-root.tsx", "composition_id": r.target.composition_id,
                    "composition": {"width": r.target.width, "height": r.target.height, "fps": r.target.fps,
                                    "durationInFrames": r.target.duration_in_frames},
                    "props": props, "frames_total": r.frames_total, "frame_range": [r.frame_start, r.frame_end],
                    "frames": list(r.frames), "crf": r.settings.crf, "scale": r.settings.scale, "concurrency": r.settings.concurrency,
                    "jpeg_quality": 90}
            if job.cancel.is_set():
                raise RenderError(C.CANCELLED, "cancelled before the process started")
            loop = asyncio.get_running_loop()
            await self._browser_slot.take_export()
            wants_browser = False

            def on_start(ref: str) -> None:
                job.process_ref = ref
                self._runner.write_record(job.job_id, self._record_of(job))

            def on_progress(progress: Mapping[str, Any]) -> None:
                loop.call_soon_threadsafe(self._apply_progress, job, dict(progress))

            try:
                outcome = await self._run_blocking(self._runner.run, job.job_id, spec, browser=job.browser, cancel=job.cancel,
                                                   timeout_s=r.timeout_s, on_start=on_start, on_progress=on_progress)
            finally:
                self._browser_slot.release()
            job.egress, job.log_tail = dict(outcome.egress), list(outcome.log_tail)
            if not outcome.ok:
                failed_scene = master_scene_failure(outcome.detail) if r.master else None
                if failed_scene is not None:
                    scene_id, position, message = failed_scene
                    raise RenderError(C.MASTER_SCENE_FAILED, f"scene {position} ({scene_id}) failed while rendering: {message}")
                raise RenderError(C.FAILED if outcome.code not in {c.value for c in C} else C(outcome.code), outcome.detail)
            await self._finalize(job)
        except RenderError as exc:
            await self._fail_job(job, exc.code.value, exc.detail)
            if job.purge_payload:  # a verified-then-different copy must not stay on disk under a failed derivative
                await self._purge(job.artifact_id)
        finally:
            if wants_browser:  # failed or cancelled before the browser: a waiting preview may go now
                self._browser_slot.withdraw_export()
            await self._run_blocking(self._runner.cleanup, job.job_id)
            await self._retain(job.snapshot_id)

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
        # A master whose scenes play an `<Audio>` must come out with an audio stream; a scene render is verified exactly as before.
        audio = {"audio_required": True} if r.audio_required else {}
        verified = await self._run_blocking(self._runner.verify, job.job_id, r.fmt.value, width=r.out_width, height=r.out_height,
                                            frames=frames, pages=pages, **audio)
        job.phase = "storing"
        artifact = await self._artifacts.get(job.artifact_id)
        spool = self._artifacts.open_spool(artifact)
        try:
            await self._run_blocking(self._runner.copy_output, job.job_id, verified, spool.write)
            size = await self._run_blocking(spool.finalize)
        except BaseException:
            spool.close()
            raise
        stored = await self._run_blocking(self._hash_payload, self._artifacts.payload_path(artifact))
        if size != verified.size_bytes or stored != verified.sha256:
            job.purge_payload = True
            raise RenderError(C.OUTPUT_INVALID, f"the stored copy ({size} bytes) is not the verified render ({verified.size_bytes} bytes, sha256 differs: "
                                                f"{stored != verified.sha256}): not registered")
        duration_ms = verified.duration_ms if verified.duration_ms is not None else None
        if r.fmt is RenderFormat.MP4 and duration_ms is None:
            duration_ms = round(1000 * r.frames_total / r.target.fps)
        denied = int(job.egress.get("proxy_denied", 0) or 0) + int(job.egress.get("blocked_connect", job.egress.get("blockedConnect", 0)) or 0)
        extra: dict[str, Any] = {"render_output_sha256": verified.sha256, "render_verified_by": verified.verified_by,
                                 "render_sandbox": bool(job.egress.get("sandbox", True)),
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
        """Dérivé `failed` d'abord, état terminal du travail ensuite : qui voit `failed` / `cancelled` lit un dérivé déjà terminal. Le travail devient
        TOUJOURS terminal : si le registre refuse (base en défaut), l'échec est journalisé en erreur, le détail le dit, et la reprise du prochain
        démarrage achèvera le dérivé resté `pending` ; jamais un travail laissé `running` en mémoire."""

        cancelled = code == C.CANCELLED.value
        job.error_code, job.error_detail = code, clean_detail(detail)
        try:
            await self._fail_artifact(job, code)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - argued: the job must still end; the registry failure is journalled and said
            job.error_detail = clean_detail(f"{detail} (the derivative could not be marked failed: {type(exc).__name__}; it is recovered at the next start)")
            self._trace("fail_artifact_failed", "Le registre n'a pas pu marquer le dérivé en échec", level="error",
                        data={"job_id": job.job_id, "artifact_id": job.artifact_id, "exception": type(exc).__name__})
        job.phase, job.finished = ("cancelled" if cancelled else "failed"), time.time()
        job.state = JobState.CANCELLED if cancelled else JobState.FAILED
        try:
            await self._record(job)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - argued: `_record` already journals its own failure; the state above is what matters
            pass
        self._trace("cancelled" if cancelled else "failed", "Rendu de présentation annulé" if cancelled else "Rendu de présentation échoué",
                    level="warning" if cancelled else "error", data={"job_id": job.job_id, "artifact_id": job.artifact_id, "code": code,
                                                                     "detail": job.error_detail, "log_tail": job.log_tail[-3:]})

    @staticmethod
    def _hash_payload(path: str | None) -> str:
        sha = hashlib.sha256()
        with open(path or "", "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                sha.update(chunk)
        return sha.hexdigest()

    async def _purge(self, artifact_id: str) -> None:
        try:
            await self._artifacts.purge_payload(artifact_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - argued: retention is best effort and journalled, never a render failure
            self._trace("purge_failed", "Fichier d'un rendu en échec non retiré", level="warning",
                        data={"artifact_id": artifact_id, "exception": type(exc).__name__})

    async def _retain(self, snapshot_id: str) -> None:
        """Rétention : par snapshot, les `KEEP_RENDERS_PER_SNAPSHOT` plus récents rendus gardent leurs fichiers ; au-delà, le payload d'un rendu
        `failed` ou `partial` est retiré (le dérivé reste un enregistrement terminal). Un rendu `complete` n'est jamais retiré ici."""

        try:
            dependents = await self._artifacts.relations(snapshot_id, RelationDirection.DEPENDENTS)
            derived = [await self._artifacts.get(r.artifact_id) for r in dependents if r.relation is ArtifactRelationKind.RENDERED_FROM]
            derived.sort(key=lambda a: (a.created_at, a.artifact_id), reverse=True)
            for artifact in derived[KEEP_RENDERS_PER_SNAPSHOT:]:
                if artifact.state in (ArtifactState.FAILED, ArtifactState.PARTIAL):
                    await self._purge(artifact.artifact_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - argued: best effort, journalled
            self._trace("retention_failed", "Rétention des rendus interrompue", level="warning", data={"exception": type(exc).__name__})

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

        report: dict[str, Any] = {"killed": 0, "failed": 0, "partial": 0, "kept": 0}
        try:
            holder = await self._run_blocking(self._runner.acquire_lock)
            if holder:
                # Another LIVE Core owns this data root's renders: its jobs are not orphans, nothing is killed, failed or cleaned here.
                self._lock_holder = holder
                report["locked"] = True
                self._trace("lock_held", "Un autre Core vivant tient le verrou des rendus : aucune reprise, aucun rendu ici", level="error",
                            data={"holder": str(holder)[:80]})
                return report
            self._lock_holder = None
            for record in await self._run_blocking(self._runner.records):
                if record.get("state") in ("complete", "failed", "cancelled"):
                    continue  # finished before the previous stop: nothing runs, nothing to kill
                ref = str(record.get("process_ref") or "")
                if ref and await self._run_blocking(self._runner.alive, ref):
                    if await self._run_blocking(self._runner.stop, ref):
                        report["killed"] += 1
                    else:
                        report["kept"] += 1
                        self._trace("orphan_unkillable", "Un processus de rendu orphelin n'a pas pu être arrêté", level="error",
                                    data={"job_id": record.get("job_id")})
                if record.get("job_id"):
                    if await self._run_blocking(self._runner.sweep, str(record["job_id"])):
                        report["killed"] += 1
                    await self._run_blocking(self._runner.cleanup, str(record["job_id"]))
                    # the record says so too: a job handled here is never treated as running at the next start
                    await self._run_blocking(self._runner.write_record, str(record["job_id"]),
                                             {**{k: v for k, v in record.items() if k != "unreadable"}, "job_id": str(record["job_id"]),
                                              "state": "failed", "error_code": C.INTERRUPTED.value})
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
        await self._run_blocking(self._runner.prune, KEEP_FINISHED * 5)
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
        if not self._lock_holder:
            await self._run_blocking(self._runner.release_lock)

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
