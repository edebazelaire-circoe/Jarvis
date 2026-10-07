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
| `targets_not_explicit`        | archive : `object_ids` explicites seulement (jamais un filtre `select`)                      |
| `too_many_targets`            | archive : au plus `max_targets` objets par action                                            |
| `protected_pinned`            | archive : objet épinglé par l'utilisateur                                                    |
| `protected_runtime_owned`     | archive : objet du runtime (étoile agent/job, signal) : il lui appartient                    |
| `no_user_intent_evidence`     | aucune intention `dismiss` de **ce** tour ne vise **chaque** objet                           |
| `evidence_unreadable`         | le registre d'intentions est illisible : fermé                                               |
| `rate_limited_turn`           | plus d'une action gardée par tour                                                            |
| `rate_limited_window`         | plus de `max_targets_per_window` objets gardés par `window_s`                                |

Pas d'annulation : un objet archivé a un id enterré (jamais réutilisé), le défaire n'est pas bon marché. Le garde-fou
est donc *avant* (preuve, bornes, protections) et l'issue rend un **reçu** (id, nature, titre) pour la reconstitution.
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from dataclasses import dataclass
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
GUARD_CODES = frozenset({
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
        self._seen[(conversation_id, correlation_id)] = self._clock()
        self._seen.move_to_end((conversation_id, correlation_id))
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
        refusals.extend(self._evidence(conversation, correlation, targets))
        refusals.extend(self._rates(correlation, conversation, len(targets)))
        return tuple(refusals)

    def reserve(self, record: ActionRecord, count: int) -> None:
        """Consomme les budgets du tour et de la fenêtre (gardé aussi en cas d'échec : fermé, pas de martèlement)."""

        self._per_turn[(record.conversation_id or "", record.correlation_id or "")] = \
            self._per_turn.get((record.conversation_id or "", record.correlation_id or ""), 0) + 1
        if len(self._per_turn) > 256:
            self._per_turn.pop(next(iter(self._per_turn)))
        self._window.append((self._clock(), count))

    def targets_of(self, record: ActionRecord, state: UiState) -> tuple[str, ...]:
        """Les objets visés (pour le décompte de `reserve`), sans refus."""

        kind = guard_class(record.server, record.tool, record.arguments)
        return self._targets(record, state, kind or IRREVERSIBLE, []) if kind else ()

    # ------------------------------------------------------------ règles

    def _targets(self, record: ActionRecord, state: UiState, kind: str, refusals: list[GuardRefusal]) -> tuple[str, ...]:
        arguments, snapshot = record.arguments, state.scene
        if kind == IRREVERSIBLE:
            ids = arguments.get("object_ids")
            if arguments.get("select") is not None or not isinstance(ids, list) or not ids \
                    or not all(isinstance(item, str) for item in ids):
                refusals.append(GuardRefusal(TARGETS_NOT_EXPLICIT, "a guarded removal names its objects: object_ids only"))
                return ()
            ids = list(dict.fromkeys(ids))
            if len(ids) > self._config.max_targets:
                refusals.append(GuardRefusal(TOO_MANY_TARGETS, f"at most {self._config.max_targets} objects per action"))
            if snapshot is not None:
                pinned = tuple(i for i in ids if (o := snapshot.get_object(i)) is not None and o.constraints.pinned_by_user)
                owned = tuple(i for i in ids if (o := snapshot.get_object(i)) is not None and o.origin is SceneActor.RUNTIME)
                if pinned:
                    refusals.append(GuardRefusal(PROTECTED_PINNED, "the user pinned these objects", pinned))
                if owned:
                    refusals.append(GuardRefusal(PROTECTED_RUNTIME_OWNED, "the runtime owns these objects", owned))
            return tuple(ids)
        # bulk_hide : la sélection est résolue sur l'état frais (filtres permis ; la preuve doit couvrir chaque membre).
        if snapshot is None:
            return ()
        from jarvis.runtime.tool_brain_executor import _selection

        try:
            return tuple(resolve_selection(snapshot, _selection(arguments)).eligible_ids)
        except (KeyError, TypeError, ValueError):
            refusals.append(GuardRefusal(TARGETS_NOT_EXPLICIT, "the selection cannot be resolved"))
            return ()

    def _evidence(self, conversation: str, correlation: str, targets: tuple[str, ...]) -> list[GuardRefusal]:
        assert self._intents is not None
        try:
            rows = list(self._intents(conversation, correlation))
        except Exception as exc:  # noqa: BLE001 - capture: no readable evidence is no evidence; closed and said
            return [GuardRefusal(EVIDENCE_UNREADABLE, f"{type(exc).__name__}: {exc}"[:160])]
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

    def _rates(self, correlation: str, conversation: str, count: int) -> list[GuardRefusal]:
        config, now = self._config, self._clock()
        while self._window and now - self._window[0][0] > config.window_s:
            self._window.popleft()
        found: list[GuardRefusal] = []
        if self._per_turn.get((conversation, correlation), 0) >= config.max_actions_per_turn:
            found.append(GuardRefusal(RATE_LIMITED_TURN, f"at most {config.max_actions_per_turn} guarded action per turn"))
        if sum(n for _, n in self._window) + count > config.max_targets_per_window:
            found.append(GuardRefusal(RATE_LIMITED_WINDOW, f"at most {config.max_targets_per_window} guarded objects "
                                      f"per {int(config.window_s)}s"))
        return found


__all__ = [
    "BULK_HIDE", "DestructiveGuard", "EVIDENCE_KIND", "GUARD_CODES", "GUARD_UNCONFIGURED", "GuardRefusal",
    "GuardrailConfig", "IRREVERSIBLE", "IntentsSource", "UserTurnLedger", "guard_class", "is_guarded",
]
