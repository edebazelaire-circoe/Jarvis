"""Service Core du graphe de variantes (handoff jarvis-interactive-presentation-studio, Slice 16).

Les opérations d'un graphe de directions créatives : **brancher** (copie profonde de la variante source et de ses documents
liés), **activer**, **renommer**, **archiver** un sous-arbre sous la politique de destruction (plan à blanc + jeton de
confirmation), **restaurer**, et **réconcilier** les fichiers avec le manifeste après un arrêt brutal. Contrat :
`docs/presentation-studio.md` › *Variant graph and operations contract*. Modèle pur : `domain/presentation_studio_variants.py`.

Pas de transaction multi-fichiers, donc un **ordre** par opération, chaque étape étant atomique et durable, et une règle de
réconciliation par état intermédiaire (« le manifeste fait foi ») :

| Opération | Étapes (chaque flèche est un point d'arrêt possible) | État laissé par un arrêt |
| --- | --- | --- |
| `create_branch` | 1 manifeste `variant_counter + 1` (**allocation**) -> 2 documents liés copiés -> 3 fichier de la variante -> 4 manifeste avec le noeud (**validation**) | 1 : un trou dans les numéros (jamais réutilisé) ; 2 : documents liés orphelins, **rapportés** ; 3 : fichier de variante orphelin, **rapporté** ; 4 : fait |
| `archive` | 1 chaque fichier `variants/` -> `archive/` (un renommage) -> 2 manifeste (noeuds vivants -> `archived`) | 1 : fichiers dans le mauvais dossier pour le manifeste : **replacés** par la réconciliation (l'archivage n'a pas eu lieu) ; 2 : fait |
| `restore` | 1 chaque fichier `archive/` -> `variants/` -> 2 manifeste | idem, dans l'autre sens |
| `activate` | manifeste seul | atomique |
| `rename` | fichier de la variante seul | atomique |

Les orphelins (fichier de variante ou document lié que rien ne nomme) ne sont **jamais adoptés ni supprimés** (CLAUDE.md :
aucune donnée n'est détruite sans copie) : ils sont comptés et nommés dans le rapport (`graph(...)["reconciliation"]`, trace
`core.presentation_studio.reconciled`), et `docs/OPERATIONS.md` dit comment les reprendre à la main.

Tout passe par le verrou du Studio (un seul écrivain) et par `PresentationStudioService.persist_variant_locked`, l'unique
porte d'écriture d'une variante (donc le registre des pins de la Slice 06 voit chaque variante écrite ici). Une branche ne
publie **aucun** prefab : elle copie les épingles `(id, version)` de la source (pins partagés, `docs/prefabs.md`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
import secrets
import time
from typing import Any

from jarvis.domain.presentation_studio import (
    Presentation, PresentationStudioError, PresentationStudioErrorCode as C, PresentationVariant, _check_title,
    dump_document, is_presentation_id, new_variant_id, parse_variant, stamp,
)
from jarvis.domain.presentation_studio_history import DropReason
from jarvis.domain.presentation_studio_checks import _check_id, _fail
from jarvis.domain.presentation_studio_variants import (
    CONFIRMATION_TTL_S, VARIANT_ID, ArchivePlan, NodeActor, Reconciliation, VariantIndexEntry, check_confirmation, issue_confirmation, new_batch_id, next_number, parse_branch, parse_expected, plan_archive,
    plan_restore, reconcile_plan, validate_graph, with_active, with_allocation, with_archived, with_node, with_restored,
)
from jarvis.core.presentation_studio_linked import LinkedDocuments, ScoreLink
from jarvis.ports.v2 import DiagnosticSink

#: Une réconciliation ne doit jamais devenir un journal sans fin : bornes des listes nommées dans les traces et le rapport.
MAX_REPORTED = 20
#: Un point d'arrêt déterministe (tests d'arrêt brutal) : appelé avec le nom de l'étape qui vient d'être **faite**.
Checkpoint = Callable[[str], None]


class PresentationStudioVariants:
    def __init__(self, studio: Any, *, history: Any | None = None, diagnostics: DiagnosticSink | None = None,
                 events: Any | None = None, linked: LinkedDocuments | None = None, secret: bytes | None = None,
                 epoch: Callable[[], float] = time.time, checkpoint: Checkpoint | None = None) -> None:
        self._studio = studio
        self._history = history
        self._diagnostics = diagnostics
        self._events = events
        self._linked = linked if linked is not None else LinkedDocuments(ScoreLink(studio))
        #: Secret de ce processus : un jeton de confirmation meurt avec lui (replanifier après un redémarrage).
        self._secret = secret if secret is not None else secrets.token_bytes(32)
        self._epoch = epoch
        self._checkpoint = checkpoint
        self._reconciled: set[str] = set()
        self._reports: dict[str, dict[str, Any]] = {}

    @property
    def linked(self) -> LinkedDocuments:
        return self._linked

    # ------------------------------------------------------------ cycle de vie / réconciliation

    async def start(self) -> dict[str, Any]:
        """Réconcilie les fichiers de chaque Presentation avec son manifeste (après un arrêt brutal) et rend le bilan.
        Ne lève jamais : une Presentation illisible est une ligne du bilan et une trace `error`."""

        done = unreadable = moved = flagged = 0
        try:
            scan = await self._studio.run_blocking("variants_start", None, self._studio.store.scan)
        except Exception as exc:  # noqa: BLE001 - intentional: reconciliation is a report, never a reason to stop Core; traced
            self._trace("core.presentation_studio.reconcile_failed", "Reconciliation des variantes impossible",
                        level="error", data={"error": f"{type(exc).__name__}: {exc}"[:300]})
            return {"presentations": 0, "reconciled": 0, "unreadable": 1, "moved": 0, "flagged": 0}
        for presentation_id in scan.presentation_ids:
            try:
                async with self._studio.exclusive():
                    report = await self._reconcile_locked(presentation_id)
                done += 1
                moved += len(report.moves)
                flagged += 0 if report.clean or report.moves else 1
            except PresentationStudioError as exc:
                unreadable += 1
                self._trace("core.presentation_studio.reconcile_failed", "Reconciliation des variantes impossible",
                            level="error", data={"presentation_id": presentation_id, "code": exc.code.value})
        return {"presentations": len(scan.presentation_ids), "reconciled": done, "unreadable": unreadable,
                "moved": moved, "flagged": flagged}

    async def reconcile(self, presentation_id: str) -> Reconciliation:
        self._require(presentation_id)
        async with self._studio.exclusive():
            return await self._studio.guarded("reconcile", presentation_id, self._reconcile_locked(presentation_id))

    async def _ensure_reconciled_locked(self, presentation_id: str) -> None:
        if presentation_id not in self._reconciled:
            await self._reconcile_locked(presentation_id)

    async def _reconcile_locked(self, presentation_id: str, *, deep: bool = False) -> Reconciliation:
        """Accorde les fichiers au manifeste : un fichier dans le mauvais dossier est replacé (opération interrompue), le reste est
        **rapporté**. Appelé sous le verrou. `deep` ajoute les documents liés qu'aucune variante ne cite (lit tous les fichiers)."""

        store = self._studio.store
        presentation = await self._studio.load_presentation_locked(presentation_id)
        live_files = await self._studio.run_blocking("reconcile", presentation_id, store.list_documents, presentation_id, "variants")
        archive_files = await self._studio.run_blocking("reconcile", presentation_id, store.list_documents, presentation_id, "archive")
        plan = reconcile_plan(live_ids=[n.variant_id for n in presentation.variants],
                              archived_ids=[a.variant_id for a in presentation.archived],
                              live_files=live_files, archive_files=archive_files)
        for variant_id, to in plan.moves:
            await self._studio.run_blocking("reconcile", presentation_id, store.move_variant, presentation_id, variant_id,
                                            "variants" if to == "live" else "archive")
        orphan_linked: dict[str, tuple[str, ...]] = {}
        unverified: tuple[str, ...] = ()
        if deep:
            orphan_linked, unverified = await self._orphan_linked_locked(presentation_id, presentation)
        report = replace(plan, orphan_linked=orphan_linked, unverified=unverified)
        self._reconciled.add(presentation_id)
        self._reports[presentation_id] = {**report.to_dict(), "at": stamp(self._studio.now())}
        if plan.moves:
            self._trace("core.presentation_studio.reconciled",
                        "Operation interrompue annulee: fichiers de variante replaces selon le manifeste", level="warning",
                        data={"presentation_id": presentation_id, "moved": len(plan.moves),
                              "variants": [i for i, _ in plan.moves][:MAX_REPORTED]})
        if plan.orphan_variants or plan.duplicate_files or plan.missing or any(orphan_linked.values()):
            self._trace("core.presentation_studio.reconcile_orphans",
                        "Fichiers que le manifeste ne nomme pas (rapportes, jamais adoptes ni supprimes) ou fichiers absents",
                        level="warning" if not plan.missing else "error",
                        data={"presentation_id": presentation_id, "orphan_variants": list(plan.orphan_variants)[:MAX_REPORTED],
                              "duplicate_files": list(plan.duplicate_files)[:MAX_REPORTED],
                              "missing": list(plan.missing)[:MAX_REPORTED],
                              "orphan_linked": {k: list(v)[:MAX_REPORTED] for k, v in orphan_linked.items()}})
        return report

    async def _orphan_linked_locked(self, presentation_id: str, presentation: Presentation
                                    ) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...]]:
        """Les documents liés qu'aucune variante (vivante ou archivée) ne cite. Si un fichier de variante est illisible ou absent, ce
        qu'il citait est inconnu : rien n'est déclaré orphelin dans ce cas (`unverified` nomme ces variantes)."""

        variants: list[PresentationVariant] = []
        unverified: list[str] = []
        for entry in presentation.variants:
            try:
                variants.append(await self._studio.load_variant_locked(presentation_id, entry.variant_id))
            except PresentationStudioError:
                unverified.append(entry.variant_id)  # reported as `missing` / unreadable by its own row
        for archived in presentation.archived:
            try:
                variants.append(await self._read_archived_locked(presentation_id, archived.variant_id))
            except PresentationStudioError:
                unverified.append(archived.variant_id)
        if unverified:
            return {}, tuple(sorted(unverified))
        found: dict[str, tuple[str, ...]] = {}
        for kind in self._linked.kinds:
            stored = await self._studio.run_blocking("reconcile", presentation_id, self._studio.store.list_documents,
                                                     presentation_id, kind.area)
            found[kind.name] = tuple(sorted(set(stored) - self._linked.referenced(variants, kind)))
        return found, ()

    async def check(self, presentation_id: str) -> dict[str, Any]:
        """Un rapport **en lecture seule** et complet (lit tous les fichiers) : ce que la réconciliation ferait et les orphelins liés."""

        self._require(presentation_id)

        async def work() -> dict[str, Any]:
            async with self._studio.exclusive():
                presentation = await self._studio.load_presentation_locked(presentation_id)
                store = self._studio.store
                live = await self._studio.run_blocking("check", presentation_id, store.list_documents, presentation_id, "variants")
                arch = await self._studio.run_blocking("check", presentation_id, store.list_documents, presentation_id, "archive")
                plan = reconcile_plan(live_ids=[n.variant_id for n in presentation.variants],
                                      archived_ids=[a.variant_id for a in presentation.archived],
                                      live_files=live, archive_files=arch)
                linked, unverified = await self._orphan_linked_locked(presentation_id, presentation)
            return replace(plan, orphan_linked=linked, unverified=unverified).to_dict()

        return await self._studio.guarded("check", presentation_id, work())

    # ------------------------------------------------------------ lecture

    async def graph(self, presentation_id: str, *, include_archived: bool = False) -> dict[str, Any]:
        """Le graphe : un noeud par variante vivante (et archivée sur demande), parent, numéro, titre, raison, auteur, sources,
        aperçu, état. `reconciliation` : le dernier bilan connu de cette Presentation (`null` avant la première réconciliation)."""

        self._require(presentation_id)
        return await self._studio.guarded("graph", presentation_id, self._graph(presentation_id, include_archived))

    async def _graph(self, presentation_id: str, include_archived: bool) -> dict[str, Any]:
        async with self._studio.exclusive():
            presentation = await self._studio.load_presentation_locked(presentation_id)
            variants = await self._load_live_locked(presentation_id, presentation)
            nodes = [self._node(entry, variants[entry.variant_id], presentation.active_variant_id)
                     for entry in presentation.variants]
            if include_archived:
                for entry in presentation.archived:
                    nodes.append(await self._archived_node_locked(presentation_id, entry))
        return {"presentation_id": presentation_id, "revision": presentation.revision,
                "variant_counter": presentation.variant_counter, "active_variant_id": presentation.active_variant_id,
                "nodes": nodes, "archived_count": len(presentation.archived),
                "reconciliation": self._reports.get(presentation_id)}

    @staticmethod
    def _node(entry: VariantIndexEntry, variant: PresentationVariant, active: str) -> dict[str, Any]:
        return {"variant_id": entry.variant_id, "variant_number": entry.variant_number, "title": variant.title,
                "parent_variant_id": variant.parent_variant_id, "rationale": entry.rationale,
                "created_by": entry.created_by, "sources": list(entry.sources), "preview_id": entry.preview_id,
                "revision": variant.revision, "created_at": variant.created_at, "updated_at": variant.updated_at,
                "scene_count": len(variant.scenes), "active": entry.variant_id == active, "state": "live"}

    async def _archived_node_locked(self, presentation_id: str, entry: Any) -> dict[str, Any]:
        node = {**entry.node.to_dict(), "parent_variant_id": entry.parent_variant_id, "state": "archived",
                "active": False, "archived_at": entry.archived_at, "archived_by": entry.archived_by,
                "batch_id": entry.batch_id, "title": None}
        try:
            node["title"] = (await self._read_archived_locked(presentation_id, entry.variant_id)).title
        except PresentationStudioError as exc:
            node["problem"] = exc.code.value  # visible in the node, never hides the other nodes
        return node

    async def pin_index(self) -> dict[tuple[str, str], frozenset[tuple[str, int]]]:
        """Les pins `(prefab_id, version)` de **chaque** variante de **chaque** Presentation, archivées comprises : une variante
        archivée se restaure, ses versions de source ne doivent donc pas vieillir hors du dernier lot (`docs/prefabs.md`,
        rétention). Même forme que `PresentationStudioService.pin_index` de la Slice 06 : une variable de plus pour le registre."""

        index: dict[tuple[str, str], frozenset[tuple[str, int]]] = {}
        scan = await self._studio.run_blocking("pin_index", None, self._studio.store.scan)
        if scan.problems:
            raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"{len(scan.problems)} presentation folder(s) are unreadable")
        for presentation_id in scan.presentation_ids:
            async with self._studio.exclusive():
                presentation = await self._studio.load_presentation_locked(presentation_id)
                for entry in presentation.variants:
                    variant = await self._studio.load_variant_locked(presentation_id, entry.variant_id)
                    index[(presentation_id, entry.variant_id)] = variant_pins(variant)
                for archived in presentation.archived:
                    variant = await self._read_archived_locked(presentation_id, archived.variant_id)
                    index[(presentation_id, archived.variant_id)] = variant_pins(variant)
        return index

    # ------------------------------------------------------------ brancher

    async def create_branch(self, presentation_id: str, raw: object) -> dict[str, Any]:
        """Crée une branche depuis `source_variant_id` (défaut : la variante active) : copie profonde de la variante **et** de
        ses documents liés sous de nouveaux ids, jamais de prefab publié (les épingles sont partagées), numéro alloué depuis
        `variant_counter` (durablement, **avant** toute écriture de la branche)."""

        self._require(presentation_id)
        request = parse_branch(raw)
        answer, event = await self._studio.guarded(
            "create_branch", presentation_id, self._create_branch(presentation_id, request))
        self._announce(event, "created", request.actor, answer["node"]["variant_number"], None)
        return answer

    async def _create_branch(self, presentation_id: str, request: Any) -> tuple[dict[str, Any], tuple[str, str, int]]:
        async with self._studio.exclusive():
            await self._ensure_reconciled_locked(presentation_id)
            presentation = await self._studio.load_presentation_locked(presentation_id)
            self._check_expected(presentation, request.expected_revision)
            source_id = request.source_variant_id or presentation.active_variant_id
            if source_id not in {n.variant_id for n in presentation.variants}:
                raise PresentationStudioError(C.UNKNOWN_VARIANT, f"{source_id} is not a live variant of this presentation")
            variants = await self._load_live_locked(presentation_id, presentation)
            source = variants[source_id]
            self._linked.refuse_unsupported(source)  # fail closed, before any write
            new_id = new_variant_id()
            prepared = [await kind.prepare(presentation_id, source, new_id, self._studio.now())
                        for kind in self._linked.kinds]  # reads only: a broken source refuses the branch before a number is spent
            number = next_number(presentation.variant_counter)
            at = stamp(self._studio.now())
            entry = VariantIndexEntry(new_id, number, request.rationale, request.actor, (source_id,), None)
            allocated = self._build(with_allocation, presentation, at)
            committed = self._build(with_node, allocated, entry, activate=request.activate,
                                    stamp_text=stamp(self._studio.now()))
            self._validate_candidate(committed, {**self._parents(variants), new_id: source_id})
            self._check_fits(committed)  # the final manifest must fit BEFORE the first write (limit_reached)
            step = "allocate"
            try:
                await self._studio.write_manifest_locked("branch_allocate", allocated)
                self._pause("allocated")
                step = "linked"
                refs: dict[str, str | None] = {}
                copies = prepared
                for kind, copy in zip(self._linked.kinds, prepared):
                    if copy.write is not None:
                        await copy.write()
                    refs[kind.field] = copy.new_ref
                    self._pause(f"linked:{kind.name}")
                step = "variant"
                branch = replace(source, variant_id=new_id, variant_number=number, title=request.title,
                                 parent_variant_id=source_id, revision=1, created_at=at, updated_at=at, **refs)
                await self._studio.persist_variant_locked("branch", presentation_id, source, branch, relink=True)
                self._pause("variant_written")
                step = "manifest"
                await self._studio.write_manifest_locked("branch_commit", committed)
                self._pause("committed")
            except BaseException as exc:
                self._reconciled.discard(presentation_id)  # the disk may hold a half-done state: reconcile before the next operation
                if isinstance(exc, Exception):
                    self._trace("core.presentation_studio.branch_failed",
                                "Branche interrompue: numero reserve (jamais reutilise), fichiers eventuels rapportes a la reprise",
                                level="error", data={"presentation_id": presentation_id, "variant_id": new_id,
                                                     "number": number, "step": step,
                                                     "code": getattr(getattr(exc, "code", None), "value", type(exc).__name__)})
                raise
            await self._verify_locked(presentation_id, "create_branch")
        node = self._node(entry, branch, committed.active_variant_id)
        answer = {"variant": branch.to_document(), "node": node, "presentation_revision": committed.revision,
                  "activated": request.activate, "source_variant_id": source_id,
                  "linked": [copy.to_dict() for copy in copies]}
        return answer, (presentation_id, new_id, committed.revision)

    # ------------------------------------------------------------ activer / renommer

    async def switch(self, presentation_id: str, variant_id: str, raw: object = None) -> dict[str, Any]:
        """Rend `variant_id` active (le manifeste seul, atomiquement). Les anneaux d'annulation par variante sont gardés ; aucun
        état ne passe d'une branche à l'autre : chaque variante a son fichier, sa partition, son anneau."""

        self._require(presentation_id, variant_id)
        data = parse_expected({} if raw is None else raw, "switch")
        result, event = await self._studio.guarded("switch", presentation_id, self._switch(presentation_id, variant_id, data))
        if result["changed"]:
            self._announce(event, "switched", data.get("actor", NodeActor.USER), result["variant_number"], None)
        return result

    async def _switch(self, presentation_id: str, variant_id: str, data: Mapping[str, Any]) -> tuple[dict[str, Any], Any]:
        async with self._studio.exclusive():
            await self._ensure_reconciled_locked(presentation_id)
            presentation = await self._studio.load_presentation_locked(presentation_id)
            self._check_expected(presentation, data.get("expected_revision"))
            entry = self._live_entry(presentation, variant_id)
            await self._studio.load_variant_locked(presentation_id, variant_id)  # never switch to a file that cannot be read
            if presentation.active_variant_id == variant_id:
                return ({"changed": False, "active_variant_id": variant_id, "variant_number": entry.variant_number,
                         "presentation_revision": presentation.revision}, None)
            candidate = self._build(with_active, presentation, variant_id, stamp(self._studio.now()))
            self._validate_candidate(candidate, None)
            self._pause("switch_validated")
            await self._studio.write_manifest_locked("switch", candidate)
            self._pause("switched")
        return ({"changed": True, "active_variant_id": variant_id, "variant_number": entry.variant_number,
                 "presentation_revision": candidate.revision}, (presentation_id, variant_id, candidate.revision))

    async def rename(self, presentation_id: str, variant_id: str, raw: object) -> dict[str, Any]:
        self._require(presentation_id, variant_id)
        data = parse_expected(raw, "rename", {"title"})
        _check_title("title", data["title"])
        result, event = await self._studio.guarded("rename", presentation_id,
                                                   self._rename(presentation_id, variant_id, data))
        if result["changed"]:
            self._announce(event, "renamed", data.get("actor", NodeActor.USER), result["variant_number"], None)
        return result

    async def _rename(self, presentation_id: str, variant_id: str, data: Mapping[str, Any]) -> tuple[dict[str, Any], Any]:
        async with self._studio.exclusive():
            await self._ensure_reconciled_locked(presentation_id)
            presentation = await self._studio.load_presentation_locked(presentation_id)
            self._check_expected(presentation, data.get("expected_revision"))
            entry = self._live_entry(presentation, variant_id)
            current = await self._studio.load_variant_locked(presentation_id, variant_id)
            if current.title == data["title"]:
                return ({"changed": False, "variant_id": variant_id, "variant_number": entry.variant_number,
                         "title": current.title, "revision": current.revision}, None)
            saved = replace(current, title=data["title"], revision=current.revision + 1, updated_at=stamp(self._studio.now()))
            await self._studio.persist_variant_locked("rename", presentation_id, current, saved)
        return ({"changed": True, "variant_id": variant_id, "variant_number": entry.variant_number, "title": saved.title,
                 "revision": saved.revision}, (presentation_id, variant_id, saved.revision))

    # ------------------------------------------------------------ archiver / restaurer

    async def plan_archive(self, presentation_id: str, variant_id: str, raw: object = None) -> dict[str, Any]:
        """**À blanc** : l'ensemble exact (ids, numéros, titres) que `archive` toucherait et, si rien ne l'empêche, le jeton de
        confirmation lié à cet ensemble, à ses titres, à la révision de la Presentation et au nouvel actif choisi. Écrit rien."""

        self._require(presentation_id, variant_id)
        data = parse_expected({} if raw is None else raw, "plan", optional=frozenset({"activate_variant_id"}))
        if data.get("activate_variant_id") is not None:
            _check_id("activate_variant_id", data["activate_variant_id"], VARIANT_ID)
        return await self._studio.guarded("plan_archive", presentation_id, self._plan_archive(presentation_id, variant_id, data))

    async def _plan_archive(self, presentation_id: str, variant_id: str, data: Mapping[str, Any]) -> dict[str, Any]:
        async with self._studio.exclusive():
            await self._ensure_reconciled_locked(presentation_id)
            plan, _ = await self._plan_locked(presentation_id, variant_id, data.get("activate_variant_id"),
                                              data.get("expected_revision"))
        token = None if plan.blocked else issue_confirmation(self._secret, plan, int(self._epoch()))
        self._trace("core.presentation_studio.archive_planned", "Archivage planifie a blanc (rien n'est ecrit)",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "count": len(plan.rows),
                          "blocked": plan.blocked, "revision": plan.revision})
        return {"plan": plan.to_dict(), "confirmation": token, "expires_in_s": None if token is None else CONFIRMATION_TTL_S}

    async def archive(self, presentation_id: str, variant_id: str, raw: object) -> dict[str, Any]:
        """Archive `variant_id` **et ses descendants** : leurs fichiers sont *déplacés* vers `archive/` (jamais détruits), réversible
        par `restore`. Exige le jeton d'un plan portant sur l'ensemble **actuel** ; l'actif ne s'archive pas tant qu'un autre n'est pas
        choisi (`activate_variant_id`). Appelle `PresentationStudioHistory.drop_variant` pour chaque variante archivée."""

        self._require(presentation_id, variant_id)
        data = parse_expected(raw, "archive", set(), frozenset({"confirmation", "activate_variant_id"}))
        if data.get("activate_variant_id") is not None:
            _check_id("activate_variant_id", data["activate_variant_id"], VARIANT_ID)
        answer, event = await self._studio.guarded("archive", presentation_id, self._archive(presentation_id, variant_id, data))
        self._announce(event, "archived", data.get("actor", NodeActor.USER), answer["root_variant_number"], answer["count"])
        self._drop_rings(presentation_id, [row["variant_id"] for row in answer["archived"]])
        return answer

    async def _archive(self, presentation_id: str, variant_id: str, data: Mapping[str, Any]) -> tuple[dict[str, Any], Any]:
        async with self._studio.exclusive():
            await self._ensure_reconciled_locked(presentation_id)
            plan, context = await self._plan_locked(presentation_id, variant_id, data.get("activate_variant_id"),
                                                    data.get("expected_revision"))
            presentation, variants = context
            if plan.blocked:
                raise PresentationStudioError(C.ACTIVE_VARIANT_PROTECTED, plan.blocked_reason)
            check_confirmation(self._secret, plan, data.get("confirmation"), int(self._epoch()))
            at = stamp(self._studio.now())
            batch = new_batch_id()
            parents = self._parents(variants)
            candidate = self._build(with_archived, presentation, plan, parents, actor=data.get("actor", NodeActor.USER),
                                    batch_id=batch, stamp_text=at)
            remaining = {i: p for i, p in parents.items() if i not in set(plan.ids)}
            self._validate_candidate(candidate, remaining)
            self._check_fits(candidate)  # must fit BEFORE the first file moves
            moved = await self._move_all(presentation_id, sorted(plan.ids, key=lambda i: -_number(presentation, i)),
                                         "archive", "archive_failed")
            try:
                await self._studio.write_manifest_locked("archive", candidate)
                self._pause("manifest_written")
            except BaseException:
                self._reconciled.discard(presentation_id)
                await self._put_back(presentation_id, moved, "variants")
                raise
            await self._verify_locked(presentation_id, "archive")
        answer = {"archived": [row.to_dict() for row in plan.rows], "count": len(plan.rows), "batch_id": batch,
                  "root_variant_id": variant_id, "root_variant_number": _number(presentation, variant_id),
                  "active_variant_id": candidate.active_variant_id, "presentation_revision": candidate.revision,
                  "restorable": True}
        return answer, (presentation_id, variant_id, candidate.revision)

    async def _plan_locked(self, presentation_id: str, variant_id: str, activate: str | None,
                           expected: int | None) -> tuple[ArchivePlan, tuple[Presentation, dict[str, PresentationVariant]]]:
        presentation = await self._studio.load_presentation_locked(presentation_id)
        self._check_expected(presentation, expected)
        variants = await self._load_live_locked(presentation_id, presentation)
        plan = plan_archive(presentation_id=presentation_id, revision=presentation.revision, root=variant_id,
                            live=presentation.variants, parents=self._parents(variants),
                            titles={i: v.title for i, v in variants.items()}, active=presentation.active_variant_id,
                            activate=activate, archived_count=len(presentation.archived))
        return plan, (presentation, variants)

    async def restore(self, presentation_id: str, variant_id: str, raw: object = None) -> dict[str, Any]:
        """Restaure une variante archivée **et ses ancêtres archivés** (un noeud vivant n'a que des ancêtres vivants) ; ses descendants
        archivés seulement avec `with_descendants`. Réversible par un nouvel archivage ; ne détruit rien, donc sans jeton."""

        self._require(presentation_id, variant_id)
        data = parse_expected({} if raw is None else raw, "restore", optional=frozenset({"with_descendants"}))
        with_descendants = data.get("with_descendants", False)
        if type(with_descendants) is not bool:
            raise _fail("with_descendants must be true or false")
        answer, event = await self._studio.guarded(
            "restore", presentation_id, self._restore(presentation_id, variant_id, with_descendants, data))
        self._announce(event, "restored", data.get("actor", NodeActor.USER), answer["variant_number"], answer["count"])
        return answer

    async def _restore(self, presentation_id: str, variant_id: str, with_descendants: bool,
                       data: Mapping[str, Any]) -> tuple[dict[str, Any], Any]:
        async with self._studio.exclusive():
            await self._ensure_reconciled_locked(presentation_id)
            presentation = await self._studio.load_presentation_locked(presentation_id)
            self._check_expected(presentation, data.get("expected_revision"))
            plan = plan_restore(presentation_id=presentation_id, variant_id=variant_id, live=presentation.variants,
                                archived=presentation.archived, with_descendants=with_descendants)
            back = await self._load_archived_set_locked(presentation_id, presentation, plan.ids)
            variants = await self._load_live_locked(presentation_id, presentation)
            candidate = self._build(with_restored, presentation, plan, stamp(self._studio.now()))
            self._validate_candidate(candidate, {**self._parents(variants), **self._parents(back)})
            self._check_fits(candidate)
            moved = await self._move_all(presentation_id, list(plan.ids), "variants", "restore_failed")
            try:
                await self._studio.write_manifest_locked("restore", candidate)
                self._pause("manifest_written")
            except BaseException:
                self._reconciled.discard(presentation_id)
                await self._put_back(presentation_id, moved, "archive")
                raise
            await self._verify_locked(presentation_id, "restore")
        answer = {"restored": [{"variant_id": i, "variant_number": n, "title": back[i].title}
                               for i, n in zip(plan.ids, plan.numbers)], "count": len(plan.ids),
                  "variant_id": variant_id, "variant_number": dict(zip(plan.ids, plan.numbers))[variant_id],
                  "presentation_revision": candidate.revision}
        return answer, (presentation_id, variant_id, candidate.revision)

    async def _load_archived_set_locked(self, presentation_id: str, presentation: Presentation,
                                        ids: tuple[str, ...]) -> dict[str, PresentationVariant]:
        """Les fichiers archivés à restaurer, lus **avant** tout déplacement : leur parent doit être celui que le manifeste a retenu."""

        loaded: dict[str, PresentationVariant] = {}
        by_id = {a.variant_id: a for a in presentation.archived}
        for variant_id in ids:
            variant = await self._read_archived_locked(presentation_id, variant_id)
            entry = by_id[variant_id]
            if variant.parent_variant_id != entry.parent_variant_id or variant.variant_number != entry.variant_number:
                raise PresentationStudioError(C.CORRUPT_DOCUMENT,
                                              f"archived variant {variant_id}: its file disagrees with the manifest (parent or number)")
            loaded[variant_id] = variant
        return loaded

    # ------------------------------------------------------------ déplacements (archive / restauration)

    async def _move_all(self, presentation_id: str, ids: list[str], to: str, failure_kind: str) -> list[str]:
        """Un renommage par fichier. Un échec (pas un arrêt brutal) remet en place ce qui a déjà bougé, puis lève : le manifeste n'a pas
        été touché, l'état est celui d'avant. Un arrêt brutal ici est replacé par `reconcile` au prochain démarrage."""

        store = self._studio.store
        moved: list[str] = []
        back = "variants" if to == "archive" else "archive"
        try:
            for index, variant_id in enumerate(ids, start=1):
                await self._studio.run_blocking("move", presentation_id, store.move_variant, presentation_id, variant_id, to)
                moved.append(variant_id)
                self._pause(f"moved:{index}")
        except BaseException as exc:  # a cancellation too: files may already have moved
            self._reconciled.discard(presentation_id)  # whatever happens next, the next operation reconciles first
            if not isinstance(exc, Exception):
                raise
            self._trace(f"core.presentation_studio.{failure_kind}", "Deplacement de fichiers de variante interrompu: remis en place",
                        level="error", data={"presentation_id": presentation_id, "moved": len(moved), "wanted": len(ids),
                                             "code": getattr(getattr(exc, "code", None), "value", type(exc).__name__)})
            await self._put_back(presentation_id, moved, back)
            raise
        return moved

    async def _put_back(self, presentation_id: str, moved: list[str], to: str) -> None:
        for variant_id in reversed(moved):
            try:
                await self._studio.run_blocking("put_back", presentation_id, self._studio.store.move_variant, presentation_id,
                                                variant_id, to)
            except Exception as exc:  # noqa: BLE001 - recorded: the next reconcile (the manifest is the truth) finishes the job
                self._trace("core.presentation_studio.reconcile_failed", "Fichier de variante non remis en place (reprise au demarrage)",
                            level="error", data={"presentation_id": presentation_id, "variant_id": variant_id,
                                                 "code": getattr(getattr(exc, "code", None), "value", type(exc).__name__)})

    # ------------------------------------------------------------ interne

    @staticmethod
    def _require(presentation_id: str, variant_id: str | None = None) -> None:
        if not is_presentation_id(presentation_id):
            raise PresentationStudioError(C.UNKNOWN_PRESENTATION, "unknown presentation id")
        if variant_id is not None and not VARIANT_ID.fullmatch(variant_id):
            raise PresentationStudioError(C.UNKNOWN_VARIANT, "unknown variant id")

    @staticmethod
    def _check_expected(presentation: Presentation, expected: int | None) -> None:
        if expected is not None and presentation.revision != expected:
            raise PresentationStudioError(
                C.STALE_REVISION, f"{presentation.presentation_id} is at revision {presentation.revision}, not {expected}: reload, then retry")

    @staticmethod
    def _live_entry(presentation: Presentation, variant_id: str) -> VariantIndexEntry:
        for entry in presentation.variants:
            if entry.variant_id == variant_id:
                return entry
        archived = any(a.variant_id == variant_id for a in presentation.archived)
        raise PresentationStudioError(
            C.UNKNOWN_VARIANT, f"{variant_id} is archived: restore it first" if archived
            else f"{variant_id} is not a variant of this presentation")

    @staticmethod
    def _parents(variants: Mapping[str, PresentationVariant]) -> dict[str, str | None]:
        return {i: v.parent_variant_id for i, v in variants.items()}

    async def _load_live_locked(self, presentation_id: str, presentation: Presentation) -> dict[str, PresentationVariant]:
        loaded: dict[str, PresentationVariant] = {}
        for entry in presentation.variants:
            try:
                loaded[entry.variant_id] = await self._studio.load_variant_locked(presentation_id, entry.variant_id)
            except PresentationStudioError as exc:
                if exc.code is C.UNKNOWN_VARIANT:  # indexed but absent: a torn state, never "unknown"
                    raise PresentationStudioError(
                        C.CORRUPT_DOCUMENT, f"{presentation_id}: indexed variant {entry.variant_id} is missing") from None
                raise
        return loaded

    async def _read_archived_locked(self, presentation_id: str, variant_id: str) -> PresentationVariant:
        text = await self._studio.run_blocking("read_archive", presentation_id, self._studio.store.read_archived_variant,
                                               presentation_id, variant_id)
        variant = self._studio.parse_stored(parse_variant, text, f"{presentation_id}/archive/{variant_id}")
        if (variant.presentation_id, variant.variant_id) != (presentation_id, variant_id):
            raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"{presentation_id}/archive/{variant_id}: file names another variant")
        return variant

    @staticmethod
    def _check_fits(presentation: Presentation) -> None:
        """Le manifeste futur tient dans 256 Kio **avant** la première écriture ; sinon un refus qui nomme la cause et la sortie."""

        try:
            dump_document(presentation.to_document())
        except PresentationStudioError as exc:
            if exc.code is not C.LIMIT_REACHED:
                raise
            raise PresentationStudioError(
                C.LIMIT_REACHED, "the presentation index would exceed its 256 KiB document limit (many branches with long "
                                 "rationales): restore some archived branches, or clear archive/ by hand with Core stopped "
                                 "(docs/OPERATIONS.md)") from exc

    @staticmethod
    def _build(transition: Callable[..., Presentation], *args: Any, **kwargs: Any) -> Presentation:
        """Une transition pure du graphe. Son invariant refuse un candidat invalide : pour l'appelant c'est un **défaut de ce service**
        (un état qui ne devait pas se présenter), pas une entrée refusée ; les limites (`limit_reached`) gardent leur code."""

        try:
            return transition(*args, **kwargs)
        except PresentationStudioError as exc:
            if exc.code is not C.INVALID_PRESENTATION:
                raise
            raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"graph invariant refused before writing: {exc.message}") from exc

    @staticmethod
    def _validate_candidate(candidate: Presentation, live_parents: Mapping[str, str | None] | None) -> None:
        """L'invariant du graphe **avant** d'écrire : un candidat invalide n'atteint jamais le disque."""

        try:
            validate_graph(candidate.variants, candidate.archived, active=candidate.active_variant_id,
                           counter=candidate.variant_counter, live_parents=live_parents)
        except PresentationStudioError as exc:
            raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"graph invariant refused before writing: {exc.message}") from exc

    async def _verify_locked(self, presentation_id: str, op: str) -> None:
        """L'invariant **après** l'écriture, sur ce que le disque contient (jamais sur ce que nous croyons avoir écrit)."""

        try:
            await self._studio.load_view_locked(presentation_id)
        except PresentationStudioError as exc:
            self._trace("core.presentation_studio.graph_invalid", "Le graphe lu apres l'operation viole son invariant",
                        level="error", data={"presentation_id": presentation_id, "op": op, "code": exc.code.value})
            raise

    def _pause(self, step: str) -> None:
        if self._checkpoint is not None:
            self._checkpoint(step)

    def _drop_rings(self, presentation_id: str, variant_ids: list[str]) -> None:
        """Entrée de la Slice 08 : archiver une variante vide son anneau d'annulation (`variant_archived`)."""

        if self._history is None:
            return
        for variant_id in variant_ids:
            try:
                self._history.drop_variant(presentation_id, variant_id, DropReason.VARIANT_ARCHIVED)
            except Exception as exc:  # noqa: BLE001 - recorded: a lingering ring is harmless (bounded LRU), the archive stands
                self._trace("core.presentation_studio.history_drop_failed", "Anneau d'annulation non vide apres archivage",
                            level="warning", data={"presentation_id": presentation_id, "variant_id": variant_id,
                                                   "error": f"{type(exc).__name__}: {exc}"[:200]})

    def drop_presentation(self, presentation_id: str) -> None:
        """Aucune suppression de Presentation n'existe encore (l'archivage est le seul retrait) ; ce point d'entrée est celui que
        l'opération future DOIT appeler (Slice 08 : `PresentationStudioHistory.drop_presentation`)."""

        if self._history is not None:
            self._history.drop_presentation(presentation_id)

    def _announce(self, identity: Any, op: str, actor: str, number: int | None, count: int | None) -> None:
        """Évènement + ligne de journal, **après** le verrou. Ne défait jamais l'opération."""

        if identity is None:
            return
        presentation_id, variant_id, revision = identity
        recorded = False
        if self._events is not None:
            try:
                recorded = self._events.changed(presentation_id=presentation_id, variant_id=variant_id, op=op, actor=actor,
                                                revision=revision, variant_number=number, count=count) is not None
            except Exception as exc:  # noqa: BLE001 - recorded at warning: the operation stands
                self._trace("core.presentation_studio.event_failed", "Evenement de variante non enregistre", level="warning",
                            data={"presentation_id": presentation_id, "op": op, "error": f"{type(exc).__name__}: {exc}"[:200]})
        self._trace(f"core.presentation_studio.variant_{op}", f"Variante {op}",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "variant_number": number,
                          "revision": revision, "actor": actor, "count": count, "event_recorded": recorded})

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
        self._studio.trace(kind, message, level=level, data=data)


def _number(presentation: Presentation, variant_id: str) -> int:
    return next(n.variant_number for n in presentation.variants if n.variant_id == variant_id)


def variant_pins(variant: PresentationVariant) -> frozenset[tuple[str, int]]:
    """Les `(prefab_id, version)` qu'une variante nomme : le pin de chaque scène et, depuis la Slice 06, son dernier pin valide."""

    pins: set[tuple[str, int]] = set()
    for scene in variant.scenes:
        pins.add((scene.prefab.prefab_id, scene.prefab.version))
        fallback = getattr(scene, "last_valid_pin", None)
        if fallback is not None:
            pins.add((fallback.prefab_id, fallback.version))
    return frozenset(pins)
