"""File d'actions d'interface du Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, S6).

Contrat : `docs/tool-brain-contracts.md` §14. La file range des **intentions de muter**, jamais un état d'écran :
chaque action est une proposition déjà validée au moment où elle a été planifiée (`validate_call`), qui sera
**revalidée par l'exécuteur** (`tool_brain_executor`) juste avant d'agir. La file est **éphémère** (mémoire de
processus, décision de l'agent 0) : un redémarrage la vide, ce qui est sûr (rien n'est jamais exécuté « à la
reprise ») ; l'autorité Board/Session qui change la vide aussi (`invalidate_all`).

- **Déclencheurs** (`Trigger`) : on privilégie la parole et les faits (un morceau commencé, une intention due, un
  évènement) à l'horloge. `delay` (absolu, borné à `MAX_DELAY_S`) n'existe que faute de repère sémantique. Toute
  action expire (`expires_at`, au plus `MAX_EXPIRES_S`) : une attente ne dure jamais indéfiniment, elle est dite.
- **Parole** : l'état d'un morceau/intention est lu dans `SpeechProgress.data` (S4) par `intent_status` (une seule
  règle) ; une chaîne **interrompue** rend obsolète toute action qui lui est liée (jamais exécutée ensuite).
- **Opérations** : `add`, `cancel`, `replace`, `reprioritize`, `reschedule`, `inspect` ; ordre déterministe
  `(priorité, séquence)`. `action_id` idempotent (un rejeu du même id ne crée rien), contenu identique dédupliqué,
  taille bornée, pas de ré-ajout d'une action tout juste invalidée (`thrash_guard`).
- **Exactement une fois** : `claim` fait passer `pending -> executing` une seule fois ; tout état terminal est
  définitif. Une exécution dont l'issue est inconnue (annulation en vol) reste `failed`, jamais rejouée.

Aucune écriture d'écran ici : la file ne connaît ni la scène ni les Boards.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping

from jarvis.domain.ui_intent import UiIntentDraft, UiIntentTiming, UiIntentKind
from jarvis.runtime.tool_brain_choices import StateRef
from jarvis.runtime.tool_brain_intents import DUE, OBSOLETE, intent_status
from jarvis.runtime.tool_brain_perception import QueueSection

ACTION_SCHEMA = "tool_brain.action/1"
QUEUE_SCHEMA = "tool_brain.queue/1"

PRIORITIES = ("high", "normal", "low")
_RANK = {name: index for index, name in enumerate(PRIORITIES)}

# Types de déclencheur.
NOW, SPEECH_CHUNK, SPEECH, INTENT, EVENT, DELAY = "now", "speech_chunk", "speech", "intent", "event", "delay"
TRIGGER_KINDS = (NOW, SPEECH_CHUNK, SPEECH, INTENT, EVENT, DELAY)

# Statuts d'une action.
QUEUED, EXECUTING = "pending", "executing"
DONE, SCHEDULED, FAILED = "done", "scheduled", "failed"
INVALIDATED, CANCELLED, SUPERSEDED, EXPIRED = "invalidated", "cancelled", "superseded", "expired"
TERMINAL = frozenset({DONE, SCHEDULED, FAILED, INVALIDATED, CANCELLED, SUPERSEDED, EXPIRED})

# Verdict de classement d'une action en attente.
WAIT, READY, GONE = "wait", "ready", "gone"

# Codes d'admission / d'opération (typés, jamais de coercition silencieuse).
INVALID_ACTION = "invalid_action"
INVALID_TRIGGER = "invalid_trigger"
INVALID_PRIORITY = "invalid_priority"
UNSUPPORTED_TOOL = "unsupported_tool"
QUEUE_FULL = "queue_full"
THRASH_GUARD = "thrash_guard"
UNKNOWN_ACTION = "unknown_action"
NOT_PENDING = "not_pending"
RESCHEDULE_LIMIT = "reschedule_limit"
# Codes de fin sans exécution.
SPEECH_OBSOLETE = "speech_obsolete"
ACTION_EXPIRED = "action_expired"
AUTHORITY_CHANGED = "authority_changed"

MAX_DELAY_S = 120.0
MAX_EXPIRES_S = 600.0
DEFAULT_EXPIRES_S = 120.0
NOW_EXPIRES_S = 30.0
MAX_ID_CHARS = 120
MAX_REASON_CODE_CHARS = 40
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-]*")
_EVENT_NAME = re.compile(r"[a-z][a-z0-9_.]{2,63}")


class QueueError(ValueError):
    """Refus typé d'une admission ou d'une opération ; `code` stable (`INVALID_*`, `QUEUE_FULL`...)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# ------------------------------------------------------------------ déclencheur


@dataclass(frozen=True)
class Trigger:
    """Quand l'action est due. Voir l'en-tête : parole et faits d'abord, `delay` en dernier recours."""

    kind: str = NOW
    chunk_id: str | None = None
    correlation_id: str | None = None
    paragraph: int | None = None
    #: `speech` : `start` (le paragraphe, ou la réponse, est commencé) ou `end` (la réponse est finie).
    when: str | None = None
    intent_id: str | None = None
    event: str | None = None
    delay_s: float | None = None

    @classmethod
    def from_payload(cls, payload: object) -> Trigger:
        """Décodage strict d'un déclencheur de décideur. Champ inconnu ou forme fausse : `invalid_trigger`."""

        if payload is None:
            return cls()
        if not isinstance(payload, Mapping):
            raise QueueError(INVALID_TRIGGER, "a trigger is an object {type, ...}")
        kind = payload.get("type")
        if kind not in TRIGGER_KINDS:
            raise QueueError(INVALID_TRIGGER, f"type must be one of {', '.join(TRIGGER_KINDS)}")
        allowed = {NOW: set(), SPEECH_CHUNK: {"chunk_id"}, SPEECH: {"correlation_id", "when", "paragraph"},
                   INTENT: {"intent_id"}, EVENT: {"name"}, DELAY: {"seconds"}}[kind]
        unknown = sorted(str(key)[:40] for key in set(payload) - allowed - {"type"})
        if unknown:
            raise QueueError(INVALID_TRIGGER, f"unknown trigger fields for {kind}: {unknown[:5]}")
        if kind == NOW:
            return cls()
        if kind == SPEECH_CHUNK:
            return cls(kind, chunk_id=_ident(payload.get("chunk_id"), "chunk_id"))
        if kind == INTENT:
            return cls(kind, intent_id=_ident(payload.get("intent_id"), "intent_id"))
        if kind == EVENT:
            name = payload.get("name")
            if not isinstance(name, str) or _EVENT_NAME.fullmatch(name) is None:
                raise QueueError(INVALID_TRIGGER, "event name must be lowercase letters, digits, '_' or '.'")
            return cls(kind, event=name)
        if kind == DELAY:
            seconds = payload.get("seconds")
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0 < seconds <= MAX_DELAY_S:
                raise QueueError(INVALID_TRIGGER, f"seconds must be in (0, {MAX_DELAY_S:g}]")
            return cls(kind, delay_s=float(seconds))
        when = payload.get("when", "start")
        if when not in ("start", "end"):
            raise QueueError(INVALID_TRIGGER, "when must be start or end")
        paragraph = payload.get("paragraph")
        if paragraph is not None and (type(paragraph) is not int or not 0 <= paragraph < 64):
            raise QueueError(INVALID_TRIGGER, "paragraph must be a small non-negative integer")
        if paragraph is not None and when == "end":
            raise QueueError(INVALID_TRIGGER, "paragraph only applies to when=start")
        return cls(kind, correlation_id=_ident(payload.get("correlation_id"), "correlation_id"), when=when,
                   paragraph=paragraph)

    @property
    def speech_bound(self) -> bool:
        return self.kind in (SPEECH_CHUNK, SPEECH, INTENT)

    def to_dict(self) -> dict[str, Any]:
        wire: dict[str, Any] = {"type": self.kind}
        for key, value in (("chunk_id", self.chunk_id), ("correlation_id", self.correlation_id),
                           ("when", self.when), ("paragraph", self.paragraph), ("intent_id", self.intent_id),
                           ("name", self.event), ("seconds", self.delay_s)):
            if value is not None:
                wire[key] = value
        return wire


def _ident(value: object, what: str) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= MAX_ID_CHARS or _ID.fullmatch(value) is None:
        raise QueueError(INVALID_TRIGGER, f"{what} must be a stable id")
    return value


# ------------------------------------------------------------------ action


@dataclass(frozen=True)
class Precondition:
    """Ce qui doit rester vrai de l'état faisant autorité pour que l'action ait encore un sens.

    `scene_epoch` : `value` = `scene_id@epoch` ; `active_board` : `value` = id du Board actif au moment du plan.
    Pas de révision par objet (décision G3) : l'existence/l'archivage d'un objet est jugé par `validate_call`.
    """

    kind: str
    value: str

    def to_dict(self) -> dict[str, str]:
        return {"type": self.kind, "value": self.value}


def preconditions_from(ref: StateRef | None) -> tuple[Precondition, ...]:
    """Préconditions dérivées de la référence observée par le décideur (jamais écrites à la main)."""

    if ref is None:
        return ()
    found: list[Precondition] = []
    if ref.scene_id is not None and ref.epoch is not None:
        found.append(Precondition("scene_epoch", f"{ref.scene_id}@{ref.epoch}"))
    if ref.active_board_id is not None:
        found.append(Precondition("active_board", ref.active_board_id))
    return tuple(found)


@dataclass(frozen=True)
class ActionRecord:
    """Une action planifiée (docs/02-architecture.md §H). Immuable ; l'état d'avancement vit dans la file."""

    action_id: str
    server: str
    tool: str
    arguments: Mapping[str, Any]
    priority: str = "normal"
    trigger: Trigger = field(default_factory=Trigger)
    planned_from: StateRef | None = None
    #: Empreinte de la perception qui a servi le plan (`UiPerception.digest()`), pour le rejeu.
    planned_from_snapshot: str | None = None
    preconditions: tuple[Precondition, ...] = ()
    supersedes: tuple[str, ...] = ()
    reason_code: str = ""
    reason: str = ""
    intent_id: str | None = None
    decision_id: str | None = None
    conversation_id: str | None = None
    correlation_id: str | None = None

    def fingerprint(self) -> str:
        body = json.dumps([self.server, self.tool, self.arguments, self.trigger.to_dict()], sort_keys=True,
                          separators=(",", ":"), default=str)
        return hashlib.sha1(body.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {"schema": ACTION_SCHEMA, "action_id": self.action_id, "server": self.server, "tool": self.tool,
                "args": dict(self.arguments), "priority": self.priority, "trigger": self.trigger.to_dict(),
                "planned_from_snapshot": self.planned_from_snapshot,
                "planned_from": self.planned_from.to_dict() if self.planned_from else None,
                "preconditions": [item.to_dict() for item in self.preconditions],
                "supersedes": list(self.supersedes), "reason_code": self.reason_code, "reason": self.reason,
                "intent_id": self.intent_id, "decision_id": self.decision_id}


@dataclass
class _Entry:
    record: ActionRecord
    seq: int
    created_at: float
    armed_at: float
    expires_at: float
    event_baseline: int
    status: str = QUEUED
    #: Code de fin (invalidation, annulation...) ou issue du propriétaire ; texte du propriétaire dans `detail`.
    code: str | None = None
    detail: Mapping[str, Any] | None = None
    finished_at: float | None = None
    reschedules: int = 0


@dataclass(frozen=True)
class ActionView:
    """Lecture figée d'une action et de son avancement."""

    record: ActionRecord
    seq: int
    status: str
    created_at: float
    expires_at: float
    code: str | None = None
    detail: Mapping[str, Any] | None = None
    reschedules: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {**self.record.to_dict(), "seq": self.seq, "status": self.status, "code": self.code,
                "detail": dict(self.detail) if self.detail else None, "expires_at": self.expires_at,
                "reschedules": self.reschedules}

    def brief(self) -> dict[str, Any]:
        """Une ligne pour la perception du décideur : pas d'arguments, pas de texte libre."""

        return {"id": self.record.action_id, "tool": self.record.tool, "status": self.status,
                "priority": self.record.priority, "trigger": self.record.trigger.to_dict(),
                "reason_code": self.record.reason_code, **({"code": self.code} if self.code else {})}


@dataclass(frozen=True)
class AddResult:
    """Issue d'une admission : `queued`, `duplicate` (id ou contenu déjà connu, rien n'est ajouté) ou `rejected`."""

    outcome: str
    action_id: str
    code: str | None = None
    detail: str = ""

    @property
    def queued(self) -> bool:
        return self.outcome == "queued"


# ------------------------------------------------------------------ contexte de déclenchement


@dataclass(frozen=True)
class TriggerContext:
    """Ce que la file lit pour classer une action : l'heure, la parole (S4) et les intentions de Jarvis.

    `intent_row(record)` rend la ligne `list_ui_intents` de `record.intent_id` (ou `None` : intention inconnue).
    """

    now: float
    speech: Mapping[str, Any] | None = None
    intent_row: Callable[[ActionRecord], Mapping[str, Any] | None] | None = None


def _chain_of(speech: Mapping[str, Any], correlation_id: str | None) -> Mapping[str, Any] | None:
    for chain in speech.get("chains", ()):
        if chain.get("corr") == correlation_id:
            return chain
    return None


def _locate_chunk(speech: Mapping[str, Any], chunk_id: str) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    for chain in speech.get("chains", ()):
        for chunk in chain.get("chunks", ()):
            if chunk.get("id") == chunk_id:
                return chain, chunk
    return None


def _speech_verdict(record: ActionRecord, ctx: TriggerContext) -> tuple[str, str | None]:
    """Verdict d'une action liée à la parole -> (`wait|ready|gone`, code de fin)."""

    trigger, speech = record.trigger, ctx.speech
    if speech is None:
        return WAIT, None  # parole non câblée : l'expiration bornera l'attente
    if trigger.kind == SPEECH_CHUNK:
        if trigger.chunk_id in speech.get("obsolete_chunk_ids", ()):
            return GONE, SPEECH_OBSOLETE
        found = _locate_chunk(speech, trigger.chunk_id or "")
        if found is None:
            return WAIT, None  # morceau pas (encore) visible : attendre, jamais deviner
        chain, chunk = found
        if chain.get("state") == "interrupted":
            return GONE, SPEECH_OBSOLETE
        phase = chunk.get("ph")
        if phase == "obsolete":
            return GONE, SPEECH_OBSOLETE
        return (READY, None) if phase in ("playing", "heard", "interrupted", "unconfirmed") else (WAIT, None)
    if trigger.kind == SPEECH:
        correlation = trigger.correlation_id
        draft = UiIntentDraft(
            UiIntentKind.REVEAL, subject="trigger",
            timing=UiIntentTiming.AFTER_SPEECH if trigger.when == "end" else UiIntentTiming.WITH_SPEECH,
            paragraph=trigger.paragraph)
        return _settle(intent_status(draft, correlation or "", speech), _chain_of(speech, correlation))
    row = ctx.intent_row(record) if ctx.intent_row else None
    if row is None:
        return WAIT, None
    try:
        draft = UiIntentDraft.from_payload({key: row[key] for key in ("kind", "refs", "subject", "timing", "paragraph")
                                            if key in row})
    except ValueError:
        return GONE, "invalid_intent"
    correlation = row.get("correlation_id")
    return _settle(intent_status(draft, correlation or "", speech), _chain_of(speech, correlation),
                   now_timing=draft.timing is UiIntentTiming.NOW)


def _settle(status: str, chain: Mapping[str, Any] | None, *, now_timing: bool = False) -> tuple[str, str | None]:
    if status == OBSOLETE or (chain is not None and chain.get("state") == "interrupted" and not now_timing):
        # Une parole coupée ne reprend pas : l'action qui lui est liée ne s'exécutera plus jamais.
        return GONE, SPEECH_OBSOLETE
    if status == DUE:
        return READY, None
    return WAIT, None  # `pending` ou `unanchored`


# ------------------------------------------------------------------ la file


class ToolBrainActionQueue:
    """Voir l'en-tête du module. Synchrone et pure en E/S (l'horloge est injectée) : testable sans boucle."""

    def __init__(self, *, clock: Callable[[], float], supported: Callable[[str, str], bool] | None = None,
                 max_pending: int = 16, history_size: int = 64, seen_ids: int = 512, thrash_cooldown_s: float = 5.0,
                 max_reschedules: int = 3) -> None:
        if max_pending < 1 or history_size < 1 or seen_ids < max_pending + history_size:
            raise ValueError("invalid queue bounds")
        self._clock = clock
        self._supported = supported
        self._max_pending, self._history_size, self._cooldown = max_pending, history_size, thrash_cooldown_s
        self._max_reschedules = max_reschedules
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        #: Ids déjà vus (même évincés de l'historique) : un rejeu ne crée ni ne ré-exécute rien.
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._seen_limit = seen_ids
        self._cool: dict[str, float] = {}
        self._events: dict[str, int] = {}
        self._seq = 0
        self._counters = {"added": 0, "duplicate": 0, "rejected": 0, "cancelled": 0, "superseded": 0,
                          "expired": 0, "invalidated": 0, "done": 0, "failed": 0, "scheduled": 0}

    # ------------------------------------------------------------ admission

    def expires_for(self, trigger: Trigger, requested: float | None = None) -> float:
        """Durée de vie bornée d'une action (secondes) : jamais d'attente sans échéance."""

        default = NOW_EXPIRES_S if trigger.kind == NOW else (
            (trigger.delay_s or 0) + NOW_EXPIRES_S if trigger.kind == DELAY else DEFAULT_EXPIRES_S)
        value = default if requested is None else requested
        return max(1.0, min(float(value), MAX_EXPIRES_S))

    def add(self, record: ActionRecord, *, expires_s: float | None = None) -> AddResult:
        """Admission : validation de forme, support par un exécuteur, doublons, borne, garde anti-ballottement."""

        return self._admit(record, expires_s, None)

    def _admit(self, record: ActionRecord, expires_s: float | None, replacing: _Entry | None) -> AddResult:
        """Admission, éventuellement en remplacement de `replacing` : celui-ci ne compte ni comme jumeau ni dans la
        borne, et n'est retiré (`superseded`) qu'**après** l'insertion réussie — un refus ne le touche pas."""

        action_id = record.action_id
        if (not isinstance(action_id, str) or not 0 < len(action_id) <= MAX_ID_CHARS
                or _ID.fullmatch(action_id) is None or not record.server or not record.tool):
            return self._rejected(action_id, INVALID_ACTION, "action_id must be a stable id and tool must be named")
        if record.priority not in _RANK:
            return self._rejected(action_id, INVALID_PRIORITY, f"priority must be one of {', '.join(PRIORITIES)}")
        if action_id in self._seen:
            self._counters["duplicate"] += 1
            return AddResult("duplicate", action_id, "duplicate_action_id")
        if self._supported is not None and not self._supported(record.server, record.tool):
            return self._rejected(action_id, UNSUPPORTED_TOOL, f"{record.server}/{record.tool} has no executor")
        fingerprint = record.fingerprint()
        twin = next((item for item in self._entries.values() if item is not replacing
                     and item.status == QUEUED and item.record.fingerprint() == fingerprint), None)
        if twin is not None:
            self._counters["duplicate"] += 1
            return AddResult("duplicate", twin.record.action_id, "duplicate_content")
        now = self._clock()
        if self._cool.get(fingerprint, 0.0) > now:
            return self._rejected(action_id, THRASH_GUARD, "the same action was just invalidated; replan, do not retry")
        missing = [old for old in record.supersedes if old not in self._entries]
        if missing:
            return self._rejected(action_id, UNKNOWN_ACTION, f"supersedes unknown action {missing[0]}")
        if sum(1 for item in self._entries.values()
               if item.status == QUEUED and item is not replacing) >= self._max_pending:
            return self._rejected(action_id, QUEUE_FULL, f"at most {self._max_pending} pending actions")
        self._seq += 1
        life = self.expires_for(record.trigger, expires_s)
        self._entries[action_id] = _Entry(record, self._seq, now, now, now + life,
                                          self._events.get(record.trigger.event or "", 0))
        self._remember(action_id)
        self._counters["added"] += 1
        if replacing is not None:
            self._finish(replacing, SUPERSEDED, action_id)  # finit par `_trim`
        else:
            self._trim()
        return AddResult("queued", action_id)

    def _rejected(self, action_id: str, code: str, detail: str) -> AddResult:
        self._counters["rejected"] += 1
        return AddResult("rejected", str(action_id)[:MAX_ID_CHARS], code, detail)

    def _remember(self, action_id: str) -> None:
        self._seen[action_id] = None
        while len(self._seen) > self._seen_limit:
            self._seen.popitem(last=False)

    def _trim(self) -> None:
        terminal = [key for key, item in self._entries.items() if item.status in TERMINAL]
        for key in terminal[: max(0, len(terminal) - self._history_size)]:
            del self._entries[key]

    # ------------------------------------------------------------ opérations

    def cancel(self, action_id: str, code: str = "cancelled_by_brain") -> str:
        """Annule une action en attente. Rend `cancelled`, ou le code du refus (`unknown_action`, `not_pending`)."""

        entry = self._entries.get(action_id)
        if entry is None:
            return UNKNOWN_ACTION
        if entry.status != QUEUED:
            return NOT_PENDING
        self._finish(entry, CANCELLED, code[:MAX_REASON_CODE_CHARS])
        return CANCELLED

    def replace(self, old_id: str, record: ActionRecord, *, expires_s: float | None = None) -> AddResult:
        """Remplace une action en attente par une autre, **atomiquement** : si la nouvelle est refusée, l'ancienne reste."""

        old = self._entries.get(old_id)
        if old is None:
            return self._rejected(record.action_id, UNKNOWN_ACTION, f"unknown action {old_id}")
        if old.status != QUEUED:
            return self._rejected(record.action_id, NOT_PENDING, f"{old_id} is {old.status}")
        record = replace(record, supersedes=tuple(dict.fromkeys((*record.supersedes, old_id))))
        return self._admit(record, expires_s, old)

    def reprioritize(self, action_id: str, priority: str) -> str:
        if priority not in _RANK:
            return INVALID_PRIORITY
        entry = self._entries.get(action_id)
        if entry is None:
            return UNKNOWN_ACTION
        if entry.status != QUEUED:
            return NOT_PENDING
        entry.record = replace(entry.record, priority=priority)
        return "reprioritized"

    def reschedule(self, action_id: str, trigger: Trigger) -> str:
        """Change le déclencheur d'une action en attente. Borné (`max_reschedules`) : pas de report sans fin."""

        entry = self._entries.get(action_id)
        if entry is None:
            return UNKNOWN_ACTION
        if entry.status != QUEUED:
            return NOT_PENDING
        if entry.reschedules >= self._max_reschedules:
            return RESCHEDULE_LIMIT
        now = self._clock()
        entry.record = replace(entry.record, trigger=trigger)
        entry.armed_at, entry.reschedules = now, entry.reschedules + 1
        entry.event_baseline = self._events.get(trigger.event or "", 0)
        # L'échéance ne glisse que jusqu'au plafond absolu depuis la création : un report n'est jamais infini.
        entry.expires_at = min(now + self.expires_for(trigger), entry.created_at + MAX_EXPIRES_S)
        return "rescheduled"

    def invalidate_all(self, code: str = AUTHORITY_CHANGED) -> int:
        """Vide la file en attente (autorité Board/Session changée, arrêt) ; rend le nombre d'actions annulées."""

        victims = [item for item in self._entries.values() if item.status == QUEUED]
        for entry in victims:
            self._finish(entry, CANCELLED, code[:MAX_REASON_CODE_CHARS])
        return len(victims)

    def note_event(self, name: str) -> None:
        """Un fait nommé est arrivé (`EVENT`) : réveille les actions qui l'attendent (une seule fois chacune)."""

        self._events[name] = self._events.get(name, 0) + 1
        if len(self._events) > 256:
            self._events.pop(next(iter(self._events)))

    # ------------------------------------------------------------ classement

    def classify(self, entry_or_id: str | _Entry, ctx: TriggerContext) -> tuple[str, str | None]:
        """`(wait|ready|gone, code)` pour une action en attente. `gone` : elle ne s'exécutera plus jamais."""

        entry = self._entries.get(entry_or_id) if isinstance(entry_or_id, str) else entry_or_id
        if entry is None or entry.status != QUEUED:
            return GONE, NOT_PENDING
        if ctx.now >= entry.expires_at:
            return GONE, ACTION_EXPIRED
        trigger = entry.record.trigger
        if trigger.kind == NOW:
            return READY, None
        if trigger.kind == DELAY:
            return (READY, None) if ctx.now >= entry.armed_at + (trigger.delay_s or 0.0) else (WAIT, None)
        if trigger.kind == EVENT:
            return (READY, None) if self._events.get(trigger.event or "", 0) > entry.event_baseline else (WAIT, None)
        return _speech_verdict(entry.record, ctx)

    def recheck(self, action_id: str, ctx: TriggerContext) -> tuple[str, str | None]:
        """Dernier contrôle d'une action **prise** (`executing`) : la parole qui la portait est-elle encore vivante ?

        Seule la mort de la parole compte ici (le déclencheur a déjà été satisfait, l'échéance ne s'applique plus).
        """

        entry = self._entries.get(action_id)
        if entry is None or entry.status != EXECUTING:
            return GONE, NOT_PENDING
        if entry.record.trigger.speech_bound:
            verdict, code = _speech_verdict(entry.record, ctx)
            if verdict == GONE:
                return GONE, code
        return READY, None

    def retire(self, action_id: str, code: str) -> None:
        """Sort une action en attente qui ne s'exécutera plus (`expired` pour l'échéance, sinon `cancelled`)."""

        entry = self._entries.get(action_id)
        if entry is not None and entry.status == QUEUED:
            self._finish(entry, EXPIRED if code == ACTION_EXPIRED else CANCELLED, code)

    def sweep(self, ctx: TriggerContext) -> list[ActionView]:
        """Retire les actions mortes (expirées, parole obsolète) et rend leurs vues finales (pour le journal)."""

        gone: list[ActionView] = []
        for entry in list(self._entries.values()):
            if entry.status != QUEUED:
                continue
            verdict, code = self.classify(entry, ctx)
            if verdict == GONE:
                self._finish(entry, EXPIRED if code == ACTION_EXPIRED else CANCELLED, code)
                gone.append(self._view(entry))
        return gone

    def ready(self, ctx: TriggerContext) -> list[str]:
        """Ids des actions dues, dans l'ordre déterministe `(priorité, séquence)`."""

        due = [item for item in self._entries.values()
               if item.status == QUEUED and self.classify(item, ctx)[0] == READY]
        due.sort(key=lambda item: (_RANK[item.record.priority], item.seq))
        return [item.record.action_id for item in due]

    def next_deadline(self) -> float | None:
        """Prochain instant utile (échéance ou délai) : la boucle ne dort jamais au-delà."""

        times: list[float] = []
        for entry in self._entries.values():
            if entry.status != QUEUED:
                continue
            times.append(entry.expires_at)
            if entry.record.trigger.kind == DELAY:
                times.append(entry.armed_at + (entry.record.trigger.delay_s or 0.0))
        return min(times) if times else None

    # ------------------------------------------------------------ exécution (exactement une fois)

    def claim(self, action_id: str) -> ActionView | None:
        """`pending -> executing`, une seule fois. `None` si l'action n'est plus à prendre (déjà prise, finie, inconnue)."""

        entry = self._entries.get(action_id)
        if entry is None or entry.status != QUEUED:
            return None
        entry.status = EXECUTING
        return self._view(entry)

    def settle(self, action_id: str, status: str, code: str | None = None,
               detail: Mapping[str, Any] | None = None) -> ActionView:
        """Fin d'une action prise (`done|scheduled|failed|invalidated`). Un statut terminal ne se réécrit jamais."""

        entry = self._entries[action_id]
        if entry.status != EXECUTING or status not in TERMINAL:
            raise ValueError(f"cannot settle {action_id}: {entry.status} -> {status}")
        self._finish(entry, status, code, detail)
        if status == INVALIDATED:
            self._cool[entry.record.fingerprint()] = self._clock() + self._cooldown
            for key in [key for key, until in self._cool.items() if until <= self._clock()]:
                del self._cool[key]
        return self._view(entry)

    def _finish(self, entry: _Entry, status: str, code: str | None = None,
                detail: Mapping[str, Any] | None = None) -> None:
        entry.status, entry.code, entry.detail, entry.finished_at = status, code, detail, self._clock()
        key = {DONE: "done", FAILED: "failed", SCHEDULED: "scheduled", INVALIDATED: "invalidated",
               CANCELLED: "cancelled", SUPERSEDED: "superseded", EXPIRED: "expired"}[status]
        self._counters[key] += 1
        self._trim()

    # ------------------------------------------------------------ lecture

    def _view(self, entry: _Entry) -> ActionView:
        return ActionView(entry.record, entry.seq, entry.status, entry.created_at, entry.expires_at, entry.code,
                          entry.detail, entry.reschedules)

    def get(self, action_id: str) -> ActionView | None:
        entry = self._entries.get(action_id)
        return self._view(entry) if entry else None

    def views(self, *, pending_only: bool = False) -> tuple[ActionView, ...]:
        found = [item for item in self._entries.values() if not pending_only or item.status == QUEUED]
        found.sort(key=lambda item: (0, _RANK[item.record.priority], item.seq) if item.status == QUEUED
                   else (1, 0, item.seq))
        return tuple(self._view(item) for item in found)

    def pending_count(self) -> int:
        return sum(1 for item in self._entries.values() if item.status == QUEUED)

    def inspect(self, action_id: str | None = None) -> dict[str, Any]:
        """`tool_brain.queue/1` : une action (complète) ou l'ensemble borné (en attente d'abord, puis récentes)."""

        if action_id is not None:
            view = self.get(action_id)
            return {"schema": QUEUE_SCHEMA, "ok": view is not None, "action": view.to_dict() if view else None,
                    **({} if view else {"code": UNKNOWN_ACTION})}
        return {"schema": QUEUE_SCHEMA, "ok": True, "pending": self.pending_count(), "max_pending": self._max_pending,
                "items": [item.to_dict() for item in self.views()], "counters": dict(self._counters)}

    def section(self, limit: int = 8) -> QueueSection:
        """Couture S3 : le résumé que la perception du décideur porte (pas d'arguments, borné)."""

        views = self.views()
        shown = views[:limit]
        return QueueSection("wired", tuple(item.brief() for item in shown))

    def stats(self) -> dict[str, int]:
        return {**self._counters, "pending": self.pending_count()}


def plan_action(proposed: Any, *, action_id: str, ref: StateRef | None, digest: str | None, decision_id: str | None,
                conversation_id: str | None = None, correlation_id: str | None = None) -> ActionRecord:
    """`ProposedAction` (port du décideur) -> `ActionRecord` : déclencheur décodé, préconditions dérivées de `ref`."""

    trigger = Trigger.from_payload(getattr(proposed, "trigger", None))
    priority = getattr(proposed, "priority", None) or "normal"
    return ActionRecord(
        action_id=action_id, server=proposed.server, tool=proposed.tool, arguments=dict(proposed.arguments),
        priority=priority, trigger=trigger, planned_from=ref, planned_from_snapshot=digest,
        preconditions=preconditions_from(ref), supersedes=tuple(getattr(proposed, "replaces", ()) or ()),
        reason_code=(getattr(proposed, "reason_code", "") or "")[:MAX_REASON_CODE_CHARS],
        reason=proposed.reason, intent_id=proposed.intent_id or trigger.intent_id, decision_id=decision_id,
        conversation_id=conversation_id, correlation_id=correlation_id)


__all__ = [
    "ACTION_EXPIRED", "ACTION_SCHEMA", "AUTHORITY_CHANGED", "AddResult", "ActionRecord", "ActionView", "CANCELLED",
    "DELAY", "DONE", "EVENT", "EXECUTING", "EXPIRED", "FAILED", "GONE", "INTENT", "INVALIDATED", "INVALID_ACTION",
    "INVALID_PRIORITY", "INVALID_TRIGGER", "MAX_DELAY_S", "MAX_EXPIRES_S", "NOT_PENDING", "NOW", "PRIORITIES",
    "Precondition", "QUEUED", "QUEUE_FULL", "QUEUE_SCHEMA", "QueueError", "READY", "RESCHEDULE_LIMIT", "SCHEDULED",
    "SPEECH", "SPEECH_CHUNK", "SPEECH_OBSOLETE", "SUPERSEDED", "TERMINAL", "THRASH_GUARD", "ToolBrainActionQueue",
    "Trigger", "TriggerContext", "UNKNOWN_ACTION", "UNSUPPORTED_TOOL", "WAIT", "plan_action", "preconditions_from",
]
