"""Rechargement a chaud d'une scene du Studio (handoff jarvis-interactive-presentation-studio, Slice 06).

**Un** chemin pour qu'une edition de SOURCE (niveau 3, D11) donne un resultat vivant coherent, ou echoue sans rien abimer.
Mecanisme R2 (decide par la Slice 00) : candidat de prefab valide **avant** toute publication, publie comme revision
immuable par `PrefabService.save` (via le coalesceur de la Slice 01a : une rafale = une version), puis le pin exact de la
scene est re-ecrit (variante, compare-and-set de la Slice 05) et la fenetre « stage » est patchee : la regle de remontage
de l'hote (changement de `(id, version)`) recharge **ce** cadre seulement. Aucun second moteur de rendu, aucun `srcdoc`
nouveau, ni le bac a sable, ni la CSP, ni `jv:1` ne bougent.

```
requete -> [1 sans verrou]  lire pin+source, composer, VALIDER (manifeste sur, validate_candidate, valeurs studio,
                            partition) -> publier (coalesceur)
        -> [2 verrou de scene]  re-lire (base inchangee ?) -> controle d'instance (catalogue) -> ecrire le pin
                            (variante, last_valid_pin = pin d'avant) -> patcher le stage -> attendre le rapport de
                            montage de l'hote (echeance) -> confirmer (effacer le repli) | retour arriere
```

Issues (`ReloadStatus`) : `reloaded`, `reloaded_state_reset`, `repinned` (aucune fenetre stage ne l'affiche), `pending_mount`
(pas de rapport dans le delai : le pin tient, le repli aussi), `refused_validation` (rien n'a change), `rolled_back`
(pin revenu, raison dite), `stale`. **Jamais** la derniere scene valide n'est detruite : le repli est le document
precedent de la scene, restaure tel quel (seul `source_revision` a monte).

Cohérence (arret entre deux etapes) : la publication precede le pin (une version non epinglee est inoffensive, la
retention l'archivera) ; le pin et son repli (`last_valid_pin`) sont ecrits **ensemble** dans un seul fichier ; la
confirmation n'efface que le repli. Au demarrage `recover()` retrouve les scenes non confirmees depuis les documents : le
prochain rapport de montage les confirme ou les ramene en arriere, et le registre des pins protege le repli entre-temps.

Concurrence : sous un verrou **par scene** (seulement apres la publication, pour que la rafale puisse fusionner) ; deux
retouches d'une rafale partagent UNE publication et recoivent la meme issue (`merged`) ; deux editions de meme base :
l'une gagne, l'autre est `stale`. Aucune attente du catalogue ni de l'hote ne tient le verrou du service des variantes.

Scenes Remotion (handoff jarvis-remotion-presentation-integration, Slice 14) : meme chemin, meme verrou, memes issues. Le corps porte
`sources` / `assets` / `restore_version` au lieu de `template` / `style` / `behavior`, et le garde de phase 1 ajoute, EN DERNIER, la
compilation reelle de la source composee (`RemotionBuildGate`) : une source qui ne compile pas n'est jamais publiee
(`presentation_studio_source_build_failed`, `diagnostics` fichier:ligne:colonne). Annuler / retablir = republier une version
(`restore_version`). Contrat : `docs/presentation-studio.md` > *Remotion sources*.

Observabilite : journaux `core.presentation_studio.reload_*` (ids, statuts, codes, comptes ; **jamais** une valeur, un
texte de source ni le message d'un cadre) et l'evenement `system.presentation_studio.scene_reloaded`.
"""

from __future__ import annotations

import asyncio
from collections import deque
import hashlib
from collections.abc import Callable, Iterable, Mapping
from contextlib import nullcontext
from dataclasses import dataclass, replace
import time
from typing import Any, Protocol

from jarvis.core.presentation_studio_edit import PresentationStudioEditService
from jarvis.core.presentation_studio_mounts import MountBook
from jarvis.core.presentation_studio_remotion_gate import RemotionBuildGate, SourceBuilder
from jarvis.core.presentation_studio_reload_limits import BRAIN_EDIT_LIMIT, BRAIN_EDIT_WINDOW_S, SourceEditLimiter  # noqa: F401 - re-exported
from jarvis.core.presentation_studio_pins import StudioPinRegistry
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.core.presentation_studio_reload_stage import StageBinding, StagePatchError, StageWindows
from jarvis.core.prefab_draft_coalescer import PrefabDraftCoalescer
from jarvis.domain.prefab import (
    PrefabDefinitionError, PrefabManifest, PrefabRef, Publication, parse_candidate,
)
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationVariant, clip
from jarvis.domain.presentation_studio_edit import StudioActor
from jarvis.domain.presentation_studio_remotion_edit import candidate_files, compose_remotion_candidate
from jarvis.domain.presentation_studio_checks import PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_reload import (
    MAX_RECENT_RELOADS, CarryOver, MountOutcome, MountReport, ReloadOrigin, ReloadResult, ReloadStatus, SourceEditRequest,
    StateReset,
    carry_live_values, compose_candidate, parse_mount_report, parse_source_edit, plan_carry_over, source_prefab_id,
    merge_restore, scene_problems, unfit_names, unsafe_manifest_key, variant_scene,
)
from jarvis.domain.presentation_studio_scene import StudioScene
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode as PC
from jarvis.ports.v2 import DiagnosticSink

#: Attente du rapport de montage : la bande d'erreur de l'hote attend `ready` 3 s ; chargement du paquet + stabilisation
#: (`SETTLE_MS` de l'hote) + une marge. Passe ce delai : `pending_mount`, jamais une attente sans fin.
DEFAULT_MOUNT_DEADLINE_S = 8.0
#: Rafale : le brouillon part apres un silence (reglage du Studio, plus court que le defaut du coalesceur de la 01a pour un
#: retour « live coding » ; le plafond de duree garde la borne de versions par minute de la rafale).
#: Attente maximale d'une edition derriere une autre de la MEME scene (composition + compilation, <= 60 s la scene) : au-dela, une erreur
#: typee « occupe » (`presentation_studio_scene_reloading`, a refaire), jamais une file sans fin (Slice 14).
DEFAULT_COMPOSE_QUEUE_S = 75.0
DEFAULT_QUIET_S = 0.4
DEFAULT_MAX_WAIT_S = 4.0
#: Attente bornee des editions en vol a l'arret de Core.
CLOSE_GRACE_S = 10.0
MAX_PROBLEMS_IN_MESSAGE = 3
#: Essais bornes pour remettre la fenetre stage sur la derniere version valide apres un echec de montage.
STAGE_RESTORE_ATTEMPTS = 3


class ReloadPrefabs(Protocol):
    """Ce que le service demande a `PrefabService` (lecture et validation seulement ; la publication passe par le coalesceur)."""

    async def get(self, prefab_id: str, version: int | None = None) -> Any: ...
    async def manifest(self, prefab_id: str, version: int) -> PrefabManifest: ...
    async def remotion_source(self, prefab_id: str, version: int) -> Any: ...
    def validate_candidate(self, candidate: object) -> Any: ...


class PlaybackProbe(Protocol):
    """Ce que le rechargement lit de la lecture (Slice 12), jamais ecrit : `PresentationStudioPlaybackService.position`. Rend
    `{"run_id", "variant_id", "scene_id", "item_id", "position", "state", "role", "stage_object_id"}` ou `None` si rien ne joue."""

    def position(self, presentation_id: str) -> Mapping[str, Any] | None: ...


@dataclass(slots=True)
class _Unverified:
    """Une scene dont le pin n'a pas encore ete vu monte : de quoi la confirmer ou la ramener en arriere."""

    presentation_id: str
    variant_id: str
    scene_id: str
    pin: PrefabRef
    fallback: PrefabRef
    source_revision: int


@dataclass(frozen=True, slots=True)
class _Base:
    """La source sur laquelle une edition se compose : manifeste brut + fichiers HTML (texte) OU fichiers Remotion (octets)."""

    manifest: dict[str, Any]
    html: dict[str, str] | None = None
    files: dict[str, bytes] | None = None

    @property
    def remotion(self) -> bool:
        return self.files is not None


#: Versions anterieures d'une scene que l'on peut republier (annuler) : bornees, en memoire.
MAX_RESTORABLE = 16


class PresentationStudioReloadService:
    def __init__(self, studio: PresentationStudioService, prefabs: ReloadPrefabs, coalescer: PrefabDraftCoalescer,
                 stage: StageWindows, *, pins: StudioPinRegistry | None = None,
                 edits: PresentationStudioEditService | None = None, mounts: MountBook | None = None,
                 playback: PlaybackProbe | None = None, events: Any | None = None,
                 diagnostics: DiagnosticSink | None = None, mount_deadline_s: float = DEFAULT_MOUNT_DEADLINE_S,
                 monotonic: Callable[[], float] = time.monotonic, builder: SourceBuilder | None = None,
                 compose_queue_s: float = DEFAULT_COMPOSE_QUEUE_S) -> None:
        self._studio, self._prefabs, self._coalescer, self._stage = studio, prefabs, coalescer, stage
        self._pins, self._edits, self._mounts = pins, edits, mounts or MountBook()
        self._playback, self._events, self._diagnostics = playback, events, diagnostics
        self._deadline_s, self._monotonic = mount_deadline_s, monotonic
        self._build = RemotionBuildGate(builder, diagnostics=diagnostics)
        self._queue_s = compose_queue_s
        self._restorable: dict[tuple[str, str, str], deque[PrefabRef]] = {}
        self._locks: dict[tuple[str, str, str], asyncio.Lock] = {}
        self._drafts: dict[str, dict[str, Any]] = {}
        self._draft_users: dict[str, int] = {}
        self._compose_locks: dict[str, asyncio.Lock] = {}
        self._outcomes: dict[tuple[str, str, str, str, int], ReloadResult] = {}
        self._unverified: dict[tuple[str, str, str], _Unverified] = {}
        self._recent: deque[dict[str, Any]] = deque(maxlen=MAX_RECENT_RELOADS)
        self._reloading: dict[tuple[str, str, str], int] = {}
        self._limiter = SourceEditLimiter(lambda: self._monotonic(), lambda kind, message, data: self._trace(kind, message, data=data))
        studio.set_scene_guard(self.is_reloading)  # QA-1 B1: an ordinary edit of a scene in flight is refused (typed 409)
        self._closing = False
        self._inflight = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._counters = {"applied": 0, "refused": 0, "rolled_back": 0, "stale": 0, "pending": 0, "merged": 0, "degraded": 0}

    def bind_playback(self, playback: PlaybackProbe) -> None:
        """La lecture (Slice 12), liee apres sa construction (`v2_app`) : la position qu'un resultat rapporte, **lue** avant
        et apres le rechargement (`preserved.playback`, `playback_unchanged`)."""

        self._playback = playback

    @property
    def mounts(self) -> MountBook:
        return self._mounts

    @property
    def stage(self) -> StageWindows:
        return self._stage

    # ------------------------------------------------------------ cycle de vie

    async def recover(self) -> int:
        """Au demarrage : retrouve dans les documents les scenes dont le pin n'a pas ete confirme (arret entre l'ecriture
        du pin et le rapport de montage). Ne ramene rien en arriere d'office : un pin non confirme n'est pas un echec,
        le prochain rapport tranche. Rend leur nombre. Ne leve pas (une panne est journalisee en `error`)."""

        try:
            variants = await self._studio.all_variants()
        except PresentationStudioError as exc:
            self._trace("core.presentation_studio.reload_recover_failed", "Scenes non confirmees illisibles au demarrage",
                        level="error", data={"code": exc.code.value})
            return 0
        self._unverified.clear()
        for variant in variants:
            for scene in variant.scenes:
                if scene.last_valid_pin is not None:
                    self._unverified[(variant.presentation_id, variant.variant_id, scene.scene_id)] = _Unverified(
                        variant.presentation_id, variant.variant_id, scene.scene_id, scene.prefab, scene.last_valid_pin,
                        scene.source_revision)
        if self._unverified:
            self._trace("core.presentation_studio.reload_unverified", "Scenes dont le pin n'a pas ete vu monte", level="warning",
                        data={"count": len(self._unverified)})
        return len(self._unverified)

    async def close(self) -> None:
        """Arret de Core : plus de nouvelle edition, la rafale en attente est publiee (`flush`, condition d'entree de la
        Slice 06), puis les editions en vol finissent (bornees). Idempotent."""

        self._closing = True
        try:
            await self._coalescer.flush()
        except Exception as exc:  # noqa: BLE001 - recorded: a flush failure is every waiter's own typed error, not Core's
            self._trace("core.presentation_studio.reload_flush_failed", "Rafale en attente non publiee a l'arret",
                        level="error", data={"error_class": type(exc).__name__})
        try:
            await asyncio.wait_for(self._idle.wait(), CLOSE_GRACE_S)
        except TimeoutError:
            self._trace("core.presentation_studio.reload_close_timeout", "Editions en vol a l'arret de Core", level="warning",
                        data={"inflight": self._inflight})

    def is_reloading(self, presentation_id: str, variant_id: str, scene_id: str) -> bool:
        """Vrai de la publication d'une source de cette scene a la confirmation du montage (ou son echec)."""

        return (presentation_id, variant_id, scene_id) in self._reloading

    def pending_scenes(self) -> tuple[_Unverified, ...]:
        return tuple(self._unverified.values())

    def recent(self, presentation_id: str | None = None) -> list[dict[str, Any]]:
        """Les derniers resultats (bornes, sans contenu), du plus ancien au plus recent."""

        return [row for row in self._recent if presentation_id is None or row["presentation_id"] == presentation_id]

    def archive_counts(self, scene_ids: Iterable[str], presentation_id: str) -> dict[str, dict[str, int]]:
        """Pour `/reloads` : par scene, les versions vivantes et archivees de sa source (lecture seule, aucune suppression)."""

        counter = getattr(self._prefabs, "retention_counts", None)
        if counter is None:
            return {}
        return {scene_id: counter(source_prefab_id(presentation_id, scene_id)) for scene_id in scene_ids}

    def stats(self) -> dict[str, int]:
        return {**self._counters, "unverified": len(self._unverified), "inflight": self._inflight}

    # ------------------------------------------------------------ edition de source

    async def apply_source_edit(self, presentation_id: str, variant_id: str, raw: object) -> ReloadResult:
        """Applique une edition de source a **une** scene. Une requete mal formee, une presentation/variante/scene
        inconnue, un prefab indisponible et une panne de donnees levent `PresentationStudioError` ; tout le reste est un
        `ReloadResult` avec son statut (rien n'est jamais perdu en silence)."""

        if self._closing:
            raise PresentationStudioError(C.RELOAD_UNAVAILABLE, "Core is stopping: no new source edit is accepted")
        request = parse_source_edit(raw)
        self._admit(presentation_id, variant_id, request)
        self._inflight += 1
        self._idle.clear()
        started = self._monotonic()
        try:
            result = await self._apply(presentation_id, variant_id, request)
        except PresentationStudioError as exc:
            hard = exc.code in (C.STORAGE_IO, C.CORRUPT_DOCUMENT, C.UNSUPPORTED_SCHEMA_VERSION, C.PREFAB_UNAVAILABLE)
            self._trace("core.presentation_studio.reload_failed" if hard else "core.presentation_studio.reload_refused",
                        "Rechargement non applique", level="error" if hard else "info",
                        data={"presentation_id": presentation_id, "variant_id": variant_id, "scene_id": request.scene_id,
                              "code": exc.code.value, "actor": request.actor.value})
            raise
        finally:
            self._inflight -= 1
            if not self._inflight:
                self._idle.set()
        self._finish(result, elapsed=self._monotonic() - started)
        return result

    def _admit(self, presentation_id: str, variant_id: str, request: SourceEditRequest) -> None:
        """Plafond par scene des editions de l'agent (`presentation_studio_reload_limits`)."""

        self._limiter.admit((presentation_id, variant_id, request.scene_id), limited=request.actor is StudioActor.BRAIN)

    async def _apply(self, presentation_id: str, variant_id: str, request: SourceEditRequest) -> ReloadResult:
        variant = await self._studio.get_variant(presentation_id, variant_id)
        scene = variant_scene(variant, request.scene_id)
        if request.basis_revision != variant.revision:
            return self._stale(presentation_id, variant, scene, request,
                               f"the variant is at revision {variant.revision}, not {request.basis_revision}: read it again, then retry")
        source_id = source_prefab_id(presentation_id, scene.scene_id)
        # ---- phase 1: compose, validate, publish. Composition is serialized PER SOURCE ID so a retouche of a burst is always
        # built on the previous one (the draft), never on the pin: the coalescer keeps the LAST candidate, which must
        # therefore contain every earlier one. Publication itself is not under any lock, so the burst can merge.
        compose = self._compose_lock(source_id)
        try:
            await asyncio.wait_for(compose.acquire(), self._queue_s)
        except TimeoutError:
            self._trace("core.presentation_studio.reload_busy", "Edition en attente trop longtemps derriere une autre de la scene",
                        level="warning", data={"presentation_id": presentation_id, "scene_id": scene.scene_id,
                                               "waited_s": self._queue_s})
            raise PresentationStudioError(
                C.SCENE_RELOADING, f"another edit of this scene has been composing or building for more than {self._queue_s:g} s: "
                                   "retry in a few seconds") from None
        try:
            # The basis is judged AGAIN once the turn comes: while this request waited, an earlier one may have landed, and a stale
            # request must not build or publish anything (Slice 14: a build is costly).
            variant = await self._studio.get_variant(presentation_id, variant_id)
            scene = variant_scene(variant, request.scene_id)
            if request.basis_revision != variant.revision:
                return self._stale(presentation_id, variant, scene, request,
                                   f"the variant moved to revision {variant.revision} while this edit waited its turn: read it again, "
                                   "then retry")
            gated = await self._gate(presentation_id, variant, scene, request, source_id)
            if isinstance(gated, ReloadResult):
                return gated
            self._draft_users[source_id] = self._draft_users.get(source_id, 0) + 1
        finally:
            compose.release()
        candidate, carry_reset = gated
        try:
            try:
                publication = await self._publish(candidate, request, scene, source_id)
            except PrefabStoreError as exc:
                return self._publish_refused(presentation_id, variant, scene, request, exc)
            published = PrefabRef(publication.prefab_id, publication.version)
            self._trace("core.presentation_studio.reload_published", "Source de scene publiee",
                        data={"presentation_id": presentation_id, "variant_id": variant_id, "scene_id": scene.scene_id,
                              "prefab": f"{published.prefab_id}@{published.version}"})
            # ---- phase 2 (per-scene lock) --------------------------------------------------------------------------
            key = (presentation_id, variant_id, scene.scene_id)
            lock = self._locks.setdefault(key, asyncio.Lock())
            self._reloading[key] = self._reloading.get(key, 0) + 1  # QA-1 B1: ordinary edits of this scene are refused until the end
            try:
                async with lock:
                    known = self._outcomes.get((*key, published.prefab_id, published.version))
                    if known is not None:  # another caller of the same burst already carried this publication through
                        self._counters["merged"] += 1
                        return replace(known, merged=True, actor=request.actor,
                                       request_id=request.request_id or known.request_id)
                    result = await self._swap(presentation_id, variant_id, scene, request, published, carry_reset)
                    self._outcomes[(*key, published.prefab_id, published.version)] = result
                    while len(self._outcomes) > MAX_RECENT_RELOADS:
                        del self._outcomes[next(iter(self._outcomes))]
                    return result
            finally:
                left = self._reloading.get(key, 1) - 1
                if left > 0:
                    self._reloading[key] = left
                else:
                    self._reloading.pop(key, None)
                if not lock.locked() and self._locks.get(key) is lock:
                    del self._locks[key]
        finally:
            self._release_draft(source_id)

    async def _write_scene(self, presentation_id: str, variant_id: str, expected_revision: int, scene: StudioScene,
                           step: str) -> PresentationVariant:
        """UNE ecriture de scene du rechargement (`replace_scene_source`), puis annoncee aux abonnes de commit du service
        d'edition avec un `ReloadOrigin` : la lecture (Slice 12) suit sans etre mise en pause, le plan relu garde son element."""

        saved = await self._studio.replace_scene_source(presentation_id, variant_id, expected_revision=expected_revision,
                                                        scene=scene)
        if self._edits is not None:
            try:
                await self._edits.announce_commit(presentation_id, variant_id, saved.revision, ReloadOrigin(scene.scene_id, step))
            except Exception as exc:  # noqa: BLE001 - recorded: an unavailable follower never undoes a committed pin
                self._trace("core.presentation_studio.reload_announce_failed", "Abonnes de commit non prevenus", level="warning",
                            data={"presentation_id": presentation_id, "scene_id": scene.scene_id, "step": step,
                                  "error_class": type(exc).__name__})
        return saved

    def _compose_lock(self, source_id: str) -> asyncio.Lock:
        return self._compose_locks.setdefault(source_id, asyncio.Lock())

    def _release_draft(self, source_id: str) -> None:
        """Le dernier appelant d'une rafale a fini (pin ecrit, refus ou echec) : le brouillon n'a plus de raison d'etre, la
        base de la prochaine edition est de nouveau le pin de la scene."""

        left = self._draft_users.get(source_id, 1) - 1
        if left > 0:
            self._draft_users[source_id] = left
            return
        self._draft_users.pop(source_id, None)
        self._drafts.pop(source_id, None)
        lock = self._compose_locks.get(source_id)
        if lock is not None and not lock.locked():
            del self._compose_locks[source_id]

    # ------------------------------------------------------------ phase 1

    async def _gate(self, presentation_id: str, variant: PresentationVariant, scene: StudioScene,
                    request: SourceEditRequest, source_id: str) -> tuple[dict[str, Any], StateReset | None] | ReloadResult:
        """Le garde-fou « compilation / validation » AVANT toute publication : rien n'est publie si un controle echoue."""

        current = await self._base_of(scene.prefab)
        base = await self._edit_base(presentation_id, variant, scene, request, source_id, current)
        if isinstance(base, ReloadResult):
            return base
        kind = "Remotion" if current.remotion else "Slidecar (HTML)"
        wants_html = any(key in request.files for key in ("template", "style", "behavior"))
        if (base.remotion != current.remotion or (request.targets_remotion and not current.remotion)
                or (wants_html and current.remotion)):
            return self._refused(presentation_id, variant, scene, request, C.SOURCE_INVALID,
                                 f"this scene is a {kind} scene: " + ("send files.sources / files.assets (and manifest)"
                                                                      if current.remotion else
                                                                      "send files.template / style / behavior (and manifest)"))
        if base.remotion:
            composed, problems = compose_remotion_candidate(
                base.manifest, base.files or {}, sources=request.sources, assets=request.assets,
                manifest=request.files.get("manifest"), prefab_id=source_id)
            if composed is None:
                return self._refused(presentation_id, variant, scene, request, C.SOURCE_INVALID, "; ".join(problems))
            candidate = composed
        else:
            candidate = compose_candidate(base.manifest, base.html or {}, request.files, prefab_id=source_id)
        # The number is Core's, given at publication; here it only has to make the candidate's ref the CURRENT pin's number, so the
        # carry-over below never sees a restored version's number as "another pin" (a restore composes on an older version).
        candidate["manifest"]["version"] = scene.prefab.version
        unsafe = unsafe_manifest_key(candidate["manifest"])
        if unsafe is not None:
            return self._refused(presentation_id, variant, scene, request, C.SOURCE_INVALID,
                                 f"the manifest declares a reserved property name ({unsafe!r}): rename it")
        verdict = self._prefabs.validate_candidate(candidate)
        if not verdict.ok:
            return self._refused(presentation_id, variant, scene, request, C.SOURCE_INVALID,
                                 "; ".join(verdict.errors[:MAX_PROBLEMS_IN_MESSAGE]) or "the candidate is invalid")
        try:
            parsed = parse_candidate(candidate)
            manifest = parsed.manifest
        except PrefabDefinitionError as exc:  # validate_candidate just accepted it: a race with the validator, still refused
            return self._refused(presentation_id, variant, scene, request, C.SOURCE_INVALID, "; ".join(exc.errors[:3]))
        carried = plan_carry_over(scene, manifest, allow_reset=request.allow_state_reset)
        if carried.scene is None:
            hint = "" if request.allow_state_reset else " (allow_state_reset would reset what no longer fits)"
            return self._refused(presentation_id, variant, scene, request, C.SCENE_INCOMPATIBLE,
                                 "the scene values or controls no longer fit the new manifest: "
                                 + "; ".join(carried.problems[:MAX_PROBLEMS_IN_MESSAGE]) + hint)
        after = tuple(carried.scene if item.scene_id == scene.scene_id else item for item in variant.scenes)
        before_problems = set(await self._studio.score_problems(presentation_id, variant.variant_id, variant.scenes))
        new_problems = [p for p in await self._studio.score_problems(presentation_id, variant.variant_id, after)
                        if p not in before_problems]
        if new_problems:
            return self._refused(presentation_id, variant, scene, request, C.SCORE_INCOMPATIBLE,
                                 "the score would no longer match the scene: " + "; ".join(new_problems[:MAX_PROBLEMS_IN_MESSAGE]))
        if base.remotion:  # the real build, last (the cheap checks first): a source that does not compile is never published
            refusal = await self._build.check(parsed.remotion_source(), scene_id=scene.scene_id)
            if refusal is not None:
                return self._refused(presentation_id, variant, scene, request, refusal.code, refusal.message,
                                     diagnostics=refusal.diagnostics)
        self._drafts[source_id] = candidate
        return candidate, carried.reset

    async def _edit_base(self, presentation_id: str, variant: PresentationVariant, scene: StudioScene, request: SourceEditRequest,
                         source_id: str, current: _Base) -> _Base | ReloadResult:
        """Sur quoi l'edition se compose : la version a restaurer (annuler / retablir), le brouillon de la rafale en cours, ou le
        pin courant."""

        if request.restore is not None:
            target = request.restore
            history = self._restorable.get((presentation_id, variant.variant_id, scene.scene_id), ())
            if target.prefab_id != source_id and target not in history:
                return self._refused(presentation_id, variant, scene, request, C.SOURCE_INVALID,
                                     f"{target.prefab_id}@{target.version} is not a version this scene had: only the scene's own "
                                     "source versions and the versions it was reloaded from can be restored")
            try:
                return await self._base_of(target)
            except PresentationStudioError as exc:
                if exc.code is not C.PREFAB_UNAVAILABLE:
                    raise
                return self._refused(presentation_id, variant, scene, request, C.SOURCE_INVALID,
                                     f"{target.prefab_id}@{target.version} cannot be restored (archived, altered or never "
                                     f"published): {exc.message}")
        draft = self._drafts.get(source_id)
        if draft is None:
            return current
        if "sources" in draft:  # a burst in progress: compose on top of it, so no retouch of the burst is lost
            return _Base(draft["manifest"], None, candidate_files(draft))
        return _Base(draft["manifest"], {k: draft[k] for k in ("template", "style", "behavior")})

    async def _base_of(self, ref: PrefabRef) -> _Base:
        """Manifeste brut et fichiers d'une version (`PrefabStoreError` -> `prefab_unavailable`, comme le catalogue). Une version
        Remotion est relue a la demande, octets verifies et gardes d'isolation rejoues (`PrefabService.remotion_source`)."""

        try:
            detail = await self._prefabs.get(ref.prefab_id, ref.version)
            bundle = detail.entry.bundle
            if bundle.is_remotion:
                source = await self._prefabs.remotion_source(ref.prefab_id, ref.version)
                return _Base(dict(bundle.manifest.raw), None, dict(source.files))
        except PrefabStoreError as exc:
            raise PresentationStudioError(
                C.PREFAB_UNAVAILABLE, f"{ref.prefab_id}@{ref.version}: {exc.code.value}: {exc.message}") from exc
        return _Base(dict(bundle.manifest.raw), dict(bundle.files()))

    async def read_source(self, presentation_id: str, variant_id: str, scene_id: str) -> dict[str, Any]:
        """La source du pin de la scene, ce qu'un agent lit avant de proposer une edition : `GET .../scenes/{id}/source`.
        Remotion : modules en texte, assets en inventaire (taille, SHA-256), jamais d'octets d'asset. Slidecar : les trois textes."""

        variant = await self._studio.get_variant(presentation_id, variant_id)
        scene = variant_scene(variant, scene_id)
        base = await self._base_of(scene.prefab)
        body: dict[str, Any] = {"scene_id": scene_id, "prefab": scene.prefab.to_dict(), "source_revision": scene.source_revision,
                                "basis": {"variant_revision": variant.revision}, "manifest": base.manifest,
                                "engine": "remotion" if base.remotion else "slidecar"}
        if base.files is not None:
            modules = sorted(str(path) for path in base.manifest["source"]["modules"])
            body["sources"] = {path: base.files[path].decode("utf-8", errors="replace") for path in modules}
            body["assets"] = {path: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                              for path, data in sorted(base.files.items()) if path not in modules}
        else:
            body["files"] = dict(base.html or {})
        return body

    async def _publish(self, candidate: dict[str, Any], request: SourceEditRequest, scene: StudioScene,
                       source_id: str) -> Publication:
        """Publication par le coalesceur de la 01a. Un id de scene deja connu est une revision ; sinon un fork du pin courant."""

        derived: PrefabRef | None = None
        try:
            await self._prefabs.get(source_id)
        except PrefabStoreError as exc:
            if exc.code is not PC.UNKNOWN_PREFAB:
                raise
            derived = scene.prefab if scene.prefab.prefab_id != source_id else None
        try:
            return await self._coalescer.submit(candidate, actor=request.actor.value, derived_from=derived)
        except PrefabStoreError as first:
            if derived is None:
                raise
            # Two edits raced on the scene's FIRST version (Slice 14: a build between the check and the submit widens the
            # window): if the other one created the id meanwhile, this one is a revision of it, not a second fork.
            try:
                await self._prefabs.get(source_id)
            except PrefabStoreError:
                raise first from None
        return await self._coalescer.submit(candidate, actor=request.actor.value, derived_from=None)

    # ------------------------------------------------------------ phase 2

    async def _swap(self, presentation_id: str, variant_id: str, expected_scene: StudioScene, request: SourceEditRequest,
                    published: PrefabRef, carry_reset: StateReset | None) -> ReloadResult:
        fresh = await self._studio.get_variant(presentation_id, variant_id)
        scene = variant_scene(fresh, expected_scene.scene_id)
        if fresh.revision != request.basis_revision or scene.prefab != expected_scene.prefab:
            return self._stale(presentation_id, fresh, scene, request,
                               "another edit landed on this scene while the source was being published: read it again, "
                               "then retry (the published version stays unpinned and harmless)", published=published)
        old = scene.prefab
        try:
            manifest = await self._prefabs.manifest(published.prefab_id, published.version)
        except PrefabStoreError as exc:
            raise PresentationStudioError(C.PREFAB_UNAVAILABLE,
                                          f"{published.prefab_id}@{published.version}: {exc.code.value}: {exc.message}") from exc
        carried = plan_carry_over(scene, manifest, allow_reset=request.allow_state_reset)
        if carried.scene is None:
            return self._refused(presentation_id, fresh, scene, request, C.SCENE_INCOMPATIBLE,
                                 "the scene values or controls no longer fit the published manifest: "
                                 + "; ".join(carried.problems[:MAX_PROBLEMS_IN_MESSAGE]), published=published)
        reset = carried.reset if carried.reset is not None else carry_reset
        binding = await self._stage.locate(presentation_id, variant_id, scene.scene_id, old)
        live_props, live_data = dict(carried.scene.props), dict(carried.scene.data)
        shown = None
        if binding is not None:
            shown = await self._stage_block(binding, old)
            if shown is not None:
                live_props, live_data, live_reset = carry_live_values(manifest, carried.scene, shown.props, shown.data)
                reset = live_reset if reset is None else (reset.merged(live_reset) if live_reset is not None else reset)
        new_scene = replace(carried.scene, prefab=published, source_revision=scene.source_revision + 1, last_valid_pin=old)
        playback_before = self._position(presentation_id)
        # The old and the new version are held against retention for the whole operation (publication -> confirmation).
        with (self._pins.hold((old.prefab_id, old.version), (published.prefab_id, published.version))
              if self._pins is not None else nullcontext()):
            return await self._write_and_stage(presentation_id, variant_id, request, binding, fresh, scene, new_scene, old,
                                               manifest, live_props, live_data, shown, reset, playback_before)

    async def _write_and_stage(self, presentation_id: str, variant_id: str, request: SourceEditRequest,
                               binding: StageBinding | None, fresh: PresentationVariant, scene: StudioScene,
                               new_scene: StudioScene, old: PrefabRef, manifest: PrefabManifest, live_props: dict[str, Any],
                               live_data: dict[str, Any], shown: Any, reset: StateReset | None,
                               playback_before: Mapping[str, Any] | None) -> ReloadResult:
        published = new_scene.prefab
        try:  # authoritative instance check against the catalogue (outside every studio lock)
            await self._studio.check_scenes(presentation_id, variant_id,
                                            tuple(new_scene if item.scene_id == scene.scene_id else item
                                                  for item in fresh.scenes), fresh.scenes)
        except PresentationStudioError as exc:
            if exc.code is not C.SCENE_INCOMPATIBLE:
                raise
            return self._refused(presentation_id, fresh, scene, request, C.SCENE_INCOMPATIBLE, exc.message, published=published)
        try:
            saved = await self._write_scene(presentation_id, variant_id, fresh.revision, new_scene, "pin")
        except PresentationStudioError as exc:
            if exc.code is C.STALE_REVISION:
                return self._stale(presentation_id, fresh, scene, request, exc.message, published=published)
            raise
        revision = saved.revision
        if binding is None:
            self._note_unverified(presentation_id, variant_id, new_scene)
            return self._ok(ReloadStatus.REPINNED, request, presentation_id, variant_id, new_scene, revision, old, reset,
                            mounted=None, playback_before=playback_before,
                            message="no stage window shows this scene: the new version is pinned and waits to be seen mounted")
        return await self._patch_and_confirm(presentation_id, variant_id, request, binding, scene, new_scene, revision, old,
                                             manifest, live_props, live_data, shown, reset, playback_before)

    async def _patch_and_confirm(self, presentation_id: str, variant_id: str, request: SourceEditRequest,
                                 binding: StageBinding, before: StudioScene, scene: StudioScene, revision: int,
                                 old: PrefabRef, manifest: PrefabManifest, props: dict[str, Any], data: dict[str, Any],
                                 shown: Any, reset: StateReset | None, playback_before: Mapping[str, Any] | None) -> ReloadResult:
        published = scene.prefab
        waiter = self._mounts.expect(binding.object_id, published.prefab_id, published.version,
                                     {"scene_id": scene.scene_id, "source_revision": scene.source_revision})
        try:
            await self._stage.repin(binding, expect=old, to=published, props=props, data=data)
        except StagePatchError as exc:
            waiter.cancel()
            return await self._roll_back(presentation_id, variant_id, request, binding, before, scene, revision, old,
                                         code=C.STAGE_FAILED, reason=exc.code, message=exc.message, patched=False,
                                         shown=shown, playback_before=playback_before)
        except Exception:
            waiter.cancel()  # an unexpected fault: the variant is restored before it propagates (never half-applied)
            try:
                await self._restore_variant(presentation_id, variant_id, before, scene)
            except Exception as exc:  # noqa: BLE001 - recorded: the ORIGINAL fault propagates, the scene waits to be repaired
                self._note_unverified(presentation_id, variant_id, scene)
                self._counters["degraded"] += 1
                self._trace("core.presentation_studio.reload_rollback_failed",
                            "Pin non restaure apres une panne du stage : la scene garde la nouvelle version et son repli",
                            level="error", data={"presentation_id": presentation_id, "scene_id": scene.scene_id,
                                                 "error_class": type(exc).__name__})
            raise
        waited_from = self._monotonic()
        report = None if self._closing else await waiter.wait(self._deadline_s)
        waited = round(self._monotonic() - waited_from, 3)
        if report is None:
            self._note_unverified(presentation_id, variant_id, scene)
            self._counters["pending"] += 1
            return self._ok(ReloadStatus.PENDING_MOUNT, request, presentation_id, variant_id, scene, revision, old, reset,
                            mounted=None, playback_before=playback_before, waited_s=waited, code=C.MOUNT_FAILED.value,
                            message=f"the page did not report the mount within {self._deadline_s:g} s: the new version "
                                    "stays pinned with its fallback, a late report will confirm or roll it back")
        if report.outcome is MountOutcome.FAILED:
            return await self._roll_back(presentation_id, variant_id, request, binding, before, scene, revision, old,
                                         code=C.MOUNT_FAILED, reason=report.reason or "mount_failed",
                                         message=report.message or "the frame failed to mount", patched=True, shown=shown,
                                         playback_before=playback_before, waited_s=waited)
        confirmed_scene, confirmed_revision, failure = await self._confirm(presentation_id, variant_id, scene, revision)
        if failure is not None:  # mounted, but the fallback could not be cleared: say so, never "reloaded"
            self._note_unverified(presentation_id, variant_id, scene)
            self._counters["pending"] += 1
            return self._ok(ReloadStatus.PENDING_MOUNT, request, presentation_id, variant_id, scene, revision, old, reset,
                            mounted=True, playback_before=playback_before, waited_s=waited, code=failure,
                            message="the frame mounted the new version, but its confirmation could not be written: the new "
                                    "version stays pinned with its fallback until a later report or reload confirms it")
        status = ReloadStatus.RELOADED_STATE_RESET if reset is not None and not reset.empty else ReloadStatus.RELOADED
        return self._ok(status, request, presentation_id, variant_id, confirmed_scene, confirmed_revision, old, reset, mounted=True,
                        playback_before=playback_before, waited_s=waited)

    # ------------------------------------------------------------ confirmation et retour arriere

    async def _confirm(self, presentation_id: str, variant_id: str, scene: StudioScene,
                       revision: int) -> tuple[StudioScene, int, str | None]:
        """Efface le repli (le pin est vu monte). Rend `(scene, revision, echec)` : `echec` est `None` si la confirmation est
        ecrite (ou inutile), sinon le code de la panne ; alors le repli reste et l'appelant ne doit PAS annoncer un succes."""

        failure = C.STALE_REVISION.value
        for _ in range(2):  # a control edit may have bumped the revision since: read it once more, then give up loudly
            try:
                current = await self._studio.get_variant(presentation_id, variant_id)
                live = variant_scene(current, scene.scene_id)
                if live.prefab != scene.prefab or live.last_valid_pin is None:
                    self._unverified.pop((presentation_id, variant_id, scene.scene_id), None)
                    return live, current.revision, None  # superseded or already confirmed: nothing to write
                saved = await self._write_scene(presentation_id, variant_id, current.revision,
                                                replace(live, last_valid_pin=None), "confirm")
                self._unverified.pop((presentation_id, variant_id, scene.scene_id), None)
                return replace(live, last_valid_pin=None), saved.revision, None
            except PresentationStudioError as exc:
                failure = exc.code.value
                if exc.code is C.STALE_REVISION:
                    continue
                break
        self._trace("core.presentation_studio.reload_confirm_failed", "Confirmation du pin non ecrite (le repli reste)",
                    level="error", data={"presentation_id": presentation_id, "variant_id": variant_id,
                                         "scene_id": scene.scene_id, "code": failure})
        return scene, revision, failure

    async def _roll_back(self, presentation_id: str, variant_id: str, request: SourceEditRequest, binding: StageBinding | None,
                         before: StudioScene, scene: StudioScene, revision: int, old: PrefabRef, *, code: C, reason: str,
                         message: str, patched: bool, shown: Any, playback_before: Mapping[str, Any] | None,
                         waited_s: float | None = None) -> ReloadResult:
        """Ramene le pin a la derniere version valide : le stage d'abord (si on l'a patche), puis la variante. Le retour
        arriere est un **compare-and-restore** minimal (`_restore_variant`) : il ne reecrit que les champs de pin ; une valeur
        ecrite par quelqu'un d'autre depuis (edition de controle...) est gardee, jamais ecrasee par une copie perimee.
        Si le stage ou la variante ne peuvent pas etre restaures (essais bornes), la scene est `degraded` : visible, son repli
        reste ecrit pour qu'un rechargement ou un redemarrage la repare."""

        if patched and binding is not None:
            failed = await self._restore_stage(binding, scene.prefab, old, shown, before)
            if failed is not None:
                return self._degraded(presentation_id, variant_id, request, scene, revision, old, C.STAGE_FAILED, failed,
                                      f"{message} (and the stage window could not be put back on the last valid version: {failed})",
                                      playback_before, waited_s, reason)
        try:
            restored_revision, restored, reset = await self._restore_variant(presentation_id, variant_id, before, scene)
        except PresentationStudioError as exc:
            return self._degraded(presentation_id, variant_id, request, scene, revision, old, exc.code, exc.code.value,
                                  f"{message} (and the previous pin could not be written back: {exc.code.value})",
                                  playback_before, waited_s, reason)
        shown_scene = restored if restored is not None else replace(before, source_revision=scene.source_revision + 1)
        self._unverified.pop((presentation_id, variant_id, scene.scene_id), None)
        self._counters["rolled_back"] += 1
        reset = None if reset is None or reset.empty else reset
        note = ""
        if reset is not None:
            gone = "; ".join(f"{name}: {', '.join(items)}" for name, items in reset.to_dict().items()
                             if name != "unfit" and isinstance(items, list) and items)
            if gone:
                note += f" (values that no longer fit the restored version were reset: {gone})"
            if reset.unfit:
                note += (f" (kept but INVALID for the restored version, correct them: {', '.join(reset.unfit)})")
        return self._make(ReloadStatus.ROLLED_BACK, request, presentation_id, variant_id, shown_scene, restored_revision,
                          prefab=old, previous=old, published=scene.prefab, code=code.value,
                          message=clip(f"{message}{note}"), mounted=False if code is C.MOUNT_FAILED else None,
                          playback_before=playback_before, waited_s=waited_s, reason=reason, reset=reset)

    def _degraded(self, presentation_id: str, variant_id: str, request: SourceEditRequest, scene: StudioScene, revision: int,
                  old: PrefabRef, code: C | str, detail: str, message: str, playback_before: Mapping[str, Any] | None,
                  waited_s: float | None, reason: str) -> ReloadResult:
        """Retour arriere impossible : la scene garde la nouvelle version et son repli (`last_valid_pin`), reperee comme non
        confirmee (le prochain rapport, un rechargement ou le redemarrage la reprend)."""

        self._note_unverified(presentation_id, variant_id, scene)
        self._counters["degraded"] += 1
        text = code.value if isinstance(code, C) else code
        self._trace("core.presentation_studio.reload_rollback_failed", "Retour arriere impossible : scene degradee",
                    level="error", data={"presentation_id": presentation_id, "variant_id": variant_id,
                                         "scene_id": scene.scene_id, "code": text, "detail": clip(detail, 120)})
        return self._make(ReloadStatus.DEGRADED, request, presentation_id, variant_id, scene, revision, prefab=scene.prefab,
                          previous=old, published=scene.prefab, code=text, message=clip(message), mounted=False,
                          playback_before=playback_before, waited_s=waited_s, reason=reason)

    async def _restore_stage(self, binding: StageBinding, current: PrefabRef, old: PrefabRef, shown: Any,
                             before: StudioScene) -> str | None:
        """Remet la fenetre stage sur `old` (essais bornes). `None` si c'est fait, sinon le code de la derniere panne."""

        props = dict(shown.props) if shown is not None else dict(before.props)
        data = dict(shown.data) if shown is not None else dict(before.data)
        failure = "stage_failed"
        for _ in range(STAGE_RESTORE_ATTEMPTS):
            try:
                await self._stage.repin(binding, expect=current, to=old, props=props, data=data)
                return None
            except StagePatchError as exc:
                failure = exc.code
            except Exception as exc:  # noqa: BLE001 - recorded below: a bounded retry, then a visible degradation
                failure = type(exc).__name__
            await asyncio.sleep(0)
        self._trace("core.presentation_studio.reload_rollback_failed", "Stage non restaure apres un echec de montage",
                    level="error", data={"object_id": binding.object_id, "code": failure,
                                         "attempts": STAGE_RESTORE_ATTEMPTS})
        return failure

    async def _restore_variant(self, presentation_id: str, variant_id: str, before: StudioScene,
                               scene: StudioScene) -> tuple[int, StudioScene | None, StateReset | None]:
        """Compare-and-restore de la scene apres un echec : seuls le pin, son repli et le compteur reviennent a `before` ;
        chaque valeur (`props`/`data` par cle, controles, ancres) que la scene ecrite par le rechargement (`scene`) porte
        toujours est remise a celle de `before`, **toute valeur ecrite depuis (edition de controle) est gardee** ; le tout est
        revalide contre le manifeste restaure (ce qui ne tient plus est retire et nomme dans le `StateReset` rendu).
        Quelqu'un a pu ecrire la variante entre-temps : on relit (trois essais). `(revision, scene restauree | None, reset)` ;
        `None` si le pin a ete change par un autre (leur pin tient, on ne restaure rien par-dessus)."""

        old = before.prefab
        try:
            manifest = await self._prefabs.manifest(old.prefab_id, old.version)
        except PrefabStoreError as exc:
            raise PresentationStudioError(C.PREFAB_UNAVAILABLE,
                                          f"{old.prefab_id}@{old.version}: {exc.code.value}: {exc.message}") from exc
        for _ in range(3):
            current = await self._studio.get_variant(presentation_id, variant_id)
            live = variant_scene(current, scene.scene_id)
            if live.prefab != scene.prefab:
                return current.revision, None, None  # superseded by someone else: their pin stands
            merged = merge_restore(live, before, scene)
            carried = plan_carry_over(merged, manifest, allow_reset=False)
            if carried.scene is None:
                carried = plan_carry_over(merged, manifest, allow_reset=True)
            if carried.scene is None:  # cannot be made valid for the restored manifest: pin fields only, values kept, traced
                self._trace("core.presentation_studio.reload_restore_unvalidated",
                            "Valeurs non validables contre la version restauree : gardees telles quelles", level="warning",
                            data={"presentation_id": presentation_id, "scene_id": scene.scene_id})
                names = unfit_names(scene_problems(merged, manifest))
                carried = CarryOver(merged, StateReset(unfit=names or ("values",)), ())
            target = replace(carried.scene, prefab=old, last_valid_pin=before.last_valid_pin,
                             source_revision=live.source_revision + 1)
            try:
                saved = await self._write_scene(presentation_id, variant_id, current.revision, target, "rollback")
            except PresentationStudioError as exc:
                if exc.code is not C.STALE_REVISION:
                    self._trace("core.presentation_studio.reload_rollback_failed",
                                "Pin non restaure : la scene garde la nouvelle version, son repli est conserve", level="error",
                                data={"presentation_id": presentation_id, "scene_id": scene.scene_id, "code": exc.code.value})
                    raise
                continue
            return saved.revision, target, carried.reset
        raise PresentationStudioError(C.STALE_REVISION, "the variant kept changing while the previous pin was restored")

    # ------------------------------------------------------------ rapports de montage

    async def handle_mount_report(self, raw: object) -> dict[str, Any]:
        """`POST .../mount-reports` : ce que l'hote a observe. Remis a l'edition qui attend ; sinon (rapport tardif ou
        scene jamais affichee) il confirme ou ramene en arriere les scenes non confirmees qui epinglent cette version."""

        report = parse_mount_report(raw)
        scenes = self._mounts.report(report)
        waiting = len(scenes)
        handled = 0
        if not waiting:
            for key, entry in list(self._unverified.items()):
                if entry.pin == report.prefab:
                    await self._resolve_unverified(key, entry, report)
                    scenes.append({"scene_id": entry.scene_id, "source_revision": entry.source_revision})
                    handled += 1
        self._trace("core.presentation_studio.mount_reported", "Montage rapporte par l'hote",
                    data={"object_id": report.object_id, "prefab": f"{report.prefab.prefab_id}@{report.prefab.version}",
                          "outcome": report.outcome.value, "reason": report.reason or None, "waiting": waiting,
                          "resolved": handled, "scenes": scenes})
        return {"matched": bool(waiting or handled), "waiting": waiting, "resolved": handled, "scenes": scenes}

    async def _resolve_unverified(self, key: tuple[str, str, str], entry: _Unverified, report: MountReport) -> None:
        presentation_id, variant_id, scene_id = key
        async with self._locks.setdefault(key, asyncio.Lock()):
            if self._unverified.get(key) is not entry:
                return
            current = await self._studio.get_variant(presentation_id, variant_id)
            scene = variant_scene(current, scene_id)
            if scene.prefab != entry.pin or scene.last_valid_pin is None:
                self._unverified.pop(key, None)  # superseded or already confirmed
                return
            if report.outcome is MountOutcome.MOUNTED:
                _, _, failure = await self._confirm(presentation_id, variant_id, scene, current.revision)
                if failure is None:
                    self._publish_late(presentation_id, variant_id, scene, ReloadStatus.RELOADED, None, report)
                else:  # stays unverified (the fallback is still written): a later report or a restart confirms it
                    self._publish_late(presentation_id, variant_id, scene, ReloadStatus.PENDING_MOUNT, failure, report)
                return
            old = scene.last_valid_pin
            before = replace(scene, prefab=old, last_valid_pin=None)
            binding = await self._stage.locate(presentation_id, variant_id, scene_id, scene.prefab)
            block = None if binding is None else await self._stage_block(binding, scene.prefab)
            if binding is not None and block is not None:  # the window still shows the failed version: put it back
                failed = await self._restore_stage(binding, scene.prefab, old, block, before)
                if failed is not None:  # stays unverified: a later report, a reload or a restart repairs it
                    self._counters["degraded"] += 1
                    self._publish_late(presentation_id, variant_id, scene, ReloadStatus.DEGRADED, C.STAGE_FAILED.value, report)
                    return
            try:
                await self._restore_variant(presentation_id, variant_id, before, scene)
            except PresentationStudioError as exc:
                self._counters["degraded"] += 1
                self._publish_late(presentation_id, variant_id, scene, ReloadStatus.DEGRADED, exc.code.value, report)
                return
            self._unverified.pop(key, None)
            self._counters["rolled_back"] += 1
            self._publish_late(presentation_id, variant_id, scene, ReloadStatus.ROLLED_BACK, C.MOUNT_FAILED.value, report)

    def _publish_late(self, presentation_id: str, variant_id: str, scene: StudioScene, status: ReloadStatus,
                      code: str | None, report: MountReport) -> None:
        row = {"presentation_id": presentation_id, "variant_id": variant_id, "scene_id": scene.scene_id,
               "status": status.value, "source_revision": scene.source_revision, "late": True, "code": code,
               "reason": report.reason or None, "message": report.message if status is ReloadStatus.ROLLED_BACK else ""}
        self._recent.append(row)
        self._emit(presentation_id, variant_id, scene.scene_id, status.value, scene.source_revision, "user", code, report.reason)
        self._trace("core.presentation_studio.reload_late", "Rapport de montage tardif applique",
                    level="warning" if status is ReloadStatus.ROLLED_BACK else "info",
                    data={k: v for k, v in row.items() if k != "message"})

    # ------------------------------------------------------------ aides

    async def _stage_block(self, binding: StageBinding, old: PrefabRef) -> Any:
        """Le bloc vivant du stage s'il montre encore `old` (sinon `None` : on repart des valeurs de la scene)."""

        try:
            block = await self._stage.current(binding)
        except Exception as exc:  # noqa: BLE001 - recorded: an unreadable stage is "not shown", the edit stays valid
            self._trace("core.presentation_studio.stage_unreadable", "Stage illisible pendant un rechargement", level="warning",
                        data={"error_class": type(exc).__name__})
            return None
        if block is None or PrefabRef(block.prefab_id, block.version) != old:
            return None
        return block

    def _position(self, presentation_id: str) -> Mapping[str, Any] | None:
        if self._playback is None:
            return None
        try:
            found = self._playback.position(presentation_id)
        except Exception as exc:  # noqa: BLE001 - recorded: the position is reported, never required
            self._trace("core.presentation_studio.playback_unreadable", "Position de lecture illisible", level="warning",
                        data={"error_class": type(exc).__name__})
            return None
        return None if found is None else dict(found)

    def _note_unverified(self, presentation_id: str, variant_id: str, scene: StudioScene) -> None:
        if scene.last_valid_pin is not None:
            self._unverified[(presentation_id, variant_id, scene.scene_id)] = _Unverified(
                presentation_id, variant_id, scene.scene_id, scene.prefab, scene.last_valid_pin, scene.source_revision)

    def _refused(self, presentation_id: str, variant: PresentationVariant, scene: StudioScene, request: SourceEditRequest,
                 code: C, message: str, *, published: PrefabRef | None = None,
                 diagnostics: tuple[Mapping[str, Any], ...] = ()) -> ReloadResult:
        self._counters["refused"] += 1
        return self._make(ReloadStatus.REFUSED_VALIDATION, request, presentation_id, variant.variant_id, scene, variant.revision,
                          prefab=scene.prefab, previous=scene.prefab, published=published, code=code.value, message=clip(message),
                          diagnostics=diagnostics)

    def _stale(self, presentation_id: str, variant: PresentationVariant, scene: StudioScene, request: SourceEditRequest,
               message: str, *, published: PrefabRef | None = None) -> ReloadResult:
        self._counters["stale"] += 1
        return self._make(ReloadStatus.STALE, request, presentation_id, variant.variant_id, scene, variant.revision,
                          prefab=scene.prefab, previous=scene.prefab, published=published, code=C.STALE_REVISION.value,
                          message=clip(message))

    def _publish_refused(self, presentation_id: str, variant: PresentationVariant, scene: StudioScene,
                         request: SourceEditRequest, exc: PrefabStoreError) -> ReloadResult:
        if exc.code is PC.STORAGE_IO:
            raise PresentationStudioError(C.STORAGE_IO, f"publication: {exc.message}") from exc
        code = C.LIMIT_REACHED if exc.code in (PC.VERSION_LIMIT, PC.ID_LIMIT) else C.SOURCE_INVALID
        detail = "; ".join(exc.errors[:MAX_PROBLEMS_IN_MESSAGE]) or exc.message
        return self._refused(presentation_id, variant, scene, request, code, f"{exc.code.value}: {detail}")

    def _ok(self, status: ReloadStatus, request: SourceEditRequest, presentation_id: str, variant_id: str, scene: StudioScene,
            revision: int, old: PrefabRef, reset: StateReset | None, *, mounted: bool | None,
            playback_before: Mapping[str, Any] | None, waited_s: float | None = None, code: str = "", message: str = "") -> ReloadResult:
        if status is not ReloadStatus.PENDING_MOUNT:
            self._counters["applied"] += 1
        return self._make(status, request, presentation_id, variant_id, scene, revision, prefab=scene.prefab, previous=old,
                          published=scene.prefab, code=code, message=message, reset=reset, mounted=mounted,
                          playback_before=playback_before, waited_s=waited_s)

    def _make(self, status: ReloadStatus, request: SourceEditRequest, presentation_id: str, variant_id: str, scene: StudioScene,
              revision: int, *, prefab: PrefabRef | None, previous: PrefabRef | None, published: PrefabRef | None = None,
              code: str = "", message: str = "", reset: StateReset | None = None, mounted: bool | None = None,
              playback_before: Mapping[str, Any] | None = None, waited_s: float | None = None, reason: str = "",
              diagnostics: tuple[Mapping[str, Any], ...] = ()) -> ReloadResult:
        position = self._position(presentation_id)
        preserved = {"variant_id": variant_id, "scene_id": scene.scene_id, "playback": position,
                     "playback_unchanged": position == playback_before}
        result = ReloadResult(status=status, actor=request.actor, presentation_id=presentation_id, variant_id=variant_id,
                              scene_id=scene.scene_id, basis_revision=request.basis_revision, revision=revision,
                              source_revision=scene.source_revision, prefab=prefab, previous=previous, published=published,
                              code=code, message=message, reason=reason, reset=reset, mounted=mounted,
                              request_id=request.request_id, preserved=preserved, waited_s=waited_s, diagnostics=diagnostics)
        return result

    def _finish(self, result: ReloadResult, *, elapsed: float) -> None:
        reason = result.reason
        row = {k: v for k, v in result.to_dict().items() if k in ("presentation_id", "variant_id", "scene_id", "status", "source_revision", "code", "merged", "mounted", "prefab")}
        row["message"] = result.message if (result.status in (ReloadStatus.ROLLED_BACK, ReloadStatus.PENDING_MOUNT)
                                            or result.diagnostics) else ""
        row["diagnostics"] = len(result.diagnostics)
        row["reason"] = reason or None
        row["reset"] = None if result.reset is None else result.reset.to_dict()
        self._recent.append(row)
        if result.status.stood and result.previous is not None and result.previous != result.prefab:
            history = self._restorable.setdefault((result.presentation_id, result.variant_id, result.scene_id),
                                                  deque(maxlen=MAX_RESTORABLE))
            if result.previous not in history:
                history.append(result.previous)
        if result.status.stood and result.request_id and self._edits is not None:
            self._edits.fulfil_source_request(result.request_id)
        level = "warning" if result.status in (ReloadStatus.ROLLED_BACK, ReloadStatus.PENDING_MOUNT) else "info"
        kind = {ReloadStatus.REFUSED_VALIDATION: "reload_refused", ReloadStatus.STALE: "reload_stale",
                ReloadStatus.ROLLED_BACK: "reload_rolled_back", ReloadStatus.PENDING_MOUNT: "reload_pending"}.get(
            result.status, "reload_applied")
        self._trace(f"core.presentation_studio.{kind}", f"Rechargement : {result.status.value}", level=level, data={
            "presentation_id": result.presentation_id, "variant_id": result.variant_id, "scene_id": result.scene_id,
            "status": result.status.value, "actor": result.actor.value, "source_revision": result.source_revision,
            "prefab": None if result.prefab is None else f"{result.prefab.prefab_id}@{result.prefab.version}",
            "previous": None if result.previous is None else f"{result.previous.prefab_id}@{result.previous.version}",
            "code": result.code or None, "reason": reason or None, "merged": result.merged, "mounted": result.mounted,
            "waited_s": result.waited_s, "elapsed_s": round(elapsed, 3),
            "reset": None if result.reset is None else {k: len(v) if isinstance(v, list) else v
                                                         for k, v in result.reset.to_dict().items()}})
        if result.status in (ReloadStatus.RELOADED, ReloadStatus.RELOADED_STATE_RESET, ReloadStatus.REPINNED,
                             ReloadStatus.PENDING_MOUNT, ReloadStatus.ROLLED_BACK):
            self._emit(result.presentation_id, result.variant_id, result.scene_id, result.status.value, result.source_revision,
                       result.actor.value, result.code or None, reason or None)

    def _emit(self, presentation_id: str, variant_id: str, scene_id: str, status: str, source_revision: int, actor: str,
              code: str | None, reason: str | None) -> None:
        if self._events is None:
            return
        try:
            self._events.reloaded(presentation_id=presentation_id, variant_id=variant_id, scene_id=scene_id, status=status,
                                  source_revision=source_revision, actor=actor, code=code, reason=reason or None)
        except Exception as exc:  # noqa: BLE001 - observability never undoes a reload; the failure is journaled
            self._trace("core.presentation_studio.event_failed", "Evenement de rechargement non pose", level="warning",
                        data={"error_class": type(exc).__name__})

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal never undoes a reload
            pass
