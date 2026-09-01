from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable
import time
import unicodedata

from jarvis.domain.actions import ActionKind, ActionRequest, ActionResult, ActionStatus
from jarvis.security.policy import V1_ACTION_POLICY

ActionExecutor = Callable[[ActionRequest], Awaitable[Any]]


@dataclass(slots=True)
class PendingAction:
    action: ActionRequest
    turn_id: str
    created_at: float
    expires_at: float


class ActionBroker:
    """Deny-by-default gate for every V1 tool action.

    The broker re-checks policy instead of trusting flags coming from a registry
    or model adapter. Only one pending confirmation is allowed in V1.
    """

    APPROVALS = frozenset({"oui", "yes"})
    DENIALS = frozenset({"non", "no"})

    def __init__(
        self,
        executors: dict[ActionKind, ActionExecutor],
        *,
        confirmation_timeout_s: float = 45.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._executors = dict(executors)
        self._timeout = confirmation_timeout_s
        self._clock = clock
        self._pending: PendingAction | None = None

    @property
    def pending(self) -> PendingAction | None:
        if self._pending and self._clock() >= self._pending.expires_at:
            self._pending = None
        return self._pending

    async def request(self, action: ActionRequest, *, turn_id: str) -> ActionResult:
        policy = V1_ACTION_POLICY.get(action.kind)
        if policy is None:
            return ActionResult(action.action_id, ActionStatus.REJECTED, "Action inconnue et refusee par defaut")
        if action.risk != policy.risk or action.requires_confirmation != policy.requires_confirmation:
            return ActionResult(action.action_id, ActionStatus.REJECTED, "La requete ne correspond pas a la politique verrouillee")
        if action.kind not in self._executors:
            return ActionResult(action.action_id, ActionStatus.FAILED, "Aucun executeur n'est disponible pour cette action")
        if policy.requires_confirmation:
            if self.pending is not None:
                return ActionResult(action.action_id, ActionStatus.REJECTED, "Une autre confirmation est deja en attente")
            now = self._clock()
            self._pending = PendingAction(action=action, turn_id=turn_id, created_at=now, expires_at=now + self._timeout)
            return ActionResult(
                action.action_id,
                ActionStatus.PENDING,
                f"Confirmation requise: {action.summary}. Repondez exactement oui ou non.",
            )
        return await self._execute(action)

    async def resolve_confirmation(self, text: str, *, action_id: str) -> ActionResult:
        pending = self._pending
        if pending is None:
            return ActionResult(action_id, ActionStatus.REJECTED, "Aucune action n'attend de confirmation")
        if self._clock() >= pending.expires_at:
            self._pending = None
            return ActionResult(action_id, ActionStatus.EXPIRED, "La confirmation a expire")
        if action_id != pending.action.action_id:
            return ActionResult(action_id, ActionStatus.REJECTED, "Confirmation obsolete ou liee a une autre action")

        normalized = self.normalize_confirmation(text)
        if normalized in self.DENIALS:
            self._pending = None
            return ActionResult(action_id, ActionStatus.DENIED, "Action annulee par l'utilisateur")
        if normalized not in self.APPROVALS:
            return ActionResult(
                action_id,
                ActionStatus.PENDING,
                "Confirmation ambigue. Repondez exactement oui ou non.",
            )

        action = pending.action
        self._pending = None
        return await self._execute(action)

    async def _execute(self, action: ActionRequest) -> ActionResult:
        try:
            output = await self._executors[action.kind](action)
            return ActionResult(action.action_id, ActionStatus.EXECUTED, "Action executee", output)
        except Exception as exc:
            return ActionResult(action.action_id, ActionStatus.FAILED, f"Echec de l'action: {type(exc).__name__}")

    def cancel_pending(self, *, reason: str = "Action annulee") -> ActionResult | None:
        pending = self._pending
        self._pending = None
        if pending is None:
            return None
        return ActionResult(pending.action.action_id, ActionStatus.DENIED, reason)

    @staticmethod
    def normalize_confirmation(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text.strip().lower())
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        cleaned = []
        for ch in normalized:
            cleaned.append(ch if (ch.isalnum() or ch.isspace()) else " ")
        return " ".join("".join(cleaned).split())
