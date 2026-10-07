"""Qui possède l'écran : la porte d'autorité du Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, Slice 8).

Contrat : `docs/tool-brain-contracts.md` §16. **Un seul décideur d'écran à la fois**, décidé en un seul endroit,
imposé mécaniquement (jamais par le seul texte de la consigne).

Matrice de propriété (réglage unique `JARVIS_TOOL_BRAIN`, lu par Core au démarrage) :

| `JARVIS_TOOL_BRAIN` | santé du Tool Brain                              | propriétaire    | raison                 |
| ------------------- | ------------------------------------------------ | --------------- | ---------------------- |
| `off` (défaut)      | -                                                | `jarvis_direct` | `mode_off`             |
| `shadow`            | -                                                | `jarvis_direct` | `mode_shadow`          |
| `active`            | pas de décision réussie depuis le démarrage      | `jarvis_direct` | `not_proven`           |
| `active`            | boucle arrêtée                                   | `jarvis_direct` | `runtime_down`         |
| `active`            | dernier échec : décideur indisponible            | `jarvis_direct` | `decider_unavailable`  |
| `active`            | >= 2 échecs consécutifs                          | `jarvis_direct` | `decider_failing`      |
| `active`            | revenu en santé depuis moins de `HOLD_DOWN_S`    | `jarvis_direct` | `hold_down`            |
| `active`            | publication impossible (disque)                  | `jarvis_direct` | `publish_failed`       |
| `active`            | sain et prouvé                                   | `tool_brain`    | `active_healthy`       |

Côté lecteurs (serveurs MCP de Jarvis, Control Center) : publication absente, périmée, illisible ou hors contrat
=> `jarvis_direct` (`no_publication`, `stale_publication`, `unreadable_publication`) : **l'écran ne gèle jamais**.

Mécanique : l'arbitre (`OwnershipArbiter`, dans Core, à côté du runtime) calcule la propriété depuis l'état du
runtime et la **publie** (`runtime/tool-brain-ownership.json`, battement toutes les `HEARTBEAT_S`, valide `TTL_S`).
Les deux côtés lisent la même vérité :

- l'exécuteur du Tool Brain n'agit que si l'arbitre répond `tool_brain` (`executor_allowed`) ;
- les outils d'écran de Jarvis (`DelegationGate`) sont refusés (`ui_delegated`) tant que la publication dit
  `tool_brain` : deux acteurs ne mutent jamais en même temps. L'ordre des transitions garantit l'exclusion : vers
  `tool_brain`, on publie **avant** d'autoriser l'exécuteur ; vers `jarvis_direct`, on retire l'exécuteur **puis** on publie.

Un repli est observable (`tool_brain.ownership.changed`, niveau warning) et vide la file d'actions : rien de l'ancien
propriétaire ne s'exécute au retour.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

OWNERSHIP_DIRECT = "jarvis_direct"
OWNERSHIP_TOOL_BRAIN = "tool_brain"
OWNERSHIPS = (OWNERSHIP_DIRECT, OWNERSHIP_TOOL_BRAIN)

OWNERSHIP_FILE = "tool-brain-ownership.json"
SCHEMA = "tool_brain.ownership/1"
HEARTBEAT_S = 5.0
TTL_S = 20.0
#: Après un repli, le Tool Brain ne reprend la main qu'au bout de ce délai de santé continue (pas de va-et-vient).
HOLD_DOWN_S = 60.0
#: Échecs consécutifs du décideur au-delà desquels Jarvis reprend l'écran (une indisponibilité suffit seule).
FAILURE_LIMIT = 2

# Raisons.
MODE_OFF, MODE_SHADOW, ACTIVE_HEALTHY = "mode_off", "mode_shadow", "active_healthy"
NOT_PROVEN, RUNTIME_DOWN, DECIDER_UNAVAILABLE = "not_proven", "runtime_down", "decider_unavailable"
DECIDER_FAILING, HOLD_DOWN, PUBLISH_FAILED, SHUTDOWN = "decider_failing", "hold_down", "publish_failed", "shutdown"
NO_PUBLICATION, STALE_PUBLICATION, UNREADABLE_PUBLICATION = "no_publication", "stale_publication", "unreadable_publication"
#: Raisons de repli : le mode demande `tool_brain` mais quelque chose empêche.
FALLBACK_REASONS = frozenset({NOT_PROVEN, RUNTIME_DOWN, DECIDER_UNAVAILABLE, DECIDER_FAILING, HOLD_DOWN, PUBLISH_FAILED,
                              STALE_PUBLICATION, UNREADABLE_PUBLICATION})

#: Refus rendu à Jarvis par un outil d'écran délégué.
UI_DELEGATED = "ui_delegated"


@dataclass(frozen=True, slots=True)
class OwnershipView:
    """Qui possède l'écran *maintenant*, pourquoi, et depuis quand (horloge murale)."""

    ownership: str
    mode: str
    reason: str
    since: float = 0.0

    def __post_init__(self) -> None:
        if self.ownership not in OWNERSHIPS:
            raise ValueError(f"ownership must be one of {OWNERSHIPS}")

    @property
    def delegated(self) -> bool:
        return self.ownership == OWNERSHIP_TOOL_BRAIN

    @property
    def fallback(self) -> bool:
        """Le mode `active` voulait déléguer mais Jarvis garde l'écran (à dire, jamais silencieux)."""

        return self.reason in FALLBACK_REASONS

    def to_payload(self, beat: float) -> dict[str, Any]:
        return {"schema": SCHEMA, "ownership": self.ownership, "mode": self.mode, "reason": self.reason,
                "since": self.since, "beat": beat}


JARVIS_DEFAULT = OwnershipView(OWNERSHIP_DIRECT, "off", NO_PUBLICATION)


@dataclass(frozen=True, slots=True)
class Health:
    """Ce que l'arbitre sait du runtime (copie de `ToolBrainRuntime.status()`, jamais le runtime lui-même)."""

    running: bool = False
    completed: int = 0
    consecutive_failures: int = 0
    last_outcome: str | None = None

    @classmethod
    def of(cls, status: Mapping[str, Any]) -> "Health":
        counters = status.get("counters") or {}
        return cls(bool(status.get("running")), int(counters.get("completed", 0) or 0),
                   int(status.get("consecutive_failures", 0) or 0), status.get("last_outcome"))


def unhealthy_reason(health: Health) -> str | None:
    """Pourquoi le Tool Brain ne peut pas posséder l'écran maintenant, ou `None` (fonction pure)."""

    if not health.running:
        return RUNTIME_DOWN
    if health.last_outcome == "unavailable":
        return DECIDER_UNAVAILABLE
    if health.consecutive_failures >= FAILURE_LIMIT:
        return DECIDER_FAILING
    if health.completed < 1:
        return NOT_PROVEN
    return None


def decide(mode: str, health: Health) -> tuple[str, str]:
    """`(propriétaire, raison)` : la matrice du module, sans état ni horloge (le délai de retenue est à l'arbitre)."""

    if mode == "active":
        reason = unhealthy_reason(health)
        return (OWNERSHIP_DIRECT, reason) if reason else (OWNERSHIP_TOOL_BRAIN, ACTIVE_HEALTHY)
    return OWNERSHIP_DIRECT, MODE_SHADOW if mode == "shadow" else MODE_OFF


# ------------------------------------------------------------------ publication


def ownership_path(runtime_root: Path | str) -> Path:
    return Path(runtime_root) / OWNERSHIP_FILE


def write_publication(path: Path, view: OwnershipView, *, beat: float) -> None:
    """Écriture atomique ; `OSError` à l'appelant (l'arbitre en fait un repli, jamais un silence)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(view.to_payload(beat), ensure_ascii=False) + "\n"
    handle, raw_tmp = tempfile.mkstemp(prefix=OWNERSHIP_FILE + ".", suffix=".tmp", dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        from jarvis.adapters.file_replace import replace_with_retry

        replace_with_retry(tmp, path)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass  # intentional: the original failure is what the caller must see; a stray .tmp is harmless
        raise


def read_ownership(runtime_root: Path | str | None, *, wall: Callable[[], float] = time.time,
                   ttl_s: float = TTL_S) -> OwnershipView:
    """Lecture **fail-safe** de la publication : toute anomalie rend `jarvis_direct` avec sa raison. Ne lève jamais."""

    if runtime_root is None:
        return JARVIS_DEFAULT
    path = ownership_path(runtime_root)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return JARVIS_DEFAULT  # argued: no arbiter ever ran (off/shadow install): the normal default, not a fault
    except OSError:
        return OwnershipView(OWNERSHIP_DIRECT, "unknown", UNREADABLE_PUBLICATION)
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("schema") != SCHEMA:
            raise ValueError("schema")
        view = OwnershipView(str(data["ownership"]), str(data["mode"]), str(data["reason"]), float(data["since"]))
        beat = float(data["beat"])
    except (ValueError, KeyError, TypeError):
        return OwnershipView(OWNERSHIP_DIRECT, "unknown", UNREADABLE_PUBLICATION)
    if wall() - beat > ttl_s:
        return OwnershipView(OWNERSHIP_DIRECT, view.mode, STALE_PUBLICATION, view.since)
    return view


# ------------------------------------------------------------------ arbitre (Core)

Trace = Callable[..., None]


class OwnershipArbiter:
    """Calcule, publie et impose la propriété ; vit dans Core à côté du runtime.

    `status` rend `ToolBrainRuntime.status()`. `on_change(old, new)` prévient (le runtime vide sa file). Toute
    lecture de la propriété passe par `evaluate()` : l'exécuteur ne peut pas agir sur une valeur périmée.
    """

    def __init__(self, status: Callable[[], Mapping[str, Any]], mode: str, runtime_root: Path | str | None, *,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
                 trace: Trace | None = None, on_change: Callable[[OwnershipView, OwnershipView], None] | None = None,
                 hold_down_s: float = HOLD_DOWN_S) -> None:
        self._status, self._mode = status, mode
        self._path = ownership_path(runtime_root) if runtime_root is not None else None
        self._clock, self._wall, self._trace = clock, wall, trace
        self._on_change = on_change
        self._hold_down_s = hold_down_s
        self._hold_until = 0.0
        self._view = OwnershipView(OWNERSHIP_DIRECT, mode, decide(mode, Health())[1], wall())
        self._publish_failed = False
        self._task: asyncio.Task[None] | None = None

    @property
    def view(self) -> OwnershipView:
        return self._view

    def evaluate(self) -> OwnershipView:
        """Recalcule ; sur changement : retire l'exécuteur/publie dans l'ordre sûr, trace, prévient."""

        try:
            health = Health.of(self._status())
        except Exception as exc:  # noqa: BLE001 - capture: unreadable runtime state is a fallback, never a guess
            self._say("tool_brain.ownership.status_failed", "Tool Brain : état du runtime illisible, Jarvis garde l'écran",
                      level="error", data={"error_class": type(exc).__name__, "detail": str(exc)[:200]})
            health = Health()
        owner, reason = decide(self._mode, health)
        now = self._clock()
        if owner == OWNERSHIP_TOOL_BRAIN:
            if now < self._hold_until:
                owner, reason = OWNERSHIP_DIRECT, HOLD_DOWN
            elif self._publish_failed:
                owner, reason = OWNERSHIP_DIRECT, PUBLISH_FAILED
        elif self._view.delegated:  # tombe de `tool_brain` : retenue avant de reprendre
            self._hold_until = now + self._hold_down_s
        old = self._view
        if (owner, reason) == (old.ownership, old.reason):
            return old
        new = OwnershipView(owner, self._mode, reason, self._wall())
        # Ordre sûr : vers `jarvis_direct`, l'exécuteur est déjà retiré (la vue interne change d'abord), puis on publie ;
        # vers `tool_brain`, la publication doit réussir avant que la vue interne n'autorise l'exécuteur.
        if new.delegated:
            if not self._publish(new):
                new = OwnershipView(OWNERSHIP_DIRECT, self._mode, PUBLISH_FAILED, self._wall())
                if (new.ownership, new.reason) == (old.ownership, old.reason):
                    return old
                self._view = new
                self._publish(new)
            else:
                self._view = new
        else:
            self._view = new
            self._publish(new)
        self._say("tool_brain.ownership.changed",
                  f"Tool Brain : propriété de l'écran {old.ownership} -> {new.ownership} ({new.reason})",
                  level="warning" if new.fallback else "info",
                  data={"from": old.ownership, "to": new.ownership, "mode": self._mode, "reason": new.reason,
                        "fallback": new.fallback})
        if self._on_change is not None:
            try:
                self._on_change(old, new)
            except Exception as exc:  # noqa: BLE001 - capture: the observer must not undo an ownership change
                self._say("tool_brain.ownership.observer_failed", "Tool Brain : observateur de propriété en échec",
                          level="error", data={"error_class": type(exc).__name__, "detail": str(exc)[:200]})
        return new

    def executor_allowed(self) -> bool:
        """La porte de l'exécuteur : vrai seulement si le Tool Brain possède l'écran à cet instant."""

        return self.evaluate().delegated

    def owns(self) -> bool:
        return self.executor_allowed()

    def beat(self) -> None:
        """Rafraîchit la publication (battement) après réévaluation."""

        view = self.evaluate()
        self._publish(view)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self.beat()
            self._task = asyncio.create_task(self._loop(), name="jarvis-tool-brain-ownership")

    async def close(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        # Un Core qui s'arrête ne laisse pas un « tool_brain » publié : les lecteurs voient Jarvis aussitôt.
        self._view = OwnershipView(OWNERSHIP_DIRECT, self._mode, SHUTDOWN, self._wall())
        self._publish(self._view)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_S)
            try:
                self.beat()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - capture: the heartbeat must survive; a stale file already means Jarvis
                self._say("tool_brain.ownership.beat_failed", "Tool Brain : battement de propriété en échec",
                          level="error", data={"error_class": type(exc).__name__, "detail": str(exc)[:200]})

    def _publish(self, view: OwnershipView) -> bool:
        if self._path is None:
            return not view.delegated  # no place to publish: readers could not see a delegation, so none is allowed
        try:
            write_publication(self._path, view, beat=self._wall())
        except OSError as exc:
            self._publish_failed = True
            self._say("tool_brain.ownership.publish_failed", "Tool Brain : propriété non publiable, Jarvis garde l'écran",
                      level="error", data={"error_class": type(exc).__name__, "detail": str(exc)[:200]})
            return False
        self._publish_failed = False
        return True

    def _say(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None) -> None:
        if self._trace is not None:
            self._trace(kind, message, level=level, data=data)


# ------------------------------------------------------------------ côté Jarvis : outils délégués


def jarvis_delegated_tools() -> frozenset[tuple[str, str]]:
    """Outils d'écran que Jarvis perd quand le Tool Brain possède l'écran : **ceux que l'exécuteur sait faire**.

    Dérivé, jamais recopié : `ToolMeta` (serveur déclaré à Jarvis, surface d'écran, effet autre que lecture) croisé avec
    les adaptateurs de l'exécuteur. Produire du contenu (`scene_create_object`, `scene_add_artifact`) reste à Jarvis.
    """

    from jarvis.runtime.mcp_tool_meta import SERVERS
    from jarvis.runtime.tool_brain_executor import default_adapters

    executable = set(default_adapters(None, None))
    return frozenset((server.server, name) for server in SERVERS if server.registration == "jarvis"
                     for name, meta in server.tools.items()
                     if meta.ui_surface is not None and meta.side_effect != "read" and (server.server, name) in executable)


def delegation_message(tool: str, view: OwnershipView) -> str:
    return (f"{tool} refusé : le Tool Brain possède l'écran (mode délégué, {view.reason}). Rien n'a été modifié. "
            "Dis ce que l'utilisateur doit voir avec ui_intent_publish ; le Tool Brain agit. Si le Tool Brain tombe, "
            "tes outils d'écran te reviennent d'eux-mêmes (la consigne du tour suivant le dit).")


class DelegationGate:
    """Porte des outils d'écran de Jarvis : refuse un outil délégué tant que la publication dit `tool_brain`."""

    def __init__(self, runtime_root: Path | str | None, *, server: str,
                 emit: Callable[..., None] | None = None, wall: Callable[[], float] = time.time) -> None:
        self._root, self._server, self._emit, self._wall = runtime_root, server, emit, wall
        self._tools = {tool for srv, tool in jarvis_delegated_tools() if srv == server}
        self._last: tuple[str, str] | None = None

    def view(self) -> OwnershipView:
        return read_ownership(self._root, wall=self._wall)

    def refusal(self, tool: str) -> str | None:
        """Le message de refus, ou `None` quand Jarvis garde la main. Journalise refus et replis (changement seulement)."""

        view = self.view()
        key = (view.ownership, view.reason)
        if view.fallback and key != self._last:
            self._say("ui_ownership.fallback", f"Tool Brain indisponible : {tool} reste à Jarvis ({view.reason})",
                      level="warning", data={"tool": tool, "reason": view.reason, "mode": view.mode})
        self._last = key
        if tool not in self._tools or not view.delegated:
            return None
        self._say("ui_ownership.refused", f"{tool} refusé : le Tool Brain possède l'écran", level="info",
                  data={"tool": tool, "server": self._server, "code": UI_DELEGATED, "reason": view.reason})
        return delegation_message(tool, view)

    def _say(self, kind: str, message: str, *, level: str, data: Mapping[str, Any]) -> None:
        if self._emit is not None:
            try:
                self._emit(kind, message, level=level, data=dict(data))
            except OSError:
                pass  # intentional: a full disk must not turn a refusal into a different failure


__all__ = [
    "ACTIVE_HEALTHY", "DelegationGate", "FALLBACK_REASONS", "FAILURE_LIMIT", "HEARTBEAT_S", "HOLD_DOWN_S", "Health",
    "JARVIS_DEFAULT", "OWNERSHIPS", "OWNERSHIP_DIRECT", "OWNERSHIP_FILE", "OWNERSHIP_TOOL_BRAIN", "OwnershipArbiter",
    "OwnershipView", "TTL_S", "UI_DELEGATED", "decide", "delegation_message", "jarvis_delegated_tools",
    "ownership_path", "read_ownership", "unhealthy_reason", "write_publication",
]
