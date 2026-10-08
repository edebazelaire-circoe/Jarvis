"""The stage window and the auxiliary windows of a playback run (handoff jarvis-interactive-presentation-studio, Slice 12).

The only writer of the global scene for the Studio's playback. It speaks **scene commands** to `SceneService`
(`apply_if`, as the prefab event service does: docs/07 section 4.4), as the same actor the Control Center relays
(`SceneActor.USER`); it adds no renderer, no prefab path and no second scene tool. The MCP `scene_*` tools
(`SceneDisplayTools`) are the same commands wrapped for the brain process, which Core cannot import.

- **One stable stage window per run.** `show(payload)` creates it once and *patches* it afterwards (`PATCH_OBJECT` with
  the next scene's `prefab` block): a prefab id/version change remounts the frame, a props/data change is a
  `host.update` (docs/prefabs.md Lifecycle). A re-show of the payload already on screen writes nothing, so the state a
  frame holds is not reset by a "resume". An archived id keeps its tombstone and can never be reused: the id carries the
  run id, and a stage the user closed is re-created once under a new generation, not silently ignored.
- **Auxiliary windows are staged hidden at birth, revealed, and always retired.** Same lifetime rule as the speculative
  stager (docs/presentation-speculative-preparation.md section 8): a scene object is durable, so the Studio asks the
  scene to archive what it put there. `retire` is the only exit and it is called on detour end, run stop, crash and
  restart (`reclaim`).
- **An id-list ledger on disk** (`StageLedger`, the `StagedObjectLedger` precedent, `jarvis/runtime/presentation_runtime.py`)
  records the ids this module created, after the scene accepted them and until the archive succeeded, so a Core killed
  mid-run can take back exactly its own objects at the next start. By id list, never by filter: a filter would also
  archive objects the brain or the user made with the same shape. It holds ids only (no title, no content) and is
  deleted when empty.

Contract: `docs/presentation-studio.md` > *Playback runtime contract*, Stage window.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from jarvis.domain.scene import (
    Representation, SceneActor, SceneCommand, SceneCommandOutcome, SceneObjectFields, SceneObjectKind, SceneOp,
    ScenePayload, ScenePrefabRef, Visibility,
)
from jarvis.domain.scene_selection import SceneSelection
from jarvis.ports.v2 import DiagnosticSink

STAGE_CATEGORY = "studio_stage"
AUX_CATEGORY = "studio_aux"
#: Ids on disk. Stage + 4 auxiliary windows of one run, and room for the leftovers of one crashed run.
MAX_LEDGER_IDS = 16
TRACE_PREFIX = "core.presentation_studio"


class StageError(Exception):
    """The scene refused or failed; `code` is stable, `message` carries the real cause (never re-labelled)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


class LedgerStore(Protocol):
    """Where the ledger keeps its ids (the file adapter in production, memory in tests)."""

    def read(self) -> list[str] | None: ...  # None: no ledger (the normal first run); raises on an unreadable one

    def write(self, ids: Sequence[str]) -> None: ...

    def erase(self) -> None: ...


class StageLedger:
    def __init__(self, store: LedgerStore, *, diagnostics: DiagnosticSink | None = None) -> None:
        self._store, self._diagnostics = store, diagnostics
        self._ids: list[str] = []

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(self._ids)

    def load(self) -> tuple[str, ...]:
        """The ids a previous life left. An unreadable ledger is an `error` row (we no longer know what to take back),
        never "nothing to do"."""

        try:
            stored = self._store.read()
        except Exception as exc:  # noqa: BLE001 - captured as an error row below, then the run continues with an empty ledger
            self._trace("stage_ledger_unreadable", "Registre de la fenetre de scene illisible", level="error",
                        data={"error_class": type(exc).__name__})
            self._ids = []
            return ()
        self._ids = [i for i in (stored or []) if isinstance(i, str) and i][:MAX_LEDGER_IDS]
        return tuple(self._ids)

    def add(self, object_id: str) -> None:
        if object_id in self._ids:
            return
        self._ids.append(object_id)
        if len(self._ids) > MAX_LEDGER_IDS:
            # The asymmetric risk is a leak (an id nobody takes back), so overflow is said loudly, not dropped quietly.
            dropped = len(self._ids) - MAX_LEDGER_IDS
            del self._ids[:dropped]
            self._trace("stage_ledger_overflow", "Registre plein : des identifiants ne seront plus repris",
                        level="error", data={"dropped": dropped, "kept": MAX_LEDGER_IDS})
        self._flush()

    def remove(self, object_ids: Sequence[str]) -> None:
        kept = [i for i in self._ids if i not in set(object_ids)]
        if len(kept) != len(self._ids):
            self._ids = kept
            self._flush()

    def clear(self) -> None:
        self._ids = []
        self._flush()

    def _flush(self) -> None:
        try:
            if self._ids:
                self._store.write(self._ids)
            else:
                self._store.erase()
        except Exception as exc:  # noqa: BLE001 - captured as an error row; the run goes on, the leak risk is said
            self._trace("stage_ledger_unwritable", "Registre de la fenetre de scene non ecrit", level="error",
                        data={"error_class": type(exc).__name__, "ids": len(self._ids)})

    def _trace(self, kind: str, message: str, *, level: str, data: Mapping[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(f"{TRACE_PREFIX}.{kind}", message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001 - intentional: a failing journal never breaks the reclaim it observes
            pass


class SceneStage:
    def __init__(self, scene: Any, ledger: StageLedger, *, diagnostics: DiagnosticSink | None = None,
                 actor: SceneActor = SceneActor.USER) -> None:
        self._scene, self._ledger, self._diagnostics, self._actor = scene, ledger, diagnostics, actor
        self._run: str | None = None
        self._generation = 0
        self._stage_id: str | None = None
        self._shown: ScenePayload | None = None

    @property
    def stage_object_id(self) -> str | None:
        return self._stage_id

    # ------------------------------------------------------------ run lifecycle

    def begin(self, run_id: str) -> None:
        self._run, self._generation, self._stage_id, self._shown = run_id, 0, None, None

    async def show(self, payload: ScenePayload) -> bool:
        """Show `payload` on the one stage window: create it, or patch it. `True` when the scene changed."""

        if self._run is None:
            raise StageError("stage_not_begun", "no run owns the stage")
        if payload == self._shown and self._stage_id is not None:
            return False
        created: list[str] = []

        def plan(snapshot: Any) -> SceneCommand | None:
            current = snapshot.get_object(self._stage_id) if self._stage_id is not None else None
            if current is not None:
                if current.payload == payload:
                    return None
                return SceneCommand(op=SceneOp.PATCH_OBJECT, actor=self._actor, object_id=current.object_id,
                                    fields=SceneObjectFields(payload=payload))
            if self._stage_id is not None:
                self._generation += 1  # the user closed it: a tombstone keeps the old id, so this is a new window
            object_id = f"studio-stage-{self._run}" + (f"-{self._generation}" if self._generation else "")
            created.append(object_id)
            return SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=self._actor, object_id=object_id,
                                fields=SceneObjectFields(kind=SceneObjectKind.WINDOW, category=STAGE_CATEGORY,
                                                         payload=payload, representation=Representation.WINDOW))

        update = await self._apply(plan)
        if created and update is not None and update.outcome in (SceneCommandOutcome.APPLIED, SceneCommandOutcome.DUPLICATE):
            self._stage_id = created[0]
            self._ledger.add(created[0])  # after the scene accepted it: noting an id that does not exist would mislead
        self._shown = payload
        self._trace("stage_shown", "Fenetre de scene du Studio affichee",
                    data={"object_id": self._stage_id, "created": bool(created), "prefab": payload.prefab.key
                          if payload.prefab else None})
        return update is not None

    async def release(self) -> None:
        """Archive the stage window (the run is over). The tombstone is the scene's, the ledger entry is dropped after."""

        if self._stage_id is None:
            return
        stage_id, self._stage_id, self._shown = self._stage_id, None, None
        await self._archive([stage_id])

    # ------------------------------------------------------------ auxiliary windows

    async def stage_aux(self, aux_id: str, title: str, block: ScenePrefabRef) -> str:
        """Create an auxiliary window **hidden at birth** (never visible between create and reveal)."""

        if self._run is None:
            raise StageError("stage_not_begun", "no run owns the stage")
        object_id = f"studio-aux-{self._run}-{aux_id}"
        payload = ScenePayload(title=title, prefab=block)
        command = SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=self._actor, object_id=object_id,
                               fields=SceneObjectFields(kind=SceneObjectKind.WINDOW, category=AUX_CATEGORY, payload=payload,
                                                        representation=Representation.WINDOW,
                                                        visibility=Visibility.HIDDEN))
        await self._apply(lambda _snapshot: command)
        self._ledger.add(object_id)
        self._trace("aux_staged", "Ressource auxiliaire montee, masquee des sa creation",
                    data={"object_id": object_id, "prefab": block.key})
        return object_id

    async def reveal_aux(self, object_id: str) -> None:
        command = SceneCommand(op=SceneOp.SET_VISIBILITY, actor=self._actor, object_id=object_id,
                               visibility=Visibility.VISIBLE)
        await self._apply(lambda _snapshot: command)
        self._trace("aux_revealed", "Ressource auxiliaire affichee", data={"object_id": object_id})

    async def retire(self, object_ids: Sequence[str]) -> None:
        await self._archive(list(object_ids))

    async def reclaim(self) -> tuple[str, ...]:
        """Take back what a killed life left, by id list. Returns what was taken back."""

        pending = self._ledger.load()
        if not pending:
            return ()
        await self._archive(list(pending), unknown_is_gone=True)
        return pending

    # ------------------------------------------------------------ internals

    async def _archive(self, ids: list[str], *, unknown_is_gone: bool = False) -> None:
        ids = list(dict.fromkeys(i for i in ids if i))
        if not ids:
            return
        command = SceneCommand(op=SceneOp.ARCHIVE_SELECTION, actor=self._actor, selection=SceneSelection(ids=tuple(ids)))
        try:
            await self._apply(lambda _snapshot: command)
        except StageError as exc:
            # An id the scene no longer knows (archived by the user, scene restored from a backup) is already gone: the
            # reclaim's goal is met. Any other refusal is a real failure and stays one.
            if not (unknown_is_gone or exc.code in _GONE_CODES):
                raise
            self._trace("archive_already_gone", "Objet deja retire de la scene", level="info",
                        data={"ids": len(ids), "code": exc.code})
        self._ledger.remove(ids)
        self._trace("archived", "Objets du Studio retires de la scene", data={"ids": len(ids)})

    async def _apply(self, plan: Callable[[Any], SceneCommand | None]) -> Any:
        try:
            update = await self._scene.apply_if(plan)
        except (ValueError, TypeError) as exc:  # a payload beyond the scene's bounds, a malformed command
            raise StageError("stage_invalid", f"{type(exc).__name__}: {exc}") from exc
        if update is None:
            return None
        if update.outcome in (SceneCommandOutcome.APPLIED, SceneCommandOutcome.DUPLICATE):
            return update
        reason = update.reason.value if update.reason is not None else update.outcome.value
        raise StageError(reason, update.detail or f"the scene refused the command ({reason})")

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(f"{TRACE_PREFIX}.{kind}", message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal never undoes a stage operation
            pass


#: Refusals that mean "this id is no longer on the scene": archiving it again has nothing left to do.
_GONE_CODES = frozenset({"unknown_object", "object_archived"})
