"""Événements des fenêtres prefab vers Core (handoff jarvis-scene-window-prefab-foundation, Slice 04).

Chemin : cadre -> hôte de la page (`control_center_prefab_host.js`) ->
`POST /api/prefabs/events` (Control Center, acteur forcé `user`) ->
`POST /v1/prefabs/events` (Core) -> `PrefabEventService.submit`.
Contrat : `docs/prefabs.md` › *Events*.

Deux classes, déclarées par le manifeste de la définition :

- **state** écrit des clés de premier niveau de `prefab.data` déclarées par
  `writes`. Contrôles, dans l'ordre : l'objet est actif, de nature `window`,
  et son bloc porte l'id et la version demandés ; l'événement est déclaré et
  de classe `state` ; les clés écrites sont dans `writes` ; la `basis` (ce que
  le cadre a vu en dernier) est égale aux données courantes sur ces clés,
  sinon `stale` et rien n'est écrit ; `{**data, **payload}` valide le schéma
  des données (`jarvis.domain.prefab.check_state_event`). Puis un
  `patch_object` de l'acteur `user` passe par le réducteur et le validateur
  de prefabs de la scène. **Le contrôle de la `basis` et l'écriture se font
  sous le verrou de la scène** (`SceneService.apply_if`, R9.1) : aucune
  commande ne peut s'intercaler entre la lecture et l'écriture ;
- **notify** est seulement consigné : rien n'est écrit.

Les deux classes, refus compris, entrent dans un anneau borné
(`EVENT_RING_SIZE`) lu par `GET /v1/prefabs/events` ; chaque entrée émet le
diagnostic `core.prefab.event` (clés, jamais les valeurs). Les `notify` non
remis se prennent une fois par `take_undelivered_notify` (le tour du cerveau,
Slice 07). Débit : seau de jetons de `RATE_PER_S` événements par seconde ;
au-delà `PrefabEventsRateLimited` (429 `rate_limited`). **Aucun événement
n'exécute d'outil.**
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
import time
from typing import Any, Protocol

from jarvis.core.v2_services import NullDiagnosticSink
from jarvis.domain._checks import check_id
from jarvis.domain.prefab import (
    MAX_EVENT_PAYLOAD_BYTES, EventClass, PrefabManifest, StateEventOutcome, canonical_json, check_state_event,
    clip_message, is_prefab_id, is_version, validate_value,
)
from jarvis.domain.scene import (
    SceneActor, SceneCommand, SceneCommandOutcome, SceneObject, SceneObjectFields, SceneObjectKind, SceneOp,
    SceneSnapshot,
)
from jarvis.domain.v2 import utc_now
from jarvis.ports.prefabs import PrefabStoreError
from jarvis.ports.scene import SceneConditionalSink, SceneReader
from jarvis.ports.v2 import DiagnosticSink

EVENT_RING_SIZE = 256
RATE_PER_S = 30.0
MAX_LIST_LIMIT = 50
MAX_NOTIFY_DELIVERY = 8
NOTIFY_PREVIEW_BYTES = 1024
EVENT_KIND = "core.prefab.event"
RATE_LIMITED_KIND = "core.prefab.event_rate_limited"
_REQUEST_KEYS = frozenset({"actor", "object_id", "prefab", "event", "payload", "basis"})


class PrefabEventOutcome(StrEnum):
    APPLIED = "applied"
    RECORDED = "recorded"
    STALE = "stale"
    REFUSED = "refused"


class PrefabEventsRateLimited(Exception):
    """Plus de `RATE_PER_S` événements par seconde : 429 `rate_limited`, rien n'est consigné."""


class PrefabManifestSource(Protocol):
    async def manifest(self, prefab_id: str, version: int) -> PrefabManifest: ...


class EventScene(SceneConditionalSink, SceneReader, Protocol):
    """Ce que le service demande à la scène : lecture et `apply_if`."""


@dataclass(frozen=True, slots=True)
class PrefabEventRequest:
    """Corps de `POST /v1/prefabs/events`, décodé strictement (`ValueError` -> 400)."""

    object_id: str
    prefab_id: str
    version: int
    event: str
    payload: Any
    basis: Any = None

    @classmethod
    def from_body(cls, body: object) -> PrefabEventRequest:
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        unknown = sorted(str(key)[:40] for key in body if key not in _REQUEST_KEYS)
        if unknown:
            raise ValueError(f"unexpected fields: {', '.join(unknown[:6])}")
        missing = sorted({"actor", "object_id", "prefab", "event", "payload"} - body.keys())
        if missing:
            raise ValueError(f"missing fields: {', '.join(missing)}")
        if body["actor"] != SceneActor.USER.value:
            # Seule la page de l'utilisateur émet ; le Control Center force `user`.
            raise ValueError("actor must be 'user'")
        if not isinstance(body["object_id"], str):
            raise ValueError("object_id must be a string")
        check_id("object_id", body["object_id"], required=True)
        prefab = body["prefab"]
        if not isinstance(prefab, dict) or set(prefab) != {"id", "version"}:
            raise ValueError("prefab must be exactly {id, version}")
        if not is_prefab_id(prefab["id"]) or not is_version(prefab["version"]):
            raise ValueError("prefab must name a valid prefab id and an integer version")
        if not isinstance(body["event"], str) or not 0 < len(body["event"]) <= 40:
            raise ValueError("event must be a name of at most 40 characters")
        return cls(body["object_id"], prefab["id"], prefab["version"], body["event"], body["payload"],
                   body.get("basis"))

    @property
    def prefab_key(self) -> str:
        return f"{self.prefab_id}@{self.version}"


@dataclass(frozen=True, slots=True)
class PrefabEventResult:
    outcome: PrefabEventOutcome
    reason: str | None = None
    detail: str = ""
    revision: int | None = None

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"outcome": self.outcome.value}
        if self.reason:
            body["reason"] = self.reason
        if self.detail:
            body["detail"] = self.detail
        if self.revision is not None:
            body["revision"] = self.revision
        return body


@dataclass(slots=True)
class PrefabEventEntry:
    """Une entrée de l'anneau. `payload` est `None` s'il dépassait `MAX_EVENT_PAYLOAD_BYTES` ou n'était pas JSON."""

    seq: int
    at: datetime
    object_id: str
    prefab: str
    event: str
    event_class: EventClass | None
    payload: Any
    outcome: PrefabEventOutcome
    reason: str | None = None
    delivered: bool = field(default=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        body = {"seq": self.seq, "at": self.at.isoformat(), "object_id": self.object_id, "prefab": self.prefab,
                "event": self.event, "class": self.event_class.value if self.event_class else None,
                "payload": self.payload, "outcome": self.outcome.value}
        if self.reason:
            body["reason"] = self.reason
        return body

    def payload_preview(self, limit: int = NOTIFY_PREVIEW_BYTES) -> str:
        """JSON du payload coupé à `limit` octets UTF-8 (aperçu du tour du cerveau)."""

        text = canonical_json(self.payload)
        raw = text.encode("utf-8")
        return text if len(raw) <= limit else raw[:limit].decode("utf-8", errors="ignore") + "…"


def _bounded_payload(payload: Any) -> Any:
    try:
        size = len(canonical_json(payload).encode("utf-8"))
    except (TypeError, ValueError):
        return None
    return payload if size <= MAX_EVENT_PAYLOAD_BYTES else None


def _object_mismatch(snapshot: SceneSnapshot, request: PrefabEventRequest) -> tuple[SceneObject | None, str]:
    """Étape 1 : objet actif, `window`, bloc de même id et version ; sinon motif."""

    target = snapshot.get_object(request.object_id)
    if target is None:
        return None, f"object {request.object_id} is not on the scene"
    if target.kind is not SceneObjectKind.WINDOW or target.payload.prefab is None:
        return None, f"object {request.object_id} is not a prefab window"
    block = target.payload.prefab
    if (block.prefab_id, block.version) != (request.prefab_id, request.version):
        return None, f"object {request.object_id} shows {block.key}, not {request.prefab_key}"
    return target, ""


class PrefabEventService:
    """Événements `state`/`notify` des cadres. Voir l'en-tête du module."""

    def __init__(self, scene: EventScene, catalog: PrefabManifestSource, *, diagnostics: DiagnosticSink | None = None,
                 ring_size: int = EVENT_RING_SIZE, rate_per_s: float = RATE_PER_S,
                 clock: Callable[[], float] = time.monotonic, now: Callable[[], datetime] = utc_now) -> None:
        self._scene = scene
        self._catalog = catalog
        self._diagnostics: DiagnosticSink = diagnostics or NullDiagnosticSink()
        self._ring: deque[PrefabEventEntry] = deque(maxlen=ring_size)
        self._seq = 0
        self._rate = float(rate_per_s)
        self._tokens = float(rate_per_s)
        self._clock = clock
        self._now = now
        self._last = clock()
        self._limited = 0

    # ------------------------------------------------------------ entrée

    async def submit(self, body: object) -> PrefabEventResult:
        """Décoder, limiter, contrôler, appliquer ou consigner. `ValueError` (400), `PrefabEventsRateLimited` (429)."""

        self._take_token()
        request = PrefabEventRequest.from_body(body)
        try:
            manifest = await self._catalog.manifest(request.prefab_id, request.version)
        except PrefabStoreError as exc:
            return self._record(request, None, PrefabEventOutcome.REFUSED, exc.code.value, exc.message)
        decl = manifest.events.get(request.event)
        if decl is None:
            return self._record(request, None, PrefabEventOutcome.REFUSED, "undeclared_event",
                                f"event {request.event} is not declared by {request.prefab_key}")
        if decl.event_class is EventClass.NOTIFY:
            return await self._notify(request, manifest)
        return await self._state(request, manifest)

    async def _notify(self, request: PrefabEventRequest, manifest: PrefabManifest) -> PrefabEventResult:
        decl = manifest.events[request.event]
        _, mismatch = _object_mismatch(await self._scene.snapshot(), request)
        if mismatch:
            return self._record(request, decl.event_class, PrefabEventOutcome.REFUSED, "object_mismatch", mismatch)
        if _bounded_payload(request.payload) is None:
            return self._record(request, decl.event_class, PrefabEventOutcome.REFUSED, "invalid_payload",
                                f"payload must be JSON of at most {MAX_EVENT_PAYLOAD_BYTES} bytes")
        _, problems = validate_value(decl.payload, request.payload, "payload")
        if problems:
            return self._record(request, decl.event_class, PrefabEventOutcome.REFUSED, "invalid_payload",
                                "; ".join(problems[:3]))
        return self._record(request, decl.event_class, PrefabEventOutcome.RECORDED)

    async def _state(self, request: PrefabEventRequest, manifest: PrefabManifest) -> PrefabEventResult:
        verdict: list[PrefabEventResult] = []

        def plan(snapshot: SceneSnapshot) -> SceneCommand | None:
            # Sous le verrou de la scène (R9.1) : la `basis` est comparée à
            # l'état qui sera réellement écrit.
            target, mismatch = _object_mismatch(snapshot, request)
            if target is None:
                verdict.append(PrefabEventResult(PrefabEventOutcome.REFUSED, "object_mismatch", mismatch))
                return None
            block = target.payload.prefab
            assert block is not None
            check = check_state_event(manifest, request.event, request.payload, request.basis, block.data)
            if check.outcome is StateEventOutcome.STALE:
                verdict.append(PrefabEventResult(PrefabEventOutcome.STALE, "stale", check.detail, snapshot.revision))
                return None
            if check.outcome is StateEventOutcome.REFUSED:
                verdict.append(PrefabEventResult(PrefabEventOutcome.REFUSED, "invalid_event", check.detail))
                return None
            assert check.merged is not None
            payload = replace(target.payload, prefab=replace(block, data=dict(check.merged)))
            return SceneCommand(op=SceneOp.PATCH_OBJECT, actor=SceneActor.USER, object_id=target.object_id,
                                fields=SceneObjectFields(payload=payload))

        try:
            update = await self._scene.apply_if(plan)
        except ValueError as exc:
            # Charge fusionnée hors bornes de la scène (16 Kio) : refus, pas une panne.
            return self._record(request, EventClass.STATE, PrefabEventOutcome.REFUSED, "invalid_event", str(exc))
        if update is None:
            result = verdict[0]
            return self._record(request, EventClass.STATE, result.outcome, result.reason, result.detail,
                                revision=result.revision)
        if update.outcome in (SceneCommandOutcome.APPLIED, SceneCommandOutcome.DUPLICATE):
            return self._record(request, EventClass.STATE, PrefabEventOutcome.APPLIED,
                                revision=update.snapshot.revision)
        reason = update.reason.value if update.reason is not None else update.outcome.value
        return self._record(request, EventClass.STATE, PrefabEventOutcome.REFUSED, reason, update.detail)

    # ------------------------------------------------------------ anneau

    def _record(self, request: PrefabEventRequest, event_class: EventClass | None, outcome: PrefabEventOutcome,
                reason: str | None = None, detail: str = "", *, revision: int | None = None) -> PrefabEventResult:
        self._seq += 1
        entry = PrefabEventEntry(self._seq, self._now(), request.object_id, request.prefab_key, request.event,
                                 event_class, _bounded_payload(request.payload), outcome, reason)
        self._ring.append(entry)
        keys = sorted(str(key)[:40] for key in request.payload)[:8] if isinstance(request.payload, dict) else []
        self._emit(EVENT_KIND, f"événement de prefab {request.event} : {outcome.value}",
                   level="info" if outcome in (PrefabEventOutcome.APPLIED, PrefabEventOutcome.RECORDED) else "warning",
                   data={"seq": entry.seq, "object_id": request.object_id, "prefab": request.prefab_key,
                         "event": request.event, "class": event_class.value if event_class else None,
                         "outcome": outcome.value, "payload_keys": keys,
                         **({"reason": reason} if reason else {}), **({"detail": clip_message(detail)} if detail else {})})
        return PrefabEventResult(outcome, reason, clip_message(detail) if detail else "", revision)

    def entries(self, *, after: int | None = None, object_id: str | None = None,
                limit: int = MAX_LIST_LIMIT) -> tuple[PrefabEventEntry, ...]:
        """Entrées de l'anneau, plus anciennes d'abord : après `after`, sinon les `limit` dernières."""

        limit = max(1, min(int(limit), MAX_LIST_LIMIT))
        rows = [entry for entry in self._ring if (after is None or entry.seq > after)
                and (object_id is None or entry.object_id == object_id)]
        return tuple(rows[:limit] if after is not None else rows[-limit:])

    @property
    def last_seq(self) -> int:
        return self._seq

    def take_undelivered_notify(self, limit: int = MAX_NOTIFY_DELIVERY) -> tuple[PrefabEventEntry, ...]:
        """`notify` consignés et pas encore remis, plus anciens d'abord (≤ `limit`) ; marqués remis (une seule fois)."""

        taken: list[PrefabEventEntry] = []
        for entry in self._ring:
            if len(taken) >= max(0, min(limit, MAX_NOTIFY_DELIVERY)):
                break
            if entry.event_class is EventClass.NOTIFY and entry.outcome is PrefabEventOutcome.RECORDED \
                    and not entry.delivered:
                entry.delivered = True
                taken.append(entry)
        return tuple(taken)

    # ------------------------------------------------------------ débit

    def _take_token(self) -> None:
        now = self._clock()
        self._tokens = min(self._rate, self._tokens + (now - self._last) * self._rate)
        self._last = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            if self._limited:
                self._emit(RATE_LIMITED_KIND, "fin de rafale d'événements de prefab", level="info",
                           data={"dropped": self._limited})
                self._limited = 0
            return
        self._limited += 1
        if self._limited == 1:
            self._emit(RATE_LIMITED_KIND, f"événements de prefab au-delà de {self._rate:g}/s : refusés (429)",
                       level="warning", data={"rate_per_s": self._rate})
        raise PrefabEventsRateLimited(f"more than {self._rate:g} prefab events per second")

    def _emit(self, kind: str, message: str, *, level: str, data: Mapping[str, Any]) -> None:
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001 - silence argumentée : un journal indisponible ne casse pas un clic
            pass
