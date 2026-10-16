"""Garde-fous mécaniques des actions d'écran irréversibles du Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, S8).

Contrat : `docs/tool-brain-contracts.md` §16.3. Les actions réversibles sont autonomes ; **irréversibles ou
destructives**, elles passent ici, dans l'exécuteur, avant l'adaptateur. Rien de ce module n'est une consigne de prompt.

Sont gardées : tout outil que `ToolMeta` marque `irreversible` / `destructive` (aujourd'hui `scene_archive`) et le
masquage en masse confirmé (`scene_update_many` + `visibility=hidden` + `confirm=true`, qui contourne la garde
« moitié de l'écran »). Règles (un code typé chacune, jamais corrigées, jamais rejouées) :

| Code                          | Règle                                                                                        |
| ----------------------------- | -------------------------------------------------------------------------------------------- |
| `guard_unconfigured`          | exécuteur sans garde configurée : tout est refusé (fermé par défaut)                         |
| `no_turn_context`             | l'action n'est rattachée à aucun tour (réveil de sûreté, état) : jamais                      |
| `not_user_turn`               | le tour n'est pas un tour **utilisateur** (`user.transcript.accepted`) : jamais d'initiative |
| `turn_too_old`                | le tour utilisateur date de plus de `evidence_max_age_s`                                      |
| `scene_unavailable`           | pas d'instantané de scène : protections (épinglé, runtime) invérifiables, refusé             |
| `targets_not_explicit`        | archive : `object_ids` explicites seulement (jamais un filtre `select`)                      |
| `too_many_targets`            | archive : au plus `max_targets` objets par action                                            |
| `protected_pinned`            | archive : objet épinglé par l'utilisateur                                                    |
| `protected_runtime_owned`     | archive : objet du runtime (étoile agent/job, signal) : il lui appartient                    |
| `no_user_intent_evidence`     | archive : aucune intention `dismiss` de **ce** tour ne vise **chaque** objet ; masquage :    |
|                               | aucune intention `dismiss` de ce tour (sans exiger une ref par objet)                        |
| `evidence_unreadable`         | le registre d'intentions est illisible : fermé                                               |
| `rate_limited_turn`           | plus de `max_actions_per_turn` actions gardées par tour (budget propre au masquage)          |
| `rate_limited_window`         | plus de `max_targets_per_window` objets gardés par `window_s` (budget propre au masquage)    |
| `too_many_targets`            | masquage : plus de `max_bulk_targets` objets dans une action                                 |

Deux niveaux : l'**archivage** (définitif) garde la règle stricte (ids, preuve par objet, 3 objets, protections) ; le
**masquage en masse** (réversible) est léger : tour utilisateur récent, une intention `dismiss` de ce tour, budget propre
et large. Les objets épinglés par l'utilisateur sont écartés du masquage (jamais touchés), ceux du runtime (étoiles de
tâches) peuvent être masqués : c'est réversible.

Pas d'annulation : un objet archivé a un id enterré (jamais réutilisé), le défaire n'est pas bon marché. Le garde-fou
est donc *avant* (preuve, bornes, protections) et l'issue rend un **reçu** (id, nature, titre) pour la reconstitution.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from jarvis.domain.scene import SceneActor
from jarvis.domain.scene_selection import resolve_selection
from jarvis.runtime.mcp_tool_meta import tool_meta
from jarvis.runtime.tool_brain_choices import UiState
from jarvis.runtime.tool_brain_queue import ActionRecord

GUARD_UNCONFIGURED = "guard_unconfigured"
NO_TURN_CONTEXT, NOT_USER_TURN, TURN_TOO_OLD = "no_turn_context", "not_user_turn", "turn_too_old"
TARGETS_NOT_EXPLICIT, TOO_MANY_TARGETS = "targets_not_explicit", "too_many_targets"
PROTECTED_PINNED, PROTECTED_RUNTIME_OWNED = "protected_pinned", "protected_runtime_owned"
NO_USER_INTENT_EVIDENCE, EVIDENCE_UNREADABLE = "no_user_intent_evidence", "evidence_unreadable"
RATE_LIMITED_TURN, RATE_LIMITED_WINDOW = "rate_limited_turn", "rate_limited_window"
SCENE_UNAVAILABLE = "scene_unavailable"
GUARD_CODES = frozenset({SCENE_UNAVAILABLE,
    GUARD_UNCONFIGURED, NO_TURN_CONTEXT, NOT_USER_TURN, TURN_TOO_OLD, TARGETS_NOT_EXPLICIT, TOO_MANY_TARGETS,
    PROTECTED_PINNED, PROTECTED_RUNTIME_OWNED, NO_USER_INTENT_EVIDENCE, EVIDENCE_UNREADABLE, RATE_LIMITED_TURN,
    RATE_LIMITED_WINDOW,
})

IRREVERSIBLE, BULK_HIDE = "irreversible", "bulk_hide"
#: Nature de l'intention qui sert de preuve : l'utilisateur veut que ces objets ne soient plus là.
EVIDENCE_KIND = "dismiss"


@dataclass(frozen=True, slots=True)
class GuardrailConfig:
    max_targets: int = 3
    max_actions_per_turn: int = 1
    window_s: float = 600.0
    max_targets_per_window: int = 5
    evidence_max_age_s: float = 120.0
    #: Masquage en masse (réversible) : budgets propres, larges (« masque toutes les tâches terminées » ~40 objets).
    max_bulk_targets: int = 60
    max_bulk_actions_per_turn: int = 3
    max_bulk_targets_per_window: int = 120


@dataclass(frozen=True, slots=True)
class GuardRefusal:
    code: str
    detail: str
    ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail, **({"ids": list(self.ids[:5])} if self.ids else {})}


def guard_class(server: str, tool: str, arguments: Mapping[str, Any]) -> str | None:
    """`irreversible`, `bulk_hide` ou `None` (action libre). Lu dans `ToolMeta`, jamais dans une liste recopiée."""

    try:
        meta = tool_meta(server, tool)
    except KeyError:
        return None
    if meta.reversibility == "irreversible" or meta.side_effect == "destructive":
        return IRREVERSIBLE
    if (tool == "scene_update_many" and arguments.get("confirm") is True
            and arguments.get("visibility") == "hidden"):
        return BULK_HIDE
    return None


def is_guarded(server: str, tool: str) -> bool:
    """Vrai pour un outil qui est *toujours* gardé (irréversible) ; sert au contrôle de construction de l'exécuteur."""

    return guard_class(server, tool, {}) == IRREVERSIBLE


class UserTurnLedger:
    """Tours **utilisateur** vus (`user.transcript.accepted`) : seul fait qui prouve qu'une personne a parlé.

    Un tour du système (réveil d'attention, notification) n'y entre jamais : Core ne le produit pas. Borné.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, capacity: int = 64) -> None:
        self._clock, self._capacity = clock, capacity
        self._seen: OrderedDict[tuple[str, str], float] = OrderedDict()

    def note(self, conversation_id: str | None, correlation_id: str | None) -> None:
        if not conversation_id or not correlation_id:
            return
        key = (conversation_id, correlation_id)
        if key in self._seen:
            return  # first-seen time governs the evidence window: a repeated event must not refresh a turn's age
        self._seen[key] = self._clock()
        while len(self._seen) > self._capacity:
            self._seen.popitem(last=False)

    def age_s(self, conversation_id: str | None, correlation_id: str | None) -> float | None:
        """Âge du tour utilisateur en secondes, ou `None` si ce n'est pas un tour utilisateur connu."""

        at = self._seen.get((conversation_id or "", correlation_id or ""))
        return None if at is None else max(0.0, self._clock() - at)


IntentsSource = Callable[[str, str | None], Sequence[Mapping[str, Any]]]


class DestructiveGuard:
    """Voir l'en-tête. `check` est pur côté état (horloge injectée) ; `reserve` consomme les budgets, une fois."""

    def __init__(self, *, intents: IntentsSource | None, user_turns: UserTurnLedger | None,
                 config: GuardrailConfig | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self._intents, self._turns, self._config, self._clock = intents, user_turns, config or GuardrailConfig(), clock
        self._per_turn: dict[tuple[str, str], int] = {}
        self._window: deque[tuple[float, int]] = deque()
        self._bulk_per_turn: dict[tuple[str, str], int] = {}
        self._bulk_window: deque[tuple[float, int]] = deque()

    @classmethod
    def closed(cls) -> "DestructiveGuard":
        """Garde sans source de preuve : refuse toute action gardée (`guard_unconfigured`). Défaut d'un exécuteur sans garde."""

        return cls(intents=None, user_turns=None)

    @property
    def configured(self) -> bool:
        return self._intents is not None and self._turns is not None

    def check(self, record: ActionRecord, state: UiState) -> tuple[GuardRefusal, ...]:
        """Refus (vide : autorisé). Ne consomme rien : `reserve` le fait après un contrôle réussi."""

        kind = guard_class(record.server, record.tool, record.arguments)
        if kind is None:
            return ()
        if not self.configured:
            return (GuardRefusal(GUARD_UNCONFIGURED, "no evidence source is wired: guarded actions are closed"),)
        conversation, correlation = record.conversation_id, record.correlation_id
        if not conversation or not correlation:
            return (GuardRefusal(NO_TURN_CONTEXT, "the action is not tied to any conversation turn"),)
        assert self._turns is not None and self._intents is not None
        age = self._turns.age_s(conversation, correlation)
        if age is None:
            return (GuardRefusal(NOT_USER_TURN, "the turn is not a user turn (no user.transcript.accepted)"),)
        if age > self._config.evidence_max_age_s:
            return (GuardRefusal(TURN_TOO_OLD, f"the user turn is {int(age)}s old (max {int(self._config.evidence_max_age_s)}s)"),)
        refusals: list[GuardRefusal] = []
        targets = self._targets(record, state, kind, refusals)
        if refusals:
            return tuple(refusals)
        refusals.extend(self._evidence(conversation, correlation, targets, bulk=kind == BULK_HIDE))
        refusals.extend(self._rates(correlation, conversation, len(targets), bulk=kind == BULK_HIDE))
        return tuple(refusals)

    def reserve(self, record: ActionRecord, count: int) -> None:
        """Consomme les budgets du tour et de la fenêtre (gardé aussi en cas d'échec : fermé, pas de martèlement)."""

        bulk = guard_class(record.server, record.tool, record.arguments) == BULK_HIDE
        per_turn, window = (self._bulk_per_turn, self._bulk_window) if bulk else (self._per_turn, self._window)
        key = (record.conversation_id or "", record.correlation_id or "")
        per_turn[key] = per_turn.get(key, 0) + 1
        if len(per_turn) > 256:
            per_turn.pop(next(iter(per_turn)))
        window.append((self._clock(), count))

    def targets_of(self, record: ActionRecord, state: UiState) -> tuple[str, ...]:
        """Les objets visés (pour le décompte de `reserve`), sans refus."""

        kind = guard_class(record.server, record.tool, record.arguments)
        return self._targets(record, state, kind or IRREVERSIBLE, []) if kind else ()

    # ------------------------------------------------------------ règles

    def _targets(self, record: ActionRecord, state: UiState, kind: str, refusals: list[GuardRefusal]) -> tuple[str, ...]:
        arguments, snapshot = record.arguments, state.scene
        if snapshot is None:  # the pinned / runtime-owned checks cannot run: closed, never skipped
            refusals.append(GuardRefusal(SCENE_UNAVAILABLE, "no scene snapshot: protections cannot be verified"))
            return ()
        if kind == IRREVERSIBLE:
            ids = arguments.get("object_ids")
            if arguments.get("select") is not None or not isinstance(ids, list) or not ids \
                    or not all(isinstance(item, str) for item in ids):
                refusals.append(GuardRefusal(TARGETS_NOT_EXPLICIT, "a guarded removal names its objects: object_ids only"))
                return ()
            ids = list(dict.fromkeys(ids))
            if len(ids) > self._config.max_targets:
                refusals.append(GuardRefusal(TOO_MANY_TARGETS, f"at most {self._config.max_targets} objects per action"))
            pinned = tuple(i for i in ids if (o := snapshot.get_object(i)) is not None and o.constraints.pinned_by_user)
            owned = tuple(i for i in ids if (o := snapshot.get_object(i)) is not None and o.origin is SceneActor.RUNTIME)
            if pinned:
                refusals.append(GuardRefusal(PROTECTED_PINNED, "the user pinned these objects", pinned))
            if owned:
                refusals.append(GuardRefusal(PROTECTED_RUNTIME_OWNED, "the runtime owns these objects", owned))
            return tuple(ids)
        # bulk_hide : la sélection est résolue UNE fois sur l'état frais (filtres permis) ; la preuve doit couvrir chaque
        # membre et l'exécuteur n'agit que sur cet ensemble (`object_ids`), jamais sur une seconde résolution du filtre.
        from jarvis.runtime.tool_brain_executor import _selection

        try:
            ids = tuple(resolve_selection(snapshot, _selection(arguments)).eligible_ids)
        except (KeyError, TypeError, ValueError):
            refusals.append(GuardRefusal(TARGETS_NOT_EXPLICIT, "the selection cannot be resolved"))
            return ()
        # Réversible : on écarte les épinglés (le choix explicite de l'utilisateur) au lieu de tout refuser.
        ids = tuple(i for i in ids if (o := snapshot.get_object(i)) is None or not o.constraints.pinned_by_user)
        if len(ids) > self._config.max_bulk_targets:
            refusals.append(GuardRefusal(TOO_MANY_TARGETS, f"at most {self._config.max_bulk_targets} objects per hide"))
        return ids

    def _evidence(self, conversation: str, correlation: str, targets: tuple[str, ...], *,
                  bulk: bool = False) -> list[GuardRefusal]:
        assert self._intents is not None
        try:
            rows = list(self._intents(conversation, correlation))
        except Exception as exc:  # noqa: BLE001 - capture: no readable evidence is no evidence; closed and said
            return [GuardRefusal(EVIDENCE_UNREADABLE, f"{type(exc).__name__}: {exc}"[:160])]
        if bulk:  # réversible : une intention dismiss de ce tour suffit, la portée est jugée par le décideur
            if not targets:
                return [GuardRefusal(NO_USER_INTENT_EVIDENCE, "the hide selects no object (nothing eligible in the fresh scene)")]
            if any(row.get("kind") == EVIDENCE_KIND and row.get("correlation_id") in (None, correlation) for row in rows):
                return []
            return [GuardRefusal(NO_USER_INTENT_EVIDENCE, f"no {EVIDENCE_KIND} intent published this user turn: publish "
                                 f"ui_intent_publish(kind={EVIDENCE_KIND}, refs or a clear subject naming the scope) first")]
        covered: set[str] = set()
        for row in rows:
            if row.get("kind") != EVIDENCE_KIND or row.get("correlation_id") not in (None, correlation):
                continue
            for ref in row.get("refs") or ():
                if isinstance(ref, Mapping) and ref.get("kind") == "object" and isinstance(ref.get("id"), str):
                    covered.add(ref["id"])
        missing = tuple(item for item in targets if item not in covered)
        if missing or not targets:
            return [GuardRefusal(NO_USER_INTENT_EVIDENCE, f"{len(missing) or 'no'} target(s) lack a {EVIDENCE_KIND} intent "
                                 "published this user turn", missing)]
        return []

    def _rates(self, correlation: str, conversation: str, count: int, *, bulk: bool = False) -> list[GuardRefusal]:
        config, now = self._config, self._clock()
        per_turn, window = (self._bulk_per_turn, self._bulk_window) if bulk else (self._per_turn, self._window)
        max_actions = config.max_bulk_actions_per_turn if bulk else config.max_actions_per_turn
        max_targets = config.max_bulk_targets_per_window if bulk else config.max_targets_per_window
        while window and now - window[0][0] > config.window_s:
            window.popleft()
        found: list[GuardRefusal] = []
        if per_turn.get((conversation, correlation), 0) >= max_actions:
            found.append(GuardRefusal(RATE_LIMITED_TURN, f"at most {max_actions} guarded action per turn"))
        if sum(n for _, n in window) + count > max_targets:
            found.append(GuardRefusal(RATE_LIMITED_WINDOW, f"at most {max_targets} guarded objects per {int(config.window_s)}s"))
        return found


# ------------------------------------------------------------------ refus rendus à Jarvis (jamais silencieux)

REFUSALS_FILE = "tool-brain-guard-refusals.json"
REFUSALS_KEPT = 4
REFUSALS_MAX_AGE_S = 300.0


def record_refusal(root: Path | str | None, *, tool: str, kind: str | None, refusals: Sequence[Mapping[str, Any]],
                   conversation_id: str | None = None, wall: Callable[[], float] = time.time) -> bool:
    """Dépose le motif d'un refus de garde (code + détail court) pour le bloc « Tool Brain — écran » du tour suivant.

    Fichier dans `runtime_root` (le Control Center qui compose le tour est un autre processus que Core). Ne lève jamais :
    rend `False` si l'écriture échoue (la trace `tool_brain.guard.refused` reste).
    """

    if root is None or not refusals:
        return False
    first = refusals[0]
    entry = {"at": wall(), "tool": tool, "kind": kind or "", "conversation_id": conversation_id or "",
             "code": str(first.get("code") or ""), "detail": str(first.get("detail") or "")[:160],
             "codes": [str(item.get("code")) for item in refusals][:4]}
    path = Path(root) / REFUSALS_FILE
    try:
        entries = [item for item in _read_entries(path) if wall() - float(item.get("at", 0)) <= REFUSALS_MAX_AGE_S]
        entries = (entries + [entry])[-REFUSALS_KEPT:]
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, raw_tmp = tempfile.mkstemp(prefix=REFUSALS_FILE + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(json.dumps({"schema": "tool_brain.guard_refusals/1", "entries": entries}, ensure_ascii=False))
            from jarvis.adapters.file_replace import replace_with_retry

            replace_with_retry(Path(raw_tmp), path)
        except BaseException:
            Path(raw_tmp).unlink(missing_ok=True)
            raise
    except (OSError, ValueError, TypeError):
        return False
    return True


def _read_entries(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("entries") if isinstance(data, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def read_recent_refusals(root: Path | str | None, *, wall: Callable[[], float] = time.time,
                         max_age_s: float = REFUSALS_MAX_AGE_S, limit: int = 2) -> list[dict[str, Any]]:
    """Derniers refus de garde récents (plus récent en dernier), `age_s` ajouté. Ne lève jamais."""

    if root is None:
        return []
    now, found = wall(), []
    for item in _read_entries(Path(root) / REFUSALS_FILE):
        try:
            age = max(0.0, now - float(item["at"]))
        except (KeyError, TypeError, ValueError):
            continue
        if age <= max_age_s:
            found.append({**item, "age_s": int(age)})
    return found[-limit:]


__all__ = [
    "BULK_HIDE", "DestructiveGuard", "EVIDENCE_KIND", "GUARD_CODES", "GUARD_UNCONFIGURED", "GuardRefusal",
    "GuardrailConfig", "IRREVERSIBLE", "SCENE_UNAVAILABLE", "IntentsSource", "REFUSALS_FILE", "UserTurnLedger", "guard_class", "is_guarded", "read_recent_refusals",
    "record_refusal",
]
