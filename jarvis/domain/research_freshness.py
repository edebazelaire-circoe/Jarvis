"""Fraîcheur d'un document de recherche : le réutiliser, le rafraîchir en partie ou le refaire.

V1.2 Slice 03 (jarvis-presentation-edition-v1-2). Un document de recherche durable vit dans la mémoire du Board,
sous `documents/research/` (`RESEARCH_DIR`, convention normalisée par la Slice 04), et commence par un
front-matter lisible et analysable :

    ---
    topic: Modèles d'OpenAI disponibles
    scope: modèles de l'API, prix exclus
    checked_at: 2026-10-20
    volatility: high
    uncertainty: dates de retrait non confirmées
    sources:
      - https://platform.openai.com/docs/models | date: 2026-10-15 | checked: 2026-10-20
      - https://openai.com/index/... | date: 2026-09-30 | volatility: medium
    ---

`decide` est la seule décision, pure et déterministe : elle ne lit ni disque ni horloge (la date du jour est un
argument). Pas de durée de vie universelle : l'âge toléré dépend de la volatilité du sujet ou de la source
(`MAX_AGE_DAYS`), et une demande d'actualité (« dernier », « actuel », « aujourd'hui », l'année en cours…)
réduit cet âge à `RECENCY_MAX_AGE_DAYS`. Contrat : `docs/subagent-roles.md` › *Recherche : existant d'abord*.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
import re
from typing import Any
import unicodedata

#: Dossier des documents de recherche, relatif à `memory/` du Board (Slice 04 : convention normalisée).
RESEARCH_DIR = "documents/research"
#: Documents lus au plus par tour, et octets lus en tête de chacun (le front-matter seul sert).
MAX_RESEARCH_DOCS = 8
MAX_RESEARCH_HEAD_BYTES = 2_048
MAX_TOPIC_CHARS = 120
MAX_SOURCE_REF_CHARS = 160
MAX_SOURCES = 24
#: Sources périmées citées dans une décision (le reste est compté).
MAX_STALE_LISTED = 3


class Volatility(StrEnum):
    """Vitesse à laquelle le sujet change : semaines (`high`), mois (`medium`), années (`low`)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


#: Mots français acceptés dans le front-matter, ramenés au vocabulaire canonique.
_VOLATILITY_ALIASES = {
    "low": Volatility.LOW, "faible": Volatility.LOW, "basse": Volatility.LOW,
    "medium": Volatility.MEDIUM, "moyenne": Volatility.MEDIUM, "moyen": Volatility.MEDIUM,
    "high": Volatility.HIGH, "forte": Volatility.HIGH, "fort": Volatility.HIGH, "haute": Volatility.HIGH,
    "elevee": Volatility.HIGH,
}
#: Âge toléré d'une vérification, par volatilité. Un sujet sans volatilité déclarée est `medium`.
MAX_AGE_DAYS = {Volatility.LOW: 730, Volatility.MEDIUM: 180, Volatility.HIGH: 30}
DEFAULT_VOLATILITY = Volatility.MEDIUM
#: Âge toléré quand la demande réclame l'état actuel, quelle que soit la volatilité.
RECENCY_MAX_AGE_DAYS = 7


class FreshnessAction(StrEnum):
    REUSE = "reuse"
    PARTIAL_REFRESH = "partial_refresh"
    FULL_REFRESH = "full_refresh"
    NEW_RESEARCH = "new_research"


#: Codes stables de la raison d'une décision.
REASON_FRESH = "fresh"
REASON_PARTIALLY_STALE = "partially_stale"
REASON_STALE = "stale"
REASON_RECENCY = "recency_requested"
REASON_UNKNOWN = "freshness_unknown"
REASON_FUTURE = "checked_at_in_future"
REASON_NO_DOCUMENT = "no_document"
REASONS = frozenset({REASON_FRESH, REASON_PARTIALLY_STALE, REASON_STALE, REASON_RECENCY, REASON_UNKNOWN,
                     REASON_FUTURE, REASON_NO_DOCUMENT})

#: Mots d'une demande d'actualité, comparés sans accents ni casse, en mots entiers.
_RECENCY_TERMS = (
    "dernier", "derniere", "derniers", "dernieres", "actuel", "actuelle", "actuels", "actuelles", "actuellement",
    "aujourd'hui", "aujourd hui", "en ce moment", "maintenant", "recent", "recente", "recents", "recentes",
    "a jour", "a ce jour", "cette annee", "ce mois", "cette semaine",
    "latest", "current", "currently", "today", "now", "newest", "up to date", "up-to-date", "this year",
)
_RECENCY_PATTERN = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(term) for term in _RECENCY_TERMS)
                              + r")(?![a-z0-9])")


def _fold(text: str) -> str:
    """Minuscules sans accents, apostrophes typographiques ramenées à `'`."""

    text = unicodedata.normalize("NFKD", text.replace("’", "'").lower())
    return "".join(char for char in text if not unicodedata.combining(char))


def recency_terms(request: str | None, today: date) -> tuple[str, ...]:
    """Les mots de `request` qui réclament l'état actuel (l'année en cours compte), dans l'ordre, sans doublon."""

    folded = _fold(str(request or ""))
    found = [match.group(1) for match in _RECENCY_PATTERN.finditer(folded)]
    if re.search(rf"(?<!\d){today.year}(?!\d)", folded):
        found.append(str(today.year))
    return tuple(dict.fromkeys(found))


def parse_volatility(value: object) -> Volatility | None:
    return _VOLATILITY_ALIASES.get(_fold(str(value or "")).strip())


def parse_day(value: object) -> date | None:
    """`AAAA-MM-JJ` (ou un horodatage ISO, dont seule la date compte) ; `None` sinon."""

    text = str(value or "").strip()
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class ResearchSource:
    """Une source citée : référence (lien ou chemin), date de la source, date de sa vérification, volatilité."""

    ref: str
    date: date | None = None
    checked_at: date | None = None
    volatility: Volatility | None = None


@dataclass(frozen=True, slots=True)
class ResearchMetadata:
    topic: str = ""
    scope: str = ""
    checked_at: date | None = None
    volatility: Volatility | None = None
    uncertainty: str = ""
    sources: tuple[ResearchSource, ...] = ()


#: Codes d'un front-matter absent ou mal fermé : le document existe mais sa fraîcheur est inconnue.
NO_FRONT_MATTER = "no_front_matter"
UNTERMINATED_FRONT_MATTER = "unterminated_front_matter"


def parse_front_matter(text: str) -> tuple[ResearchMetadata | None, str | None]:
    """Le front-matter d'un document de recherche, ou `(None, code)`. Ne lève jamais.

    Sous-ensemble délibérément simple : lignes `clé: valeur`, et sous `sources:` une ligne `- <réf>` par source,
    suivie de champs `| date: …`, `| checked: …`, `| volatility: …`. Une clé inconnue est ignorée ; une date
    illisible vaut absente (la décision dit alors `freshness_unknown`).
    """

    lines = str(text or "").lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return None, NO_FRONT_MATTER
    fields: dict[str, str] = {}
    sources: list[ResearchSource] = []
    in_sources = False
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            return ResearchMetadata(
                topic=" ".join(fields.get("topic", "").split())[:MAX_TOPIC_CHARS],
                scope=" ".join(fields.get("scope", "").split())[:MAX_TOPIC_CHARS],
                checked_at=parse_day(fields.get("checked_at")),
                volatility=parse_volatility(fields.get("volatility")),
                uncertainty=" ".join(fields.get("uncertainty", "").split())[:MAX_TOPIC_CHARS],
                sources=tuple(sources[:MAX_SOURCES]),
            ), None
        if in_sources and stripped.startswith("-"):
            sources.append(_parse_source(stripped[1:]))
            continue
        key, sep, value = stripped.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        in_sources = key == "sources"
        if not in_sources:
            fields[key] = value.strip()
    return None, UNTERMINATED_FRONT_MATTER


def _parse_source(text: str) -> ResearchSource:
    ref, *parts = (part.strip() for part in text.split("|"))
    found: dict[str, str] = {}
    for part in parts:
        key, sep, value = part.partition(":")
        if sep:
            found[key.strip().lower()] = value.strip()
    return ResearchSource(ref=ref[:MAX_SOURCE_REF_CHARS], date=parse_day(found.get("date")),
                          checked_at=parse_day(found.get("checked") or found.get("checked_at")),
                          volatility=parse_volatility(found.get("volatility")))


@dataclass(frozen=True, slots=True)
class FreshnessDecision:
    """`action`, sa raison stable, les sources à revérifier (références) et les mots d'actualité de la demande."""

    action: FreshnessAction
    reason: str
    stale_sources: tuple[str, ...] = ()
    recency: tuple[str, ...] = ()
    age_days: int | None = None


def _stale(source: ResearchSource, meta: ResearchMetadata, today: date, recency: bool) -> bool:
    volatility = source.volatility or meta.volatility or DEFAULT_VOLATILITY
    max_age = min(MAX_AGE_DAYS[volatility], RECENCY_MAX_AGE_DAYS) if recency else MAX_AGE_DAYS[volatility]
    checked = source.checked_at or meta.checked_at
    if checked is None or (today - checked).days > max_age:
        return True
    # Une source volatile déjà ancienne quand on l'a lue ne rend pas un état récent.
    return volatility is Volatility.HIGH and source.date is not None and (checked - source.date).days > max_age


def decide(meta: ResearchMetadata | None, *, today: date, request: str | None = "",
           exists: bool = True) -> FreshnessDecision:
    """Réutiliser, rafraîchir en partie, tout revérifier, ou chercher à neuf. Déterministe ; ne lève jamais.

    Règles, dans cet ordre : pas de document → `new_research` ; pas de date de vérification lisible →
    `full_refresh` (`freshness_unknown`) ; date future → `full_refresh` ; demande d'actualité et document vérifié
    il y a plus de `RECENCY_MAX_AGE_DAYS` jours → `full_refresh` (`recency_requested`) ; sinon chaque source est
    jugée à l'âge toléré de sa volatilité (réduit par une demande d'actualité) : aucune périmée → `reuse`, toutes
    → `full_refresh`, certaines → `partial_refresh` avec leurs références. Sans source citée, le document entier
    est jugé à la volatilité du sujet.
    """

    terms = recency_terms(request, today)
    if not exists:
        return FreshnessDecision(FreshnessAction.NEW_RESEARCH, REASON_NO_DOCUMENT, recency=terms)
    if meta is None or meta.checked_at is None:
        return FreshnessDecision(FreshnessAction.FULL_REFRESH, REASON_UNKNOWN, recency=terms)
    age = (today - meta.checked_at).days
    if age < -1:
        return FreshnessDecision(FreshnessAction.FULL_REFRESH, REASON_FUTURE, recency=terms, age_days=age)
    if terms and age > RECENCY_MAX_AGE_DAYS:
        return FreshnessDecision(FreshnessAction.FULL_REFRESH, REASON_RECENCY, recency=terms, age_days=age)
    sources = meta.sources or (ResearchSource(ref=""),)
    stale = [source for source in sources if _stale(source, meta, today, bool(terms))]
    if not stale:
        return FreshnessDecision(FreshnessAction.REUSE, REASON_FRESH, recency=terms, age_days=age)
    if len(stale) == len(sources):
        return FreshnessDecision(FreshnessAction.FULL_REFRESH, REASON_STALE, recency=terms, age_days=age)
    return FreshnessDecision(FreshnessAction.PARTIAL_REFRESH, REASON_PARTIALLY_STALE,
                             stale_sources=tuple(source.ref for source in stale), recency=terms, age_days=age)


# ------------------------------------------------------------- statut d'un document, transporté dans le bloc `board`

@dataclass(frozen=True, slots=True)
class ResearchDocStatus:
    """Un document de `documents/research/` et la décision pour la demande du tour (bloc `board`, édition Presentation)."""

    path: str
    action: FreshnessAction
    reason: str
    topic: str = ""
    checked_at: date | None = None
    volatility: Volatility | None = None
    stale_sources: tuple[str, ...] = ()
    stale_count: int = 0

    def __post_init__(self) -> None:
        if not is_research_path(self.path):
            raise ValueError(f"research path must sit under {RESEARCH_DIR}/ and end in .md")
        if not isinstance(self.action, FreshnessAction) or self.reason not in REASONS:
            raise ValueError("unknown freshness action or reason")
        if len(self.topic) > MAX_TOPIC_CHARS or len(self.stale_sources) > MAX_STALE_LISTED:
            raise ValueError("research status exceeds its bounds")

    @classmethod
    def from_decision(cls, path: str, meta: ResearchMetadata | None, decision: FreshnessDecision) -> ResearchDocStatus:
        stale = tuple(ref[:MAX_SOURCE_REF_CHARS] for ref in decision.stale_sources if ref)
        return cls(path=path, action=decision.action, reason=decision.reason,
                   topic=meta.topic if meta else "", checked_at=meta.checked_at if meta else None,
                   volatility=meta.volatility if meta else None, stale_sources=stale[:MAX_STALE_LISTED],
                   stale_count=len(stale))

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"path": self.path, "action": self.action.value, "reason": self.reason}
        if self.topic:
            payload["topic"] = self.topic
        if self.checked_at is not None:
            payload["checked_at"] = self.checked_at.isoformat()
        if self.volatility is not None:
            payload["volatility"] = self.volatility.value
        if self.stale_count:
            payload["stale_sources"] = list(self.stale_sources)
            payload["stale_count"] = self.stale_count
        return payload

    @classmethod
    def from_payload(cls, payload: object) -> ResearchDocStatus | None:
        """Décodage strict (Control Center) : `None` pour une entrée hors contrat, jamais une exception."""

        if not isinstance(payload, dict):
            return None
        try:
            stale = payload.get("stale_sources") or []
            count = payload.get("stale_count") or 0
            if not isinstance(stale, list) or not all(isinstance(ref, str) for ref in stale) or type(count) is not int:
                return None
            topic = payload.get("topic") or ""
            if not isinstance(topic, str):
                return None
            return cls(path=str(payload.get("path") or ""), action=FreshnessAction(payload.get("action")),
                       reason=str(payload.get("reason") or ""), topic=" ".join(topic.split()),
                       checked_at=parse_day(payload.get("checked_at")),
                       volatility=parse_volatility(payload.get("volatility")),
                       stale_sources=tuple(" ".join(ref.split())[:MAX_SOURCE_REF_CHARS] for ref in stale),
                       stale_count=max(count, len(stale)))
        except ValueError:
            return None


def is_research_path(value: object) -> bool:
    """Chemin relatif à `memory/`, sous `RESEARCH_DIR/`, en `.md`, sans `..` ni séparateur Windows."""

    if not isinstance(value, str) or len(value) > 240 or not value.startswith(RESEARCH_DIR + "/"):
        return False
    return (value.lower().endswith(".md") and "\\" not in value and ".." not in value.split("/")
            and not any(char in value for char in "\r\n\0"))


def today_local(now: datetime | None = None) -> date:
    """La date du jour (heure locale du poste) : seul point où l'horloge entre, côté appelant."""

    return (now or datetime.now()).date()
