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
from collections.abc import Callable, Mapping
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
from jarvis.domain.presentation_studio_checks import is_scene_id
from jarvis.domain.presentation_studio_score import (
    ActionKind, Score, check_score, check_score_values, new_score, parse_score, parse_score_create, parse_score_update,
    raise_if_incompatible,
)
from jarvis.domain.v2 import utc_now
from jarvis.ports.presentation_studio import PrefabCatalog, PresentationStudioStore
from jarvis.ports.v2 import DiagnosticSink

T = TypeVar("T")
#: Une Presentation illisible ne doit pas rendre le listage illisible : bornes du rapport de problèmes.
MAX_LISTED_PROBLEMS = 20
#: Rafraîchi à chaque écriture (`updated_at`) : horloge injectable pour les tests.
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class Listing:
    presentations: tuple[Mapping[str, Any], ...]
    problems: tuple[Mapping[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {"presentations": [dict(row) for row in self.presentations],
                "problems": [dict(row) for row in self.problems]}


class PresentationStudioService:
    def __init__(self, store: PresentationStudioStore, *, diagnostics: DiagnosticSink | None = None,
                 clock: Clock = utc_now, prefabs: PrefabCatalog | None = None) -> None:
        self._store = store
        self._scenes = SceneCatalog(prefabs) if prefabs is not None else None
        self._diagnostics = diagnostics
        self._clock = clock
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ cycle de vie

    async def start(self) -> None:
        """Balaie les restes d'un arrêt brutal. Ne lève jamais : un balayage en échec est journalisé en `error`."""

        try:
            report = await asyncio.to_thread(self._store.sweep)
        except Exception as exc:  # noqa: BLE001 - intentional: a failed sweep never blocks Core; traced below
            self._trace("core.presentation_studio.sweep_failed", "Balayage du magasin des presentations impossible",
                        level="error", data={"error": clip(f"{type(exc).__name__}: {exc}")})
            return
        if report.removed:
            self._trace("core.presentation_studio.swept", "Restes d'ecritures interrompues retires",
                        data={"removed": list(report.removed)[:20], "count": len(report.removed)})
        if report.failed:
            self._trace("core.presentation_studio.sweep_failed", "Restes d'ecritures interrompues non retires",
                        level="warning", data={"failed": list(report.failed)[:20]})
        self._trace("core.presentation_studio.started", "Magasin des presentations pret", data={})

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
            presentation = await self._load_presentation(presentation_id)
            if variant_id not in {entry.variant_id for entry in presentation.variants}:
                raise PresentationStudioError(C.UNKNOWN_VARIANT, f"{variant_id} is not a variant of this presentation")
            current = await self._load_variant(presentation_id, variant_id)
            self._check_revision(current.revision, update.expected_revision, f"{presentation_id}/{variant_id}")
            if current.score_id is not None and update.score_id != current.score_id:
                # Slice 10: once a variant has a score, only the score routes own the link (a stale body must not detach it).
                raise PresentationStudioError(C.INVALID_PRESENTATION,
                                              f"score_id is {current.score_id}: keep it (the score routes own that link)")
            await self._check_scenes(presentation_id, variant_id, update.scenes, current.scenes)
            saved = replace(current, title=update.title, scenes=update.scenes, art_direction_id=update.art_direction_id,
                            score_id=update.score_id, revision=current.revision + 1, updated_at=stamp(self._clock()))
            await self._run("save_variant", presentation_id, self._store.write_variant, presentation_id, variant_id,
                            dump_document(saved.to_document()))
        self._trace("core.presentation_studio.saved", "Variante sauvegardee",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "part": "variant",
                          "revision": saved.revision, "scenes": len(saved.scenes)})
        return saved

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
            if variant.score_id is not None:
                raise PresentationStudioError(C.ALREADY_EXISTS, f"variant {variant_id} already has score {variant.score_id}: save it")
            score = new_score(presentation_id, variant_id, body.content, self._clock())
            await self._check_score(score, variant)
            await self._run("create_score", presentation_id, self._store.write_score, presentation_id, score.score_id,
                            dump_document(score.to_document()))
            saved = replace(variant, score_id=score.score_id, revision=variant.revision + 1,
                            updated_at=stamp(self._clock()))
            await self._run("create_score", presentation_id, self._store.write_variant, presentation_id, variant_id,
                            dump_document(saved.to_document()))
        self._trace("core.presentation_studio.saved", "Partition creee",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "part": "score",
                          "score_id": score.score_id, "revision": score.revision, "items": len(score.items)})
        return {"score": score.to_document(), "problems": []}

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
                              "error": exc.message})
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
