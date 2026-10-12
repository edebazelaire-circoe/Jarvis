"""Legacy run-stage reclaim (handoff jarvis-interactive-presentation-studio, Slice 12; retired by native-studio-playback-fix Slice 09).

Until Slice 09 a playback run was shown on a Board window of its own (`studio-stage-<run_id>`, category `studio_stage`) and its
detours on hidden-then-revealed Board windows (`studio-aux-*`, category `studio_aux`), with an id-list ledger on disk so a Core killed
mid-run could archive exactly those at its next start. That surface is **retired**: a run now plays inside Variants, on a memory
surface (`presentation_studio_run_surface.py`), and Core never writes a Board object for a run.

What stays here, and why:

- `StageError`: the typed failure of the run surface (`code` stable, `message` the real cause), raised by `RunSurface` and read by the
  playback service.
- `LegacyStageReclaimer`: **one last reclaim pass** for what an older Core left on this machine's scene (contract
  `docs/presentation-studio.md` > *2026-10 § 2*, PX-16). At Core start and before each run it archives
  1. the ids of the old ledger file (`StageLedger`, read only), and
  2. every object this module namespaced, found by a scan of the scene: category `studio_stage` **and** an id starting
     `studio-stage-`, or category `studio_aux` **and** an id starting `studio-aux-` (never a free filter: a brain object of the same
     shape but another id survives).
  An id the scene no longer knows is already gone (not a failure). Once the archive succeeded, the ledger file is **kept aside**
  (`<file>.retired-<UTC timestamp>`, repo data rules: never deleted without a copy) and no new one is ever written. An unreadable
  ledger is quarantined (`.corrupt-<timestamp>`) and said as an `error` row, then the scan still runs.
- The category and prefix constants: the Tool Brain keeps these retired categories reserved (`tool_brain_executor.studio_owned_targets`),
  the Control Center page never draws them (`control_center_scene_page.js`), the document hygiene still refuses stage handles.

Contract: `docs/presentation-studio.md` > *Variants run surface (Level 3, Slice 09)*.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from jarvis.domain.scene import SceneActor, SceneCommand, SceneCommandOutcome, SceneOp
from jarvis.domain.scene_selection import SceneSelection
from jarvis.ports.v2 import DiagnosticSink

STAGE_CATEGORY = "studio_stage"
AUX_CATEGORY = "studio_aux"
#: Retired Board categories of the floating viewer (the page never draws them, the Tool Brain never writes them).
LEGACY_CATEGORIES = frozenset({STAGE_CATEGORY, AUX_CATEGORY})
#: Ids read from an old ledger, and the scan bound (one archive command).
MAX_LEDGER_IDS = 16
MAX_SCAN_IDS = 64
STAGE_ID_PREFIX = "studio-stage-"
AUX_ID_PREFIX = "studio-aux-"
TRACE_PREFIX = "core.presentation_studio"


class StageError(Exception):
    """The run surface (or the catalogue behind it) refused or failed; `code` is stable, `message` carries the real cause."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


class LedgerStore(Protocol):
    """Where an older Core kept its ids (the file adapter in production, memory in tests). Read only, then retired."""

    def read(self) -> list[str] | None: ...  # None: no ledger (the normal state); raises on an unreadable one

    def retire(self) -> str | None: ...  # keep the file aside once its ids are taken back; returns the new name

    def quarantine(self) -> str | None: ...  # keep an unreadable ledger aside; returns the new name (None: nothing to keep)


class StageLedger:
    """The old id ledger, read once and retired. Never written again (Slice 09)."""

    def __init__(self, store: LedgerStore, *, diagnostics: DiagnosticSink | None = None) -> None:
        self._store, self._diagnostics = store, diagnostics

    def load(self) -> tuple[str, ...]:
        """The ids an older life left. An unreadable ledger is an `error` row and is kept aside, never "nothing to do"."""

        try:
            stored = self._store.read()
        except Exception as exc:  # noqa: BLE001 - captured as an error row below; the scan still runs
            _trace(self._diagnostics, "stage_ledger_unreadable", "Registre de la fenetre de scene illisible", level="error",
                   data={"error_class": type(exc).__name__})
            self._keep_aside("quarantine", "stage_ledger_quarantined", "Registre illisible conserve a part")
            return ()
        return tuple(i for i in (stored or []) if isinstance(i, str) and i)[:MAX_LEDGER_IDS]

    def retire(self) -> None:
        """The ids are taken back: the file is kept aside (never deleted) and no ledger exists any more."""

        self._keep_aside("retire", "stage_ledger_retired", "Registre de l'ancienne fenetre de scene mis de cote")

    def _keep_aside(self, method: str, kind: str, message: str) -> None:
        keep = getattr(self._store, method, None)
        if keep is None:
            return
        try:
            name = keep()
        except Exception as exc:  # noqa: BLE001 - captured as an error row; the reclaim itself is done
            _trace(self._diagnostics, f"{kind}_failed", f"{message} : echec", level="error", data={"error_class": type(exc).__name__})
            return
        if name:
            _trace(self._diagnostics, kind, message, level="warning", data={"file": name})


class LegacyStageReclaimer:
    """See the module header. `scene`: `SceneService` (`apply_if`)."""

    def __init__(self, scene: Any, ledger: StageLedger, *, diagnostics: DiagnosticSink | None = None,
                 actor: SceneActor = SceneActor.USER) -> None:
        self._scene, self._ledger, self._diagnostics, self._actor = scene, ledger, diagnostics, actor

    async def reclaim(self) -> tuple[str, ...]:
        """Archive what an older Core left (ledger ids + namespaced scan). Returns the ids taken back. Raises `StageError` when
        the scene refuses the archive (the caller says it; the next pass tries again)."""

        listed = self._ledger.load()
        found: list[str] = []

        def plan(snapshot: Any) -> SceneCommand | None:
            known = {o.object_id for o in snapshot.objects}
            scanned = [o.object_id for o in snapshot.objects
                       if (o.category == STAGE_CATEGORY and o.object_id.startswith(STAGE_ID_PREFIX))
                       or (o.category == AUX_CATEGORY and o.object_id.startswith(AUX_ID_PREFIX))]
            found[:] = list(dict.fromkeys([*(i for i in listed if i in known), *scanned]))[:MAX_SCAN_IDS]
            if not found:
                return None
            return SceneCommand(op=SceneOp.ARCHIVE_SELECTION, actor=self._actor, selection=SceneSelection(ids=tuple(found)))

        try:
            update = await self._scene.apply_if(plan)
        except (ValueError, TypeError) as exc:
            raise StageError("stage_invalid", f"{type(exc).__name__}: {exc}") from exc
        if update is not None and update.outcome not in (SceneCommandOutcome.APPLIED, SceneCommandOutcome.DUPLICATE):
            reason = update.reason.value if update.reason is not None else update.outcome.value
            raise StageError(reason, update.detail or f"the scene refused the archive ({reason})")
        if listed:
            self._ledger.retire()
        if found:
            _trace(self._diagnostics, "legacy_stage_reclaimed", "Anciennes fenetres de lecture archivees (vue flottante retiree)",
                   level="warning", data={"count": len(found), "from_ledger": len(listed)})
        return tuple(found)


def _trace(diagnostics: DiagnosticSink | None, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
    if diagnostics is None:
        return
    try:
        diagnostics.emit(f"{TRACE_PREFIX}.{kind}", message, level=level, data=dict(data))
    except Exception:  # noqa: BLE001 - intentional: an unavailable journal never undoes a reclaim
        pass
