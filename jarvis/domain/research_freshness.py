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
#: casse, en mots entiers. Écartés délibérément : « maintenant » / « now » seuls (« maintenant, fais la slide 3 »),
#: une année seule (« les chiffres de 2025 »), « nouveau » (reprise QA M3) ; « à jour » (« mets à jour la slide »,
#: « le deck est-il à jour ? » : un verbe ou un état d'édition, seconde reprise F2).
RECENCY_TRIGGERS: dict[str, str] = {
    "dernier": "dernier", "derniere": "dernière", "derniers": "derniers", "dernieres": "dernières",
    "actuel": "actuel", "actuelle": "actuelle", "actuels": "actuels", "actuelles": "actuelles",
    "actuellement": "actuellement", "aujourd'hui": "aujourd'hui", "aujourd hui": "aujourd'hui",
    "en ce moment": "en ce moment", "a ce jour": "à ce jour",
    "recent": "récent", "recente": "récente", "recents": "récents", "recentes": "récentes",
    "cette annee": "cette année", "cette semaine": "cette semaine",
    "latest": "latest", "current": "current", "currently": "currently", "today": "today", "newest": "newest",
    "up to date": "up to date", "up-to-date": "up-to-date",
}
#: « dernier·e·s » ou « current » suivi (à deux mots près) d'un de ces noms parle du projet ou de la conversation,
#: pas de l'état du monde : « la dernière diapo », « dernière chose », « le dernier mot », « current slide ».
#: `version` n'est écartée que suivie du deck ou du document.
RECENCY_EXCLUDED_NOUNS = frozenset({
    "diapo", "diapos", "diapositive", "diapositives", "slide", "slides", "page", "pages", "partie", "parties",
    "etape", "etapes", "section", "sections", "phrase", "phrases", "ligne", "lignes", "point", "points",
    "question", "questions", "chapitre", "chapitres", "image", "images", "scene", "scenes", "paragraphe",
    "paragraphes", "titre", "titres", "message", "messages", "modification", "modifications", "fois", "demande",
    "demandes", "reponse", "reponses", "minute", "minutes", "seconde", "secondes", "transition", "transitions",
    "animation", "animations", "graphique", "graphiques", "puce", "puces", "chose", "choses", "mot", "mots",
    "deck", "plan", "document", "fichier", "tour", "remarque", "detail", "details",
    "slide", "page", "step", "item", "deck", "file", "line", "question", "thing",
})
_DECK_VERSION_FOLLOWERS = ("du deck", "de la presentation", "de ma presentation", "de notre presentation",
                           "de la diapo", "du document", "du plan", "de mon", "de ma", "de notre", "de nos")
#: Marque d'ordre d'octets en tête d'un fichier : écrite par son code, jamais en littéral invisible.
_BOM = chr(0xFEFF)
#: Déclencheurs qui peuvent désigner un élément du projet (« la dernière diapo », « current slide », « en dernier »).
_ORDINAL_TRIGGERS = frozenset({"dernier", "derniere", "derniers", "dernieres", "current"})
_RECENCY_PATTERN = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(term) for term in sorted(
    RECENCY_TRIGGERS, key=len, reverse=True)) + r")(?![a-z0-9])")


def _fold(text: str) -> str:
    """Minuscules sans accents, apostrophes typographiques ramenées à `'`."""

    text = unicodedata.normalize("NFKD", text.replace(chr(0x2019), "'").lower())
    return "".join(char for char in text if not unicodedata.combining(char))


def _about_the_deck(folded: str, start: int, end: int) -> bool:
    """« dernier·e·s » / « current » qui désigne un élément du projet ou de la conversation, pas l'état du monde."""

    if re.search(r"(?<![a-z])en\s+$", folded[:start]):
        return True  # « en dernier, ajoute une image »
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
        if term in _ORDINAL_TRIGGERS and _about_the_deck(folded, match.start(), match.end()):
            continue
        found.append(RECENCY_TRIGGERS[term])
    return tuple(dict.fromkeys(found))


#: Mots vides et mots génériques qui ne suffisent jamais à rapprocher une demande d'un document
#: (`matches_topic`) : grammaire, consignes d'édition, et vocabulaire commun à toute recherche de présentation
#: (« prix », « outils », « comparaison »… : seconde reprise F2, « le prix actuel de Synthesia » touchait Gamma).
TOPIC_STOPWORDS = frozenset({
    # grammaire et consignes
    "pour", "dans", "avec", "sans", "sont", "quels", "quelles", "quel", "quelle", "cette", "comment", "combien",
    "faire", "fais", "peux", "pouvez", "rappelle", "donne", "dire", "entre", "plus", "moins", "tous", "toutes",
    "tout", "leur", "leurs", "depuis", "apres", "avant", "aussi", "encore", "votre", "notre", "nous", "vous", "elle",
    "elles", "mais", "donc", "alors", "chez", "selon", "quoi", "modifie", "modifier", "change", "changer", "mets",
    "mettre", "mise", "ajoute", "ajouter", "besoin", "veux", "voudrais", "avez", "avons", "faut", "parle", "parler",
    "explique", "montre", "cherche", "chercher", "trouve", "resume", "resumer", "jour", "rien", "juste", "bien",
    "what", "which", "with", "from", "about", "this", "that", "they", "have", "does", "show", "tell", "find",
    "les", "des", "une", "est", "qui", "que", "sur", "par", "aux", "son", "ses", "mon", "mes", "nos", "vos", "the",
    "and", "for", "are", "how", "moi", "toi", "lui", "ces", "pas", "ont", "dit", "fai", "mis", "via",
    # vocabulaire générique d'une recherche de présentation
    "prix", "tarif", "tarifs", "cout", "couts", "outil", "outils", "comparaison", "comparatif", "comparer",
    "presentation", "presentations", "slide", "slides", "diapo", "diapos", "diapositive", "diapositives", "deck",
    "document", "documents", "note", "notes", "recherche", "recherches", "sujet", "sujets", "point", "points",
    "offre", "offres", "formule", "formules", "fonctionnalite", "fonctionnalites", "etat", "version", "versions",
    "nouveaute", "nouveautes", "tendance", "tendances", "actualite", "actualites", "information", "informations",
    "donnee", "donnees", "chiffre", "chiffres", "synthese", "analyse", "liste", "exemple", "exemples", "solution",
    "solutions", "produit", "produits", "service", "services", "plateforme", "plateformes", "logiciel",
    "logiciels", "application", "applications", "abonnement", "abonnements", "marche", "option", "options",
    "price", "prices", "pricing", "tool", "tools", "comparison", "compare", "feature", "features", "plan", "plans",
})
#: Mots courts (2-3 lettres) gardés comme sujet, rapprochés par mot entier : « IA », « LLM », « GPT », « VAE ».
_SHORT_TOPIC = re.compile(r"[a-z0-9]{2,3}\Z")
#: Mots-outils courts, jamais un sujet (« de », « la », « j'ai »…).
_SHORT_STOPWORDS = frozenset({
    "de", "la", "le", "du", "en", "et", "ou", "un", "au", "il", "on", "je", "tu", "ce", "se", "sa", "ne", "ni",
    "si", "ai", "as", "va", "vu", "ca", "me", "te", "qu", "of", "to", "in", "is", "it", "an", "at", "by", "or",
    "be", "we", "my", "us", "do", "no", "so", "up", "if", "elle", "ils", "mai", "oui", "non", "car", "ici", "est",
    "les", "des", "une", "qui", "que", "sur", "par", "aux", "son", "ses", "mon", "mes", "nos", "vos", "the",
    "and", "for", "are", "how", "moi", "toi", "lui", "ces", "pas", "ont", "dit", "mis", "via", "peu", "bon",
})


def _topic_tokens(text: str) -> set[str]:
    """Racines significatives : mots de 4 lettres et plus (racine de 6 lettres, pluriel ôté) ; mots de 2-3 lettres
    gardés entiers (`=ia`) ; nombres seuls, mots vides et génériques (`TOPIC_STOPWORDS`), déclencheurs écartés."""

    tokens = set()
    for word in re.findall(r"[a-z0-9]+", _fold(text)):
        if word.isdigit() or word in TOPIC_STOPWORDS or word in RECENCY_TRIGGERS:
            continue
        if len(word) >= 4:
            stem = word.rstrip("s")
            if stem not in TOPIC_STOPWORDS:
                tokens.add(stem[:6])
        elif _SHORT_TOPIC.fullmatch(word) and word not in _SHORT_STOPWORDS:
            tokens.add("=" + word)
    return tokens


def matches_topic(request: str | None, *texts: str) -> bool:
    """La demande parle-t-elle du sujet d'un document (`topic`, `scope`, nom de fichier) ? Recouvrement d'au moins
    un mot significatif (`_topic_tokens`). Sans mot significatif dans la demande : non."""

    asked = _topic_tokens(str(request or ""))
    if not asked:
        return False
    known: set[str] = set()
    for text in texts:
        known |= _topic_tokens(re.sub(r"[-_/.]", " ", str(text or "")))
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


#: Une vérification ratée (page refusée, vide, illisible) : `status: failed` ou ces mots, entiers, dans `checked`
#: (m4). Un code HTTP n'est reconnu que s'il est isolé : jamais les millisecondes d'un horodatage (`12.450Z`).
_FAILED_STATUS = frozenset({"failed", "echec", "error", "erreur", "ko", "unreadable", "illisible"})
_FAILED_WORDS = re.compile(r"(?<![a-z])(echec|failed|erreur|error|non lue?|illisible|vide|empty|refusee?|blocked|"
                           r"bloquee?|forbidden|timeout)(?![a-z])|(?<![\w.:+-])[45]\d\d(?![\w.:])")


@dataclass(frozen=True, slots=True)
class ResearchSource:
    """Une source citée : référence (lien ou chemin), date de la source, date de sa dernière lecture réussie,
    volatilité, et sa dernière tentative ratée (`failed`, `tried_at`).

    Une source en échec n'est pas « vérifiée » ; elle n'est réessayée qu'après l'âge toléré de sa volatilité
    depuis `tried_at` (seconde reprise F1) : un refus durable (403) ne relance pas un rafraîchissement à chaque tour.
    """

    ref: str
    date: date | None = None
    checked_at: date | None = None
    volatility: Volatility | None = None
    failed: bool = False
    tried_at: date | None = None


@dataclass(frozen=True, slots=True)
class ResearchMetadata:
    topic: str = ""
    scope: str = ""
    checked_at: date | None = None
    volatility: Volatility | None = None
    uncertainty: str = ""
    sources: tuple[ResearchSource, ...] = ()


#: Codes d'un front-matter absent, jamais fermé (le fichier s'arrête avant), ou plus long que
#: `MAX_FRONT_MATTER_BYTES` (on ne sait pas s'il se ferme). Les deux derniers sont signalés et jugés de la même
#: façon prudente (`decide_for`) : métadonnées lues gardées pour l'affichage, fraîcheur inconnue.
NO_FRONT_MATTER = "no_front_matter"
UNTERMINATED_FRONT_MATTER = "unterminated_front_matter"
FRONT_MATTER_TOO_LONG = "front_matter_too_long"
HEADER_PROBLEMS = frozenset({UNTERMINATED_FRONT_MATTER, FRONT_MATTER_TOO_LONG})
_BLOCK_SCALARS = frozenset({">", "|", ">-", "|-", ">+", "|+"})


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def parse_front_matter(text: str, *, complete: bool = True) -> tuple[ResearchMetadata | None, str | None]:
    """Le front-matter d'un document de recherche et un code de problème (ou `None`). Ne lève jamais.

    Sous-ensemble délibérément simple de YAML : lignes `clé: valeur` (guillemets acceptés, blocs `>` / `|` lus
    sur leurs lignes indentées) ; sous `sources:`, une source par `- `, sur une ligne (`- <réf> | date: … |
    checked: … | tried: … | status: failed`) ou en bloc imbriqué (`- url: …` suivi de `date:`, `checked:`,
    `tried:`, `status:`, `volatility:` indentés). Pas de `---` de fermeture : ce qui a été lu est rendu, avec
    `unterminated_front_matter` (le texte est complet) ou `front_matter_too_long` (`complete` faux : tête coupée).
    """

    lines = str(text or "").lstrip(_BOM).splitlines()
    if not lines or lines[0].strip() != "---":
        return None, NO_FRONT_MATTER
    fields: dict[str, str] = {}
    sources: list[dict[str, str]] = []
    in_sources = False
    block_key: str | None = None
    item_indent = 0

    def meta() -> ResearchMetadata:
        return ResearchMetadata(
            topic=" ".join(_unquote(fields.get("topic", "")).split())[:MAX_TOPIC_CHARS],
            scope=" ".join(_unquote(fields.get("scope", "")).split())[:MAX_TOPIC_CHARS],
            checked_at=parse_day(fields.get("checked_at")),
            volatility=parse_volatility(fields.get("volatility")),
            uncertainty=" ".join(_unquote(fields.get("uncertainty", "")).split())[:MAX_TOPIC_CHARS],
            sources=tuple(_source(item) for item in sources[:MAX_SOURCES]),
        )

    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            return meta(), None
        if not stripped:
            continue
        if block_key is not None:
            if _indent(line) > 0:
                fields[block_key] = f"{fields.get(block_key, '')} {stripped}".strip()
                continue
            block_key = None
        if in_sources and stripped.startswith("-"):
            sources.append(_source_fields(stripped[1:]))
            item_indent = _indent(line)
            continue
        if in_sources and sources and _indent(line) > item_indent:
            key, sep, value = stripped.partition(":")
            if sep:
                sources[-1].setdefault(key.strip().lower(), value.strip())
            continue
        key, sep, value = stripped.partition(":")
        if not sep or _indent(line) > 0:
            continue
        key = key.strip().lower()
        in_sources = key == "sources"
        if not in_sources:
            if value.strip() in _BLOCK_SCALARS:
                block_key, fields[key] = key, ""
            else:
                fields[key] = value.strip()
    return meta(), (UNTERMINATED_FRONT_MATTER if complete else FRONT_MATTER_TOO_LONG)


def _source_fields(text: str) -> dict[str, str]:
    """Champs d'une source : `<réf> | clé: valeur | …` sur une ligne, ou `url: …` qui ouvre un bloc imbriqué."""

    first, *parts = (part.strip() for part in text.split("|"))
    found: dict[str, str] = {}
    key, sep, value = first.partition(":")
    if sep and key.strip().lower() in ("url", "ref", "source", "lien", "link", "path", "chemin") and value.strip():
        found["ref"] = value.strip()
    else:
        found["ref"] = first
    for part in parts:
        key, sep, value = part.partition(":")
        if sep:
            found[key.strip().lower()] = value.strip()
    return found


def _source(found: dict[str, str]) -> ResearchSource:
    checked_text = found.get("checked") or found.get("checked_at") or ""
    status = _fold(_unquote(found.get("status", ""))).strip()
    failed_in_checked = bool(_FAILED_WORDS.search(_fold(checked_text)))
    failed = status in _FAILED_STATUS or failed_in_checked
    checked = parse_day(checked_text)
    tried = parse_day(found.get("tried") or found.get("tried_at"))
    if failed and tried is None:
        # Ancienne forme : la date de `checked` est celle de la tentative ratée, pas d'une lecture réussie.
        tried, checked = checked, None
    return ResearchSource(ref=_unquote(found.get("ref", ""))[:MAX_SOURCE_REF_CHARS], date=parse_day(found.get("date")),
                          checked_at=checked, volatility=parse_volatility(found.get("volatility")),
                          failed=failed, tried_at=tried)


# ------------------------------------------------------------- décision

@dataclass(frozen=True, slots=True)
class FreshnessDecision:
    """`action`, sa raison stable, les sources à revérifier, les sources déjà anciennes à leur lecture et les
    sources non vérifiables pour l'instant (information seulement), et les déclencheurs d'actualité **appliqués**."""

    action: FreshnessAction
    reason: str
    stale_sources: tuple[str, ...] = ()
    recency: tuple[str, ...] = ()
    age_days: int | None = None
    old_sources: tuple[str, ...] = ()
    unverifiable_sources: tuple[str, ...] = ()


def _max_age(volatility: Volatility, recency: bool) -> int:
    return min(MAX_AGE_DAYS[volatility], RECENCY_MAX_AGE_DAYS) if recency else MAX_AGE_DAYS[volatility]


def _source_state(source: ResearchSource, meta: ResearchMetadata, today: date, recency: bool) -> str:
    """`fresh`, `stale` ou `unverifiable`.

    Lecture réussie : jugée sur sa date (`checked`, sinon `checked_at` du document). Tentative ratée : la source
    est `unverifiable` tant que la tentative a moins que l'âge toléré de sa volatilité (on ne la réessaie pas à
    chaque tour), puis `stale` (on la réessaie) ; une lecture réussie plus récente que la tentative l'emporte.
    """

    volatility = source.volatility or meta.volatility or DEFAULT_VOLATILITY
    max_age = _max_age(volatility, recency)
    if source.failed and not (source.checked_at and source.tried_at and source.checked_at > source.tried_at):
        tried = source.tried_at or meta.checked_at
        return "unverifiable" if tried is not None and (today - tried).days <= max_age else "stale"
    checked = source.checked_at or meta.checked_at
    return "stale" if checked is None or (today - checked).days > max_age else "fresh"


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
    (`recency_requested`) ; sinon chaque source est jugée (`_source_state`), à l'âge toléré de sa volatilité
    (réduit par une demande d'actualité sur ce sujet) : aucune périmée → `reuse` (les non vérifiables pour
    l'instant sont seulement signalées), toutes → `full_refresh`, certaines → `partial_refresh` avec leurs
    références. Sans source citée, le document entier est jugé à la volatilité du sujet.
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
    states = [(source, _source_state(source, meta, today, bool(terms))) for source in sources]
    stale = [source for source, state in states if state == "stale"]
    unverifiable = tuple(source.ref for source, state in states if state == "unverifiable")
    common = {"recency": terms, "age_days": age, "old_sources": old, "unverifiable_sources": unverifiable}
    if not stale:
        return FreshnessDecision(FreshnessAction.REUSE, REASON_FRESH, **common)
    if len(stale) == len(sources):
        return FreshnessDecision(FreshnessAction.FULL_REFRESH, REASON_STALE, **common)
    return FreshnessDecision(FreshnessAction.PARTIAL_REFRESH, REASON_PARTIALLY_STALE,
                             stale_sources=tuple(source.ref for source in stale), **common)


def decide_for(meta: ResearchMetadata | None, problem: str | None, *, today: date, request: str | None = "",
               on_topic: bool = True) -> FreshnessDecision:
    """`decide`, sauf pour un en-tête jamais fermé ou trop long (`HEADER_PROBLEMS`) : décision prudente
    identique quelle que soit la taille du fichier, `full_refresh` / `freshness_unknown` (on ne sait pas quelles
    sources manquent). Les métadonnées lues restent affichées, et le problème est signalé."""

    if problem in HEADER_PROBLEMS:
        terms = recency_terms(request) if on_topic else ()
        return FreshnessDecision(FreshnessAction.FULL_REFRESH, REASON_UNKNOWN, recency=terms)
    return decide(meta, today=today, request=request, on_topic=on_topic)


# ------------------------------------------------------------- statut d'un document, transporté dans le bloc `board`

@dataclass(frozen=True, slots=True)
class ResearchDocStatus:
    """Un document de `documents/research/` et la décision pour la demande du tour (bloc `board`, édition Presentation).

    `on_topic` : la demande du tour parle de son sujet (seuls ceux-là prennent la demande d'actualité) ;
    `problem` : un en-tête jamais fermé ou trop long (`HEADER_PROBLEMS`, décision prudente de `decide_for`) ;
    `unverifiable_*` : sources dont la dernière tentative a échoué et qu'on ne réessaie pas encore (seconde
    reprise F1) ; `old_count` : sources déjà anciennes à leur lecture. Les deux sont des informations.
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
    unverifiable_sources: tuple[str, ...] = ()
    unverifiable_count: int = 0

    def __post_init__(self) -> None:
        if not is_research_path(self.path):
            raise ValueError(f"research path must sit under {RESEARCH_DIR}/ and end in .md")
        if not isinstance(self.action, FreshnessAction) or self.reason not in REASONS:
            raise ValueError("unknown freshness action or reason")
        if (len(self.topic) > MAX_TOPIC_CHARS or len(self.stale_sources) > MAX_STALE_LISTED
                or len(self.unverifiable_sources) > MAX_STALE_LISTED):
            raise ValueError("research status exceeds its bounds")
        if self.problem is not None and self.problem not in HEADER_PROBLEMS:
            raise ValueError("unknown research document problem")

    @classmethod
    def from_decision(cls, path: str, meta: ResearchMetadata | None, decision: FreshnessDecision, *,
                      on_topic: bool = False, problem: str | None = None) -> ResearchDocStatus:
        stale = tuple(ref[:MAX_SOURCE_REF_CHARS] for ref in decision.stale_sources if ref)
        unverifiable = tuple(ref[:MAX_SOURCE_REF_CHARS] for ref in decision.unverifiable_sources if ref)
        return cls(path=path, action=decision.action, reason=decision.reason,
                   topic=meta.topic if meta else "", checked_at=meta.checked_at if meta else None,
                   volatility=meta.volatility if meta else None, stale_sources=stale[:MAX_STALE_LISTED],
                   stale_count=len(stale), on_topic=on_topic,
                   problem=problem if problem in HEADER_PROBLEMS else None,
                   old_count=len(decision.old_sources), unverifiable_sources=unverifiable[:MAX_STALE_LISTED],
                   unverifiable_count=len(unverifiable))

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
        if self.unverifiable_count:
            payload["unverifiable_sources"] = list(self.unverifiable_sources)
            payload["unverifiable_count"] = self.unverifiable_count
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
            unverifiable = payload.get("unverifiable_sources") or []
            unverifiable_count = payload.get("unverifiable_count") or 0
            if (not isinstance(stale, list) or not all(isinstance(ref, str) for ref in stale)
                    or not isinstance(unverifiable, list) or not all(isinstance(ref, str) for ref in unverifiable)
                    or type(count) is not int or type(old) is not int or type(unverifiable_count) is not int):
                return None
            topic = payload.get("topic") or ""
            problem = payload.get("problem")
            if not isinstance(topic, str) or (problem is not None and problem not in HEADER_PROBLEMS):
                return None
            return cls(path=str(payload.get("path") or ""), action=FreshnessAction(payload.get("action")),
                       reason=str(payload.get("reason") or ""), topic=" ".join(topic.split()),
                       checked_at=parse_day(payload.get("checked_at")),
                       volatility=parse_volatility(payload.get("volatility")),
                       stale_sources=tuple(" ".join(ref.split())[:MAX_SOURCE_REF_CHARS] for ref in stale),
                       stale_count=max(count, len(stale)), on_topic=payload.get("on_topic") is True,
                       problem=problem, old_count=max(old, 0),
                       unverifiable_sources=tuple(" ".join(ref.split())[:MAX_SOURCE_REF_CHARS]
                                                  for ref in unverifiable),
                       unverifiable_count=max(unverifiable_count, len(unverifiable)))
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
