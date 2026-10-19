"""Purge definitive des presentations archivees : plan (n'ecrit rien), puis execution confirmee, **sauvegarde d'abord**.

Archiver (`PresentationRail.act`, `rail.json`) reste la « suppression » restaurable de tous les jours. La purge est le geste
explicite, demande par l'utilisateur, qui efface vraiment ce qui est archive :

1. **Plan** (`plan`) : sous le verrou du Studio, liste les presentations archivees (toutes, ou le filtre `presentation_ids`, ou une
   presentation non archivee est **refusee** `not_archived`) et, pour chacune, ce qui partira : variantes vivantes et archivees,
   partitions, directions artistiques, compositions, Artifacts derives (snapshots dont la source est la presentation, et leurs
   rendus en cascade), sources de scene `presentation-studio.p<12 hex>.*` (catalogue et `.archive`). Rend un jeton HMAC a duree
   limitee lie a cet ensemble exact (`jarvis.domain.presentation_studio_purge`). Une archivee dont un Artifact est encore `pending`
   (rendu en cours) est laissee hors du plan (`blocked`), jamais effacee a moitie.
2. **Execution** (`purge`) : exige le jeton et `confirmed: true` (pour tous les acteurs ; le cerveau ne le pose qu'apres le oui de
   l'utilisateur). Sous le verrou du Studio : replanifie, refuse si une presentation est jouee (`variant_in_playback`) ou si
   l'ensemble a change (`confirmation_stale`) ; puis **sauvegarde** dans `<data_root>/backups/purge-presentations-<horodatage UTC>/`
   (dossiers de presentation, dossiers de prefabs, dossiers d'Artifacts, copie coherente de `jarvis.sqlite3` par l'API sqlite3
   backup si des Artifacts partent, `purge.json`) ; si la sauvegarde echoue, **rien n'est efface** (`storage_io`). Ensuite, par
   presentation : Artifacts (`ArtifactService.delete(cascade=True)`, base puis dossiers), sources de scene (`PrefabService.remove_ids`,
   catalogue relu), dossier (`FilePresentationStudioStore.remove_presentation`). Une etape qui echoue laisse la presentation en
   place (toujours archivee, rien d'autre d'elle n'est efface ensuite) et se dit dans `failed`.
3. **Oubli** : apres le verrou, chaque crochet en memoire (`add_forget_hook` : historique d'annulation, index des pins, graphe des
   variantes, comparaison, rechargement, liaison de stage, permissions d'auteur, rail...) oublie la presentation purgee.

Les sources `presentation-studio.rm-*` (adressees par leur contenu, donc partageables entre presentations) ne sont **jamais**
purgees ici : une fois la presentation oubliee de l'index des pins, la retention des prefabs (`core/prefab_retention.py`) les
archive comme toute version non epinglee. Contrat : `docs/presentation-studio.md` > *Rail des presentations* > *Purge definitive*.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
import inspect
from pathlib import Path
import secrets
import time
from typing import Any

from jarvis.core.presentation_studio_rail import parse_rail
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.domain.artifacts import Artifact, ArtifactError, ArtifactErrorCode, ArtifactQuery, ArtifactState
from jarvis.domain.presentation_artifacts import SNAPSHOT_KIND
from jarvis.domain.presentation_studio import PresentationStudioError, stamp
from jarvis.domain.presentation_studio_checks import PresentationStudioErrorCode as C, clip
from jarvis.domain.presentation_studio_purge import (
    PURGE_CONFIRMATION_TTL_S, PurgePlan, PurgeTarget, check_purge_confirmation, issue_purge_confirmation, parse_purge_request,
)
from jarvis.ports.artifacts import RelationDirection
from jarvis.ports.prefabs import PrefabStoreError
from jarvis.ports.presentation_studio import PurgeBackupStore

#: Sources de scene propres a une presentation : `presentation-studio.p<12 premiers hex du pst>.s<12 hex>`
#: (`domain/presentation_studio_reload.source_prefab_id`).
SOURCE_PREFIX = "presentation-studio.p"
ARTIFACT_ORIGIN = "presentation_purge"
#: Lecture du registre par pages ; au-dela, le plan est refuse (`limit_reached`) plutot que de rater des snapshots.
SCAN_PAGE = 200
MAX_SCAN_PAGES = 250
#: Profondeur et nombre de derives suivis par snapshot (la cascade du registre s'arrete a 256).
MAX_DEPENDENTS = 256
MANIFEST_SCHEMA = "jarvis.presentation_studio.purge_backup"

ForgetHook = Callable[[str], Any]


class PresentationPurge:
    """Voir l'en-tete du module. `backups` : les sauvegardes (`<data_root>/backups/`, `FilePurgeBackups`)."""

    def __init__(self, studio: PresentationStudioService, *, backups: PurgeBackupStore | None, secret: bytes | None = None,
                 epoch: Callable[[], float] = time.time) -> None:
        self._studio = studio
        self._backups = backups
        self._secret = secret or secrets.token_bytes(32)
        self._epoch = epoch
        self._artifacts: Any = None
        self._database_backup: Callable[[Path], Awaitable[None]] | None = None
        self._prefabs: Any = None
        self._playback: Any = None
        self._hooks: list[tuple[str, ForgetHook]] = []

    # ------------------------------------------------------------ cablage (v2_app)

    def bind_artifacts(self, artifacts: Any, database_backup: Callable[[Path], Awaitable[None]]) -> None:
        """Registre d'Artifacts et copie coherente de `jarvis.sqlite3` (`SQLiteStateRepository.backup_to`). Absent : aucun Artifact
        n'est planifie ni efface (les snapshots restent, sans source)."""

        self._artifacts, self._database_backup = artifacts, database_backup

    def bind_prefabs(self, prefabs: Any) -> None:
        self._prefabs = prefabs

    def bind_playback(self, playback: Any) -> None:
        self._playback = playback

    def add_forget_hook(self, name: str, hook: ForgetHook) -> None:
        """`hook(presentation_id)` (synchrone ou coroutine), appele apres la purge pour chaque presentation effacee."""

        self._hooks.append((name, hook))

    # ------------------------------------------------------------ plan

    async def plan(self, raw: object = None) -> dict[str, Any]:
        request = parse_purge_request(raw, execute=False)
        async with self._studio.exclusive():
            plan = await self._plan_locked(request.presentation_ids)
        token = issue_purge_confirmation(self._secret, plan, int(self._epoch())) if plan.targets else None
        self._studio.trace("core.presentation_studio.purge_planned", "Purge des presentations archivees planifiee",
                           data={"count": len(plan.targets), "blocked": len(plan.blocked), "actor": request.actor,
                                 "filtered": request.presentation_ids is not None})
        return {"plan": plan.view(), "confirmation": token, "expires_in_s": PURGE_CONFIRMATION_TTL_S}

    async def _plan_locked(self, only: tuple[str, ...] | None) -> PurgePlan:
        scan = await self._studio.run_blocking("purge_plan", None, self._studio.store.scan)
        known = set(scan.presentation_ids)
        if only is not None:
            missing = [pid for pid in only if pid not in known]
            if missing:
                raise PresentationStudioError(C.UNKNOWN_PRESENTATION, f"{missing[0]} is not in the store")
        archived: list[tuple[str, str | None]] = []
        for pid in (only if only is not None else scan.presentation_ids):
            try:
                text = await self._studio.run_blocking("purge_plan", pid, self._studio.store.read_rail, pid)
                flags = parse_rail(text)
            except PresentationStudioError:
                if only is not None:
                    raise  # an unreadable rail.json is not "archived": the caller sees why
                continue  # intentional: the rail overview already reports it; never purged on a guess
            if not flags.archived:
                if only is not None:
                    raise PresentationStudioError(C.NOT_ARCHIVED, f"{pid} is not archived: only archived presentations are purged "
                                                                  "(archive it first, with the user's yes)")
                continue
            archived.append((pid, flags.archived_at))
        if not archived:
            return PurgePlan(())
        snapshots = await self._snapshots_of({pid for pid, _ in archived})
        ready: list[tuple[str, str | None, str | None, int | None, set[str]]] = []
        blocked: list[dict[str, Any]] = []
        for pid, archived_at in archived:
            title, revision = await self._identity(pid)
            artifacts, pending = await self._cascade(snapshots.get(pid, []))
            if pending:
                blocked.append({"presentation_id": pid, "title": title, "reason": "artifact_pending",
                                "message": "an export of this presentation is still being written: purge it once it is done"})
                continue
            ready.append((pid, archived_at, title, revision, artifacts))
        purged = {row[0] for row in ready}
        sources, notes = await self._sources_of(purged, known - purged)  # a blocked one stays: its sources are never taken
        targets: list[PurgeTarget] = []
        for pid, archived_at, title, revision, artifacts in ready:
            listed = {area: await self._studio.run_blocking("purge_plan", pid, self._studio.store.list_documents, pid, area)
                      for area in ("variants", "archive", "scores", "art_directions", "compositions")}
            targets.append(PurgeTarget(
                pid, title, archived_at, revision, listed["variants"], listed["archive"], tuple(sorted(artifacts)),
                tuple(sorted(sources.get(pid, ()))), scores=len(listed["scores"]), art_directions=len(listed["art_directions"]),
                compositions=len(listed["compositions"]), snapshot_ids=tuple(sorted(a.artifact_id for a in snapshots.get(pid, [])))))
        return PurgePlan(tuple(targets), tuple(blocked), tuple(notes))

    async def _identity(self, pid: str) -> tuple[str | None, int | None]:
        try:
            presentation = await self._studio.load_presentation_locked(pid)
        except PresentationStudioError:
            return None, None  # intentional: an unreadable manifest of an archived presentation is still purgeable (rail.json says so)
        return clip(presentation.title, 120), presentation.revision

    async def _snapshots_of(self, ids: set[str]) -> dict[str, list[Artifact]]:
        """Snapshots dont la source est l'une des presentations : provenance `source_presentation_id`, ou l'id derive
        `jart_ps_<32 hex>_...` (une ligne sans provenance lisible reste reconnue par son id)."""

        found: dict[str, list[Artifact]] = {}
        if self._artifacts is None:
            return found
        by_hex = {pid.removeprefix("pst_"): pid for pid in ids}
        cursor = None
        for _ in range(MAX_SCAN_PAGES):
            page = await self._artifacts.query(ArtifactQuery(kinds=(SNAPSHOT_KIND,), cursor=cursor, limit=SCAN_PAGE))
            for artifact in page.items:
                owner = artifact.metadata.get("source_presentation_id")
                if owner is not None:
                    owner = owner if owner in ids else None  # the provenance decides when it is there, never the id shape
                else:
                    parts = artifact.artifact_id.split("_")
                    owner = by_hex.get(parts[2]) if len(parts) > 2 and artifact.artifact_id.startswith("jart_ps_") else None
                if owner is not None:
                    found.setdefault(owner, []).append(artifact)
            if page.next_cursor is None:
                return found
            cursor = page.next_cursor
        raise PresentationStudioError(C.LIMIT_REACHED, f"more than {SCAN_PAGE * MAX_SCAN_PAGES} snapshots in the registry: the exports "
                                                       "of the archived presentations cannot all be found, nothing is planned")

    async def _cascade(self, snapshots: list[Artifact]) -> tuple[set[str], bool]:
        """Les snapshots et tout ce qui en derive (`rendered_from`, recursif) ; `True` si l'un d'eux est encore `pending`."""

        seen: set[str] = set()
        pending = False
        queue = list(snapshots)
        while queue:
            artifact = queue.pop()
            if artifact.artifact_id in seen:
                continue
            seen.add(artifact.artifact_id)
            pending = pending or artifact.state is ArtifactState.PENDING
            if len(seen) > MAX_DEPENDENTS * max(1, len(snapshots)):
                raise PresentationStudioError(C.LIMIT_REACHED, "too many exports derive from these snapshots: nothing is planned")
            for relation in await self._artifacts.relations(artifact.artifact_id, RelationDirection.DEPENDENTS):
                try:
                    queue.append(await self._artifacts.get(relation.artifact_id))
                except ArtifactError as exc:
                    if exc.code is not ArtifactErrorCode.ARTIFACT_NOT_FOUND:
                        raise
        return seen, pending

    async def _sources_of(self, ids: set[str], remaining: set[str]) -> tuple[dict[str, list[str]], list[str]]:
        """Sources de scene `presentation-studio.p<12 hex>.*` de chaque presentation purgee. Un prefixe de 12 hex partage avec une
        presentation qui reste (collision possible : 48 bits) n'est jamais purge : il est signale."""

        if self._prefabs is None:
            return {}, []
        candidates = await self._prefabs.purge_candidates(SOURCE_PREFIX)
        shared = {pid.removeprefix("pst_")[:12] for pid in remaining}
        owners: dict[str, list[str]] = {}
        for pid in sorted(ids):
            owners.setdefault(pid.removeprefix("pst_")[:12], []).append(pid)
        out: dict[str, list[str]] = {}
        notes: list[str] = []
        for prefab_id in candidates:
            short = prefab_id[len(SOURCE_PREFIX):].split(".", 1)[0]
            if short not in owners:
                continue
            if short in shared:
                notes.append(f"{prefab_id}: its 12-hex prefix is shared with a presentation that stays; kept")
                continue
            out.setdefault(owners[short][0], []).append(prefab_id)
        return out, notes

    # ------------------------------------------------------------ execution

    async def purge(self, raw: object) -> dict[str, Any]:
        request = parse_purge_request(raw, execute=True)
        if request.confirmed is not True:
            raise PresentationStudioError(C.CONFIRMATION_REQUIRED, "purging deletes for good: read the plan to the user, wait for "
                                                                   "their yes, then pass the plan's confirmation and confirmed=true")
        async with self._studio.exclusive():
            plan = await self._plan_locked(request.presentation_ids)
            playing = self._playing()
            if playing is not None and playing in plan.presentation_ids:
                raise PresentationStudioError(C.VARIANT_IN_PLAYBACK, "an archived presentation is being played: stop the playback first")
            check_purge_confirmation(self._secret, plan, request.confirmation, int(self._epoch()))
            backup, copied = await self._backup(plan)
            report = await self._delete(plan, copied)
        await self._forget(report["purged"], report)
        report["backup"] = backup
        report["complete"] = not report["failed"] and not report["orphan_folders"]
        self._studio.trace("core.presentation_studio.purged", "Presentations archivees purgees (sauvegarde gardee)",
                           level="info" if report["complete"] else "warning",
                           data={"purged": report["purged"], "deleted": report["deleted"], "failed": report["failed"],
                                 "backup": backup, "actor": request.actor})
        return report

    def _playing(self) -> str | None:
        running = None if self._playback is None else self._playback.running_variant()
        return running[0] if running else None

    async def _backup(self, plan: PurgePlan) -> tuple[str, dict[str, Any]]:
        """La sauvegarde complete, publiee d'un renommage (`.partial-...` -> nom final). Echec : `storage_io`, rien n'est efface."""

        if self._backups is None:
            raise PresentationStudioError(C.STORAGE_IO, "no backup store is wired: nothing was deleted")
        copied: dict[str, Any] = {"presentations": {}, "prefabs": {}, "artifacts": {}}
        draft = None
        try:
            draft = await self._studio.run_blocking("purge_backup", None, self._backups.begin, self._studio.now())
            for target in plan.targets:
                copied["presentations"][target.presentation_id] = await self._studio.run_blocking(
                    "purge_backup", target.presentation_id, self._studio.store.copy_presentation, target.presentation_id,
                    draft.folder / "presentations")
            prefab_ids = [p for t in plan.targets for p in t.prefab_ids]
            if prefab_ids:
                copied["prefabs"] = await self._prefabs.export_ids(prefab_ids, draft.folder / "prefabs")
            artifact_ids = [a for t in plan.targets for a in t.artifact_ids]
            for artifact_id in artifact_ids:
                count = await self._studio.run_blocking("purge_backup", None, self._backups.copy_artifact_folder, draft, artifact_id)
                if count is not None:
                    copied["artifacts"][artifact_id] = count
            if artifact_ids:
                if self._database_backup is None:
                    raise RuntimeError("no database backup is wired")
                await self._database_backup(await self._studio.run_blocking("purge_backup", None, self._backups.database_path, draft))
            manifest = {"schema": MANIFEST_SCHEMA, "schema_version": 1, "created_at": stamp(self._studio.now()),
                        "presentation_ids": list(plan.presentation_ids), "plan": plan.view(),
                        "prefab_folders": sorted(copied["prefabs"]), "artifact_ids": sorted(artifact_ids),
                        "database": "state/jarvis.sqlite3" if artifact_ids else None,
                        "restore": "docs/OPERATIONS.md > Purge définitive des présentations archivées"}
            await self._studio.run_blocking("purge_backup", None, self._backups.write_manifest, draft, manifest)
            published = await self._studio.run_blocking("purge_backup", None, self._backups.publish, draft)
        except Exception as exc:  # noqa: BLE001 - any failure of the backup refuses the purge, coded; nothing is deleted
            if draft is not None:
                await self._studio.run_blocking("purge_backup", None, self._backups.discard, draft)
            # never an absolute path in a refusal: an OS error says its kind and its reason, not its file
            detail = exc.message if isinstance(exc, PresentationStudioError) else (
                f"{type(exc).__name__}: {exc.strerror or ''}" if isinstance(exc, OSError) else f"{type(exc).__name__}: {exc}")
            raise PresentationStudioError(C.STORAGE_IO, f"the backup failed, nothing was deleted: {clip(detail, 300)}") from None
        return published, copied

    async def _delete(self, plan: PurgePlan, copied: dict[str, Any]) -> dict[str, Any]:
        deleted = {"presentations": 0, "variants": 0, "artifacts": 0, "prefabs": 0, "files": 0}
        purged: list[str] = []
        failed: list[dict[str, str]] = []
        orphans: list[str] = []
        for target in plan.targets:
            pid = target.presentation_id
            step = "artifacts"
            try:
                for snapshot_id in target.snapshot_ids:
                    try:
                        result = await self._artifacts.delete(snapshot_id, cascade=True, origin=ARTIFACT_ORIGIN)
                    except ArtifactError as exc:
                        if exc.code is ArtifactErrorCode.ARTIFACT_NOT_FOUND:
                            continue  # intentional: already gone (deleted by hand meanwhile): nothing left to delete
                        raise
                    deleted["artifacts"] += len(result.artifact_ids)
                    orphans.extend(result.orphan_folders)
                step = "prefabs"
                labels = {label: count for label, count in copied["prefabs"].items()
                          if label.removeprefix(".archive/") in target.prefab_ids}
                if labels:
                    await self._prefabs.remove_ids(labels)
                    deleted["prefabs"] += len(target.prefab_ids)
                step = "presentation"
                await self._studio.run_blocking("purge", pid, self._studio.store.remove_presentation, pid)
            except (ArtifactError, PrefabStoreError, PresentationStudioError) as exc:
                code = getattr(getattr(exc, "code", None), "value", type(exc).__name__)
                failed.append({"presentation_id": pid, "step": step, "code": str(code), "message": clip(str(exc), 200)})
                self._studio.trace("core.presentation_studio.purge_failed", "Purge d'une presentation interrompue (sauvegarde gardee)",
                                   level="error", data={"presentation_id": pid, "step": step, "code": str(code)})
                continue
            purged.append(pid)
            deleted["presentations"] += 1
            deleted["variants"] += len(target.variant_ids) + len(target.archived_variant_ids)
            deleted["files"] += copied["presentations"][pid].files
        return {"purged": purged, "count": len(purged), "deleted": deleted, "failed": failed, "orphan_folders": orphans,
                "blocked": list(plan.blocked), "notes": list(plan.notes), "forget_failed": []}

    async def _forget(self, presentation_ids: Iterable[str], report: dict[str, Any]) -> None:
        for pid in presentation_ids:
            for name, hook in self._hooks:
                try:
                    outcome = hook(pid)
                    if inspect.isawaitable(outcome):
                        await outcome
                except Exception as exc:  # noqa: BLE001 - traced and reported: the purge stands, a bounded in-memory leftover remains
                    report["forget_failed"].append({"presentation_id": pid, "hook": name})
                    self._studio.trace("core.presentation_studio.purge_forget_failed", "Etat en memoire non oublie apres une purge",
                                       level="warning", data={"presentation_id": pid, "hook": name,
                                                              "error": f"{type(exc).__name__}: {exc}"[:200]})
