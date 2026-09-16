"""Contrats de l'état de travail détaillé, possédé par Core (handoff work-state, tâche 10).

Les sous-tâches d'un agent (Claude Code), les jobs Core et, demain, d'autres
fournisseurs décrivent tous du travail en cours. Ce module en donne une forme
**neutre** et **bornée**, que le cerveau et l'UI liront à la même source
(Décisions D15 à D17) :

- `WorkObservation` : ce qu'un observateur de bord constate à un instant ;
- `WorkItem` : l'état normalisé d'un travail, tel que Core le retient ;
- `WorkSnapshot` : l'ensemble borné des éléments, avec une révision globale ;
- `WorkLink` : le rattachement explicite au `work_id` du cerveau et au tour
  (`correlation_id`) qui l'a demandé.

Invariants transverses :

- identité fournisseur ≠ identité cerveau. Un élément est identifié par
  `(source, external_id)` ; son `work_id` n'est connu que si l'émetteur l'a
  donné explicitement. Il n'est jamais déduit d'un libellé ni égalé à
  l'identifiant externe ;
- aucun JSON brut de fournisseur : seuls les champs déclarés ici traversent
  le fil, et `from_payload` ignore tout le reste ;
- toutes les chaînes et collections sont bornées ; la validation refuse ce
  qui dépasse, `clip_text` sert aux observateurs pour tronquer avant ;
- un état terminal est définitif : aucune observation ne le rouvre.

Les règles d'application (`apply_observation`) sont des fonctions pures : le
futur `WorkStateStore` (tâche 11) se contente de les appliquer et d'avancer
sa révision. Aucun raisonnement caché n'est représentable ici (Décision 12).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
import math
from typing import Any

from jarvis.domain._checks import MAX_ID_CHARS
from jarvis.domain._checks import check_id as _check_id
from jarvis.domain._checks import check_text as _check_text
from jarvis.domain._checks import check_token as _check_token

# Bornes des champs publics. Choisies pour contenir ce que `AgentTaskTracker`
# conserve déjà (libellé 160, résumé 1 000) sans laisser passer une trace.
MAX_SOURCE_CHARS = 32
MAX_KIND_CHARS = 64
# `MAX_ID_CHARS` (128) vient de `jarvis.domain._checks`, partagé avec la scène.
MAX_LABEL_CHARS = 160
MAX_ACTIVITY_CHARS = 160
MAX_SUMMARY_CHARS = 1_000
MAX_MODEL_CHARS = 80
MAX_ERROR_CLASS_CHARS = 64
#: Éléments d'un instantané. Le magasin élague d'abord les éléments terminés
#: les plus anciens ; au-delà, l'instantané est refusé plutôt que tronqué.
MAX_WORK_ITEMS = 64
#: Observations d'un lot sur le fil d'ingestion (tâche 11) ; un lot vide est
#: refusé.
MAX_OBSERVATION_BATCH = 64

_ELLIPSIS = "…"


class WorkStatus(StrEnum):
    """Statut normalisé d'un travail.

    `BLOCKED` : le travail attend une décision ou une donnée de l'utilisateur.
    Les trois fins anormales se distinguent : `FAILED` (le travail a échoué),
    `CANCELLED` (arrêt demandé), `INTERRUPTED` (son hôte a disparu : processus
    arrêté, Core redémarré).
    """

    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_WORK_STATUSES


TERMINAL_WORK_STATUSES = frozenset(
    {WorkStatus.COMPLETED, WorkStatus.FAILED, WorkStatus.CANCELLED, WorkStatus.INTERRUPTED}
)
#: Seuls statuts pouvant porter une `error_class` : une réussite n'a pas
#: d'erreur, et un travail en cours n'a pas encore d'issue.
ERROR_WORK_STATUSES = frozenset({WorkStatus.FAILED, WorkStatus.CANCELLED, WorkStatus.INTERRUPTED})

#: Transitions permises depuis un statut non terminal. Rester dans le même
#: statut est permis (l'activité change). Revenir à `PENDING` ne l'est pas :
#: un travail commencé ne redevient pas « pas encore commencé ». Un statut
#: terminal n'a aucune transition sortante.
ALLOWED_WORK_TRANSITIONS: dict[WorkStatus, frozenset[WorkStatus]] = {
    WorkStatus.PENDING: frozenset({WorkStatus.PENDING, WorkStatus.RUNNING, WorkStatus.BLOCKED, *TERMINAL_WORK_STATUSES}),
    WorkStatus.RUNNING: frozenset({WorkStatus.RUNNING, WorkStatus.BLOCKED, *TERMINAL_WORK_STATUSES}),
    WorkStatus.BLOCKED: frozenset({WorkStatus.BLOCKED, WorkStatus.RUNNING, *TERMINAL_WORK_STATUSES}),
    **{status: frozenset() for status in TERMINAL_WORK_STATUSES},
}


def can_transition(current: WorkStatus, target: WorkStatus) -> bool:
    """Vrai si un élément au statut `current` peut passer à `target`."""

    return target in ALLOWED_WORK_TRANSITIONS[current]


def clip_text(value: str, limit: int, *, single_line: bool = True) -> str:
    """Tronquer un texte public à `limit` caractères, marque de coupure comprise.

    Destiné aux observateurs de bord, avant construction d'une observation :
    les types de ce module refusent un texte trop long au lieu de le couper
    en silence. `single_line` ramène sauts de ligne et caractères de contrôle
    à des espaces simples, forme exigée par les champs d'une ligne (libellé,
    activité, modèle).
    """

    if limit < 1:
        raise ValueError("limit must be positive")
    text = value
    if single_line:
        text = " ".join("".join(ch if ch.isprintable() else " " for ch in text).split())
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - len(_ELLIPSIS)].rstrip() + _ELLIPSIS


# ------------------------------------------------------------------ validation
# Texte, jeton et identifiant : `jarvis.domain._checks` (importés en tête).


def _check_datetime(name: str, value: object, *, required: bool = True) -> None:
    if value is None and not required:
        return
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _check_count(name: str, value: object) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be positive or zero")


def _check_fraction(value: object) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("progress_fraction must be a number")
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("progress_fraction must be between 0 and 1")


def _check_public_fields(value: WorkObservation | WorkItem) -> None:
    """Validation commune aux champs publics d'une observation et d'un élément."""

    _check_token("source", value.source, MAX_SOURCE_CHARS, required=True)
    _check_id("external_id", value.external_id, required=True)
    if not isinstance(value.status, WorkStatus):
        raise TypeError("status must be a WorkStatus")
    _check_token("kind", value.kind, MAX_KIND_CHARS, required=False)
    _check_text("label", value.label, MAX_LABEL_CHARS)
    _check_text("activity", value.activity, MAX_ACTIVITY_CHARS)
    _check_text("summary", value.summary, MAX_SUMMARY_CHARS, single_line=False)
    _check_text("model", value.model, MAX_MODEL_CHARS)
    _check_id("parent_external_id", value.parent_external_id, required=False)
    if value.parent_external_id == value.external_id:
        raise ValueError("a work item cannot be its own parent")
    if not isinstance(value.link, WorkLink):
        raise TypeError("link must be a WorkLink")
    _check_fraction(value.progress_fraction)
    if value.error_class is not None:
        _check_token("error_class", value.error_class, MAX_ERROR_CLASS_CHARS, required=True)
        if value.status not in ERROR_WORK_STATUSES:
            raise ValueError(f"error_class is only allowed for {sorted(s.value for s in ERROR_WORK_STATUSES)}")
    _check_count("tool_uses", value.tool_uses)
    _check_count("tokens", value.tokens)
    if value.status.is_terminal and value.activity:
        # L'activité décrit un instant du travail en cours : un travail fini
        # ne « fait » plus rien.
        raise ValueError("a terminal work item has no current activity")


# ------------------------------------------------------------------ fil


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_datetime(payload: dict[str, Any], key: str) -> datetime | None:
    raw = payload.get(key)
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise TypeError(f"{key} must be an ISO 8601 string")
    return datetime.fromisoformat(raw)


def _payload_text(payload: dict[str, Any], key: str) -> str:
    raw = payload.get(key)
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise TypeError(f"{key} must be a string")
    return raw


def _payload_optional_id(payload: dict[str, Any], key: str) -> str | None:
    """Chaîne vide et absence valent « inconnu » sur le fil."""

    raw = payload.get(key)
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise TypeError(f"{key} must be a string")
    return raw


def _payload_optional_bool(payload: dict[str, Any], key: str) -> bool | None:
    raw = payload.get(key)
    if raw is None or isinstance(raw, bool):
        return raw
    raise TypeError(f"{key} must be a boolean")


def _public_payload(value: WorkObservation | WorkItem) -> dict[str, Any]:
    return {
        "source": value.source,
        "external_id": value.external_id,
        "status": value.status.value,
        "kind": value.kind,
        "label": value.label,
        "activity": value.activity,
        "summary": value.summary,
        "model": value.model,
        "parent_external_id": value.parent_external_id,
        **value.link.to_payload(),
        "progress_fraction": value.progress_fraction,
        "error_class": value.error_class,
        "tool_uses": value.tool_uses,
        "tokens": value.tokens,
    }


#: Clés d'une observation sur le fil : exactement celles de
#: `WorkObservation.to_payload`. L'ingress Core refuse toute autre clé.
OBSERVATION_WIRE_KEYS = frozenset(
    {
        "source", "external_id", "status", "kind", "label", "activity", "summary", "model",
        "parent_external_id", "work_id", "correlation_id", "progress_fraction", "error_class",
        "tool_uses", "tokens", "background", "observed_at", "started_at",
    }
)
_BATCH_WIRE_KEYS = frozenset({"source", "producer_id", "observations"})


def _reject_unknown_keys(name: str, payload: dict[str, Any], allowed: frozenset[str]) -> None:
    unknown = sorted(str(key)[:40] for key in payload if key not in allowed)
    if unknown:
        raise ValueError(f"{name} has unknown fields: {unknown[:5]}")


def _public_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    """Champs publics communs relus depuis le fil ; tout autre clé est ignorée."""

    if not isinstance(payload, dict):
        raise TypeError("work payload must be a dict")
    return {
        "source": _payload_text(payload, "source"),
        "external_id": _payload_text(payload, "external_id"),
        "status": WorkStatus(payload.get("status")),
        "kind": _payload_text(payload, "kind"),
        "label": _payload_text(payload, "label"),
        "activity": _payload_text(payload, "activity"),
        "summary": _payload_text(payload, "summary"),
        "model": _payload_text(payload, "model"),
        "parent_external_id": _payload_optional_id(payload, "parent_external_id"),
        "link": WorkLink.from_payload(payload),
        "progress_fraction": payload.get("progress_fraction"),
        "error_class": _payload_optional_id(payload, "error_class"),
        "tool_uses": payload.get("tool_uses"),
        "tokens": payload.get("tokens"),
    }


# ------------------------------------------------------------------ types


@dataclass(frozen=True, slots=True)
class WorkLink:
    """Rattachement explicite d'un travail observé au cerveau.

    `work_id` est l'identifiant de travail nommé par le cerveau (celui des
    `brain.work.*`), `correlation_id` celui du tour qui l'a demandé. `None`
    signifie « inconnu », et le reste tant qu'aucun émetteur ne l'a affirmé :
    Core ne déduit jamais un rattachement d'un libellé, et n'égale jamais
    l'identifiant externe du fournisseur à un `work_id`.
    """

    work_id: str | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        _check_id("work_id", self.work_id, required=False)
        _check_id("correlation_id", self.correlation_id, required=False)

    @property
    def known(self) -> bool:
        return self.work_id is not None or self.correlation_id is not None

    def merge(self, incoming: WorkLink) -> tuple[WorkLink, tuple[str, ...]]:
        """Compléter ce rattachement par `incoming`, sans jamais le réécrire.

        Un champ inconnu prend la valeur annoncée ; un champ déjà connu la
        garde. Rend le rattachement fusionné et le nom des champs pour
        lesquels `incoming` contredisait une valeur déjà établie : le premier
        rattachement affirmé fait foi, la contradiction est signalée à
        l'appelant pour diagnostic.
        """

        conflicts: list[str] = []
        merged: dict[str, str | None] = {}
        for name in ("work_id", "correlation_id"):
            known, announced = getattr(self, name), getattr(incoming, name)
            if known is not None and announced is not None and known != announced:
                conflicts.append(name)
            merged[name] = known if known is not None else announced
        return WorkLink(**merged), tuple(conflicts)

    def to_payload(self) -> dict[str, Any]:
        return {"work_id": self.work_id, "correlation_id": self.correlation_id}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> WorkLink:
        return cls(
            work_id=_payload_optional_id(payload, "work_id"),
            correlation_id=_payload_optional_id(payload, "correlation_id"),
        )


@dataclass(frozen=True, slots=True)
class WorkObservation:
    """Constat ponctuel d'un observateur de bord sur un travail.

    Un champ vide (`""`) ou `None` signifie « non observé cette fois » : il
    ne remplace pas une valeur déjà connue. Seule `activity` fait exception,
    parce qu'elle décrit l'instant : vide, elle dit « rien en ce moment ».

    `observed_at` est l'horloge de l'observateur, pas celle de Core : c'est
    elle qui ordonne les observations d'une même source. `started_at` n'est
    renseigné que si le fournisseur connaît le début réel du travail.
    """

    source: str
    external_id: str
    status: WorkStatus
    observed_at: datetime
    kind: str = ""
    label: str = ""
    activity: str = ""
    summary: str = ""
    model: str = ""
    parent_external_id: str | None = None
    link: WorkLink = field(default_factory=WorkLink)
    progress_fraction: float | None = None
    error_class: str | None = None
    tool_uses: int | None = None
    tokens: int | None = None
    background: bool | None = None
    started_at: datetime | None = None

    def __post_init__(self) -> None:
        _check_public_fields(self)
        _check_datetime("observed_at", self.observed_at)
        _check_datetime("started_at", self.started_at, required=False)
        if self.started_at is not None and self.started_at > self.observed_at:
            raise ValueError("started_at cannot be after observed_at")
        if self.background is not None and not isinstance(self.background, bool):
            raise TypeError("background must be a boolean")

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.external_id)

    def to_payload(self) -> dict[str, Any]:
        return {
            **_public_payload(self),
            "background": self.background,
            "observed_at": self.observed_at.isoformat(),
            "started_at": _iso(self.started_at),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> WorkObservation:
        return cls(
            **_public_kwargs(payload),
            observed_at=_parse_datetime(payload, "observed_at"),  # type: ignore[arg-type]
            background=_payload_optional_bool(payload, "background"),
            started_at=_parse_datetime(payload, "started_at"),
        )


@dataclass(frozen=True, slots=True)
class WorkObservationBatch:
    """Lot d'observations d'un même producteur, tel qu'il franchit l'ingress Core.

    `producer_id` désigne une instance de l'observateur (un processus Control
    Center, par exemple). Quand Core voit changer le producteur d'une source,
    les éléments encore actifs de cette source appartenaient à l'instance
    disparue : Core les interrompt (tâche 11).

    Contrairement à `WorkObservation.from_payload`, qui ignore les clés
    inconnues, le lot est strict : c'est la frontière de confiance entre
    processus, et un champ inconnu (trace brute, `prompt`...) y trahit un
    producteur défectueux plutôt qu'une donnée à trier.
    """

    source: str
    producer_id: str
    observations: tuple[WorkObservation, ...]

    def __post_init__(self) -> None:
        _check_token("source", self.source, MAX_SOURCE_CHARS, required=True)
        _check_id("producer_id", self.producer_id, required=True)
        if not isinstance(self.observations, tuple) or not all(
            isinstance(observation, WorkObservation) for observation in self.observations
        ):
            raise TypeError("observations must be a tuple of WorkObservation")
        if not 1 <= len(self.observations) <= MAX_OBSERVATION_BATCH:
            raise ValueError(f"a batch holds between 1 and {MAX_OBSERVATION_BATCH} observations")
        if any(observation.source != self.source for observation in self.observations):
            raise ValueError("every observation of a batch must come from the batch source")

    def to_payload(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "producer_id": self.producer_id,
            "observations": [observation.to_payload() for observation in self.observations],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> WorkObservationBatch:
        if not isinstance(payload, dict):
            raise TypeError("work observation batch must be a dict")
        _reject_unknown_keys("batch", payload, _BATCH_WIRE_KEYS)
        raw = payload.get("observations")
        if not isinstance(raw, list):
            raise TypeError("observations must be a list")
        if len(raw) > MAX_OBSERVATION_BATCH:
            # Refusé avant de décoder, comme `WorkSnapshot.from_payload`.
            raise ValueError(f"a batch holds between 1 and {MAX_OBSERVATION_BATCH} observations")
        observations: list[WorkObservation] = []
        for index, item in enumerate(raw):
            name = f"observations[{index}]"
            if not isinstance(item, dict):
                raise TypeError(f"{name} must be an object")
            _reject_unknown_keys(name, item, OBSERVATION_WIRE_KEYS)
            try:
                observations.append(WorkObservation.from_payload(item))
            except (TypeError, ValueError) as exc:
                raise type(exc)(f"{name}: {exc}") from exc
        return cls(
            source=_payload_text(payload, "source"),
            producer_id=_payload_text(payload, "producer_id"),
            observations=tuple(observations),
        )


@dataclass(frozen=True, slots=True)
class WorkItem:
    """État normalisé d'un travail, tel que Core le retient.

    `revision` est la révision globale de l'état de travail à laquelle cet
    élément a changé pour la dernière fois : elle ne décroît jamais et ne
    dépasse pas celle de l'instantané qui le contient. `ended_at` est posé
    exactement quand le statut est terminal.
    """

    source: str
    external_id: str
    status: WorkStatus
    revision: int
    started_at: datetime
    updated_at: datetime
    kind: str = ""
    label: str = ""
    activity: str = ""
    summary: str = ""
    model: str = ""
    parent_external_id: str | None = None
    link: WorkLink = field(default_factory=WorkLink)
    progress_fraction: float | None = None
    error_class: str | None = None
    tool_uses: int | None = None
    tokens: int | None = None
    background: bool = False
    ended_at: datetime | None = None

    def __post_init__(self) -> None:
        _check_public_fields(self)
        if isinstance(self.revision, bool) or not isinstance(self.revision, int):
            raise TypeError("revision must be an integer")
        if self.revision < 1:
            raise ValueError("a work item revision starts at 1")
        _check_datetime("started_at", self.started_at)
        _check_datetime("updated_at", self.updated_at)
        _check_datetime("ended_at", self.ended_at, required=False)
        if not isinstance(self.background, bool):
            raise TypeError("background must be a boolean")
        if self.updated_at < self.started_at:
            raise ValueError("updated_at cannot be before started_at")
        if self.status.is_terminal != (self.ended_at is not None):
            raise ValueError("ended_at is set exactly when the status is terminal")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at cannot be before started_at")

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.external_id)

    @classmethod
    def from_observation(cls, observation: WorkObservation, *, revision: int) -> WorkItem:
        """Premier état d'un travail, à partir de sa première observation."""

        started_at = observation.started_at or observation.observed_at
        return cls(
            source=observation.source,
            external_id=observation.external_id,
            status=observation.status,
            revision=revision,
            started_at=started_at,
            updated_at=observation.observed_at,
            kind=observation.kind,
            label=observation.label,
            activity=observation.activity,
            summary=observation.summary,
            model=observation.model,
            parent_external_id=observation.parent_external_id,
            link=observation.link,
            progress_fraction=observation.progress_fraction,
            error_class=observation.error_class,
            tool_uses=observation.tool_uses,
            tokens=observation.tokens,
            background=bool(observation.background),
            ended_at=observation.observed_at if observation.status.is_terminal else None,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            **_public_payload(self),
            "background": self.background,
            "revision": self.revision,
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "ended_at": _iso(self.ended_at),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> WorkItem:
        background = _payload_optional_bool(payload, "background")
        return cls(
            **_public_kwargs(payload),
            revision=payload.get("revision"),  # type: ignore[arg-type]
            started_at=_parse_datetime(payload, "started_at"),  # type: ignore[arg-type]
            updated_at=_parse_datetime(payload, "updated_at"),  # type: ignore[arg-type]
            background=bool(background),
            ended_at=_parse_datetime(payload, "ended_at"),
        )


@dataclass(frozen=True, slots=True)
class WorkSnapshot:
    """État de travail complet et borné, à une révision donnée.

    La révision est globale et strictement croissante : chaque élément créé
    ou modifié l'avance d'une unité, une observation sans effet ne la touche
    pas. Un consommateur qui voit un saut de révision sait qu'il a manqué un
    changement et relit l'instantané.
    """

    revision: int
    items: tuple[WorkItem, ...]
    updated_at: datetime

    def __post_init__(self) -> None:
        if isinstance(self.revision, bool) or not isinstance(self.revision, int):
            raise TypeError("revision must be an integer")
        if self.revision < 0:
            raise ValueError("revision must be positive or zero")
        if not isinstance(self.items, tuple) or not all(isinstance(item, WorkItem) for item in self.items):
            raise TypeError("items must be a tuple of WorkItem")
        if len(self.items) > MAX_WORK_ITEMS:
            raise ValueError(f"a work snapshot holds at most {MAX_WORK_ITEMS} items")
        if len({item.key for item in self.items}) != len(self.items):
            raise ValueError("work items must be unique per (source, external_id)")
        if any(item.revision > self.revision for item in self.items):
            raise ValueError("an item cannot be newer than its snapshot")
        _check_datetime("updated_at", self.updated_at)

    def to_payload(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "items": [item.to_payload() for item in self.items],
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> WorkSnapshot:
        if not isinstance(payload, dict):
            raise TypeError("work snapshot payload must be a dict")
        raw_items = payload.get("items", [])
        if not isinstance(raw_items, list):
            raise TypeError("items must be a list")
        if len(raw_items) > MAX_WORK_ITEMS:
            # Refusé avant de décoder : un fil hostile ne fait pas construire
            # un nombre arbitraire d'objets.
            raise ValueError(f"a work snapshot holds at most {MAX_WORK_ITEMS} items")
        return cls(
            revision=payload.get("revision"),  # type: ignore[arg-type]
            items=tuple(WorkItem.from_payload(item) for item in raw_items),
            updated_at=_parse_datetime(payload, "updated_at"),  # type: ignore[arg-type]
        )


# ------------------------------------------------------------------ règles


class ObservationOutcome(StrEnum):
    """Effet d'une observation sur l'état retenu."""

    CREATED = "created"
    UPDATED = "updated"
    #: Rien de neuf : l'état retenu est inchangé, la révision n'avance pas.
    DUPLICATE = "duplicate"
    #: Plus ancienne que l'état retenu, et non terminale : ignorée.
    STALE = "stale"
    #: L'élément est déjà terminé avec un autre statut : un état terminal ne
    #: se rouvre pas, et la première fin constatée fait foi.
    TERMINAL = "terminal"
    #: Transition interdite par `ALLOWED_WORK_TRANSITIONS`.
    INVALID_TRANSITION = "invalid_transition"


@dataclass(frozen=True, slots=True)
class WorkUpdate:
    """Résultat de `apply_observation` : l'état retenu et ce qui s'est passé.

    `conflicts` nomme les champs d'identité (`work_id`, `correlation_id`,
    `parent_external_id`) que l'observation contredisait : la valeur établie
    est gardée, la contradiction est rendue pour diagnostic.
    """

    outcome: ObservationOutcome
    item: WorkItem
    conflicts: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return self.outcome in (ObservationOutcome.CREATED, ObservationOutcome.UPDATED)


def apply_observation(current: WorkItem | None, observation: WorkObservation, *, revision: int) -> WorkUpdate:
    """Appliquer une observation à l'état retenu d'un travail. Fonction pure.

    `revision` est la révision que prendra l'élément s'il change ; elle doit
    dépasser la sienne. Règles, dans l'ordre :

    1. premier constat : l'élément est créé, quel que soit son statut ;
    2. élément terminé : une observation d'un autre statut est refusée
       (`TERMINAL`) ; du même statut, elle ne peut qu'enrichir les champs
       descriptifs (résumé, compteurs...), jamais la date de fin ;
    3. une observation terminale met fin au travail même si elle est plus
       ancienne que le dernier constat : la fin est un fait qui ne se défait
       pas, et un progrès tardif ne doit pas la masquer ;
    4. une observation non terminale plus ancienne que le dernier constat est
       ignorée (`STALE`) : un progrès en retard ne rembobine pas l'état ;
    5. une transition hors `ALLOWED_WORK_TRANSITIONS` est refusée ;
    6. sinon, fusion champ par champ (voir `WorkObservation`) ; si rien ne
       change hormis l'heure du constat, c'est un doublon (`DUPLICATE`).
    """

    if current is None:
        return WorkUpdate(ObservationOutcome.CREATED, WorkItem.from_observation(observation, revision=revision))
    if current.key != observation.key:
        raise ValueError("observation does not describe this work item")
    if revision <= current.revision:
        raise ValueError("revision must increase")

    if current.status.is_terminal:
        if observation.status is not current.status:
            return WorkUpdate(ObservationOutcome.TERMINAL, current)
        if observation.observed_at < current.updated_at:
            return WorkUpdate(ObservationOutcome.STALE, current)
    elif not observation.status.is_terminal:
        if observation.observed_at < current.updated_at:
            return WorkUpdate(ObservationOutcome.STALE, current)
        if not can_transition(current.status, observation.status):
            return WorkUpdate(ObservationOutcome.INVALID_TRANSITION, current)

    merged, conflicts = _merge(current, observation)
    if merged == replace(current, updated_at=merged.updated_at):
        return WorkUpdate(ObservationOutcome.DUPLICATE, current, conflicts)
    return WorkUpdate(ObservationOutcome.UPDATED, replace(merged, revision=revision), conflicts)


def _merge(current: WorkItem, observation: WorkObservation) -> tuple[WorkItem, tuple[str, ...]]:
    """Fusion champ par champ ; la révision est laissée à l'appelant."""

    link, conflicts = current.link.merge(observation.link)
    parent = current.parent_external_id
    if observation.parent_external_id is not None:
        if parent is None:
            parent = observation.parent_external_id
        elif parent != observation.parent_external_id:
            conflicts = (*conflicts, "parent_external_id")

    status = observation.status
    started_at = current.started_at
    if observation.started_at is not None and observation.started_at < started_at:
        started_at = observation.started_at
    ended_at = current.ended_at
    if status.is_terminal and ended_at is None:
        ended_at = max(observation.observed_at, started_at)

    merged = replace(
        current,
        status=status,
        started_at=started_at,
        updated_at=max(current.updated_at, observation.observed_at),
        kind=observation.kind or current.kind,
        label=observation.label or current.label,
        activity="" if status.is_terminal else observation.activity,
        summary=observation.summary or current.summary,
        model=observation.model or current.model,
        parent_external_id=parent,
        link=link,
        progress_fraction=_known(observation.progress_fraction, current.progress_fraction),
        error_class=observation.error_class or (current.error_class if status in ERROR_WORK_STATUSES else None),
        tool_uses=_known(observation.tool_uses, current.tool_uses),
        tokens=_known(observation.tokens, current.tokens),
        background=_known(observation.background, current.background),
        ended_at=ended_at,
    )
    return merged, conflicts


def _known(announced: Any, current: Any) -> Any:
    return current if announced is None else announced
