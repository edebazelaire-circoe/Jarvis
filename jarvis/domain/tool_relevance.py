"""Pertinence d'un outil pour une intention (generic-mcp-plugin-runtime, Slice 04 ; ARCH §7.4, D7).

`list_tools(intent)` de la passerelle `jarvis-tools` classe tous les outils
accessibles (natifs du lancement + outils des plugins activés et connectés)
avec ce module. Contrat : `docs/mcp/plugins.md` §6.4.

- `fold` : NFKD, marques combinantes retirées, casefold (« Réunion » → « reunion ») ;
- `tokens` : découpe sur tout non-alphanumérique **et** aux frontières
  snake/camel/kebab, pliage, mots vides FR/EN retirés, racinisation légère ;
- `SYNONYMS` : petits groupes bilingues ; l'intention est étendue par groupe
  au poids `EXPANSION_WEIGHT`. Un membre de plusieurs mots (`PHRASES`,
  « pièce jointe », « à faire ») étend son groupe seulement quand ses mots se
  suivent dans l'intention ;
- découpe camel : un `s` seul après une suite de capitales reste au sigle
  (« PDFs » → `pdf`, jamais « PD » + « Fs ») ;
- `rank` : BM25F (k1 = 1,2, b = 0,75), poids de champ nom 3,0, libellé 2,0,
  noms de paramètres 1,5, description 1,0, descriptions de paramètres + valeurs
  d'énumération 0,75 ; IDF sur l'ensemble accessible de l'appel.

Racinisation légère : un pluriel (`s`, `x`, `es` après s/x/z/ch/sh), puis un
suffixe dérivationnel (`tion`→`t`, `ment`, `ing`, `ed`), puis un `e` final —
chaque étape seulement s'il reste au moins trois lettres. L'ARCH dit « un
suffixe parmi » ; l'enchaînement pluriel → dérivation → `e` est nécessaire pour
que « événements » et « événement », « messages » et « message » tombent sur la
même racine (écart documenté dans `docs/mcp/plugins.md` §6.4).

Déterministe : aucune horloge, aucun hasard ; départage `(-score, ordre de la
source, id)`. Pur : bibliothèque standard seulement.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import math
import re
import unicodedata

K1 = 1.2
B = 0.75
EXPANSION_WEIGHT = 0.6
FIELD_WEIGHTS: dict[str, float] = {
    "name": 3.0,
    "label": 2.0,
    "param_names": 1.5,
    "description": 1.0,
    "param_texts": 0.75,
}
MIN_STEM_CHARS = 3
#: Racines dont le `e` final distingue deux mots : « file » (fichier) ≠ « fil » (fil de discussion).
_KEEP_FINAL_E = frozenset({"file"})

_STOPWORDS_RAW = (
    # FR
    "a au aux avec ce ces cet cette dans de des du elle en et il ils je la le les leur leurs lui ma me mes moi mon "
    "ne nos notre nous on ou par pas pour qu que qui sa se ses si son sur ta te tes toi ton tu un une vos votre vous "
    "y est sont etre avoir fait faire mais plus tout tous toute toutes quel quelle quels quelles l d j m n s t c "
    "peux peut veux voudrais stp svp merci"
    # EN
    " an and are as at be by for from has have in into is it its of on or that the their them this to was were "
    "will with you your i me my we our please can could would should do does what which who how"
)

# Groupes bilingues (ARCH §7.4) ; les membres passent par la même normalisation que le texte.
_SYNONYM_GROUPS_RAW: tuple[tuple[str, ...], ...] = (
    ("mail", "email", "courriel", "message", "mails", "emails", "inbox"),
    ("envoyer", "send", "envoi"),
    ("agenda", "calendar", "calendrier", "evenement", "event", "meeting", "reunion", "rendez-vous", "rdv"),
    ("contact", "personne", "people", "user", "utilisateur", "adresse", "address"),
    ("fichier", "file", "document", "doc"),
    ("chercher", "search", "find", "trouver", "retrouver", "retrouve", "lookup", "rechercher", "query"),
    ("lire", "read", "get", "fetch", "afficher", "show", "voir"),
    ("creer", "create", "add", "ajouter", "new", "nouveau", "nouvelle"),
    ("supprimer", "delete", "remove", "effacer", "archiver", "archive"),
    ("modifier", "update", "edit", "changer", "change", "set"),
    ("lister", "list", "liste"),
    ("brouillon", "draft"),
    ("ecrire", "write", "rediger", "compose"),
    ("reglage", "setting", "parametre", "option", "config"),
    # QA Slice 04 (jeu de régression) : vocabulaire mail / agenda / tâches / fichiers courant.
    ("reply", "repondre", "reponds", "reponse"),
    ("forward", "transferer", "transfere", "faire suivre"),
    ("phone", "telephone", "numero", "tel", "mobile"),
    ("task", "tache", "todo", "a faire"),
    ("attachment", "piece jointe", "pj"),
    ("folder", "dossier"),
    ("share", "partager", "partage"),
    ("download", "telecharger", "telecharge"),
    ("upload", "televerser", "televerse", "envoyer un fichier"),
    ("schedule", "planifier", "programmer"),
    ("cancel", "annuler", "annule"),
)

_SPLIT = re.compile(r"[^0-9a-z]+")
#: Frontières camel : « sendMail » → send|Mail, « HTTPServer » → HTTP|Server, mais « PDFs », « URLs »,
#: « IDsFor » gardent le `s` de leur sigle (un `s` seul après une suite de capitales n'ouvre pas un mot).
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z](?!s(?![a-z]))[a-z])")


def fold(text: str) -> str:
    """NFKD, marques combinantes retirées, casefold."""

    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _stem(token: str) -> str:
    word = token
    # 1. pluriel
    if len(word) - 2 >= MIN_STEM_CHARS and word.endswith("es") and re.search(r"(s|x|z|ch|sh)es$", word):
        word = word[:-2]
    elif len(word) - 1 >= MIN_STEM_CHARS and word[-1] in "sx" and not word.endswith("ss"):
        word = word[:-1]
    # 2. dérivation
    for suffix, replacement in (("tion", "t"), ("ment", ""), ("ing", ""), ("ed", "")):
        if word.endswith(suffix) and len(word) - len(suffix) + len(replacement) >= MIN_STEM_CHARS:
            word = word[: len(word) - len(suffix)] + replacement
            break
    # 3. `e` final
    if word.endswith("e") and len(word) - 1 >= MIN_STEM_CHARS and word not in _KEEP_FINAL_E:
        word = word[:-1]
    return word


def _raw_tokens(text: str) -> list[str]:
    spaced = _CAMEL.sub(" ", text)
    return [part for part in _SPLIT.split(fold(spaced)) if part]


_STOPWORDS = frozenset(_STOPWORDS_RAW.split())


def tokens(text: str) -> list[str]:
    """Mots utiles, pliés et racinisés, dans l'ordre du texte (doublons gardés : ce sont des fréquences)."""

    return [_stem(part) for part in _raw_tokens(text) if part not in _STOPWORDS]


def _group_members(group: Iterable[str]) -> frozenset[str]:
    """Racines des membres d'un seul mot ; une locution (« pièce jointe ») n'est qu'un déclencheur."""

    return frozenset(token for member in group if len(_raw_tokens(member)) == 1 for token in tokens(member))


#: Racine → membres (racines) de son groupe, elle comprise.
SYNONYMS: dict[str, frozenset[str]] = {}
#: Locution (mots pliés, mots vides compris : « a faire ») → racines de son groupe. Elle déclenche
#: l'expansion quand ses mots se suivent dans l'intention ; ses mots seuls n'étendent rien, pour que
#: « envoyer » (de « envoyer un fichier ») n'amène pas `upload` dans « envoyer un mail ».
PHRASES: dict[tuple[str, ...], frozenset[str]] = {}
for _group in _SYNONYM_GROUPS_RAW:
    _members = _group_members(_group)
    for _member in _members:
        SYNONYMS[_member] = SYNONYMS.get(_member, frozenset()) | _members
    for _raw in _group:
        _words = tuple(_raw_tokens(_raw))
        if len(_words) > 1:
            PHRASES[_words] = PHRASES.get(_words, frozenset()) | _members


@dataclass(frozen=True, slots=True)
class ToolDoc:
    """Ce que le classement lit d'un outil. `source` : serveur natif ou nom du plugin."""

    id: str
    name: str
    label: str
    description: str
    param_names: tuple[str, ...]
    param_texts: tuple[str, ...]
    source: str


def query_weights(intent: str) -> dict[str, float]:
    """Termes de l'intention et leur poids : 1,0 par occurrence, `EXPANSION_WEIGHT` pour un synonyme ajouté."""

    weights: dict[str, float] = {}
    for token in tokens(intent):
        weights[token] = weights.get(token, 0.0) + 1.0
    expansions = [SYNONYMS.get(token, frozenset()) for token in list(weights)]
    words = _raw_tokens(intent)
    for phrase, members in PHRASES.items():
        if any(tuple(words[i: i + len(phrase)]) == phrase for i in range(len(words) - len(phrase) + 1)):
            expansions.append(members)
    for group in expansions:
        for synonym in group:
            if synonym not in weights:
                weights[synonym] = EXPANSION_WEIGHT
    return weights


def _fields(doc: ToolDoc) -> dict[str, list[str]]:
    return {
        "name": tokens(doc.name),
        "label": tokens(doc.label),
        "param_names": [token for name in doc.param_names for token in tokens(name)],
        "description": tokens(doc.description),
        "param_texts": [token for text in doc.param_texts for token in tokens(text)],
    }


@dataclass(frozen=True, slots=True)
class RankIndex:
    """Ce que `rank` relit à chaque intention, calculé une fois pour un ensemble d'outils.

    La passerelle le garde par `catalog_revision` (QA Slice 04 : la découpe des
    descriptions dominait la latence de `list_tools`). Immuable ; le score ne
    dépend que de lui et de l'intention.
    """

    docs: tuple[ToolDoc, ...]
    counts: tuple[dict[str, Counter[str]], ...]
    lengths: tuple[dict[str, int], ...]
    average: dict[str, float]
    frequency: dict[str, int]
    source_order: dict[str, int]


def build_index(docs: Sequence[ToolDoc]) -> RankIndex:
    """Découpe et statistiques BM25F de `docs` (IDF sur cet ensemble)."""

    source_order: dict[str, int] = {}
    for doc in docs:
        source_order.setdefault(doc.source, len(source_order))
    fields = [_fields(doc) for doc in docs]
    count = len(fields)
    average = {
        field: (sum(len(values[field]) for values in fields) / count if count else 0.0) or 1.0
        for field in FIELD_WEIGHTS
    }
    frequency: dict[str, int] = {}
    for values in fields:
        for term in {term for terms in values.values() for term in terms}:
            frequency[term] = frequency.get(term, 0) + 1
    return RankIndex(docs=tuple(docs),
                     counts=tuple({field: Counter(terms) for field, terms in values.items()} for values in fields),
                     lengths=tuple({field: len(terms) for field, terms in values.items()} for values in fields),
                     average=average, frequency=frequency, source_order=source_order)


def rank(intent: str, docs: Sequence[ToolDoc] | RankIndex) -> list[tuple[ToolDoc, float]]:
    """Tous les `docs`, du plus pertinent au moins pertinent ; score 0 = aucun terme commun.

    `docs` : les outils, ou leur `RankIndex` déjà construit (même résultat, sans
    redécouper). Intention vide après pliage : scores nuls, ordre alphabétique
    des `id` (`docs/mcp/plugins.md` §6.3).
    """

    index = docs if isinstance(docs, RankIndex) else None
    query = query_weights(intent)
    if not query:
        return [(doc, 0.0) for doc in sorted(index.docs if index else docs, key=lambda doc: doc.id)]
    if index is None:
        index = build_index(docs)  # type: ignore[arg-type]
    count = len(index.docs)
    terms = [(term, weight, index.frequency[term]) for term, weight in query.items() if index.frequency.get(term)]
    scored: list[tuple[ToolDoc, float]] = []
    for doc, counts, lengths in zip(index.docs, index.counts, index.lengths):
        score = 0.0
        for term, weight, df in terms:
            pseudo_tf = 0.0
            for field, field_weight in FIELD_WEIGHTS.items():
                tf = counts[field][term]
                if tf:
                    pseudo_tf += field_weight * tf / (1.0 - B + B * lengths[field] / index.average[field])
            if pseudo_tf:
                idf = math.log(1.0 + (count - df + 0.5) / (df + 0.5))
                score += weight * idf * pseudo_tf * (K1 + 1.0) / (pseudo_tf + K1)
        scored.append((doc, score))
    scored.sort(key=lambda pair: (-pair[1], index.source_order[pair[0].source], pair[0].id))
    return scored
