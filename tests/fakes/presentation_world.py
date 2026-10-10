"""Monde de test d'une présentation Remotion gelable (Slice 16 : tests du service de rendu et harnais de preuve réelle).

Vrai registre SQLite, vrai Studio de fichiers, vrai `PrefabService` (source Remotion réelle), vrai `PresentationPackager` et vrai spool
d'`ArtifactService`, le tout sous un dossier jetable. Rien n'y lance de processus.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis.adapters.artifact_payloads import FileArtifactPayloads
from jarvis.adapters.board_memory_store import FileBoardMemoryStore
from jarvis.adapters.file_prefab_library import FilePrefabLibrary
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.adapters.sqlite_artifacts import SQLiteArtifactRepository
from jarvis.adapters.sqlite_board_artifact_links import SQLiteBoardArtifactLinks
from jarvis.adapters.sqlite_session_activity import SQLiteActivityLedger
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.core.artifact_service import ArtifactService
from jarvis.core.prefab_service import PrefabService
from jarvis.core.presentation_artifacts import PresentationArtifacts
from jarvis.core.presentation_live_refs import LiveRefResolver
from jarvis.core.presentation_snapshot_packager import PresentationPackager
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.domain.workspace_board import default_board, open_session
from tests.fakes.prefabs import install_version
from tests.fakes.remotion_scene import COMPOSITION, ENGINE, PROPS_SCHEMA, SAMPLE, scene_candidate, scene_files

T0 = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)
SID = "jsess_0123456789abcdef"
SCENE_PREFAB = "presentation-studio.p000000000001.s000000000001"
SCENE_ID = "pss_000000000001"
OK_BOARDS = {"default"}


class Sink:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.rows.append((kind, level, dict(data or {})))

    def kinds(self) -> list[str]:
        return [row[0] for row in self.rows]


class PresentationWorld:
    """Attributs : `state`, `boards`, `artifacts`, `links`, `studio`, `prefabs`, `snapshots` (PresentationArtifacts), `packager`, `sink`."""

    async def open(self, root: Path, *, runtime: dict[str, Any] | None = None) -> "PresentationWorld":
        self.root = root
        self.state = SQLiteStateRepository(root / "state" / "jarvis.sqlite3")
        await self.state.initialize()
        self.boards = SQLiteBoardRepository(self.state)
        first = default_board(now=T0)
        await self.boards.save_board(first)
        await self.boards.save_session(open_session(first, now=T0, jarvis_session_id=SID))
        for name in ("data", "studio", "package", "prefabs", "boards_root"):
            (root / name).mkdir(parents=True, exist_ok=True)
        self.sink = Sink()
        self.artifacts = ArtifactService(SQLiteArtifactRepository(self.state), SQLiteActivityLedger(self.state),
                                         FileArtifactPayloads(root / "data"), diagnostics=self.sink)
        self.links = SQLiteBoardArtifactLinks(self.state)
        self.memory = FileBoardMemoryStore(root / "boards_root")
        self.studio = PresentationStudioService(FilePresentationStudioStore(root / "studio"))
        if not (root / "package" / "jarvis.counter").exists():
            install_version(root / "package", "jarvis.counter", title="Base counter")
        self.prefabs = PrefabService(FilePrefabLibrary(root / "package", root / "prefabs"), diagnostics=self.sink, clock=lambda: T0)
        self.snapshots = PresentationArtifacts(self.studio, self.artifacts, self.links, diagnostics=self.sink)
        self.resolver = LiveRefResolver(boards=self.boards, memory=self.memory, artifacts=self.artifacts, links=self.links,
                                        diagnostics=self.sink)
        self.packager = PresentationPackager(
            studio=self.studio, artifacts=self.artifacts, snapshots=self.snapshots, prefabs=self.prefabs, resolver=self.resolver,
            runtime=runtime if runtime is None else (lambda: runtime), clock=lambda: T0, diagnostics=self.sink)
        return self

    async def close(self) -> None:
        await self.state.close()

    async def new_presentation(self, files: dict[str, Any] | None = None, *, prefab_id: str = SCENE_PREFAB, composition=COMPOSITION,
                               engine=ENGINE, props: dict[str, Any] | None = None, sample: dict[str, Any] | None = None,
                               props_schema: dict[str, Any] | None = None) -> tuple[str, str]:
        """Publie une scène Remotion réelle et crée une présentation d'une scène ; rend `(presentation_id, variant_id)`."""

        options: dict[str, Any] = {"files": files or scene_files(), "composition": composition, "engine": engine,
                                   "props": props_schema or PROPS_SCHEMA, "sample": sample or SAMPLE}
        published = await self.prefabs.save(scene_candidate(prefab_id, **options), actor="user")
        created = await self.studio.create({"title": "Atelier"})
        pid, vid = created.presentation.presentation_id, created.presentation.active_variant_id
        variant = created.variants[0].to_document()
        scene: dict[str, Any] = {"scene_id": SCENE_ID, "prefab": {"id": prefab_id, "version": published.version}}
        if props:
            scene["props"] = props
        await self.studio.save_variant(pid, vid, {
            "expected_revision": variant["revision"], "title": variant["title"], "scenes": [scene],
            "art_direction_id": None, "score_id": None})
        return pid, vid

    async def revisions(self, pid: str) -> tuple[int, int]:
        view = await self.studio.get(pid)
        return view.presentation.revision, view.variants[0].revision

    async def freeze(self, pid: str, vid: str, boards=OK_BOARDS) -> dict[str, Any]:
        p, v = await self.revisions(pid)
        return await self.packager.freeze(pid, vid, expected_presentation_revision=p, expected_variant_revision=v,
                                          authorised_boards=boards)
