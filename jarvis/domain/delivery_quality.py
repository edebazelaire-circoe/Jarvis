"""Qualité de restitution d'un Mission Owner : choix de la surface, garde-fous, repli (Slice 11).

Handoff jarvis-organic-agent-orchestration, décision D23 : un rapport ou une comparaison sérieuse se livre
sur une surface riche **existante** (`jarvis.document`, `jarvis.table`, un prefab plus riche trouvé par
`prefab_search`), jamais en mur de texte ; une réponse simple reste simple. Ce module ne construit aucun
rendu : il dit au Mission Owner quand et comment utiliser les outils `jarvis-display` qu'il a déjà
(`scene_create_object` avec `prefab`), et il prépare le repli quand un affichage échoue.

Trois choses, toutes pures (aucune entrée-sortie) :

- **heuristique de forme** (`classify_delivery`) : la forme probable de la demande (simple, comparaison,
  rapport, liste à cocher) lue dans la consigne de l'appelant. Ce n'est qu'un indice : le Mission Owner
  juge sur le résultat réel, et une demande simple ne reçoit aucun indice qui la pousserait vers un
  artefact lourd ;
- **consigne de restitution** (`delivery_brief`) : le paragraphe que le hook ajoute au bloc
  « RESPONSABILITÉ DE MISSION (JARVIS) » (`agent_orchestration.mission_brief`). Formes et bornes des
  prefabs de base reprises de leurs manifestes livrés (`jarvis/prefabs/base/*/1/manifest.json`), égalité
  vérifiée par `tests/unit/test_delivery_quality.py` ;
- **repli structuré** (`fallback_note`) : le texte joint à l'erreur d'un affichage de prefab refusé ou en
  panne (`display_mcp.SceneDisplayTools`) : rien n'est à l'écran, ne pas le prétendre, livrer le contenu
  dans le compte rendu sous une forme lisible, prête à l'emploi (tableau Markdown, corps du document,
  liste à cocher).

Contrat : `docs/subagent-roles.md` §5bis, `docs/prefabs.md` « Consumers ».
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import json
import re
import unicodedata
from typing import Any

#: Tête du paragraphe de restitution ; sert aussi à ne jamais le doubler.
DELIVERY_MARK = "RESTITUTION (JARVIS)"
#: Tête du repli joint à une erreur d'affichage de prefab.
FALLBACK_MARK = "REPLI DE RESTITUTION (JARVIS)"
#: Outil d'affichage d'un Mission Owner (serveur `jarvis-display`, nom complet vu par un sous-agent).
DISPLAY_TOOL = "mcp__jarvis-display__scene_create_object"
SEARCH_TOOL = "mcp__jarvis-display__prefab_search"
#: Borne du contenu prêt à l'emploi joint à un repli : de quoi livrer sans noyer le message d'erreur.
MAX_FALLBACK_CHARS = 6000


class DeliveryShape(StrEnum):
    SIMPLE = "simple"
    COMPARISON = "comparison"
    REPORT = "report"
    CHECKLIST = "checklist"


@dataclass(frozen=True, slots=True)
class Surface:
    """La surface conseillée pour une forme : un prefab de base, ou `None` (réponse directe)."""

    shape: DeliveryShape
    prefab_id: str | None
    label: str


#: Bornes des prefabs de base, recopiées de leurs manifestes v1 (test de conformité).
TABLE_MAX_COLUMNS = 8
TABLE_MAX_ROWS = 64
TABLE_MAX_CELL = 200
TABLE_MAX_COLUMN_LABEL = 40
DOCUMENT_MAX_BODY = 12000
CHECKLIST_MAX_ITEMS = 64

SURFACES: Mapping[DeliveryShape, Surface] = {
    DeliveryShape.SIMPLE: Surface(DeliveryShape.SIMPLE, None, "une réponse directe dans votre compte rendu"),
    DeliveryShape.COMPARISON: Surface(DeliveryShape.COMPARISON, "jarvis.table", "un tableau jarvis.table"),
    DeliveryShape.REPORT: Surface(DeliveryShape.REPORT, "jarvis.document", "un document jarvis.document"),
    DeliveryShape.CHECKLIST: Surface(DeliveryShape.CHECKLIST, "jarvis.checklist", "une liste jarvis.checklist"),
}

_SHAPE_LABELS = {
    DeliveryShape.COMPARISON: "une comparaison",
    DeliveryShape.REPORT: "un rapport",
    DeliveryShape.CHECKLIST: "une liste à cocher",
}

# Mots repérés dans un texte sans accents et en minuscules. « compte rendu » n'en est pas : c'est ce que tout
# appelant demande en retour, pas une forme. « par rapport à » est retiré avant la recherche.
_COMPARISON = re.compile(
    r"\b(compar\w*|versus|vs\.?|benchmark\w*|avantages et inconvenients|pour et contre|pros and cons|"
    r"lequel choisir|laquelle choisir|differences? entre|tableau comparatif|classement)\b")
_REPORT = re.compile(
    r"\b(rapports?|reports?|synthese|etude|etat de l'art|livre blanc|white ?paper|note de synthese|"
    r"analyse approfondie|recherche approfondie|dossier de recherche|document de synthese|memo)\b")
_CHECKLIST = re.compile(r"\b(check-?list|liste de controle|liste de taches|a cocher|to-?do)\b")
_NOT_A_REPORT = re.compile(r"\bpar rapport\b")


def _normalized(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _NOT_A_REPORT.sub(" ", plain.replace("’", "'"))


def classify_delivery(text: str) -> DeliveryShape:
    """La forme probable de la demande. Comparaison avant rapport (un « rapport comparatif » est un tableau
    et quelques lignes), rapport avant liste à cocher ; rien de repéré : simple. Ne lève jamais."""

    plain = _normalized(text if isinstance(text, str) else "")
    if _COMPARISON.search(plain):
        return DeliveryShape.COMPARISON
    if _REPORT.search(plain):
        return DeliveryShape.REPORT
    if _CHECKLIST.search(plain):
        return DeliveryShape.CHECKLIST
    return DeliveryShape.SIMPLE


def surface_for(shape: DeliveryShape) -> Surface:
    return SURFACES[shape]


def delivery_brief(request: str = "") -> str:
    """Le paragraphe de restitution d'un Mission Owner, avec un indice de forme tiré de `request`.

    Il dit quand une surface riche sert, laquelle, comment l'afficher, et quoi faire si l'affichage échoue ;
    il n'impose ni gabarit ni artefact. Une demande jugée simple ne reçoit aucun indice.
    """

    lines = [
        DELIVERY_MARK,
        "L'utilisateur ne lit pas votre compte rendu : le cerveau vocal le lui résume en quelques phrases. Ce qui "
        "doit être lu (un tableau, un rapport) n'atteint l'utilisateur que s'il est affiché à l'écran. Choisissez "
        "la forme d'après l'usage du résultat, pas d'après l'effort fourni :",
        "- Fait, chiffre, oui/non, petite correction : rendez-le tel quel dans votre compte rendu, sans fenêtre "
        "ni document.",
        f"- Comparaison sérieuse (plusieurs options sur plusieurs critères) : affichez un tableau jarvis.table, "
        f"data {{columns: [{{label, align?}}], rows: [[cellules]]}}, {TABLE_MAX_COLUMNS} colonnes et "
        f"{TABLE_MAX_ROWS} lignes au plus, cellules courtes (≤ {TABLE_MAX_CELL} caractères) ; la recommandation "
        "va dans un document jarvis.document à côté si elle dépasse quelques lignes.",
        f"- Rapport, synthèse, recherche approfondie : affichez un document jarvis.document, data {{body: "
        f"Markdown ≤ {DOCUMENT_MAX_BODY} caractères}}, structuré (titres, listes, sources nommées).",
        "- Actions à cocher : jarvis.checklist, data {items: [{id, label, done?, note?}]}. Une surface plus "
        f"riche existe peut-être : {SEARCH_TOOL}.",
        f"- Pour afficher : {DISPLAY_TOOL} (kind window, category, title, prefab {{prefab_id, data}}) ; s'il "
        "n'est pas chargé, chargez-le avec ToolSearch (« select:" + DISPLAY_TOOL + " »).",
        "- L'affichage n'est fait que si l'outil rend un object_id. Sur un refus ou une erreur, ne dites pas "
        "qu'il est à l'écran : livrez le contenu en Markdown structuré dans votre compte rendu et dites en une "
        "phrase ce qui a échoué (l'erreur joint un repli prêt à l'emploi). Sans ces outils dans votre session, "
        "même chose.",
        "- Dans votre compte rendu final, après un affichage réussi : l'object_id, la conclusion en quelques "
        "lignes, sans recopier ce qui est affiché.",
    ]
    shape = classify_delivery(request)
    if shape is not DeliveryShape.SIMPLE:
        lines.append(f"Indice : la consigne ressemble à {_SHAPE_LABELS[shape]} ; affichez {surface_for(shape).label}, "
                     "sauf si le résultat réel tient en une phrase.")
    return "\n".join(lines)


# ------------------------------------------------------------------ repli

def _cell(value: object, limit: int = TABLE_MAX_CELL) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _table_markdown(data: Mapping[str, Any]) -> str | None:
    columns = data.get("columns")
    if not isinstance(columns, list) or not columns:
        return None
    labels = [_cell(column.get("label", "") if isinstance(column, Mapping) else column, 80) for column in columns]
    lines = ["| " + " | ".join(labels) + " |", "|" + "---|" * len(labels)]
    rows = data.get("rows")
    for row in rows if isinstance(rows, list) else []:
        cells = [_cell(value) for value in row] if isinstance(row, list) else [_cell(row)]
        cells = (cells + [""] * len(labels))[: max(len(labels), len(cells))]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _checklist_markdown(data: Mapping[str, Any]) -> str | None:
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return None
    lines = []
    for item in items:
        if not isinstance(item, Mapping):
            lines.append(f"- [ ] {_cell(item)}")
            continue
        mark = "x" if item.get("done") is True else " "
        note = f" — {_cell(item['note'])}" if item.get("note") else ""
        lines.append(f"- [{mark}] {_cell(item.get('label', ''))}{note}")
    return "\n".join(lines)


def readable_content(prefab_id: str, data: object) -> str | None:
    """Le contenu de `data` sous une forme lisible sans fenêtre, ou `None` s'il n'y a rien à livrer.

    `jarvis.table` : tableau Markdown ; `jarvis.document`, `jarvis.window`, `jarvis.browser` : le corps ;
    `jarvis.checklist` : liste à cocher ; tout autre prefab : ses données en JSON indenté. Borné à
    `MAX_FALLBACK_CHARS`, la coupure est dite.
    """

    if not isinstance(data, Mapping) or not data:
        return None
    text: str | None
    if prefab_id == "jarvis.table":
        text = _table_markdown(data)
    elif prefab_id == "jarvis.checklist":
        text = _checklist_markdown(data)
    elif isinstance(data.get("body"), str) and data["body"].strip():
        text = data["body"].strip()
    else:
        text = None
    if text is None:
        text = json.dumps(data, ensure_ascii=False, indent=1, default=str)
    if len(text) > MAX_FALLBACK_CHARS:
        text = text[:MAX_FALLBACK_CHARS].rstrip() + f"\n[… coupé à {MAX_FALLBACK_CHARS} caractères]"
    return text


def fallback_note(prefab: object) -> str:
    """Le repli joint à l'erreur d'un affichage de prefab (`prefab` : l'argument de l'outil, tel que reçu)."""

    given = prefab if isinstance(prefab, Mapping) else {}
    prefab_id = given.get("prefab_id") if isinstance(given.get("prefab_id"), str) else "?"
    content = readable_content(prefab_id, given.get("data"))
    lines = [
        FALLBACK_MARK,
        f"La fenêtre {prefab_id} n'est pas affichée : rien n'est à l'écran, ne dites pas le contraire. Corrigez "
        "et réessayez si la cause est claire ; sinon livrez le contenu dans votre compte rendu sous une forme "
        "lisible et dites en une phrase que l'affichage a échoué, avec la cause ci-dessus.",
    ]
    if content is not None:
        lines += ["Contenu prêt à livrer :", content]
    return "\n".join(lines)
