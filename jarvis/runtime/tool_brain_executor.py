"""Exécuteur des actions d'interface du Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, S6).

Contrat : `docs/tool-brain-contracts.md` §14. C'est **le seul endroit du Tool Brain qui peut muter l'écran**, et il ne
le fait que par les propriétaires canoniques : `SceneService.apply_if` (scène) et `BoardService.switch(origin="brain")`
(Boards). Aucun second chemin de mutation : un outil sans adaptateur n'est pas exécutable (`unsupported_tool` à
l'admission, `no_adapter` ici en défense).

Séquence d'une exécution (sous un verrou : une mutation à la fois, ordre déterministe) :

1. **porte de mode** : hors mode `active`, rien ne s'exécute (`execution_disabled`, l'action reste en file) ;
2. **encore due ?** la parole/les faits sont relus (jamais l'instantané de planification) : une action liée à une
   parole interrompue ou expirée n'est jamais exécutée ;
3. `claim` : `pending -> executing`, **une seule fois** (rejeu, double déclenchement, course : sans effet) ;
4. **état faisant autorité relu maintenant** (`read_ui_state`), préconditions (époque de scène, Board actif) puis
   `validate_call` contre cet état frais, avec la référence observée au plan : tout refus est une **invalidation
   typée** (`stale_scene_epoch`, `stale_active_board`, `unknown_object`, `object_archived`, ...), jamais corrigée ;
5. exécution par l'adaptateur de l'outil, qui parle au propriétaire ; le refus du propriétaire (scène : `invalid` /
   `rejected_authority`, Board : introuvable/archivé) est lui aussi une invalidation ; une panne est `failed` ;
6. issue enregistrée dans la file (`done`, `scheduled`, `failed`, `invalidated`), journalisée, et `on_result` prévient
   le runtime : une invalidation le **réveille aussitôt** avec l'état frais pour replanifier.

Un `board_switch` effectif change l'autorité Board/Session : les autres actions en file (planifiées pour l'ancien
Board) sont annulées tout de suite (`authority_changed`), sans attendre le fait du bus.

Une annulation en vol pendant la mutation laisse l'action `failed` (`execution_interrupted`, issue inconnue) : la
mutation relative (ex. `scene_move`) n'est **jamais rejouée** — la décision suivante relit l'état.
"""

from __future__ import annotations

import asyncio
import traceback
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Protocol

from jarvis.domain.scene import SceneActor, SceneCommand, SceneCommandOutcome, SceneOp, SceneSnapshot
from jarvis.domain.scene_batch import SceneDelta
from jarvis.domain.scene_selection import SceneSelection
from jarvis.domain.workspace_board import BoardError, BoardErrorCode
from jarvis.ports.scene import SceneUnavailableError
from jarvis.runtime.crash_guard import tail
from jarvis.runtime.tool_brain_guardrails import DestructiveGuard, guard_class
from jarvis.runtime.tool_brain_choices import UiState, read_ui_state, validate_call
from jarvis.runtime.tool_brain_queue import (
    ACTION_EXPIRED, AUTHORITY_CHANGED, CANCELLED, DONE, EXPIRED, FAILED, GONE, INVALIDATED, SCHEDULED, WAIT,
    EXECUTING, ActionRecord, ActionView, ToolBrainActionQueue, TriggerContext,
)

# Statuts rendus par un adaptateur.
APPLIED, UNCHANGED, SCHEDULED_BY_OWNER, REFUSED = "applied", "unchanged", "scheduled", "refused"
# Issues d'`execute` (en plus des statuts terminaux de la file).
SKIPPED = "skipped"
EXECUTION_DISABLED, NOT_DUE, NOT_PENDING, NO_ADAPTER = "execution_disabled", "not_due", "not_pending", "no_adapter"
EXECUTION_INTERRUPTED, EXECUTION_FAILED, STATE_UNREADABLE = "execution_interrupted", "execution_failed", "state_unreadable"
STALE_SCENE_EPOCH, STALE_ACTIVE_BOARD = "stale_scene_epoch", "stale_active_board"
SCENE_UNAVAILABLE = "scene_unavailable"
#: Statut d'adaptateur : l'infrastructure du propriétaire est en panne (ce n'est pas « l'état a changé »).
UNAVAILABLE = "unavailable"

#: Refus de `BoardService.switch` qui disent « l'état a changé depuis le plan » (le reste est une panne).
_BOARD_REFUSALS = frozenset({BoardErrorCode.BOARD_NOT_FOUND, BoardErrorCode.BOARD_ARCHIVED, BoardErrorCode.INVALID_BOARD})


@dataclass(frozen=True)
class AdapterOutcome:
    """Ce qu'un propriétaire a répondu. `refused` : l'état ne permet plus l'action (code du propriétaire)."""

    status: str
    code: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecContext:
    """Ce que l'adaptateur peut utiliser de l'état observé au plan (jamais comme autorité)."""

    scene_id: str | None = None


class ExecutionAdapter(Protocol):
    """Un outil d'interface -> son propriétaire. Une seule entrée de mutation par outil."""

    async def execute(self, arguments: Mapping[str, Any], context: ExecContext) -> AdapterOutcome: ...


# ------------------------------------------------------------------ adaptateurs


def _selection(arguments: Mapping[str, Any]) -> SceneSelection:
    """`object_ids` XOR `select` -> `SceneSelection` de domaine (mêmes règles que `scene_move`, validées avant l'écriture)."""

    select, ids = arguments.get("select"), arguments.get("object_ids")
    if (select is None) == (ids is None):
        raise ValueError("give select (filters) or object_ids (explicit list), and only one of the two")
    if select is not None:
        from jarvis.runtime.display_mcp import selection_of

        if not isinstance(select, Mapping):
            raise TypeError("select must be an object of scene_query filters")
        return selection_of(select)
    if not isinstance(ids, list):
        raise TypeError("object_ids must be a list of identifiers")
    return SceneSelection(ids=tuple(dict.fromkeys(ids)))


class PlanUnchanged(Exception):
    """Le plan voit que la scène est déjà dans l'état demandé : rien à écrire, issue `unchanged`."""


class PlanRefused(Exception):
    """Le plan refuse avec un code qui lui est propre (ex. `selection_too_broad`) : `invalidated`, jamais corrigé."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


ScenePlanner = Callable[[SceneSnapshot], SceneCommand]


async def run_scene_plan(scene: Any, context: ExecContext, plan: ScenePlanner, *,
                         extra: Mapping[str, Any] | None = None) -> AdapterOutcome:
    """Lire et écrire **sous le même verrou** (`SceneService.apply_if`) : l'unique chemin de mutation de scène du Tool Brain.

    `plan(snapshot)` rend la `SceneCommand` du cerveau (ou lève) sur l'instantané lu *dans* le verrou : une autre scène
    que celle observée au plan n'écrit rien (`stale_scene_epoch`). Refus typés, jamais corrigés : arguments
    invalides (`invalid_arguments`), refus de domaine d'une surface (`SurfaceError.code`), scène absente, puis issue du
    réducteur (`invalid` / `rejected_authority` avec son motif). `extra` s'ajoute au détail d'une issue (ids rendus).
    """

    from jarvis.domain.browser_surface import SurfaceError

    refusal: list[AdapterOutcome] = []

    def locked_plan(snapshot: SceneSnapshot) -> SceneCommand | None:
        if context.scene_id is not None and snapshot.scene_id != context.scene_id:
            return None
        try:
            return plan(snapshot)
        except PlanUnchanged:
            refusal.append(AdapterOutcome(UNCHANGED, None, dict(extra or {})))
        except (SurfaceError, PlanRefused) as exc:
            refusal.append(AdapterOutcome(REFUSED, exc.code, {"detail": exc.detail[:200]}))
        except (KeyError, TypeError, ValueError) as exc:
            refusal.append(AdapterOutcome(REFUSED, "invalid_arguments", {"detail": f"{type(exc).__name__}: {exc}"[:200]}))
        return None

    try:
        update = await scene.apply_if(locked_plan)
    except SceneUnavailableError as exc:
        return AdapterOutcome(UNAVAILABLE, SCENE_UNAVAILABLE, {"detail": str(exc)[:200]})
    if update is None:
        return refusal[0] if refusal else AdapterOutcome(
            REFUSED, STALE_SCENE_EPOCH, {"detail": "the scene is not the one the plan observed"})
    detail: dict[str, Any] = {**dict(extra or {}), "revision": update.snapshot.revision, "outcome": update.outcome.value}
    if update.batch is not None:
        detail.update(matched=len(update.batch.matched_ids), changed=len(update.batch.changed_ids))
    if update.outcome is SceneCommandOutcome.APPLIED:
        return AdapterOutcome(APPLIED, None, detail)
    if update.outcome is SceneCommandOutcome.DUPLICATE:
        return AdapterOutcome(UNCHANGED, None, detail)
    return AdapterOutcome(REFUSED, update.reason.value if update.reason else update.outcome.value,
                          {**detail, "detail": update.detail})


class SceneMoveAdapter:
    """`scene_move` : `TRANSLATE_SELECTION` par `SceneService.apply_if` (lecture et écriture sous le même verrou).

    L'autorité est celle du Tool Brain (`SceneActor.BRAIN`), comme les outils d'affichage.
    """

    def __init__(self, scene: Any) -> None:
        self._scene = scene

    async def execute(self, arguments: Mapping[str, Any], context: ExecContext) -> AdapterOutcome:
        def plan(_snapshot: SceneSnapshot) -> SceneCommand:
            pin = arguments.get("pin")
            if pin is not None and pin is not True:
                raise ValueError("pin only accepts true")
            return SceneCommand(op=SceneOp.TRANSLATE_SELECTION, actor=SceneActor.BRAIN, selection=_selection(arguments),
                                delta=SceneDelta(dx=arguments["dx"], dy=arguments["dy"]), pin=True if pin else None)

        return await run_scene_plan(self._scene, context, plan)


BoardSwitcher = Callable[[str], Awaitable[Mapping[str, Any]]]


def core_board_switcher(boards: Any) -> BoardSwitcher:
    """Bascule par `BoardService.switch(origin="brain")` (transaction de Core, seule gardienne de ses invariants)."""

    async def switch(board_id: str) -> Mapping[str, Any]:
        result = await boards.switch(board_id, origin="brain")
        return {"status": APPLIED if result.changed else UNCHANGED, "board_id": board_id,
                "previous_board_id": result.previous_board_id}

    return switch


class BoardSwitchAdapter:
    """`board_switch` : `status` du propriétaire = `applied`, `unchanged` ou `scheduled` (différée jusqu'à la fin du tour).

    Un `scheduled` n'est ni un succès ni un échec : la demande est acceptée, **pas encore appliquée** ; l'action est
    terminée (`scheduled`, jamais rejouée) et le changement d'autorité qui suivra vide la file.
    """

    def __init__(self, switcher: BoardSwitcher) -> None:
        self._switch = switcher

    async def execute(self, arguments: Mapping[str, Any], context: ExecContext) -> AdapterOutcome:
        board_id = arguments.get("board_id")
        if not isinstance(board_id, str) or not board_id:
            return AdapterOutcome(REFUSED, "invalid_arguments", {"detail": "board_id must be a non-empty string"})
        try:
            answer = await self._switch(board_id)
        except BoardError as exc:
            if exc.code in _BOARD_REFUSALS:
                return AdapterOutcome(REFUSED, exc.code.value, {"detail": str(exc)[:200]})
            raise
        status = str(answer.get("status", ""))
        if status not in (APPLIED, UNCHANGED, SCHEDULED_BY_OWNER):
            raise RuntimeError(f"board switch answered an unknown status {status!r}")
        return AdapterOutcome(status, None, {key: answer[key] for key in ("board_id", "previous_board_id",
                                                                           "replaced_board_id") if key in answer})


def default_adapters(scene: Any, boards: Any, *, board_switcher: BoardSwitcher | None = None
                     ) -> dict[tuple[str, str], ExecutionAdapter]:
    """Outils exécutables : `scene_move` et `board_switch` (S6), puis les adaptateurs de S7 (`tool_brain_adapters`).

    Jamais un outil irréversible ou destructif (`scene_archive`) : c'est S8 qui décide s'il devient exécutable et sous
    quelle garde. Chaque adaptateur parle à un propriétaire canonique (scène : `SceneService.apply_if`).

    S8 : `scene_archive` y figure, mais l'exécuteur le refuse sans passer par `DestructiveGuard` (preuve utilisateur,
    bornes, protections, débit : `tool_brain_guardrails`). Sans garde configurée, l'exécuteur est fermé pour lui.
    """

    from jarvis.runtime.tool_brain_adapters import scene_and_surface_adapters

    return {("jarvis-display", "scene_move"): SceneMoveAdapter(scene),
            ("jarvis-workspace", "board_switch"): BoardSwitchAdapter(board_switcher or core_board_switcher(boards)),
            **scene_and_surface_adapters(scene)}


# ------------------------------------------------------------------ résultat


@dataclass(frozen=True)
class ExecutionResult:
    """`status` : `done | scheduled | failed | invalidated | cancelled | expired | skipped` ; `code` toujours dit."""

    action_id: str
    status: str
    code: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)
    view: ActionView | None = None

    @property
    def terminal(self) -> bool:
        return self.status != SKIPPED

    def to_dict(self) -> dict[str, Any]:
        return {"action_id": self.action_id, "status": self.status, "code": self.code, "detail": dict(self.detail)}


Trace = Callable[..., None]
ResultSink = Callable[[ExecutionResult, ActionRecord | None], None]


def _diagnostic(exc: BaseException) -> dict[str, Any]:
    """Ce que la file et le décideur voient d'une panne : classe et texte bornés (la pile va au journal, pas au cerveau)."""

    return {"error_class": type(exc).__name__, "detail": f"{type(exc).__name__}: {exc}"[:200]}


class UiActionExecutor:
    """Voir l'en-tête. `gate()` rend vrai seulement en mode `active` ; `context()` rend la parole/les intentions du moment."""

    def __init__(self, scene: Any, boards: Any, queue: ToolBrainActionQueue,
                 adapters: Mapping[tuple[str, str], ExecutionAdapter], *, gate: Callable[[], bool],
                 guard: DestructiveGuard | None = None) -> None:
        self._scene, self._boards, self._queue = scene, boards, queue
        self._adapters = dict(adapters)
        self._gate = gate
        # S8 : une action irréversible ne s'exécute que par cette garde ; sans garde fournie, elle est fermée (refuse tout).
        self._guard = guard or DestructiveGuard.closed()
        self._context: Callable[[], TriggerContext] | None = None
        self._on_result: ResultSink | None = None
        self._trace: Trace | None = None
        self._lock = asyncio.Lock()

    @property
    def queue(self) -> ToolBrainActionQueue:
        return self._queue

    def supports(self, server: str, tool: str) -> bool:
        return (server, tool) in self._adapters

    def attach(self, *, context: Callable[[], TriggerContext], on_result: ResultSink | None = None,
               trace: Trace | None = None) -> None:
        """Le runtime branche ce que l'exécuteur lit (parole/intentions du moment), la sortie des issues et le journal.

        Sans `attach`, `execute` refuse d'agir : une exécution sans contexte de parole ne saurait pas qu'elle est périmée.
        """

        self._context, self._on_result, self._trace = context, on_result, trace

    async def execute(self, action_id: str) -> ExecutionResult:
        """Exécute `action_id` si — et seulement si — elle est due, encore valide et jamais prise."""

        async with self._lock:
            return await self._execute_locked(action_id)

    async def _execute_locked(self, action_id: str) -> ExecutionResult:
        if not self._gate():
            return ExecutionResult(action_id, SKIPPED, EXECUTION_DISABLED)
        if self._context is None:
            raise RuntimeError("the executor is not attached to a runtime (no speech context)")
        verdict, code = self._queue.classify(action_id, self._context())
        if verdict == GONE and code != NOT_PENDING:
            return self._retire(action_id, code)
        if verdict == WAIT:
            return ExecutionResult(action_id, SKIPPED, NOT_DUE)
        if verdict == GONE:
            return ExecutionResult(action_id, SKIPPED, NOT_PENDING)
        view = self._queue.claim(action_id)
        if view is None:
            return ExecutionResult(action_id, SKIPPED, NOT_PENDING)
        record = view.record
        try:
            return await self._run_claimed(action_id, record)
        except asyncio.CancelledError:
            # Issue inconnue : jamais rejouée (une translation relative appliquée deux fois serait fausse).
            self._abort(action_id, record, EXECUTION_INTERRUPTED, None)
            raise
        except Exception as exc:  # noqa: BLE001 - capture: whatever broke after the claim, the action must still end
            return self._abort(action_id, record, EXECUTION_FAILED, exc)

    async def _run_claimed(self, action_id: str, record: ActionRecord) -> ExecutionResult:
        """Tout ce qui suit la prise : ne doit jamais laisser l'action `executing` (l'appelant règle toute exception)."""

        try:
            fresh = await read_ui_state(self._scene, self._boards)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: no authoritative state, no mutation; failed and said
            return self._finish(action_id, FAILED, STATE_UNREADABLE, _diagnostic(exc), exc)
        refusals = self._refusals(record, fresh)
        if refusals:
            return self._finish(action_id, INVALIDATED, refusals[0]["code"], {"refusals": refusals})
        # Dernier contrôle avant d'écrire : la parole a pu être coupée pendant la relecture de l'état.
        verdict, code = self._queue.recheck(action_id, self._context())
        if verdict == GONE:
            return self._finish(action_id, CANCELLED, code)
        adapter = self._adapters.get((record.server, record.tool))
        if adapter is None:
            return self._finish(action_id, FAILED, NO_ADAPTER, {"detail": f"{record.server}/{record.tool}"})
        if guard_class(record.server, record.tool, record.arguments) is not None:
            guarded = self._guard.check(record, fresh)
            if guarded:  # S8 : refus mécanique typé, final (pas de replan : le même plan serait refusé de nouveau)
                return self._finish(action_id, INVALIDATED, guarded[0].code,
                                    {"guard": True, "refusals": [item.to_dict() for item in guarded]})
            self._guard.reserve(record, len(self._guard.targets_of(record, fresh)))
        try:
            outcome = await adapter.execute(record.arguments,
                                            ExecContext(record.planned_from.scene_id if record.planned_from else None))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: the owner failed; typed, said, never retried silently
            return self._finish(action_id, FAILED, EXECUTION_FAILED, _diagnostic(exc), exc)
        if outcome.status == UNAVAILABLE:
            return self._finish(action_id, FAILED, outcome.code or EXECUTION_FAILED, dict(outcome.detail))
        if outcome.status == REFUSED:
            return self._finish(action_id, INVALIDATED, outcome.code or "refused",
                                {"refusals": [{"code": outcome.code, **dict(outcome.detail)}]})
        status = SCHEDULED if outcome.status == SCHEDULED_BY_OWNER else DONE
        result = self._finish(action_id, status, outcome.status, dict(outcome.detail))
        if record.tool == "board_switch" and outcome.status == APPLIED:
            self._queue.invalidate_all(AUTHORITY_CHANGED)  # les autres actions visaient l'ancien Board
        return result

    # ------------------------------------------------------------ pièces

    def _refusals(self, record: ActionRecord, fresh: UiState) -> list[dict[str, Any]]:
        """Préconditions de l'action puis `validate_call` contre l'état frais ; rend tous les refus (dicts)."""

        found: list[dict[str, Any]] = []
        now = fresh.ref()
        for item in record.preconditions:
            if item.kind == "scene_epoch" and f"{now.scene_id}@{now.epoch}" != item.value:
                found.append({"code": STALE_SCENE_EPOCH, "parameter": None, "value": item.value,
                              "detail": "the scene or its epoch changed since the plan"})
            if item.kind == "active_board" and now.active_board_id != item.value:
                found.append({"code": STALE_ACTIVE_BOARD, "parameter": None, "value": item.value,
                              "detail": f"the active board is now {now.active_board_id}"})
        verdict = validate_call(record.server, record.tool, record.arguments, fresh, observed=record.planned_from)
        known = {item["code"] for item in found}
        found.extend(item.to_dict() for item in verdict.refusals if item.code not in known)
        return found

    def _retire(self, action_id: str, code: str | None) -> ExecutionResult:
        self._queue.retire(action_id, code or ACTION_EXPIRED)
        view = self._queue.get(action_id)
        status = EXPIRED if code == ACTION_EXPIRED else CANCELLED
        result = ExecutionResult(action_id, status, code, view=view)
        self._emit_result(result, view.record if view else None)
        return result

    def _finish(self, action_id: str, status: str, code: str | None, detail: Mapping[str, Any] | None = None,
                error: BaseException | None = None) -> ExecutionResult:
        view = self._queue.settle(action_id, status, code, detail or {})
        result = ExecutionResult(action_id, status, code, detail or {}, view)
        self._emit_result(result, view.record, error)
        return result

    def _abort(self, action_id: str, record: ActionRecord, code: str, error: BaseException | None) -> ExecutionResult:
        """Clôt une action prise sur une exception inattendue : toujours terminale, dite, jamais rejouée.

        Si l'action est déjà terminale (la panne est venue après son règlement), on n'écrit rien de plus.
        """

        current = self._queue.get(action_id)
        if current is None or current.status != EXECUTING:
            return ExecutionResult(action_id, current.status if current else FAILED, current.code if current else code,
                                   (current.detail or {}) if current else {}, current)
        detail = _diagnostic(error) if error is not None else {}
        view = self._queue.settle(action_id, FAILED, code, detail)
        result = ExecutionResult(action_id, FAILED, code, detail, view)
        self._emit_result(result, record, error)
        return result

    def _emit_result(self, result: ExecutionResult, record: ActionRecord | None,
                     error: BaseException | None = None) -> None:
        if self._trace is not None:
            level = "info" if result.status in (DONE, SCHEDULED, CANCELLED, EXPIRED) else "warning"
            stack = ({"traceback": tail("".join(traceback.format_exception(type(error), error, error.__traceback__)))}
                     if error is not None else {})
            self._trace(f"tool_brain.action.{result.status}", f"Tool Brain : action {result.status}", level=level,
                        data={**stack, "action_id": result.action_id, "tool": record.tool if record else None,
                              "code": result.code, "decision_id": record.decision_id if record else None,
                              "trigger": record.trigger.kind if record else None})
        if self._on_result is not None:
            try:
                self._on_result(result, record)
            except Exception as exc:  # noqa: BLE001 - capture: a failing observer must not undo a finished mutation
                if self._trace is not None:
                    self._trace("tool_brain.action.sink_failed", "Tool Brain : observateur d'action en échec",
                                level="error", data={"error_class": type(exc).__name__, "detail": str(exc)[:200]})


__all__ = [
    "APPLIED", "AdapterOutcome", "BoardSwitchAdapter", "BoardSwitcher", "EXECUTION_DISABLED", "EXECUTION_FAILED",
    "EXECUTION_INTERRUPTED", "ExecContext", "ExecutionAdapter", "ExecutionResult", "NOT_DUE", "NO_ADAPTER",
    "PlanRefused", "PlanUnchanged", "REFUSED", "SCENE_UNAVAILABLE", "SKIPPED", "UNAVAILABLE", "STALE_ACTIVE_BOARD", "STALE_SCENE_EPOCH", "STATE_UNREADABLE",
    "ScenePlanner", "SceneMoveAdapter", "UNCHANGED", "UiActionExecutor", "core_board_switcher", "default_adapters", "run_scene_plan",
]
