"""Service Core des Presentations (handoff jarvis-interactive-presentation-studio, Slice 02).

Seule autorité sur les documents d'une Presentation (`docs/presentation-studio.md`
› *Presentation contract*) : crée, charge, valide, sauvegarde, liste. Core est
l'unique écrivain ; les écritures sont sérialisées par un verrou, les accès
disque passent par `asyncio.to_thread`.

- **create** : Presentation + variante n° 1 active, publiées d'un seul renommage.
- **get / get_variant** : relit le disque à chaque appel (pas de cache : la source
  de vérité est le fichier, y compris après un redémarrage) et revalide tout. Un
  document plus récent que ce Core -> `unsupported_schema_version`, un document
  illisible ou incohérent -> `corrupt_document` ; jamais une lecture au mieux.
- **save_presentation / save_variant** : remplacement entier sous
  `expected_revision` (`stale_revision` sinon : relire puis recommencer). Chaque
  sauvegarde relit d'abord le document stocké, donc un fichier d'une version
  future n'est jamais écrasé. `save_variant` ne touche que le fichier de la
  variante ; `save_presentation` que `presentation.json` (la révision de la
  Presentation ne compte que ses changements propres). Un futur changement qui
  touche plusieurs fichiers écrira les variantes d'abord, le manifeste en dernier.
- **list** : un résumé par Presentation lisible, plus la liste visible des
  dossiers refusés (`problems`) : un document corrompu ne disparaît pas du listage.
- **validate** : documents au format disque, rien n'est écrit.
- **Partition (Slice 10)** : `create_score` / `get_score` / `save_score` sur la partition d'une
  variante (`scores/<score_id>.json`, révision propre). Chaque écriture est validée contre la variante
  (`check_score` : scènes, contrôles, ancres, bornes) et, avec un catalogue, contre les manifestes
  (`check_score_values`). La création écrit la partition **puis** la variante (qui reçoit `score_id`) : un arrêt entre
  les deux laisse un fichier de partition orphelin, jamais référencé et inoffensif. `get_score` relit les références
  contre la variante *actuelle* et rend `problems` (une scène retirée depuis ne casse pas la lecture, elle se voit).
- **Direction artistique (Slice 09)** : `create_art_direction` / `get_art_direction` / `save_art_direction` /
  `create_fallback_art_direction` / `art_direction_candidates` / `require_art_direction` sur la DA d'une variante
  (`art_directions/<art_direction_id>.json`, révision propre, même mécanique que la partition : DA écrite **puis**
  variante, lien rompu réparé par `create`, `art_direction_id` propriété de ces routes). Les candidats exploratoires sont
  *calculés* (`diverge`, déterministes), jamais stockés ; adopter l'un d'eux = `create` ou `save` de son contenu.
- **Scènes (Slice 04)** : avec un catalogue de prefabs (`PrefabCatalog`, Core y met
  `PrefabService`), `save_variant` vérifie chaque scène **nouvelle ou modifiée**
  (pin existant, valeurs valides, contrôles dans le manifeste) avant d'écrire, et
  `describe_scene` répond à « qu'est-ce qui s'édite sur cette scène ? ». Sans catalogue
  (bancs d'essai du magasin) la sauvegarde ne contrôle que la forme et la description
  est refusée : jamais un contrôle présenté comme valide sans manifeste.

Diagnostics (`core.presentation_studio.*`, ids et codes, jamais le contenu) : le
chemin normal en `info`, un refus de l'appelant en `info` avec son code, une
panne de données ou de disque et tout imprévu en `error` (ce qui les fait
apparaître dans le visualiseur d'erreurs).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, TypeVar

from jarvis.domain.prefab import canonical_json
from jarvis.domain.presentation_studio import (
    MAX_PRESENTATIONS, MAX_VALIDATION_ERRORS, Presentation, PresentationStudioError, PresentationStudioErrorCode as C,
    PresentationUpdate, PresentationVariant, PresentationView, StudioScene, VariantUpdate, clip, dump_document, is_presentation_id,
    is_variant_id, load_document, new_presentation, parse_create, parse_presentation, parse_presentation_update,
    parse_variant, parse_variant_update, stamp, validate_documents,
)
from jarvis.core.presentation_studio_scene_catalog import SceneCatalog
from jarvis.core.presentation_studio_pins import StudioPinRegistry
from jarvis.domain.presentation_studio_checks import is_scene_id
from jarvis.domain.presentation_studio_score import (
    ActionKind, Score, check_score, check_score_values, new_score, parse_score, parse_score_create, parse_score_update,
    raise_if_incompatible,
)
from jarvis.domain.presentation_studio_art_direction import (
    ArtDirection, ArtDirectionResolution, new_art_direction_document, parse_art_direction, parse_art_direction_create,
    parse_art_direction_update, require_art_direction,
)
from jarvis.domain.presentation_studio_art_direction_authoring import (
    MAX_DIVERGE, SeedContext, diverge, generate_fallback_profile, parse_seed_context,
)
from jarvis.domain.presentation_studio_checks import _check_int, _exact_keys
from jarvis.domain.v2 import utc_now
from jarvis.ports.presentation_studio import PrefabCatalog, PresentationStudioStore
from jarvis.ports.v2 import DiagnosticSink

def variant_pins(scenes: Iterable[StudioScene]) -> frozenset[tuple[str, int]]:
    """Les `(id, version)` qu'un document de variante nomme : le pin de chaque scene et son pin de repli."""

    pins: set[tuple[str, int]] = set()
    for scene in scenes:
        pins.add((scene.prefab.prefab_id, scene.prefab.version))
        if scene.last_valid_pin is not None:
            pins.add((scene.last_valid_pin.prefab_id, scene.last_valid_pin.version))
    return frozenset(pins)


def own_scene_fields(stored: tuple[StudioScene, ...], given: tuple[StudioScene, ...]) -> tuple[StudioScene, ...]:
    """Les champs de rechargement a chaud appartiennent au service, pas au corps d'une requete (meme regle que `score_id`).

    Une scene inchangee garde ses valeurs stockees ; si son pin change par une sauvegarde ordinaire, le compteur monte de
    un et le pin de repli est efface (un changement manuel n'est pas une edition non verifiee) ; une scene neuve
    repart de zero. Une valeur que l'appelant fait differer de celle-la est **refusee**, pas corrigee en silence.
    """

    by_id = {scene.scene_id: scene for scene in stored}
    out: list[StudioScene] = []
    for scene in given:
        before = by_id.get(scene.scene_id)
        if before is None:
            if scene.source_revision != 0 or scene.last_valid_pin is not None:
                raise PresentationStudioError(
                    C.INVALID_PRESENTATION,
                    f"scene {scene.scene_id} is new: source_revision and last_valid_pin belong to the hot reload "
                    "(0 and null)")
            out.append(scene)
            continue
        moved = before.prefab != scene.prefab
        allowed_revisions = {before.source_revision, before.source_revision + 1} if moved else {before.source_revision}
        allowed_pins = {None, before.last_valid_pin} if moved else {before.last_valid_pin}
        if scene.source_revision not in allowed_revisions or scene.last_valid_pin not in allowed_pins:
            raise PresentationStudioError(
                C.INVALID_PRESENTATION,
                f"scene {scene.scene_id}: source_revision is {before.source_revision} and last_valid_pin is "
                "owned by the hot reload: a variant save cannot set them (use the source edit route)")
        if moved:
            out.append(replace(scene, source_revision=before.source_revision + 1, last_valid_pin=None))
        else:
            out.append(scene)
    return tuple(out)


T = TypeVar("T")
#: Une Presentation illisible ne doit pas rendre le listage illisible : bornes du rapport de problèmes.
MAX_LISTED_PROBLEMS = 20
#: Rafraîchi à chaque écriture (`updated_at`) : horloge injectable pour les tests.
Clock = Callable[[], datetime]


class _Loaded:
    """Le `ArtDirectionLookup` du domaine sur un document déjà lu sous le verrou (le domaine est synchrone et pur)."""

    def __init__(self, art: ArtDirection | None) -> None:
        self._art = art

    def find(self, presentation_id: str, art_direction_id: str) -> ArtDirection | None:
        return self._art


@dataclass(frozen=True, slots=True)
class Recovery:
    """Le bilan du démarrage (Slice 08) : combien de Presentations, combien de variantes actives rechargées, lesquelles sont illisibles."""

    presentations: int
    active_loaded: int
    unreadable: tuple[Mapping[str, str], ...] = ()
    swept: int = 0
    sweep_failed: int = 0
    #: Presentations whose active variant has not been checked yet: the check runs behind `start()` (it costs about 24 ms per
    #: Presentation, 6 s at the 256 limit, and must not delay Core). `complete` is true once `pending` is 0; until then
    #: `active_loaded` and `unreadable` are partial and say so. A read never waits: it hits the disk and raises its own typed error.
    pending: int = 0
    complete: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"presentations": self.presentations, "active_loaded": self.active_loaded,
                "unreadable": [dict(row) for row in self.unreadable], "swept": self.swept,
                "sweep_failed": self.sweep_failed, "pending": self.pending, "complete": self.complete}


@dataclass(frozen=True, slots=True)
class Listing:
    presentations: tuple[Mapping[str, Any], ...]
    problems: tuple[Mapping[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {"presentations": [dict(row) for row in self.presentations],
                "problems": [dict(row) for row in self.problems]}


class PresentationStudioService:
    def __init__(self, store: PresentationStudioStore, *, diagnostics: DiagnosticSink | None = None,
                 clock: Clock = utc_now, prefabs: PrefabCatalog | None = None,
                 pins: StudioPinRegistry | None = None) -> None:
        self._store = store
        #: Slice 06 : le registre des epinglages (retention des sources). Chaque ecriture de variante y enregistre ses
        #: pins **avant** d'ecrire le fichier (condition d'entree de la Slice 06, `docs/prefabs.md`).
        self._pins = pins
        self._scenes = SceneCatalog(prefabs) if prefabs is not None else None
        self._diagnostics = diagnostics
        self._clock = clock
        self._lock = asyncio.Lock()
        #: Slice 06 (QA-1 B1) : « cette scene est-elle en cours de rechargement ? » (posee par `PresentationStudioReloadService`).
        self._scene_busy: Callable[[str, str, str], bool] | None = None
        #: Bilan du dernier démarrage (`None` avant `start`) : ce qui a été rechargé et ce qui est illisible.
        self.last_recovery: Recovery | None = None
        self._recovery_task: asyncio.Task[None] | None = None

    def set_scene_guard(self, busy: Callable[[str, str, str], bool] | None) -> None:
        """Le rechargement a chaud declare ici ses scenes en vol : une ecriture ordinaire de variante (edition de controles,
        structure, restauration, sauvegarde) qui **modifie ou retire** l'une d'elles est refusee `scene_reloading`. Seul
        `replace_scene_source` (le rechargement lui-meme) passe."""

        self._scene_busy = busy

    async def start(self) -> None:
        """Balaie les restes d'un arrêt brutal puis recharge la variante active de chaque Presentation (reprise, Slice 08).
        Ne lève jamais : un balayage ou une reprise en échec est journalisé en `error` et rendu visible (`last_recovery`)."""

        swept = failed = 0
        try:
            report = await asyncio.to_thread(self._store.sweep)
        except Exception as exc:  # noqa: BLE001 - intentional: a failed sweep never blocks Core; traced below
            self._trace("core.presentation_studio.sweep_failed", "Balayage du magasin des presentations impossible",
                        level="error", data={"error": clip(f"{type(exc).__name__}: {exc}")})
        else:
            swept, failed = len(report.removed), len(report.failed)
            if report.removed:
                self._trace("core.presentation_studio.swept", "Restes d'ecritures interrompues retires",
                            data={"removed": list(report.removed)[:20], "count": len(report.removed)})
            if report.failed:
                self._trace("core.presentation_studio.sweep_failed", "Restes d'ecritures interrompues non retires",
                            level="warning", data={"failed": list(report.failed)[:20]})
        try:
            scan = await self._run("recover", None, self._store.scan)
            unreadable: list[Mapping[str, str]] = [
                {"presentation_id": p.name, "code": C.CORRUPT_DOCUMENT.value, "message": clip(p.reason)} for p in scan.problems]
            self.last_recovery = Recovery(len(scan.presentation_ids), 0, tuple(unreadable[:MAX_LISTED_PROBLEMS]), swept, failed,
                                          pending=len(scan.presentation_ids), complete=not scan.presentation_ids)
            self._recovery_task = asyncio.create_task(self._recover_in_background(scan.presentation_ids, unreadable, swept, failed))
        except Exception as exc:  # noqa: BLE001 - intentional: recovery is a report, never a reason to stop Core; traced
            self._trace("core.presentation_studio.recovery_failed", "Reprise des presentations impossible",
                        level="error", data={"error": clip(f"{type(exc).__name__}: {exc}")})
        self._trace("core.presentation_studio.started", "Magasin des presentations pret", data={})

    async def wait_recovered(self) -> Recovery | None:
        """Attend la fin de la reprise lancée par `start()` (tests, diagnostic) ; ne lève jamais."""

        task = self._recovery_task
        if task is not None:
            await asyncio.wait({task})
        return self.last_recovery

    async def stop(self) -> None:
        """Arrête la reprise si elle tourne encore (elle ne touche à rien, `last_recovery` reste `complete: false`)."""

        task, self._recovery_task = self._recovery_task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait({task})

    async def _recover_in_background(self, ids: tuple[str, ...], unreadable: list[Mapping[str, str]], swept: int,
                                     sweep_failed: int) -> None:
        try:
            await self._recover(ids, unreadable, swept, sweep_failed)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - intentional: a report never stops Core; the failure is traced and the report stays incomplete
            self._trace("core.presentation_studio.recovery_failed", "Reprise des presentations interrompue",
                        level="error", data={"error": clip(f"{type(exc).__name__}: {exc}")})

    async def _recover(self, ids: tuple[str, ...], unreadable: list[Mapping[str, str]], swept: int,
                       sweep_failed: int) -> Recovery:
        """Recharge, depuis le disque seulement, la variante active de chaque Presentation, une à la fois ; chaque lecture de
        disque passe par `asyncio.to_thread` et rend donc la main à la boucle (quelques dizaines de ms par Presentation, jamais un blocage d'ensemble). Un document
        illisible est une ligne `unreadable` avec son code (et une trace `error`) : jamais remplacé par une variante plus
        ancienne, jamais reconstruit depuis un `*.tmp`. Rien n'est écrit. `last_recovery` avance (`pending`)."""

        loaded = 0
        for index, presentation_id in enumerate(ids):
            variant_id = None
            try:
                presentation = await self._load_presentation(presentation_id)
                variant_id = presentation.active_variant_id
                await self._load_variant(presentation_id, variant_id)
                loaded += 1
            except PresentationStudioError as exc:
                code = C.CORRUPT_DOCUMENT if exc.code is C.UNKNOWN_VARIANT else exc.code  # indexed but absent = torn state
                unreadable.append({"presentation_id": presentation_id, "variant_id": variant_id or "",
                                   "code": code.value, "message": exc.message})
                if len(unreadable) <= MAX_LISTED_PROBLEMS:
                    self._trace("core.presentation_studio.recovery_failed", "Variante active illisible au demarrage",
                                level="error", data={"presentation_id": presentation_id, "variant_id": variant_id,
                                                     "code": code.value})
            pending = len(ids) - index - 1
            self.last_recovery = Recovery(len(ids), loaded, tuple(unreadable[:MAX_LISTED_PROBLEMS]), swept, sweep_failed,
                                          pending=pending, complete=pending == 0)
        recovery = Recovery(len(ids), loaded, tuple(unreadable[:MAX_LISTED_PROBLEMS]), swept, sweep_failed)
        self.last_recovery = recovery
        self._trace("core.presentation_studio.recovered", "Variantes actives rechargees",
                    data={"presentations": recovery.presentations, "active_loaded": loaded,
                          "unreadable": len(unreadable), "swept": swept, "sweep_failed": sweep_failed})
        return recovery

    # ------------------------------------------------------------ lecture

    async def list_presentations(self, limit: int = MAX_PRESENTATIONS) -> Listing:
        async with self._lock:  # reads see whole documents between saves, never a replace in flight
            return await self._list(limit)

    async def _list(self, limit: int) -> Listing:
        scan = await self._run("list", None, self._store.scan)
        rows: list[Mapping[str, Any]] = []
        problems: list[Mapping[str, str]] = [{"presentation_id": p.name, "code": C.CORRUPT_DOCUMENT.value,
                                              "message": clip(p.reason)} for p in scan.problems]
        for presentation_id in scan.presentation_ids:
            try:
                rows.append((await self._load_presentation(presentation_id)).summary())
            except PresentationStudioError as exc:
                # visible in the answer and in the Error Logs; one broken presentation never hides the others
                problems.append({"presentation_id": presentation_id, "code": exc.code.value, "message": exc.message})
                self._trace("core.presentation_studio.unreadable", "Presentation illisible au listage",
                            level="error", data={"presentation_id": presentation_id, "code": exc.code.value})
        rows.sort(key=lambda row: (row["updated_at"], row["presentation_id"]), reverse=True)
        self._trace("core.presentation_studio.listed", "Presentations listees",
                    data={"count": len(rows), "problems": len(problems)})
        return Listing(tuple(rows[:limit]), tuple(problems[:MAX_LISTED_PROBLEMS]))

    async def get(self, presentation_id: str) -> PresentationView:
        self._require_ids(presentation_id)
        return await self._guard("get", presentation_id, self._locked(self._load_view(presentation_id)))

    async def get_variant(self, presentation_id: str, variant_id: str) -> PresentationVariant:
        self._require_ids(presentation_id, variant_id)
        return await self._guard("get_variant", presentation_id,
                                 self._locked(self._load_variant(presentation_id, variant_id)))

    async def describe_scene(self, presentation_id: str, variant_id: str, scene_id: str) -> dict[str, Any]:
        """Les contrôles résolus d'une scène (ids stables, widgets, bornes, défauts, valeurs), ses ancres et son budget de charge."""

        self._require_ids(presentation_id, variant_id)
        return await self._guard("describe_scene", presentation_id,
                                 self._describe_scene(presentation_id, variant_id, scene_id))

    async def _describe_scene(self, presentation_id: str, variant_id: str, scene_id: str) -> dict[str, Any]:
        if not is_scene_id(scene_id):
            raise PresentationStudioError(C.UNKNOWN_SCENE, "unknown scene id")
        async with self._lock:
            presentation = await self._load_presentation(presentation_id)
            if variant_id not in {entry.variant_id for entry in presentation.variants}:
                raise PresentationStudioError(C.UNKNOWN_VARIANT, f"{variant_id} is not a variant of this presentation")
            variant = await self._load_variant(presentation_id, variant_id)
        order = next((i for i, scene in enumerate(variant.scenes) if scene.scene_id == scene_id), None)
        if order is None:
            raise PresentationStudioError(C.UNKNOWN_SCENE, f"{scene_id} is not a scene of this variant")
        if self._scenes is None:
            raise PresentationStudioError(C.PREFAB_UNAVAILABLE, "no prefab catalog is wired: controls cannot be resolved")
        description = await self._scenes.describe(variant.scenes[order], order)
        self._trace("core.presentation_studio.scene_described", "Controles de scene decrits",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "scene_id": scene_id,
                          "controls": len(description["controls"]), "problems": len(description["problems"]),
                          "payload_bytes": description["payload"]["bytes"]})
        return {"presentation_id": presentation_id, "variant_id": variant_id, "variant_revision": variant.revision,
                **description}

    def validate(self, raw: object) -> dict[str, Any]:
        """`{ok, errors: [{code, message}]}` ; pur, rien n'est écrit. Une seule erreur est rapportée (la première)."""

        try:
            view = validate_documents(raw)
        except PresentationStudioError as exc:
            self._trace("core.presentation_studio.validated", "Validation refusee", data={"code": exc.code.value})
            return {"ok": False, "errors": [{"code": exc.code.value, "message": exc.message}][:MAX_VALIDATION_ERRORS]}
        self._trace("core.presentation_studio.validated", "Validation reussie",
                    data={"presentation_id": view.presentation.presentation_id, "variants": len(view.variants)})
        return {"ok": True, "errors": []}

    # ------------------------------------------------------------ écriture

    async def create(self, raw: object) -> PresentationView:
        return await self._guard("create", None, self._create(raw))

    async def _create(self, raw: object) -> PresentationView:
        view = new_presentation(parse_create(raw), self._clock())
        presentation_id = view.presentation.presentation_id
        async with self._lock:
            scan = await self._run("create", presentation_id, self._store.scan)
            if len(scan.presentation_ids) >= MAX_PRESENTATIONS:
                raise PresentationStudioError(C.LIMIT_REACHED, f"at most {MAX_PRESENTATIONS} presentations")
            await self._run("create", presentation_id, self._store.create, presentation_id,
                            dump_document(view.presentation.to_document()),
                            {v.variant_id: dump_document(v.to_document()) for v in view.variants})
        self._trace("core.presentation_studio.created", "Presentation creee",
                    data={"presentation_id": presentation_id, "variant_id": view.presentation.active_variant_id})
        return view

    async def save_presentation(self, presentation_id: str, raw: object) -> Presentation:
        self._require_ids(presentation_id)
        return await self._guard("save_presentation", presentation_id, self._save_presentation(presentation_id, raw))

    async def _save_presentation(self, presentation_id: str, raw: object) -> Presentation:
        update: PresentationUpdate = parse_presentation_update(raw)
        async with self._lock:
            current = await self._load_presentation(presentation_id)
            self._check_revision(current.revision, update.expected_revision, presentation_id)
            if update.active_variant_id not in {entry.variant_id for entry in current.variants}:
                raise PresentationStudioError(C.UNKNOWN_VARIANT, "active_variant_id is not a variant of this presentation")
            saved = replace(current, title=update.title, active_variant_id=update.active_variant_id,
                            resources=update.resources, revision=current.revision + 1, updated_at=stamp(self._clock()))
            await self._run("save_presentation", presentation_id, self._store.write_manifest, presentation_id,
                            dump_document(saved.to_document()))
        self._trace("core.presentation_studio.saved", "Presentation sauvegardee",
                    data={"presentation_id": presentation_id, "part": "presentation", "revision": saved.revision})
        return saved

    async def save_variant(self, presentation_id: str, variant_id: str, raw: object) -> PresentationVariant:
        self._require_ids(presentation_id, variant_id)
        return await self._guard("save_variant", presentation_id, self._save_variant(presentation_id, variant_id, raw))

    async def _save_variant(self, presentation_id: str, variant_id: str, raw: object) -> PresentationVariant:
        update: VariantUpdate = parse_variant_update(raw)
        async with self._lock:
            await self._require_variant(presentation_id, variant_id)
            current = await self._load_variant(presentation_id, variant_id)
            self._check_revision(current.revision, update.expected_revision, f"{presentation_id}/{variant_id}")
        # Prefab authority is awaited OUTSIDE the lock (a slow catalogue stalls this save, never every studio read/write);
        # the revision is compared again at the write, so a save that landed meanwhile is a `stale_revision`, not a lost update.
        await self._check_scenes(presentation_id, variant_id, update.scenes, current.scenes)
        return await self._write_variant(presentation_id, variant_id, update, op="save_variant")

    @property
    def scene_catalog(self) -> SceneCatalog | None:
        """Le seul pont vers les prefabs (`None` sans catalogue câblé) ; l'API d'édition y lit les manifestes."""

        return self._scenes

    async def check_scenes(self, presentation_id: str, variant_id: str, scenes: tuple[StudioScene, ...],
                           stored: tuple[StudioScene, ...]) -> None:
        """Les scènes nouvelles ou modifiées contre leurs prefabs (hors verrou), comme `save_variant`. Journalise le refus."""

        await self._guard("check_scenes", presentation_id, self._check_scenes(presentation_id, variant_id, scenes, stored))

    async def guarded(self, op: str, presentation_id: str | None, work: Any) -> Any:
        """Exécute `work` (un awaitable de l'API d'édition qui lit le catalogue) avec la même journalisation que les autres
        opérations : un refus en `info`, une panne ou un prefab altéré en `error`, puis relance."""

        return await self._guard(op, presentation_id, work)

    async def write_variant(self, presentation_id: str, variant_id: str, update: VariantUpdate) -> PresentationVariant:
        """Écrit la variante sous `expected_revision` **sans** revérifier les scènes : l'appelant (`save_variant`, l'API
        d'édition) les a déjà fait passer par `check_scenes`. Seule la comparaison de révision et l'écriture sont sous le verrou."""

        self._require_ids(presentation_id, variant_id)
        return await self._guard("write_variant", presentation_id,
                                 self._write_variant(presentation_id, variant_id, update, op="write_variant"))

    async def _write_variant(self, presentation_id: str, variant_id: str, update: VariantUpdate, *,
                             op: str) -> PresentationVariant:
        async with self._lock:
            await self._require_variant(presentation_id, variant_id)
            current = await self._load_variant(presentation_id, variant_id)
            self._check_revision(current.revision, update.expected_revision, f"{presentation_id}/{variant_id}")
            saved = replace(current, title=update.title, scenes=own_scene_fields(current.scenes, update.scenes),
                            art_direction_id=update.art_direction_id, score_id=update.score_id,
                            revision=current.revision + 1, updated_at=stamp(self._clock()))
            self._refuse_reloading_scenes(presentation_id, variant_id, current, saved)
            await self._persist_variant(op, presentation_id, current, saved)
        self._trace("core.presentation_studio.saved", "Variante sauvegardee",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "part": "variant",
                          "revision": saved.revision, "scenes": len(saved.scenes)})
        return saved

    async def scenes_for_copy(self, presentation_id: str, variant: PresentationVariant) -> tuple[StudioScene, ...]:
        """Les scenes d'une variante telles qu'une **copie** (branche, Slice 16) doit les emporter. Une scene dont la nouvelle
        source est en cours de rechargement refuse la copie (`scene_reloading`, 409 : a refaire dans quelques secondes) ; une
        scene dont le pin n'a pas ete vu monte (`last_valid_pin`) est copiee sur son **dernier pin valide**, repli efface, si
        ses valeurs y tiennent, sinon la copie est refusee de meme. Une copie n'herite jamais d'un pin non verifie."""

        copied: list[StudioScene] = []
        for scene in variant.scenes:
            if self._scene_busy is not None and self._scene_busy(presentation_id, variant.variant_id, scene.scene_id):
                raise PresentationStudioError(
                    C.SCENE_RELOADING,
                    f"scene {scene.scene_id} is being reloaded: a branch of this variant is refused, retry in a few seconds")
            if scene.last_valid_pin is not None:
                confirmed = replace(scene, prefab=scene.last_valid_pin, last_valid_pin=None)
                try:
                    if self._scenes is not None:
                        await self._scenes.check(confirmed)
                except PresentationStudioError as exc:
                    raise PresentationStudioError(
                        C.SCENE_RELOADING,
                        f"scene {scene.scene_id} runs a source that was not seen mounted yet and its values do not fit the "
                        f"last valid version ({exc.code.value}): show it (or wait for its report), then branch") from exc
                scene = confirmed
            copied.append(scene)
        return tuple(copied)

    def _refuse_reloading_scenes(self, presentation_id: str, variant_id: str, current: PresentationVariant,
                                 saved: PresentationVariant) -> None:
        if self._scene_busy is None:
            return
        after = {scene.scene_id: scene for scene in saved.scenes}
        for scene in current.scenes:
            if after.get(scene.scene_id) != scene and self._scene_busy(presentation_id, variant_id, scene.scene_id):
                raise PresentationStudioError(
                    C.SCENE_RELOADING,
                    f"scene {scene.scene_id} is being reloaded (its new source is waiting to be seen mounted): "
                    "this edit is refused, retry in a few seconds")

    async def _persist_variant(self, op: str, presentation_id: str, previous: PresentationVariant,
                               saved: PresentationVariant, *, relink: bool = False,
                               relink_art_direction: bool = False) -> None:
        """The one place that puts a variant file on disk (`_write_variant`, the locked revision-checked write that
        `save_variant` and the edit API share, and `create_score` all end here). Slice 10 guard: `score_id` is owned by the score routes, so a variant
        save can neither attach, swap nor clear it (a stale body must not detach a score, and a made-up id must not lock the
        variant out of its own score). Only `create_score` passes `relink=True`. Slice 09 applies the same rule to
        `art_direction_id`: only the art direction creation (and the fallback, which ends there) passes
        `relink_art_direction=True`. Every writer of a variant goes through here."""

        if not relink and saved.score_id != previous.score_id:
            raise PresentationStudioError(
                C.INVALID_PRESENTATION,
                f"score_id is {previous.score_id}: a variant save cannot attach, swap or clear it "
                "(create the score through the score routes)")
        if not relink_art_direction and saved.art_direction_id != previous.art_direction_id:
            raise PresentationStudioError(
                C.INVALID_PRESENTATION,
                f"art_direction_id is {previous.art_direction_id}: a variant save cannot attach, swap or clear it "
                "(create the art direction through the art direction routes)")
        text = dump_document(saved.to_document())
        # Entry condition (docs/prefabs.md): the pins of the document are registered BEFORE the file is written, so a
        # retention pass racing this write can never archive a version the new document is about to name. A failed
        # write puts the previous set back (never less protected than before).
        before = None if self._pins is None else self._pins.register_variant(presentation_id, saved.variant_id,
                                                                            variant_pins(saved.scenes))
        try:
            await self._run(op, presentation_id, self._store.write_variant, presentation_id, saved.variant_id, text)
        except BaseException:
            if self._pins is not None and before is not None:
                self._pins.restore_variant(presentation_id, saved.variant_id, before)
            raise

    async def replace_scene_source(self, presentation_id: str, variant_id: str, *, expected_revision: int,
                                   scene: StudioScene) -> PresentationVariant:
        """Ecrit **une** scene de la variante sous `expected_revision`, dont ses champs de rechargement a chaud
        (`source_revision`, `last_valid_pin`) : le seul chemin qui les fait bouger (Slice 06). Le compteur est
        monotone : `+1` exactement quand le pin change, inchange sinon, jamais decroissant. Les scenes ne sont pas
        reverifiees contre les prefabs ici : l'appelant (`PresentationStudioReloadService`) l'a fait."""

        self._require_ids(presentation_id, variant_id)
        return await self._guard("replace_scene_source", presentation_id,
                                 self._replace_scene_source(presentation_id, variant_id, expected_revision, scene))

    async def _replace_scene_source(self, presentation_id: str, variant_id: str, expected_revision: int,
                                    scene: StudioScene) -> PresentationVariant:
        async with self._lock:
            await self._require_variant(presentation_id, variant_id)
            current = await self._load_variant(presentation_id, variant_id)
            self._check_revision(current.revision, expected_revision, f"{presentation_id}/{variant_id}")
            before = next((item for item in current.scenes if item.scene_id == scene.scene_id), None)
            if before is None:
                raise PresentationStudioError(C.UNKNOWN_SCENE, f"{scene.scene_id} is not a scene of this variant")
            moved = before.prefab != scene.prefab
            if scene.source_revision != before.source_revision + (1 if moved else 0):
                raise PresentationStudioError(
                    C.INVALID_PRESENTATION,
                    f"scene {scene.scene_id}: source_revision is {before.source_revision}; it moves by exactly one "
                    "when the pin changes and never otherwise")
            scenes = tuple(scene if item.scene_id == scene.scene_id else item for item in current.scenes)
            saved = replace(current, scenes=scenes, revision=current.revision + 1, updated_at=stamp(self._clock()))
            await self._persist_variant("replace_scene_source", presentation_id, current, saved)
        self._trace("core.presentation_studio.saved", "Source de scene epinglee",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "part": "scene_source",
                          "revision": saved.revision, "scene_id": scene.scene_id,
                          "source_revision": scene.source_revision, "unverified": scene.last_valid_pin is not None})
        return saved

    async def all_variants(self) -> list[PresentationVariant]:
        """**Chaque** variante de chaque Presentation (lecture disque, au demarrage : index des pins, scenes non verifiees).
        `PresentationStudioError` si un dossier ou un document est illisible : ses pins sont inconnus, l'appelant ferme
        alors la retention (jamais « aucun pin »)."""

        variants: list[PresentationVariant] = []
        ids = await self._guard("all_variants", None, self._locked(self._scan_for_pins()))
        for presentation_id in ids:
            variants.extend((await self.get(presentation_id)).variants)
        return variants

    async def _scan_for_pins(self) -> tuple[str, ...]:
        scan = await self._run("pin_index", None, self._store.scan)
        if scan.problems:
            raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"{len(scan.problems)} presentation folder(s) are unreadable")
        return tuple(scan.presentation_ids)

    async def score_problems(self, presentation_id: str, variant_id: str, scenes: tuple[StudioScene, ...]) -> list[str]:
        """Les problemes de la partition de la variante **si** ses scenes devenaient `scenes` (aucun si elle n'a pas de
        partition). Lecture seule : le service de rechargement refuse un changement qui casserait la partition."""

        self._require_ids(presentation_id, variant_id)
        return await self._guard("score_problems", presentation_id, self._score_problems(presentation_id, variant_id, scenes))

    async def _score_problems(self, presentation_id: str, variant_id: str, scenes: tuple[StudioScene, ...]) -> list[str]:
        async with self._lock:
            variant = await self._variant_of(presentation_id, variant_id)
            if variant.score_id is None:
                return []
            score = await self._load_score(presentation_id, variant)
        return list(check_score(score, scenes))

    # ------------------------------------------------------------ partition (Slice 10)

    async def get_score(self, presentation_id: str, variant_id: str) -> dict[str, Any]:
        """`{score, problems}` : la partition de la variante et, si la variante a changé depuis, les références qui ne se résolvent plus."""

        self._require_ids(presentation_id, variant_id)
        return await self._guard("get_score", presentation_id, self._get_score(presentation_id, variant_id))

    async def _get_score(self, presentation_id: str, variant_id: str) -> dict[str, Any]:
        async with self._lock:
            variant = await self._variant_of(presentation_id, variant_id)
            score = await self._load_score(presentation_id, variant)
        problems = check_score(score, variant.scenes)
        self._trace("core.presentation_studio.score_loaded", "Partition chargee",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "score_id": score.score_id,
                          "revision": score.revision, "items": len(score.items), "problems": len(problems)})
        return {"score": score.to_document(), "problems": problems}

    async def create_score(self, presentation_id: str, variant_id: str, raw: object) -> dict[str, Any]:
        self._require_ids(presentation_id, variant_id)
        return await self._guard("create_score", presentation_id, self._create_score(presentation_id, variant_id, raw))

    async def _create_score(self, presentation_id: str, variant_id: str, raw: object) -> dict[str, Any]:
        body = parse_score_create(raw)
        async with self._lock:
            variant = await self._variant_of(presentation_id, variant_id)
            self._check_revision(variant.revision, body.expected_variant_revision, f"{presentation_id}/{variant_id}")
            relinked_from = None
            if variant.score_id is not None:
                try:
                    await self._load_score(presentation_id, variant)
                except PresentationStudioError as exc:
                    if exc.code is not C.UNKNOWN_SCORE:
                        raise  # the file exists but is unusable: corrupt / newer. Never replaced here.
                    relinked_from = variant.score_id  # dangling link (file absent): this create repairs it
                else:
                    raise PresentationStudioError(C.ALREADY_EXISTS, f"variant {variant_id} already has score {variant.score_id}: save it")
            score = new_score(presentation_id, variant_id, body.content, self._clock())
            await self._check_score(score, variant)
            await self._run("create_score", presentation_id, self._store.write_score, presentation_id, score.score_id,
                            dump_document(score.to_document()))
            saved = replace(variant, score_id=score.score_id, revision=variant.revision + 1,
                            updated_at=stamp(self._clock()))
            await self._persist_variant("create_score", presentation_id, variant, saved, relink=True)
        self._trace("core.presentation_studio.saved", "Partition creee",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "part": "score",
                          "score_id": score.score_id, "revision": score.revision, "items": len(score.items)})
        answer: dict[str, Any] = {"score": score.to_document(), "problems": []}
        if relinked_from is not None:
            self._trace("core.presentation_studio.score_relinked", "Lien de partition sans fichier remplace",
                        level="warning", data={"presentation_id": presentation_id, "variant_id": variant_id,
                                               "missing_score_id": relinked_from, "score_id": score.score_id})
            answer["relinked_from"] = relinked_from
        return answer

    async def save_score(self, presentation_id: str, variant_id: str, raw: object) -> dict[str, Any]:
        self._require_ids(presentation_id, variant_id)
        return await self._guard("save_score", presentation_id, self._save_score(presentation_id, variant_id, raw))

    async def _save_score(self, presentation_id: str, variant_id: str, raw: object) -> dict[str, Any]:
        body = parse_score_update(raw)
        async with self._lock:
            variant = await self._variant_of(presentation_id, variant_id)
            current = await self._load_score(presentation_id, variant)
            self._check_revision(current.revision, body.expected_revision, f"{presentation_id}/{current.score_id}")
            candidate = Score(current.score_id, presentation_id, variant_id, **body.content,
                              revision=current.revision + 1, created_at=current.created_at,
                              updated_at=stamp(self._clock()))
            await self._check_score(candidate, variant)
            await self._run("save_score", presentation_id, self._store.write_score, presentation_id, candidate.score_id,
                            dump_document(candidate.to_document()))
        self._trace("core.presentation_studio.saved", "Partition sauvegardee",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "part": "score",
                          "score_id": candidate.score_id, "revision": candidate.revision, "items": len(candidate.items)})
        return {"score": candidate.to_document(), "problems": []}

    # ------------------------------------------------------------ direction artistique (Slice 09)

    async def get_art_direction(self, presentation_id: str, variant_id: str) -> dict[str, Any]:
        """`{art_direction}` : le document de la variante. `unknown_art_direction` (404) si elle n'en a pas ou si son fichier est absent."""

        self._require_ids(presentation_id, variant_id)
        return await self._guard("get_art_direction", presentation_id, self._get_art_direction(presentation_id, variant_id))

    async def _get_art_direction(self, presentation_id: str, variant_id: str) -> dict[str, Any]:
        async with self._lock:
            variant = await self._variant_of(presentation_id, variant_id)
            art = await self._load_art_direction(presentation_id, variant)
        self._trace("core.presentation_studio.art_direction_loaded", "Direction artistique chargee",
                    data={"presentation_id": presentation_id, "variant_id": variant_id,
                          "art_direction_id": art.art_direction_id, "revision": art.revision,
                          "origin": art.profile.provenance.origin.value, "fallback": art.profile.provenance.fallback})
        return {"art_direction": art.to_document()}

    async def create_art_direction(self, presentation_id: str, variant_id: str, raw: object) -> dict[str, Any]:
        """`{expected_variant_revision, profile}` : écrit la DA **puis** la variante (qui reçoit `art_direction_id`)."""

        self._require_ids(presentation_id, variant_id)
        return await self._guard("create_art_direction", presentation_id,
                                 self._create_art_direction(presentation_id, variant_id, raw))

    async def _create_art_direction(self, presentation_id: str, variant_id: str, raw: object) -> dict[str, Any]:
        body = parse_art_direction_create(raw)
        return await self._attach_art_direction(presentation_id, variant_id, body.expected_variant_revision,
                                                body.profile, op="create_art_direction", fallback=False)

    async def create_fallback_art_direction(self, presentation_id: str, variant_id: str, raw: object) -> dict[str, Any]:
        """`{expected_variant_revision, seed_context?}` : génère le profil de repli (déterministe, `fallback: true`) et le crée comme
        `create_art_direction`. Une variante qui a déjà une DA utilisable : `already_exists`."""

        self._require_ids(presentation_id, variant_id)
        return await self._guard("create_fallback_art_direction", presentation_id,
                                 self._create_fallback(presentation_id, variant_id, raw))

    async def _create_fallback(self, presentation_id: str, variant_id: str, raw: object) -> dict[str, Any]:
        data = _exact_keys(raw, "fallback art direction", {"expected_variant_revision"}, frozenset({"seed_context"}))
        _check_int("expected_variant_revision", data["expected_variant_revision"], 1, 2**31 - 1)
        profile = generate_fallback_profile(parse_seed_context(data.get("seed_context", {})))
        return await self._attach_art_direction(presentation_id, variant_id, data["expected_variant_revision"], profile,
                                                op="create_fallback_art_direction", fallback=True)

    async def _attach_art_direction(self, presentation_id: str, variant_id: str, expected_variant_revision: int,
                                    profile: Any, *, op: str, fallback: bool) -> dict[str, Any]:
        async with self._lock:
            variant = await self._variant_of(presentation_id, variant_id)
            self._check_revision(variant.revision, expected_variant_revision, f"{presentation_id}/{variant_id}")
            relinked_from = None
            if variant.art_direction_id is not None:
                try:
                    await self._load_art_direction(presentation_id, variant)
                except PresentationStudioError as exc:
                    if exc.code is not C.UNKNOWN_ART_DIRECTION:
                        raise  # the file exists but is unusable: corrupt / newer. Never replaced here.
                    relinked_from = variant.art_direction_id  # dangling link (file absent): this create repairs it
                else:
                    raise PresentationStudioError(
                        C.ALREADY_EXISTS,
                        f"variant {variant_id} already has art direction {variant.art_direction_id}: save it")
            art = new_art_direction_document(presentation_id, variant_id, profile, self._clock())
            await self._run(op, presentation_id, self._store.write_art_direction, presentation_id, art.art_direction_id,
                            dump_document(art.to_document()))
            saved = replace(variant, art_direction_id=art.art_direction_id, revision=variant.revision + 1,
                            updated_at=stamp(self._clock()))
            await self._persist_variant(op, presentation_id, variant, saved, relink_art_direction=True)
        self._trace("core.presentation_studio.saved", "Direction artistique creee",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "part": "art_direction",
                          "art_direction_id": art.art_direction_id, "revision": art.revision,
                          "origin": art.profile.provenance.origin.value, "fallback": fallback})
        answer: dict[str, Any] = {"art_direction": art.to_document()}
        if relinked_from is not None:
            self._trace("core.presentation_studio.art_direction_relinked",
                        "Lien de direction artistique sans fichier remplace", level="warning",
                        data={"presentation_id": presentation_id, "variant_id": variant_id,
                              "missing_art_direction_id": relinked_from, "art_direction_id": art.art_direction_id})
            answer["relinked_from"] = relinked_from
        return answer

    async def save_art_direction(self, presentation_id: str, variant_id: str, raw: object) -> dict[str, Any]:
        """`{expected_revision, profile}` : remplacement entier sous la révision de la DA (`stale_revision` sinon)."""

        self._require_ids(presentation_id, variant_id)
        return await self._guard("save_art_direction", presentation_id,
                                 self._save_art_direction(presentation_id, variant_id, raw))

    async def _save_art_direction(self, presentation_id: str, variant_id: str, raw: object) -> dict[str, Any]:
        body = parse_art_direction_update(raw)
        async with self._lock:
            variant = await self._variant_of(presentation_id, variant_id)
            current = await self._load_art_direction(presentation_id, variant)
            self._check_revision(current.revision, body.expected_revision, f"{presentation_id}/{current.art_direction_id}")
            candidate = ArtDirection(current.art_direction_id, presentation_id, variant_id, body.profile,
                                     current.revision + 1, current.created_at, stamp(self._clock()))
            await self._run("save_art_direction", presentation_id, self._store.write_art_direction, presentation_id,
                            candidate.art_direction_id, dump_document(candidate.to_document()))
        self._trace("core.presentation_studio.saved", "Direction artistique sauvegardee",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "part": "art_direction",
                          "art_direction_id": candidate.art_direction_id, "revision": candidate.revision,
                          "origin": candidate.profile.provenance.origin.value,
                          "fallback": candidate.profile.provenance.fallback})
        return {"art_direction": candidate.to_document()}

    async def art_direction_candidates(self, presentation_id: str, variant_id: str, raw: object) -> dict[str, Any]:
        """`{count, seed_context?}` -> `{base, base_profile, candidates}` : `count` profils divergents calculés (rien n'est écrit)
        à partir de la DA de la variante, ou du repli de `seed_context` si elle n'en a pas encore."""

        self._require_ids(presentation_id, variant_id)
        return await self._guard("art_direction_candidates", presentation_id,
                                 self._candidates(presentation_id, variant_id, raw))

    async def _candidates(self, presentation_id: str, variant_id: str, raw: object) -> dict[str, Any]:
        data = _exact_keys(raw, "art direction candidates", {"count"}, frozenset({"seed_context"}))
        _check_int("count", data["count"], 1, MAX_DIVERGE)
        seed: SeedContext = parse_seed_context(data.get("seed_context", {}))
        async with self._lock:
            variant = await self._variant_of(presentation_id, variant_id)
            try:
                base, source = (await self._load_art_direction(presentation_id, variant)).profile, "stored"
            except PresentationStudioError as exc:
                if exc.code is not C.UNKNOWN_ART_DIRECTION:
                    raise
                base, source = generate_fallback_profile(seed), "fallback"
        candidates = diverge(base, data["count"])
        self._trace("core.presentation_studio.art_direction_candidates", "Candidats de direction artistique calcules",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "base": source,
                          "count": len(candidates)})
        return {"base": source, "base_profile": base.to_dict(), "candidates": [c.to_dict() for c in candidates]}

    async def require_art_direction(self, presentation_id: str, variant_id: str, *, serious: bool = True) -> dict[str, Any]:
        """`require_art_direction` du domaine, chargé depuis le disque : `{status, fallback, art_direction}` ou refus
        (`art_direction_required`, `unknown_art_direction`). Appelé par l'auteur (Slice 11) avant de livrer une variante
        sérieuse ou générée, et par la lecture (Slice 12) avant de jouer."""

        self._require_ids(presentation_id, variant_id)
        return await self._guard("require_art_direction", presentation_id,
                                 self._require_art_direction(presentation_id, variant_id, serious))

    async def _require_art_direction(self, presentation_id: str, variant_id: str, serious: bool) -> dict[str, Any]:
        async with self._lock:
            variant = await self._variant_of(presentation_id, variant_id)
            loaded: ArtDirection | None = None
            if variant.art_direction_id is not None:
                try:
                    loaded = await self._load_art_direction(presentation_id, variant)
                except PresentationStudioError as exc:
                    if exc.code is not C.UNKNOWN_ART_DIRECTION:
                        raise
        resolution: ArtDirectionResolution = require_art_direction(variant, _Loaded(loaded), serious)
        self._trace("core.presentation_studio.art_direction_resolved", "Direction artistique resolue",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "serious": serious,
                          "status": resolution.status.value, "fallback": resolution.is_fallback})
        return {"status": resolution.status.value, "fallback": resolution.is_fallback,
                "art_direction": None if resolution.art_direction is None else resolution.art_direction.to_document()}

    async def _load_art_direction(self, presentation_id: str, variant: PresentationVariant) -> ArtDirection:
        if variant.art_direction_id is None:
            raise PresentationStudioError(C.UNKNOWN_ART_DIRECTION,
                                          f"variant {variant.variant_id} has no art direction yet: create it")
        label = f"{presentation_id}/{variant.art_direction_id}"
        text = await self._run("read", presentation_id, self._store.read_art_direction, presentation_id,
                               variant.art_direction_id)
        art = self._parse_stored(parse_art_direction, text, label)
        if (art.presentation_id, art.variant_id, art.art_direction_id) != (
                presentation_id, variant.variant_id, variant.art_direction_id):
            raise PresentationStudioError(C.CORRUPT_DOCUMENT,
                                          f"{label}: file names another art direction, variant or presentation")
        return art

    async def _variant_of(self, presentation_id: str, variant_id: str) -> PresentationVariant:
        presentation = await self._load_presentation(presentation_id)
        if variant_id not in {entry.variant_id for entry in presentation.variants}:
            raise PresentationStudioError(C.UNKNOWN_VARIANT, f"{variant_id} is not a variant of this presentation")
        return await self._load_variant(presentation_id, variant_id)

    async def _load_score(self, presentation_id: str, variant: PresentationVariant) -> Score:
        if variant.score_id is None:
            raise PresentationStudioError(C.UNKNOWN_SCORE, f"variant {variant.variant_id} has no score yet: create it")
        label = f"{presentation_id}/{variant.score_id}"
        text = await self._run("read", presentation_id, self._store.read_score, presentation_id, variant.score_id)
        score = self._parse_stored(parse_score, text, label)
        if (score.presentation_id, score.variant_id, score.score_id) != (presentation_id, variant.variant_id, variant.score_id):
            raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"{label}: file names another score, variant or presentation")
        return score

    async def _check_score(self, score: Score, variant: PresentationVariant) -> None:
        """Références (pur) puis, avec un catalogue, valeurs contre les manifestes. Sinon `score_incompatible` / `prefab_unavailable`."""

        raise_if_incompatible(check_score(score, variant.scenes))
        if self._scenes is None:
            return
        wanted = {a.scene_id for item in score.items for a in (*item.visual, *item.motion) if a.kind is ActionKind.CONTROL_SET}
        wanted |= {a.scene_id for seq in score.sequences for step in seq.steps for a in (*step.visual, *step.motion)
                   if a.kind is ActionKind.CONTROL_SET}
        scenes = {scene.scene_id: scene for scene in variant.scenes}
        manifests = {scene_id: await self._scenes.manifest_of(scenes[scene_id]) for scene_id in sorted(wanted)}
        raise_if_incompatible(check_score_values(score, variant.scenes, manifests))
    async def _require_variant(self, presentation_id: str, variant_id: str) -> None:
        presentation = await self._load_presentation(presentation_id)
        if variant_id not in {entry.variant_id for entry in presentation.variants}:
            raise PresentationStudioError(C.UNKNOWN_VARIANT, f"{variant_id} is not a variant of this presentation")

    # ------------------------------------------------------------ jointures du graphe de variantes (Slice 16)
    # `PresentationStudioVariants` (core/presentation_studio_variants.py) écrit plusieurs fichiers sous **ce** verrou et par
    # **ce** magasin : un seul écrivain, une seule porte d'écriture de variante (`_persist_variant`). Ces accesseurs sont
    # l'unique surface qu'il utilise ; ils ne contiennent aucune règle.

    @property
    def store(self) -> PresentationStudioStore:
        return self._store

    def exclusive(self) -> asyncio.Lock:
        """Le verrou d'écriture des Presentations (`async with studio.exclusive():`). Non réentrant : n'appeler que les méthodes `*_locked`."""

        return self._lock

    def now(self) -> datetime:
        return self._clock()

    async def load_presentation_locked(self, presentation_id: str) -> Presentation:
        return await self._load_presentation(presentation_id)

    async def load_variant_locked(self, presentation_id: str, variant_id: str) -> PresentationVariant:
        return await self._load_variant(presentation_id, variant_id)

    async def persist_variant_locked(self, op: str, presentation_id: str, previous: PresentationVariant,
                                     saved: PresentationVariant, *, relink: bool = False,
                                     relink_art_direction: bool = False) -> None:
        await self._persist_variant(op, presentation_id, previous, saved, relink=relink,
                                    relink_art_direction=relink_art_direction)

    async def load_art_direction_locked(self, presentation_id: str, variant: PresentationVariant) -> ArtDirection:
        return await self._load_art_direction(presentation_id, variant)

    async def write_manifest_locked(self, op: str, presentation: Presentation) -> None:
        """Le manifeste, atomiquement, dernier fichier écrit d'une opération multi-fichiers."""

        await self._run(op, presentation.presentation_id, self._store.write_manifest, presentation.presentation_id,
                        dump_document(presentation.to_document()))

    async def run_blocking(self, op: str, presentation_id: str | None, call: Callable[..., T], *args: Any) -> T:
        return await self._run(op, presentation_id, call, *args)

    def parse_stored(self, parse: Callable[[object], T], text: str, label: str) -> T:
        return self._parse_stored(parse, text, label)

    async def load_view_locked(self, presentation_id: str) -> PresentationView:
        return await self._load_view(presentation_id)

    async def load_score_locked(self, presentation_id: str, variant: PresentationVariant) -> Score:
        return await self._load_score(presentation_id, variant)

    def trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
        self._trace(kind, message, level=level, data=data)

    # ------------------------------------------------------------ interne

    async def _check_scenes(self, presentation_id: str, variant_id: str, scenes: tuple[StudioScene, ...],
                            stored: tuple[StudioScene, ...]) -> None:
        """Les scènes nouvelles ou modifiées passent par le catalogue des prefabs ; les inchangées ne sont pas revérifiées
        (renommer une variante ne dépend pas de l'état du catalogue)."""

        if self._scenes is None:
            return
        # Compared by stored form, never by `==`: in Python {"count": 1} == {"count": True} == {"count": 1.0}.
        known = {canonical_json(scene.to_dict()) for scene in stored}
        changed = [scene for scene in scenes if canonical_json(scene.to_dict()) not in known]
        for scene in changed:
            await self._scenes.check(scene)
        self._trace("core.presentation_studio.scenes_checked", "Scenes verifiees contre les prefabs",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "checked": len(changed),
                          "unchanged": len(scenes) - len(changed)})

    @staticmethod
    def _require_ids(presentation_id: str, variant_id: str | None = None) -> None:
        if not is_presentation_id(presentation_id):
            raise PresentationStudioError(C.UNKNOWN_PRESENTATION, "unknown presentation id")
        if variant_id is not None and not is_variant_id(variant_id):
            raise PresentationStudioError(C.UNKNOWN_VARIANT, "unknown variant id")

    def _check_revision(self, current: int, expected: int, label: str) -> None:
        if current != expected:
            raise PresentationStudioError(C.STALE_REVISION, f"{label} is at revision {current}, not {expected}: reload, then retry")

    async def _run(self, op: str, presentation_id: str | None, call: Callable[..., T], *args: Any) -> T:
        """Appel du magasin hors de la boucle. Ses refus codés repartent tels quels ; un imprévu devient `storage_io`."""

        try:
            return await asyncio.to_thread(call, *args)
        except PresentationStudioError:
            raise
        except Exception as exc:  # noqa: BLE001 - re-raised as a coded storage failure carrying the real cause
            raise PresentationStudioError(C.STORAGE_IO, f"{op}: {type(exc).__name__}: {exc}") from exc

    async def _load_presentation(self, presentation_id: str) -> Presentation:
        text = await self._run("read", presentation_id, self._store.read_manifest, presentation_id)
        presentation = self._parse_stored(parse_presentation, text, presentation_id)
        if presentation.presentation_id != presentation_id:
            raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"{presentation_id}: manifest names another presentation")
        return presentation

    async def _load_variant(self, presentation_id: str, variant_id: str) -> PresentationVariant:
        text = await self._run("read", presentation_id, self._store.read_variant, presentation_id, variant_id)
        variant = self._parse_stored(parse_variant, text, f"{presentation_id}/{variant_id}")
        if (variant.presentation_id, variant.variant_id) != (presentation_id, variant_id):
            raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"{presentation_id}/{variant_id}: file names another variant")
        return variant

    async def _load_view(self, presentation_id: str) -> PresentationView:
        presentation = await self._load_presentation(presentation_id)
        variants: list[PresentationVariant] = []
        for entry in presentation.variants:
            try:
                variants.append(await self._load_variant(presentation_id, entry.variant_id))
            except PresentationStudioError as exc:
                if exc.code is C.UNKNOWN_VARIANT:  # indexed but absent: the stored state is torn, not "unknown"
                    raise PresentationStudioError(C.CORRUPT_DOCUMENT,
                                                  f"{presentation_id}: indexed variant {entry.variant_id} is missing") from None
                raise
        try:
            return PresentationView(presentation, tuple(variants))
        except PresentationStudioError as exc:
            raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"{presentation_id}: {exc.message}") from exc

    @staticmethod
    def _parse_stored(parse: Callable[[object], T], text: str, label: str) -> T:
        """Un document **stocké** invalide est une panne de données (409), pas une entrée refusée (400)."""

        try:
            return parse(load_document(text))
        except PresentationStudioError as exc:
            if exc.code in (C.UNSUPPORTED_SCHEMA_VERSION, C.CORRUPT_DOCUMENT):
                raise PresentationStudioError(exc.code, f"{label}: {exc.message}") from exc
            raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"{label}: {exc.message}") from exc

    async def _locked(self, work: Any) -> Any:
        """Lit sous le verrou des écritures : un `os.replace` en vol ne croise jamais une lecture (et inversement,
        sous Windows un lecteur tient le fichier et ferait échouer le remplacement du rédacteur)."""

        async with self._lock:
            return await work

    async def _guard(self, op: str, presentation_id: str | None, work: Any) -> Any:
        """Exécute `work`, journalise le refus (info) ou la panne (error) avec son code, et relance."""

        try:
            return await work
        except PresentationStudioError as exc:
            hard = exc.code in (C.STORAGE_IO, C.CORRUPT_DOCUMENT, C.UNSUPPORTED_SCHEMA_VERSION) \
                or (exc.code is C.PREFAB_UNAVAILABLE and not exc.warn)
            level = "error" if hard else "warning" if exc.warn else "info"
            self._trace("core.presentation_studio.failed" if hard else "core.presentation_studio.refused",
                        f"Operation {op} {'en panne' if hard else 'refusee'}", level=level,
                        data={"op": op, "presentation_id": presentation_id, "code": exc.code.value,
                              # a caller's refusal may quote the value it refused: only a fault of ours is logged in words
                              **({"error": exc.message} if hard else {})})
            raise

    def report_unexpected(self, op: str, exc: BaseException) -> None:
        """Appelé par la frontière HTTP pour un imprévu : visible dans le visualiseur d'erreurs avec la vraie cause."""

        self._trace("core.presentation_studio.unexpected", f"Erreur imprevue dans {op}", level="error",
                    data={"op": op, "error": clip(f"{type(exc).__name__}: {exc}")})

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal never undoes a studio operation
            pass
