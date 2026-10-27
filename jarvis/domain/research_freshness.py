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
      - https://help.openai.com/... | checked: 2026-10-20 | status: failed
    ---

`decide` est la seule décision, pure et déterministe : elle ne lit ni disque ni horloge (la date du jour est un
argument). Pas de durée de vie universelle : l'âge toléré **depuis la dernière vérification** dépend de la
volatilité du sujet ou de la source (`MAX_AGE_DAYS`), et une demande d'actualité (`RECENCY_TRIGGERS`) le réduit
à `RECENCY_MAX_AGE_DAYS`, pour les seuls documents dont le sujet correspond au tour (`matches_topic`).
La date de publication d'une source informe (`old_sources`), elle ne déclenche jamais de rafraîchissement : sinon
un document juste revérifié resterait « périmé » pour toujours (reprise QA B2).
Contrat : `docs/subagent-roles.md` › *11. Recherche : existant d'abord*.
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
#: Documents lus au plus par tour (le surplus est compté et dit au cerveau).
MAX_RESEARCH_DOCS = 8
#: Première lecture, qui suffit à un en-tête ordinaire ; un en-tête plus long est relu jusqu'à
#: `MAX_FRONT_MATTER_BYTES` (borne propre à l'en-tête, reprise QA B1 : 24 sources et plus dépassent 2 Kio).
MAX_RESEARCH_HEAD_BYTES = 2_048
MAX_FRONT_MATTER_BYTES = 16_384
MAX_TOPIC_CHARS = 120
MAX_SOURCE_REF_CHARS = 160
MAX_SOURCES = 64
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

# ------------------------------------------------------------- demande d'actualité

#: Déclencheurs explicites d'une demande d'actualité (forme repliée -> forme dite). Comparés sans accents ni
#: casse, en mots entiers. Écartés délibérément (reprise QA M3) : « maintenant » / « now » seuls (« maintenant,
#: fais la slide 3 »), une année seule (« les chiffres de 2025 »), « nouveau ».
RECENCY_TRIGGERS: dict[str, str] = {
    "dernier": "dernier", "derniere": "dernière", "derniers": "derniers", "dernieres": "dernières",
    "actuel": "actuel", "actuelle": "actuelle", "actuels": "actuels", "actuelles": "actuelles",
    "actuellement": "actuellement", "aujourd'hui": "aujourd'hui", "aujourd hui": "aujourd'hui",
    "en ce moment": "en ce moment", "a ce jour": "à ce jour", "a jour": "à jour",
    "recent": "récent", "recente": "récente", "recents": "récents", "recentes": "récentes",
    "cette annee": "cette année", "cette semaine": "cette semaine",
    "latest": "latest", "current": "current", "currently": "currently", "today": "today", "newest": "newest",
    "up to date": "up to date", "up-to-date": "up-to-date",
}
#: « dernier·e·s » suivi (à deux mots près) d'un de ces noms parle du projet lui-même, pas de l'actualité :
#: « la dernière diapo », « mes derniers messages ». `version` n'est écartée que suivie du deck ou du document.
RECENCY_EXCLUDED_NOUNS = frozenset({
    "diapo", "diapos", "diapositive", "diapositives", "slide", "slides", "page", "pages", "partie", "parties",
    "etape", "etapes", "section", "sections", "phrase", "phrases", "ligne", "lignes", "point", "points",
    "question", "questions", "chapitre", "chapitres", "image", "images", "scene", "scenes", "paragraphe",
    "paragraphes", "titre", "titres", "message", "messages", "modification", "modifications", "fois", "demande",
    "demandes", "reponse", "reponses", "minute", "minutes", "seconde", "secondes", "transition", "transitions",
    "animation", "animations", "graphique", "graphiques", "puce", "puces",
})
_DECK_VERSION_FOLLOWERS = ("du deck", "de la presentation", "de ma presentation", "de notre presentation",
                           "de la diapo", "du document", "du plan", "de mon", "de ma", "de notre", "de nos")
_DERNIER = frozenset({"dernier", "derniere", "derniers", "dernieres"})
_RECENCY_PATTERN = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(term) for term in sorted(
    RECENCY_TRIGGERS, key=len, reverse=True)) + r")(?![a-z0-9])")


def _fold(text: str) -> str:
    """Minuscules sans accents, apostrophes typographiques ramenées à `'`."""

    text = unicodedata.normalize("NFKD", text.replace("’", "'").lower())
    return "".join(char for char in text if not unicodedata.combining(char))


def _about_the_deck(folded: str, end: int) -> bool:
    """« dernier·e·s » qui désigne un élément du projet (« la dernière diapo »), pas l'état du monde."""

    after = folded[end:].lstrip()
    words = re.findall(r"[a-z0-9']+", after)[:2]
    if any(word in RECENCY_EXCLUDED_NOUNS for word in words):
        return True
    if words and words[0] in ("version", "versions"):
        rest = after[len(words[0]):].lstrip()
        return rest.startswith(_DECK_VERSION_FOLLOWERS)
    return False


def recency_terms(request: str | None, today: date | None = None) -> tuple[str, ...]:
    """Les déclencheurs d'actualité de `request` (forme dite), dans l'ordre, sans doublon. `today` : inutilisé
    (l'année seule ne déclenche plus rien), gardé pour les appelants."""

    folded = _fold(str(request or ""))
    found = []
    for match in _RECENCY_PATTERN.finditer(folded):
        term = match.group(1)
        if term in _DERNIER and _about_the_deck(folded, match.end()):
            continue
        found.append(RECENCY_TRIGGERS[term])
    return tuple(dict.fromkeys(found))


#: Mots trop généraux pour rapprocher une demande d'un document (`matches_topic`).
_TOPIC_STOPWORDS = frozenset({
    "pour", "dans", "avec", "sans", "sont", "quels", "quelles", "quel", "quelle", "cette", "comment", "combien",
    "faire", "fais", "peux", "pouvez", "rappelle", "rappelle-moi", "donne", "donne-moi", "dire", "entre", "plus",
    "tous", "toutes", "tout", "leur", "leurs", "depuis", "apres", "avant", "sujet", "slide", "slides", "diapo",
    "diapos", "presentation", "document", "note", "notes", "recherche", "recherches", "point", "aussi", "encore",
    "votre", "notre", "nous", "vous", "elle", "elles", "mais", "donc", "alors", "chez", "selon", "what", "which",
    "with", "from", "about", "the", "les", "des", "une", "est", "qui", "que", "quoi", "modifie", "change",
    "mets", "ajoute", "besoin", "veux", "voudrais", "avez", "avons", "faut", "the", "this", "that",
})


def _topic_stems(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", _fold(text))
    stems = set()
    for word in words:
        if len(word) < 4 or word in _TOPIC_STOPWORDS or word in RECENCY_TRIGGERS:
            continue
        stems.add(word.rstrip("s")[:6])
    return stems


def matches_topic(request: str | None, *texts: str) -> bool:
    """La demande parle-t-elle du sujet d'un document (`topic`, `scope`, nom de fichier) ? Recouvrement d'au moins
    un mot significatif (4 lettres et plus, mots vides écartés, racine de 6 lettres). Sans mot : non."""

    asked = _topic_stems(str(request or ""))
    if not asked:
        return False
    known: set[str] = set()
    for text in texts:
        known |= _topic_stems(re.sub(r"[-_/.]", " ", str(text or "")))
    return bool(asked & known)


# ------------------------------------------------------------- front-matter

def parse_volatility(value: object) -> Volatility | None:
    return _VOLATILITY_ALIASES.get(_fold(_unquote(value)).strip())


def _unquote(value: object) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1].strip()
    return text


def parse_day(value: object) -> date | None:
    """`AAAA-MM-JJ` (ou un horodatage ISO, dont seule la date compte), guillemets YAML acceptés ; `None` sinon."""

    text = _unquote(value).lstrip("'\"")
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


#: Une vérification ratée (page refusée, vide, illisible) : `status: failed` ou ces mots dans `checked` (m4).
_FAILED_STATUS = frozenset({"failed", "echec", "error", "erreur", "ko", "unreadable", "illisible"})
_FAILED_WORDS = re.compile(r"echec|failed|erreur|error|non lue?|illisible|vide|empty|(?<!\d)[45]\d\d(?!\d)")


@dataclass(frozen=True, slots=True)
class ResearchSource:
    """Une source citée : référence (lien ou chemin), date de la source, date de sa vérification, volatilité.

    `failed` : la dernière vérification a échoué ; la source ne compte pas comme vérifiée.
    """

    ref: str
    date: date | None = None
    checked_at: date | None = None
    volatility: Volatility | None = None
    failed: bool = False


@dataclass(frozen=True, slots=True)
class ResearchMetadata:
    topic: str = ""
    scope: str = ""
    checked_at: date | None = None
    volatility: Volatility | None = None
    uncertainty: str = ""
    sources: tuple[ResearchSource, ...] = ()


#: Codes d'un front-matter absent, mal fermé, ou plus long que `MAX_FRONT_MATTER_BYTES`.
NO_FRONT_MATTER = "no_front_matter"
UNTERMINATED_FRONT_MATTER = "unterminated_front_matter"
FRONT_MATTER_TOO_LONG = "front_matter_too_long"


def parse_front_matter(text: str, *, complete: bool = True) -> tuple[ResearchMetadata | None, str | None]:
    """Le front-matter d'un document de recherche, ou `(None, code)`. Ne lève jamais.

    Sous-ensemble délibérément simple : lignes `clé: valeur` (guillemets acceptés), et sous `sources:` une ligne
    `- <réf>` par source, suivie de champs `| date: …`, `| checked: …`, `| volatility: …`, `| status: failed`.
    `complete` faux (le texte est une tête coupée) et pas de `---` de fermeture : ce qui a été lu est rendu, avec
    `front_matter_too_long` (signalé, jamais confondu avec « sans date »).
    """

    lines = str(text or "").lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return None, NO_FRONT_MATTER
    fields: dict[str, str] = {}
    sources: list[ResearchSource] = []
    in_sources = False

    def meta() -> ResearchMetadata:
        return ResearchMetadata(
            topic=" ".join(_unquote(fields.get("topic", "")).split())[:MAX_TOPIC_CHARS],
            scope=" ".join(_unquote(fields.get("scope", "")).split())[:MAX_TOPIC_CHARS],
            checked_at=parse_day(fields.get("checked_at")),
            volatility=parse_volatility(fields.get("volatility")),
            uncertainty=" ".join(_unquote(fields.get("uncertainty", "")).split())[:MAX_TOPIC_CHARS],
            sources=tuple(sources[:MAX_SOURCES]),
        )

    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            return meta(), None
        if in_sources and stripped.startswith("-"):
            sources.append(_parse_source(stripped[1:]))
            continue
        key, sep, value = stripped.partition(":")
        if not sep or line[:1] in (" ", "\t") and in_sources:
            continue
        key = key.strip().lower()
        in_sources = key == "sources"
        if not in_sources:
            fields[key] = value.strip()
    if not complete:
        return meta(), FRONT_MATTER_TOO_LONG
    return None, UNTERMINATED_FRONT_MATTER


def _parse_source(text: str) -> ResearchSource:
    ref, *parts = (part.strip() for part in text.split("|"))
    found: dict[str, str] = {}
    for part in parts:
        key, sep, value = part.partition(":")
        if sep:
            found[key.strip().lower()] = value.strip()
    checked_text = found.get("checked") or found.get("checked_at") or ""
    status = _fold(_unquote(found.get("status", ""))).strip()
    failed = status in _FAILED_STATUS or bool(_FAILED_WORDS.search(_fold(checked_text)))
    return ResearchSource(ref=_unquote(ref)[:MAX_SOURCE_REF_CHARS], date=parse_day(found.get("date")),
                          checked_at=parse_day(checked_text), volatility=parse_volatility(found.get("volatility")),
                          failed=failed)


# ------------------------------------------------------------- décision

@dataclass(frozen=True, slots=True)
class FreshnessDecision:
    """`action`, sa raison stable, les sources à revérifier, les sources déjà anciennes à leur lecture
    (information seulement) et les déclencheurs d'actualité **appliqués** à ce document."""

    action: FreshnessAction
    reason: str
    stale_sources: tuple[str, ...] = ()
    recency: tuple[str, ...] = ()
    age_days: int | None = None
    old_sources: tuple[str, ...] = ()


def _max_age(volatility: Volatility, recency: bool) -> int:
    return min(MAX_AGE_DAYS[volatility], RECENCY_MAX_AGE_DAYS) if recency else MAX_AGE_DAYS[volatility]


def _stale(source: ResearchSource, meta: ResearchMetadata, today: date, recency: bool) -> bool:
    """Périmée = vérification ratée, ou dernière vérification (de la source, sinon du document) trop ancienne."""

    if source.failed:
        return True
    checked = source.checked_at or meta.checked_at
    volatility = source.volatility or meta.volatility or DEFAULT_VOLATILITY
    return checked is None or (today - checked).days > _max_age(volatility, recency)


def _old_when_read(source: ResearchSource, meta: ResearchMetadata) -> bool:
    """Source volatile déjà ancienne quand on l'a lue : à signaler, jamais un motif de rafraîchissement."""

    volatility = source.volatility or meta.volatility or DEFAULT_VOLATILITY
    checked = source.checked_at or meta.checked_at
    return (volatility is Volatility.HIGH and source.date is not None and checked is not None
            and (checked - source.date).days > MAX_AGE_DAYS[Volatility.HIGH])


def decide(meta: ResearchMetadata | None, *, today: date, request: str | None = "",
           exists: bool = True, on_topic: bool = True) -> FreshnessDecision:
    """Réutiliser, rafraîchir en partie, tout revérifier, ou chercher à neuf. Déterministe ; ne lève jamais.

    Règles, dans cet ordre : pas de document → `new_research` ; pas de date de vérification lisible →
    `full_refresh` (`freshness_unknown`) ; date future → `full_refresh` ; demande d'actualité **sur ce sujet**
    (`on_topic`) et document vérifié il y a plus de `RECENCY_MAX_AGE_DAYS` jours → `full_refresh`
    (`recency_requested`) ; sinon chaque source est jugée sur sa dernière vérification, à l'âge toléré de sa
    volatilité (réduit par une demande d'actualité sur ce sujet), une vérification ratée comptant comme absente :
    aucune périmée → `reuse`, toutes → `full_refresh`, certaines → `partial_refresh` avec leurs références. Sans
    source citée, le document entier est jugé à la volatilité du sujet.
    """

    terms = recency_terms(request) if on_topic else ()
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
    old = tuple(source.ref for source in meta.sources if _old_when_read(source, meta))
    stale = [source for source in sources if _stale(source, meta, today, bool(terms))]
    if not stale:
        return FreshnessDecision(FreshnessAction.REUSE, REASON_FRESH, recency=terms, age_days=age, old_sources=old)
    if len(stale) == len(sources):
        return FreshnessDecision(FreshnessAction.FULL_REFRESH, REASON_STALE, recency=terms, age_days=age,
                                 old_sources=old)
    return FreshnessDecision(FreshnessAction.PARTIAL_REFRESH, REASON_PARTIALLY_STALE,
                             stale_sources=tuple(source.ref for source in stale), recency=terms, age_days=age,
                             old_sources=old)


# ------------------------------------------------------------- statut d'un document, transporté dans le bloc `board`

@dataclass(frozen=True, slots=True)
class ResearchDocStatus:
    """Un document de `documents/research/` et la décision pour la demande du tour (bloc `board`, édition Presentation).

    `on_topic` : la demande du tour parle de son sujet (seuls ceux-là prennent la demande d'actualité) ;
    `problem` : `front_matter_too_long` quand l'en-tête dépasse sa borne (décision prise sur ce qui a été lu).
    """

    path: str
    action: FreshnessAction
    reason: str
    topic: str = ""
    checked_at: date | None = None
    volatility: Volatility | None = None
    stale_sources: tuple[str, ...] = ()
    stale_count: int = 0
    on_topic: bool = False
    problem: str | None = None
    old_count: int = 0

    def __post_init__(self) -> None:
        if not is_research_path(self.path):
            raise ValueError(f"research path must sit under {RESEARCH_DIR}/ and end in .md")
        if not isinstance(self.action, FreshnessAction) or self.reason not in REASONS:
            raise ValueError("unknown freshness action or reason")
        if len(self.topic) > MAX_TOPIC_CHARS or len(self.stale_sources) > MAX_STALE_LISTED:
            raise ValueError("research status exceeds its bounds")
        if self.problem not in (None, FRONT_MATTER_TOO_LONG):
            raise ValueError("unknown research document problem")

    @classmethod
    def from_decision(cls, path: str, meta: ResearchMetadata | None, decision: FreshnessDecision, *,
                      on_topic: bool = False, problem: str | None = None) -> ResearchDocStatus:
        stale = tuple(ref[:MAX_SOURCE_REF_CHARS] for ref in decision.stale_sources if ref)
        return cls(path=path, action=decision.action, reason=decision.reason,
                   topic=meta.topic if meta else "", checked_at=meta.checked_at if meta else None,
                   volatility=meta.volatility if meta else None, stale_sources=stale[:MAX_STALE_LISTED],
                   stale_count=len(stale), on_topic=on_topic,
                   problem=problem if problem == FRONT_MATTER_TOO_LONG else None,
                   old_count=len(decision.old_sources))

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
        if self.on_topic:
            payload["on_topic"] = True
        if self.problem:
            payload["problem"] = self.problem
        if self.old_count:
            payload["old_count"] = self.old_count
        return payload

    @classmethod
    def from_payload(cls, payload: object) -> ResearchDocStatus | None:
        """Décodage strict (Control Center) : `None` pour une entrée hors contrat, jamais une exception."""

        if not isinstance(payload, dict):
            return None
        try:
            stale = payload.get("stale_sources") or []
            count = payload.get("stale_count") or 0
            old = payload.get("old_count") or 0
            if (not isinstance(stale, list) or not all(isinstance(ref, str) for ref in stale)
                    or type(count) is not int or type(old) is not int):
                return None
            topic = payload.get("topic") or ""
            problem = payload.get("problem")
            if not isinstance(topic, str) or problem not in (None, FRONT_MATTER_TOO_LONG):
                return None
            return cls(path=str(payload.get("path") or ""), action=FreshnessAction(payload.get("action")),
                       reason=str(payload.get("reason") or ""), topic=" ".join(topic.split()),
                       checked_at=parse_day(payload.get("checked_at")),
                       volatility=parse_volatility(payload.get("volatility")),
                       stale_sources=tuple(" ".join(ref.split())[:MAX_SOURCE_REF_CHARS] for ref in stale),
                       stale_count=max(count, len(stale)), on_topic=payload.get("on_topic") is True,
                       problem=problem, old_count=max(old, 0))
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
