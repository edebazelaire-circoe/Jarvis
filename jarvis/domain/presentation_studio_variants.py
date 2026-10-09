"""Presentation Studio : le graphe des variantes (handoff jarvis-interactive-presentation-studio, Slice 16).

Une *variante* est une direction créative de la présentation entière, pas un état d'annulation : l'historique fin
(Slice 08) reste un anneau mémoire par variante et n'est **jamais** un noeud ici. Ce module est le modèle **pur** du
graphe (aucune E/S, aucune horloge, aucun secret en dur) :

- `VariantIndexEntry` : un noeud vivant du manifeste (`presentation.json`). Id machine stable `psv_<32 hex>`, numéro
  d'affichage **immuable** et monotone (alloué depuis `variant_counter`, jamais réutilisé), raison de création (texte
  non fiable, borné), auteur (`user` / `brain` / `system`), `sources` (les variantes dont celle-ci dérive : la Slice 16
  n'écrit que l'arête parent, la Slice 19 y ajoutera la composition) et une poignée d'aperçu opaque (`psp_<12 hex>` ou
  `None`, réservée à la Slice 18). Le **titre** et le **parent** vivent dans le fichier de la variante (un seul endroit).
- `ArchivedEntry` : un noeud archivé (le fichier a été **déplacé** vers `archive/`, jamais détruit) ; il garde ses
  métadonnées et son parent pour que le graphe se valide depuis le seul manifeste et que `restore` soit possible.
- `validate_graph` : l'invariant du graphe (ids et numéros uniques sur vivants + archivés, compteur >= tout numéro, actif
  vivant, parents existants, pas de cycle, un noeud vivant n'a que des ancêtres vivants, numéro d'un enfant > celui de son
  parent, sources valides), exécuté au chargement et avant **chaque** écriture.
- Plans purs : `plan_archive` (l'ensemble exact des variantes touchées + jeton de confirmation lié à cet ensemble et à la
  révision), `plan_restore`, et les transitions `with_*` qui rendent la Presentation suivante.

Contrat : `docs/presentation-studio.md` › *Variant graph and operations contract*.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import hmac
import json
import re
import secrets
from typing import Any

from jarvis.domain.presentation_studio_checks import (
    PresentationStudioError, PresentationStudioErrorCode as _C, _check_id, _check_int, _check_title, _exact_keys, _fail,
)

#: Id machine d'une variante (`psv_` + 32 hex) : immuable (D18).
VARIANT_ID = re.compile(r"psv_[0-9a-f]{32}\Z")
PREVIEW_ID = re.compile(r"psp_[0-9a-f]{12}\Z")
BATCH_ID = re.compile(r"psb_[0-9a-f]{12}\Z")
_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z")

MAX_VARIANT_COUNTER = 10_000
#: Variantes vivantes d'une Presentation (`presentation_studio.MAX_VARIANTS`, égal : testé).
MAX_LIVE_VARIANTS = 64
#: Variantes archivées conservées (déplacées, jamais détruites). Au-delà : `limit_reached` avec la marche à suivre.
MAX_ARCHIVED_VARIANTS = 128
MAX_RATIONALE = 600
#: Borne de la raison **telle qu'elle s'écrit sur disque** (octets UTF-8 du texte JSON, guillemets et antislash échappés compris) :
#: 64 vivants + 128 archivés, chacun avec une raison pleine, tiennent dans un manifeste de 256 Kio (testé, pire cas : 4 octets par
#: caractère). Sans elle, 600 émojis par raison saturent le manifeste au 93e noeud.
MAX_RATIONALE_BYTES = 800
MAX_SOURCES = 4
#: Validité d'un jeton de confirmation (secondes).
CONFIRMATION_TTL_S = 600
#: La raison d'un refus d'archivage plein (nomme la cause et la sortie).
ARCHIVE_FULL = ("archiving {n} branch(es) would exceed the {cap} archived branches kept: restore some archived branches first, "
                "or clear archive/ by hand with Core stopped (docs/OPERATIONS.md)")
TOKEN_PREFIX = "psk_"
#: Texte d'un jeton : `psk_<expiration epoch>.<64 hex>`.
_TOKEN = re.compile(rf"{TOKEN_PREFIX}[0-9]{{1,12}}\.[0-9a-f]{{64}}\Z")


class NodeActor:
    """Qui a créé un noeud : l'acteur de l'opération (`user`, `brain`) ou `system` (variante n° 1, migration)."""

    USER, BRAIN, SYSTEM = "user", "brain", "system"
    ALL = frozenset({USER, BRAIN, SYSTEM})


def new_preview_id() -> str:
    return "psp_" + secrets.token_hex(6)


def new_batch_id() -> str:
    return "psb_" + secrets.token_hex(6)


def is_variant_id(value: object) -> bool:
    return isinstance(value, str) and bool(VARIANT_ID.fullmatch(value))


def _check_stamp(name: str, value: object) -> None:
    if not isinstance(value, str) or not _STAMP.fullmatch(value):
        raise _fail(f"{name} must be a UTC timestamp like 2026-10-07T12:00:00.000000Z")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        raise _fail(f"{name} is not a real date") from None


def rationale_bytes(value: str) -> int:
    """Octets que le texte occupe dans le manifeste : sa forme JSON (échappements) encodée en UTF-8, sans les guillemets de bord."""

    return len(json.dumps(value, ensure_ascii=False).encode("utf-8", errors="replace")) - 2


def check_rationale(value: object, name: str = "rationale") -> str:
    """Texte **non fiable** de création : une ligne imprimable <= `MAX_RATIONALE`, sans espace en bordure. Jamais interprété."""

    if not isinstance(value, str):
        raise _fail(f"{name} must be a string")
    if value != value.strip():
        raise _fail(f"{name} must not have surrounding spaces")
    if len(value) > MAX_RATIONALE:
        raise _fail(f"{name} exceeds {MAX_RATIONALE} characters")
    if rationale_bytes(value) > MAX_RATIONALE_BYTES:
        raise _fail(f"{name} exceeds {MAX_RATIONALE_BYTES} bytes once encoded (emoji and CJK text weigh 3 to 4 bytes per character, "
                    "a quote or a backslash 2)")
    if value and not value.isprintable():
        raise _fail(f"{name} must be a single printable line")
    return value


# ------------------------------------------------------------------ noeuds

@dataclass(frozen=True, slots=True)
class VariantIndexEntry:
    """Un noeud **vivant** du manifeste. `(variant_id, variant_number)` suffisaient à la Slice 02 ; le reste a une valeur par défaut."""

    variant_id: str
    variant_number: int
    rationale: str = ""
    created_by: str = NodeActor.SYSTEM
    sources: tuple[str, ...] = ()
    preview_id: str | None = None

    def __post_init__(self) -> None:
        _check_id("variant_id", self.variant_id, VARIANT_ID)
        _check_int("variant_number", self.variant_number, 1, MAX_VARIANT_COUNTER)
        check_rationale(self.rationale)
        if self.created_by not in NodeActor.ALL:
            raise _fail("created_by must be user, brain or system")
        object.__setattr__(self, "sources", tuple(self.sources))
        if len(self.sources) > MAX_SOURCES:
            raise _fail(f"sources exceed {MAX_SOURCES}")
        for source in self.sources:
            _check_id("sources[]", source, VARIANT_ID)
        if len(set(self.sources)) != len(self.sources) or self.variant_id in self.sources:
            raise _fail("sources must be distinct variants other than the node itself")
        _check_id("preview_id", self.preview_id, PREVIEW_ID, optional=True)

    def to_dict(self) -> dict[str, Any]:
        return {"variant_id": self.variant_id, "variant_number": self.variant_number, "rationale": self.rationale,
                "created_by": self.created_by, "sources": list(self.sources), "preview_id": self.preview_id}


@dataclass(frozen=True, slots=True)
class ArchivedEntry:
    """Un noeud archivé : son fichier est dans `archive/`, ses métadonnées et son parent restent ici."""

    node: VariantIndexEntry
    parent_variant_id: str | None
    archived_at: str
    archived_by: str
    batch_id: str

    def __post_init__(self) -> None:
        _check_id("parent_variant_id", self.parent_variant_id, VARIANT_ID, optional=True)
        _check_stamp("archived_at", self.archived_at)
        if self.archived_by not in (NodeActor.USER, NodeActor.BRAIN, NodeActor.SYSTEM):
            raise _fail("archived_by must be user, brain or system")
        _check_id("batch_id", self.batch_id, BATCH_ID)

    @property
    def variant_id(self) -> str:
        return self.node.variant_id

    @property
    def variant_number(self) -> int:
        return self.node.variant_number

    def to_dict(self) -> dict[str, Any]:
        return {**self.node.to_dict(), "parent_variant_id": self.parent_variant_id, "archived_at": self.archived_at,
                "archived_by": self.archived_by, "batch_id": self.batch_id}


def entry_from_dict(raw: object, where: str) -> VariantIndexEntry:
    data = _exact_keys(raw, where, {"variant_id", "variant_number", "rationale", "created_by", "sources", "preview_id"})
    if not isinstance(data["sources"], list):
        raise _fail(f"{where}.sources must be a list")
    return VariantIndexEntry(data["variant_id"], data["variant_number"], data["rationale"], data["created_by"],
                             tuple(data["sources"]), data["preview_id"])


def archived_from_dict(raw: object, where: str) -> ArchivedEntry:
    data = _exact_keys(raw, where, {"variant_id", "variant_number", "rationale", "created_by", "sources", "preview_id",
                                    "parent_variant_id", "archived_at", "archived_by", "batch_id"})
    node = entry_from_dict({k: data[k] for k in ("variant_id", "variant_number", "rationale", "created_by", "sources",
                                                 "preview_id")}, where)
    return ArchivedEntry(node, data["parent_variant_id"], data["archived_at"], data["archived_by"], data["batch_id"])


def upgrade_entry_v1(entry: object) -> object:
    """Manifeste v1 -> v2 : une entrée `{variant_id, variant_number}` reçoit les valeurs par défaut (rien n'est réinterprété)."""

    if isinstance(entry, dict) and set(entry) == {"variant_id", "variant_number"}:
        return {**entry, "rationale": "", "created_by": NodeActor.SYSTEM, "sources": [], "preview_id": None}
    return entry


# ------------------------------------------------------------------ invariant du graphe

def validate_graph(live: Sequence[VariantIndexEntry], archived: Sequence[ArchivedEntry], *, active: str, counter: int,
                   live_parents: Mapping[str, str | None] | None = None) -> None:
    """L'invariant du graphe. `live_parents` : parent de chaque variante **vivante** (lu dans leurs fichiers ; `None`
    quand l'appelant ne l'a pas, seuls les contrôles du manifeste tournent). Lève `presentation_studio_invalid`.

    1. ids et numéros uniques sur vivants **et** archivés ; 2. `counter` >= tout numéro (jamais de réutilisation) ;
    3. l'actif existe et n'est pas archivé ; 4. tout parent existe, un noeud vivant n'a que des ancêtres vivants (on archive
    un sous-arbre entier), pas de cycle ; 5. le numéro d'un enfant dépasse celui de son parent ; 6. `sources` existent,
    de numéro inférieur."""

    everyone: dict[str, int] = {}
    for node in (*live, *(a.node for a in archived)):
        if node.variant_id in everyone:
            raise _fail("variant ids must be unique across live and archived variants")
        everyone[node.variant_id] = node.variant_number
    if len(set(everyone.values())) != len(everyone):
        raise _fail("variant numbers must be unique across live and archived variants (a number is never reused)")
    if everyone and max(everyone.values()) > counter:
        raise _fail("variant_counter is below an indexed variant_number")
    live_ids = {node.variant_id for node in live}
    if active not in live_ids:
        raise _fail("active_variant_id is not a live variant (it is missing or archived)")
    if len(archived) > MAX_ARCHIVED_VARIANTS:
        raise _fail(f"archived variants exceed {MAX_ARCHIVED_VARIANTS}")
    parents: dict[str, str | None] = {a.variant_id: a.parent_variant_id for a in archived}
    if live_parents is not None:
        if set(live_parents) != live_ids:
            raise _fail("the variant index and the variants differ")
        parents.update(live_parents)
    for variant_id, parent in parents.items():
        if parent is None:
            continue
        if parent == variant_id:
            raise _fail("a variant cannot be its own parent")
        if parent not in everyone:
            raise _fail(f"variant {variant_id} has a parent outside the presentation")
        if variant_id in live_ids and parent not in live_ids:
            raise _fail(f"variant {variant_id} is live but its parent is archived (a subtree is archived whole)")
    for start in parents:
        seen, current = {start}, parents[start]
        while current is not None:
            if current in seen:
                raise _fail(f"variant {start} is part of a parent cycle")
            seen.add(current)
            current = parents.get(current)
    for variant_id, parent in parents.items():
        if parent is not None and everyone[parent] >= everyone[variant_id]:
            raise _fail(f"variant {variant_id}: its number must be above its parent's (numbers grow with creation)")
    for node in (*live, *(a.node for a in archived)):
        for source in node.sources:
            if source not in everyone:
                raise _fail(f"variant {node.variant_id}: source {source} is not a variant of this presentation")
            if everyone[source] >= node.variant_number:
                raise _fail(f"variant {node.variant_id}: a source must be older (lower number) than the variant")


def children_map(parents: Mapping[str, str | None]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {variant_id: [] for variant_id in parents}
    for variant_id, parent in parents.items():
        if parent is not None and parent in result:
            result[parent].append(variant_id)
    return result


def subtree(root: str, parents: Mapping[str, str | None]) -> list[str]:
    """`root` et tous ses descendants (itératif, sans récursion), ordre de découverte déterministe."""

    children = children_map(parents)
    order, stack = [], [root]
    while stack:
        current = stack.pop()
        order.append(current)
        stack.extend(sorted(children.get(current, ()), reverse=True))
    return order


def ancestors(variant_id: str, parents: Mapping[str, str | None]) -> list[str]:
    """Du parent direct vers la racine."""

    chain, current = [], parents.get(variant_id)
    while current is not None and current not in chain:
        chain.append(current)
        current = parents.get(current)
    return chain


# ------------------------------------------------------------------ plans

@dataclass(frozen=True, slots=True)
class PlanRow:
    variant_id: str
    variant_number: int
    title: str

    def to_dict(self) -> dict[str, Any]:
        return {"variant_id": self.variant_id, "variant_number": self.variant_number, "title": self.title}


@dataclass(frozen=True, slots=True)
class ArchivePlan:
    """Ce qu'un `archive` toucherait, **exactement** : l'ensemble des variantes (ids, numéros, titres), ordonné par numéro."""

    presentation_id: str
    revision: int
    root_variant_id: str
    rows: tuple[PlanRow, ...]
    active_variant_id: str
    #: Nouvel actif demandé quand l'actif est dans l'ensemble (sinon `None`).
    activate_variant_id: str | None
    #: Un nouvel actif est nécessaire (l'actif est dans l'ensemble) et n'a pas été donné.
    requires_new_active: bool
    suggested_active: str | None
    #: `None` si exécutable ; sinon le code du blocage.
    blocked: str | None
    blocked_reason: str = ""

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(row.variant_id for row in self.rows)

    def to_dict(self) -> dict[str, Any]:
        return {"presentation_id": self.presentation_id, "revision": self.revision,
                "root_variant_id": self.root_variant_id, "affected": [row.to_dict() for row in self.rows],
                "count": len(self.rows), "includes_active": self.active_variant_id in self.ids,
                "active_variant_id": self.active_variant_id, "activate_variant_id": self.activate_variant_id,
                "requires_new_active": self.requires_new_active, "suggested_active": self.suggested_active,
                "blocked": self.blocked, "blocked_reason": self.blocked_reason}


def plan_archive(*, presentation_id: str, revision: int, root: str, live: Sequence[VariantIndexEntry],
                 parents: Mapping[str, str | None], titles: Mapping[str, str], active: str,
                 activate: str | None, archived_count: int = 0) -> ArchivePlan:
    """L'ensemble touché par l'archivage de `root` et de ses descendants, et ce qui le bloque. Pur. `archived_count` : les noeuds
    déjà archivés ; si l'ensemble dépasserait `MAX_ARCHIVED_VARIANTS`, le plan est refusé d'emblée (`limit_reached`), pour qu'aucun jeton
    ne soit délivré pour une exécution qui échouerait après confirmation."""

    numbers = {node.variant_id: node.variant_number for node in live}
    if root not in numbers:
        raise PresentationStudioError(_C.UNKNOWN_VARIANT, f"{root} is not a live variant of this presentation")
    ids = subtree(root, parents)
    if archived_count + len(ids) > MAX_ARCHIVED_VARIANTS:
        raise PresentationStudioError(_C.LIMIT_REACHED, ARCHIVE_FULL.format(n=len(ids), cap=MAX_ARCHIVED_VARIANTS))
    rows = tuple(sorted((PlanRow(i, numbers[i], titles.get(i, "")) for i in ids), key=lambda r: r.variant_number))
    inside = set(ids)
    remaining = sorted((i for i in numbers if i not in inside), key=lambda i: numbers[i])
    suggested = None
    if active in inside:
        parent = parents.get(root)
        suggested = parent if parent is not None and parent not in inside else (remaining[0] if remaining else None)
    if activate is not None:
        if active not in inside:
            raise _fail("activate_variant_id is only for an archive that holds the active variant")
        if activate not in remaining:
            raise _fail("activate_variant_id must be a live variant that stays after the archive")
    blocked, reason = None, ""
    if not remaining:
        blocked, reason = _C.ACTIVE_VARIANT_PROTECTED.value, "nothing would remain: a presentation keeps at least one live variant"
    elif active in inside and activate is None:
        blocked = _C.ACTIVE_VARIANT_PROTECTED.value
        reason = "the active variant is in this set: choose another active variant (activate_variant_id) first"
    return ArchivePlan(presentation_id, revision, root, rows, active, activate, active in inside and activate is None,
                       suggested, blocked, reason)


def confirmation_digest(secret: bytes, plan: ArchivePlan, expires_at: int) -> str:
    """HMAC du plan : présentation, révision, **ensemble exact** (id, numéro, titre), racine, nouvel actif, expiration."""

    body = json.dumps({"p": plan.presentation_id, "r": plan.revision, "root": plan.root_variant_id,
                       "rows": [[r.variant_id, r.variant_number, r.title] for r in plan.rows],
                       "act": plan.activate_variant_id, "exp": expires_at}, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def issue_confirmation(secret: bytes, plan: ArchivePlan, now_epoch: int) -> str:
    if plan.blocked is not None:
        raise PresentationStudioError(_C.ACTIVE_VARIANT_PROTECTED, plan.blocked_reason)
    expires = now_epoch + CONFIRMATION_TTL_S
    return f"{TOKEN_PREFIX}{expires}.{confirmation_digest(secret, plan, expires)}"


def check_confirmation(secret: bytes, plan: ArchivePlan, token: object, now_epoch: int) -> None:
    """Le jeton doit être celui de **ce** plan (ensemble, titres, révision, nouvel actif). Absent/mal formé : `confirmation_required`.
    Valide mais pour un autre ensemble, une autre révision ou expiré : `confirmation_stale`. Comparaison à temps constant."""

    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise PresentationStudioError(_C.CONFIRMATION_REQUIRED,
                                      "archiving needs the confirmation token of a plan (plan first, then confirm)")
    expires = int(token[len(TOKEN_PREFIX):].split(".", 1)[0])
    expected = f"{TOKEN_PREFIX}{expires}.{confirmation_digest(secret, plan, expires)}"
    if not hmac.compare_digest(token, expected):
        raise PresentationStudioError(
            _C.CONFIRMATION_STALE, "the confirmation does not match what would be archived now (the set, a title, "
                                   "the presentation revision or the chosen active variant changed, or the token is not "
                                   "from this plan): plan again and confirm what you see")
    if now_epoch > expires:
        raise PresentationStudioError(_C.CONFIRMATION_STALE, "the confirmation expired: plan again")


@dataclass(frozen=True, slots=True)
class RestorePlan:
    presentation_id: str
    variant_id: str
    #: Dans l'ordre de restauration : ancêtres archivés d'abord, puis la variante, puis (option) ses descendants archivés.
    ids: tuple[str, ...]
    numbers: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"presentation_id": self.presentation_id, "variant_id": self.variant_id,
                "restored": [{"variant_id": i, "variant_number": n} for i, n in zip(self.ids, self.numbers)]}


def plan_restore(*, presentation_id: str, variant_id: str, live: Sequence[VariantIndexEntry],
                 archived: Sequence[ArchivedEntry], with_descendants: bool) -> RestorePlan:
    """Restaure `variant_id` **et ses ancêtres archivés** (un noeud vivant n'a que des ancêtres vivants) ; ses descendants
    archivés seulement sur demande. Refuse s'il n'y a pas la place (`limit_reached`)."""

    by_id = {a.variant_id: a for a in archived}
    if variant_id not in by_id:
        live_ids = {n.variant_id for n in live}
        if variant_id in live_ids:
            raise PresentationStudioError(_C.NOT_ARCHIVED, f"{variant_id} is not archived")
        raise PresentationStudioError(_C.UNKNOWN_VARIANT, f"{variant_id} is not an archived variant of this presentation")
    parents = {i: a.parent_variant_id for i, a in by_id.items()}
    chain = []
    for ancestor in ancestors(variant_id, parents):
        if ancestor in by_id:
            chain.append(ancestor)
        else:
            break  # a live ancestor: the chain ends there
    ordered = [*reversed(chain), variant_id]
    if with_descendants:
        ordered += [i for i in subtree(variant_id, parents) if i != variant_id]
    if len(live) + len(ordered) > MAX_LIVE_VARIANTS:
        raise PresentationStudioError(
            _C.LIMIT_REACHED, f"restoring {len(ordered)} variants would exceed {MAX_LIVE_VARIANTS} live variants: archive something first")
    return RestorePlan(presentation_id, variant_id, tuple(ordered), tuple(by_id[i].variant_number for i in ordered))


# ------------------------------------------------------------------ transitions (Presentation -> Presentation)

def next_number(counter: int) -> int:
    if counter >= MAX_VARIANT_COUNTER:
        raise PresentationStudioError(
            _C.LIMIT_REACHED, f"variant numbers are exhausted ({MAX_VARIANT_COUNTER}): a number is never reused")
    return counter + 1


def with_allocation(presentation: Any, stamp_text: str) -> Any:
    """Réserve le prochain numéro : `variant_counter + 1`, aucun noeud (un arrêt ici laisse un trou, jamais une réutilisation)."""

    return replace(presentation, variant_counter=next_number(presentation.variant_counter),
                   revision=presentation.revision + 1, updated_at=stamp_text)


def with_node(presentation: Any, entry: VariantIndexEntry, *, activate: bool, stamp_text: str) -> Any:
    if len(presentation.variants) >= MAX_LIVE_VARIANTS:
        raise PresentationStudioError(_C.LIMIT_REACHED, f"at most {MAX_LIVE_VARIANTS} live variants: archive a branch first")
    return replace(presentation, variants=(*presentation.variants, entry),
                   active_variant_id=entry.variant_id if activate else presentation.active_variant_id,
                   revision=presentation.revision + 1, updated_at=stamp_text)


def with_active(presentation: Any, variant_id: str, stamp_text: str) -> Any:
    return replace(presentation, active_variant_id=variant_id, revision=presentation.revision + 1, updated_at=stamp_text)


def with_archived(presentation: Any, plan: ArchivePlan, parents: Mapping[str, str | None], *, actor: str, batch_id: str,
                  stamp_text: str) -> Any:
    inside = set(plan.ids)
    moved = [ArchivedEntry(node, parents.get(node.variant_id), stamp_text, actor, batch_id)
             for node in presentation.variants if node.variant_id in inside]
    if len(presentation.archived) + len(moved) > MAX_ARCHIVED_VARIANTS:
        raise PresentationStudioError(_C.LIMIT_REACHED, ARCHIVE_FULL.format(n=len(moved), cap=MAX_ARCHIVED_VARIANTS))
    return replace(
        presentation, variants=tuple(n for n in presentation.variants if n.variant_id not in inside),
        archived=(*presentation.archived, *sorted(moved, key=lambda a: a.variant_number)),
        active_variant_id=plan.activate_variant_id or presentation.active_variant_id,
        revision=presentation.revision + 1, updated_at=stamp_text)


def with_restored(presentation: Any, plan: RestorePlan, stamp_text: str) -> Any:
    back = set(plan.ids)
    nodes = sorted((a.node for a in presentation.archived if a.variant_id in back), key=lambda n: n.variant_number)
    return replace(presentation, variants=(*presentation.variants, *nodes),
                   archived=tuple(a for a in presentation.archived if a.variant_id not in back),
                   revision=presentation.revision + 1, updated_at=stamp_text)


# ------------------------------------------------------------------ rapport de réconciliation (pur)

@dataclass(frozen=True, slots=True)
class Reconciliation:
    """Ce qu'il faut faire, et ce qu'il faut seulement dire, pour accorder les fichiers au manifeste (`reconcile_plan`)."""

    #: `(variant_id, vers)` : un fichier dans le mauvais dossier pour l'état du manifeste (`live` <-> `archive`) : déplacé.
    moves: tuple[tuple[str, str], ...] = ()
    #: Fichiers de variante que le manifeste ne nomme pas (création interrompue) : **rapportés**, jamais adoptés ni supprimés.
    orphan_variants: tuple[str, ...] = ()
    #: Fichiers présents des deux côtés pour un même id : rapportés, jamais touchés (le manifeste dit lequel fait foi).
    duplicate_files: tuple[str, ...] = ()
    #: Noeuds du manifeste dont le fichier n'existe nulle part : `corrupt_document` à la lecture.
    missing: tuple[str, ...] = ()
    #: Documents liés (partition...) qu'aucune variante vivante ou archivée ne cite : rapportés, jamais supprimés. `{kind: [ids]}`.
    orphan_linked: Mapping[str, tuple[str, ...]] = None  # type: ignore[assignment]
    #: Variantes dont le fichier est illisible ou absent pendant le contrôle complet : leurs documents liés ne sont pas jugés
    #: (on ne les déclare pas orphelins à tort).
    unverified: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.orphan_linked is None:
            object.__setattr__(self, "orphan_linked", {})

    @property
    def clean(self) -> bool:
        return not (self.moves or self.orphan_variants or self.duplicate_files or self.missing or self.unverified
                    or any(self.orphan_linked.values()))

    def to_dict(self) -> dict[str, Any]:
        return {"moved": [{"variant_id": i, "to": to} for i, to in self.moves], "orphan_variants": list(self.orphan_variants),
                "duplicate_files": list(self.duplicate_files), "missing": list(self.missing),
                "orphan_linked": {k: list(v) for k, v in self.orphan_linked.items()}, "unverified": list(self.unverified),
                "clean": self.clean}


def reconcile_plan(*, live_ids: Sequence[str], archived_ids: Sequence[str], live_files: Sequence[str],
                   archive_files: Sequence[str]) -> Reconciliation:
    """Le manifeste fait foi. Un fichier dans le **mauvais** dossier (opération interrompue entre le déplacement des
    fichiers et l'écriture du manifeste) retourne là où le manifeste le place ; un fichier que personne ne nomme est un
    orphelin **rapporté** ; un id présent des deux côtés est un doublon **rapporté** ; un noeud sans fichier est `missing`."""

    live, archived = set(live_ids), set(archived_ids)
    in_live, in_archive = set(live_files), set(archive_files)
    moves: list[tuple[str, str]] = []
    duplicates: list[str] = []
    for variant_id in sorted(live | archived):
        want_live = variant_id in live
        here, there = (variant_id in in_live, variant_id in in_archive)
        if want_live and not here and there:
            moves.append((variant_id, "live"))
        elif not want_live and not there and here:
            moves.append((variant_id, "archive"))
        elif here and there:
            duplicates.append(variant_id)
    named = live | archived
    orphans = sorted((in_live | in_archive) - named)
    missing = sorted(i for i in named if i not in in_live and i not in in_archive)
    return Reconciliation(tuple(moves), tuple(orphans), tuple(duplicates), tuple(missing))


# ------------------------------------------------------------------ corps de requête

@dataclass(frozen=True, slots=True)
class BranchRequest:
    source_variant_id: str | None  # None : la variante active
    title: str
    rationale: str
    actor: str
    activate: bool
    expected_revision: int | None


def parse_branch(raw: object) -> BranchRequest:
    data = _exact_keys(raw, "branch", {"title"},
                       frozenset({"source_variant_id", "rationale", "actor", "activate", "expected_revision"}))
    _check_title("title", data["title"])
    source = data.get("source_variant_id")
    _check_id("source_variant_id", source, VARIANT_ID, optional=True)
    actor = data.get("actor", NodeActor.USER)
    if actor not in (NodeActor.USER, NodeActor.BRAIN):
        raise _fail("actor must be user or brain")
    activate = data.get("activate", False)
    if type(activate) is not bool:
        raise _fail("activate must be true or false")
    return BranchRequest(source, data["title"], check_rationale(data.get("rationale", "")), actor, activate,
                         _expected(data))


def _expected(data: Mapping[str, Any]) -> int | None:
    value = data.get("expected_revision")
    if value is None:
        return None
    _check_int("expected_revision", value, 1, 2**31 - 1)
    return value


def check_actor(data: Mapping[str, Any]) -> str:
    actor = data.get("actor", NodeActor.USER)
    if actor not in (NodeActor.USER, NodeActor.BRAIN):
        raise _fail("actor must be user or brain")
    return actor


def parse_expected(raw: object, where: str, required: set[str] = frozenset(),
                   optional: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Corps exact d'une opération du graphe : `actor` et `expected_revision` optionnels en plus des clés données."""

    data = _exact_keys(raw, where, set(required), optional | {"actor", "expected_revision"})
    check_actor(data)
    _expected(data)
    return data
