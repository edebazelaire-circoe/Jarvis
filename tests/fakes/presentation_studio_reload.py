"""Banc du rechargement a chaud (jarvis-interactive-presentation-studio, Slice 06) : tout est reel sauf le navigateur.

Magasin de fichiers, `PrefabService` + bibliotheque, `SceneService` (SQLite sous `tmp_path`), registre des pins, coalesceur,
stage, service de rechargement. Le navigateur est `FakeHost` : il regarde la scene globale comme la page le ferait et rapporte
le montage de ce que la fenetre stage affiche, selon une regle (`policy`) que chaque test choisit.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import json
import secrets
from pathlib import Path
from typing import Any

import jarvis

from jarvis.adapters.file_prefab_library import LIBRARY_DIR, FilePrefabLibrary, FilePrefabRuntime
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.core.prefab_draft_coalescer import PrefabDraftCoalescer
from jarvis.core.prefab_service import PrefabService
from jarvis.core.presentation_studio_edit import PresentationStudioEditService
from jarvis.core.presentation_studio_events import StudioEditEvents
from jarvis.core.presentation_studio_pins import StudioPinRegistry
from jarvis.adapters.file_presentation_studio_stage_ledger import FileStageLedger
from jarvis.core.interaction_mode import InteractionModeService
from jarvis.core.presentation_studio_autosave import PresentationStudioHistory
from jarvis.core.presentation_studio_playback import PresentationStudioPlaybackService
from jarvis.core.presentation_studio_reload import PresentationStudioReloadService
from jarvis.core.presentation_studio_reload_stage import StageWindows
from jarvis.core.presentation_studio_stage import SceneStage, StageLedger
from jarvis.core.presentation_studio_variants import PresentationStudioVariants
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.core.scene_service import SceneService
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.prefab import PrefabRef
from tests.fakes.prefabs import FIXTURES, install_version

SID, SID2 = "pss_0000000000a1", "pss_0000000000a2"
I1, I2 = "psi_000000000001", "psi_000000000002"
CONTROLS = [
    {"control_id": "headline", "path": "props.label", "label": "Titre", "group": "content"},
    {"control_id": "start_count", "path": "data.count", "label": "Valeur", "group": "content",
     "bounds": {"min": 0, "max": 100}, "default": 10},
]
GOOD_STYLE = "p{color:#abcdef}"


def scene_body(scene_id=SID, prefab=("lab.counter", 1), **changes) -> dict:
    return {"scene_id": scene_id, "prefab": {"id": prefab[0], "version": prefab[1]}, "title": "Ouverture",
            "section": "Intro", "props": {"label": "Visiteurs"}, "data": {"count": 12}, "controls": CONTROLS,
            "anchors": [{"anchor_id": "reveal", "label": "Reveler", "control_id": "start_count"}],
            "preview": {"caption": "Le chiffre", "alt": ""}, **changes}


class _Bus:
    async def publish(self, envelope) -> None:  # the playback's bus messages are not what these tests are about
        return None


class _Gate:
    async def require_art_direction(self, presentation_id, variant_id, *, serious=True):
        return {"status": "resolved", "fallback": False, "art_direction": {"revision": 1}}


def score_content() -> dict:
    """Une partition de deux elements, un par scene du banc."""

    return {"start_item_id": I1, "items": [
        {"item_id": I1, "scene_id": SID, "presenter": "user", "kind": "speech", "note": "Un", "label": "Un", "next_item_id": I2},
        {"item_id": I2, "scene_id": SID2, "presenter": "user", "kind": "speech", "note": "Deux", "label": "Deux"}],
        "cues": [], "sequences": [], "recovery_points": []}


class Sink:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.rows.append((kind, level, dict(data or {})))

    def of(self, kind: str) -> list[tuple[str, dict]]:
        return [(level, data) for k, level, data in self.rows if k == kind]

    def kinds(self, level: str | None = None) -> list[str]:
        return [k for k, lv, _ in self.rows if level is None or lv == level]


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


class Emitter:
    def __init__(self) -> None:
        self.recorded: list[tuple[T, tuple[str, ...], dict]] = []

    def record(self, event_type, *, producer, conversation_id, source_ids, occurred_at, attributes, **_):
        self.recorded.append((event_type, source_ids, dict(attributes)))
        return "cev-" + "0" * 64


class FakeHost:
    """Le navigateur : suit les revisions de la scene globale et rapporte le montage de l'objet stage.

    `policy(pin)` rend le rapport `{outcome, reason?, message?}` pour cette version, ou `None` (la page ne repond pas).
    Par defaut tout monte. Les pins deja rapportes ne le sont pas deux fois (un cadre ne remonte que sur changement de pin)."""

    def __init__(self, rig: Rig, policy: Callable[[PrefabRef], dict | None] | None = None) -> None:
        self.rig, self.policy = rig, policy or (lambda pin: {"outcome": "mounted"})
        self.mounted: dict[str, PrefabRef] = {}
        self.reports: list[dict] = []
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._watch())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _watch(self) -> None:
        scene = self.rig.scene
        revision = (await scene.snapshot()).revision
        while True:
            revision = await scene.wait_for_revision(revision, timeout_s=30)
            for item in (await scene.snapshot()).objects:
                block = item.payload.prefab
                if block is None:
                    continue
                pin = PrefabRef(block.prefab_id, block.version)
                if self.mounted.get(item.object_id) == pin:
                    continue
                self.mounted[item.object_id] = pin
                answer = self.policy(pin)
                if answer is None:
                    continue
                body = {"object_id": item.object_id, "prefab": pin.to_dict(), **answer}
                self.reports.append(body)
                await self.rig.reload.handle_mount_report(body)


class Rig:
    """Voir l'en-tete du module. `await Rig(tmp_path).open()` puis `rig.edit(...)`."""

    def __init__(self, tmp_path: Path, *, mount_deadline_s: float = 2.0, quiet_s: float = 0.02, max_wait_s: float = 0.1,
                 conversation: str | None = "conv-1", existing: bool = False, builder: Any = None,
                 reload_options: dict | None = None) -> None:
        """`existing=True` : rouvre les dossiers d'une vie precedente (apres un arret brutal) au lieu d'en creer."""

        self.tmp, self.existing, self.builder = tmp_path, existing, builder
        self.reload_options = reload_options or {}
        self.package, self.data = tmp_path / "package", tmp_path / "data"
        if not existing:
            for folder in (self.package, self.data):
                folder.mkdir()
            install_version(self.package, "jarvis.counter", title="Base")
            install_version(self.data / LIBRARY_DIR, "lab.counter", 1)
        self.sink, self.emitter = Sink(), Emitter()
        self.mount_deadline_s, self.quiet_s, self.max_wait_s, self.conversation = mount_deadline_s, quiet_s, max_wait_s, conversation
        self.host: FakeHost | None = None
        self.playback: Any = None

    async def open(self, scenes=None, *, host: bool | Callable | None = True, show: bool = True) -> Rig:
        self.pins = StudioPinRegistry(diagnostics=self.sink)
        self.prefabs = PrefabService(FilePrefabLibrary(self.package, self.data), pin_registry=self.pins, diagnostics=self.sink,
                                     runtime=FilePrefabRuntime(Path(jarvis.__file__).resolve().parent / "prefabs" / "runtime"))
        await self.prefabs.start()
        self.scene = SceneService(SQLiteSceneRepository(self.tmp / "scene.sqlite3"), diagnostics=self.sink,
                                  prefab_validator=self.prefabs)
        await self.scene.start()
        self.pins.bind_scene(self.scene)
        (self.tmp / "studio").mkdir(exist_ok=True)
        self.studio = PresentationStudioService(FilePresentationStudioStore(self.tmp / "studio"), diagnostics=self.sink,
                                                clock=Clock(), prefabs=self.prefabs, pins=self.pins)
        await self.studio.start()
        self.events = StudioEditEvents(self.emitter, lambda: self.conversation)
        self.history = PresentationStudioHistory(self.studio, diagnostics=self.sink)
        self.edits = PresentationStudioEditService(self.studio, diagnostics=self.sink, events=self.events, history=self.history)
        self.history.bind(self.edits)
        self.variants = PresentationStudioVariants(self.studio, history=self.history, diagnostics=self.sink)
        self.pins.add_source("undo", self.history.pins)
        self.coalescer = PrefabDraftCoalescer(self.prefabs, quiet_s=self.quiet_s, max_wait_s=self.max_wait_s,
                                              diagnostics=self.sink)
        self.stage = StageWindows(self.scene, diagnostics=self.sink)
        self.reload = PresentationStudioReloadService(
            self.studio, self.prefabs, self.coalescer, self.stage, pins=self.pins, edits=self.edits,
            events=self.events, diagnostics=self.sink, mount_deadline_s=self.mount_deadline_s, builder=self.builder,
            **self.reload_options)
        # The REAL playback runtime (Slice 12) owns the stage window: a run creates `studio-stage-<run_id>` and tells the
        # reload (`stage_observer`) which scene it shows; the reload reads its position (`PlaybackProbe`).
        self.stage_scene = SceneStage(self.scene, StageLedger(FileStageLedger(self.tmp), diagnostics=self.sink), diagnostics=self.sink)
        self.mode = InteractionModeService(events=_Bus(), epoch="epoch-1")
        self.playback = PresentationStudioPlaybackService(
            self.studio, self.edits, self.stage_scene, self.mode, gate=_Gate(), bus=_Bus(), diagnostics=self.sink,
            new_run_id=self._run_id, detour_validator=self.prefabs, stage_observer=self.stage)
        self.reload.bind_playback(self.playback)
        self.variants.bind_playback(self.playback)
        if self.existing:
            first = (await self.studio.list_presentations()).presentations[0]
            self.pid, self.vid = first["presentation_id"], first["active_variant_id"]
            await self.rebuild_pins()
            await self.reload.recover()
            await self.playback.start_service()  # as at Core start: the stage window of the killed life is taken back by id list
            return self
        view = await self.studio.create({"title": "Atelier"})
        self.pid, self.vid = view.presentation.presentation_id, view.presentation.active_variant_id
        await self.seed()
        await self.save_scenes([scene_body(), scene_body(SID2, title="Milieu")] if scenes is None else scenes)
        await self.rebuild_pins()
        if host:
            self.host = FakeHost(self, host if callable(host) else None)
            self.host.start()
        if show:
            await self.play()
        return self

    async def seed(self) -> None:
        """Crochet des bancs derives (Slice 14 : une source Remotion publiee avant les scenes) ; rien par defaut."""

    def _run_id(self) -> str:
        return secrets.token_hex(6)       # as in production: an id of a killed life is a tombstone and is never reused

    async def play(self, *, scene_index: int = 0, role: str = "user_presenter", content: dict | None = None) -> dict:
        """Demarre une VRAIE lecture (score de deux elements) ; `scene_index` 1 : on avance sur la 2e scene. Rend l'etat."""

        variant = await self.variant()
        if variant.score_id is None:
            await self.studio.create_score(self.pid, self.vid, {"expected_variant_revision": variant.revision, **(content or score_content())})
        result = await self.playback.start({"actor": "user", "presentation_id": self.pid, "role": role})
        assert result.status.value == "applied", result.to_dict()
        for _ in range(scene_index):
            moved = await self.playback.next({"actor": "user"})
            assert moved.status.value == "applied", moved.to_dict()
        await asyncio.sleep(0.05)
        return result.to_dict()["state"]

    async def rebuild_pins(self) -> None:
        assert await self.pins.rebuild(self.variants)

    async def close(self) -> None:
        if self.host is not None:
            await self.host.stop()
        if self.playback is not None and self.playback.state.active:
            await self.playback.stop({"actor": "user"}, reason="shutdown")
        await self.reload.close()
        await self.scene.close()

    async def variant(self):
        return await self.studio.get_variant(self.pid, self.vid)

    async def save_scenes(self, scenes) -> None:
        variant = await self.studio.get_variant(self.pid, self.vid)
        await self.studio.save_variant(self.pid, self.vid, {
            "expected_revision": variant.revision, "title": variant.title, "scenes": scenes,
            "art_direction_id": None, "score_id": variant.score_id})

    def variant_file(self) -> Path:
        return self.tmp / "studio" / "presentations" / self.pid / "variants" / f"{self.vid}.json"

    def request(self, revision: int, files: dict, *, scene_id: str = SID, actor: str = "user", **extra) -> dict:
        return {"actor": actor, "basis": {"variant_revision": revision}, "scene_id": scene_id, "files": files, **extra}

    async def record_request(self, scene_id: str = SID, *, actor: str = "user", origin: str | None = None) -> str:
        """Remotion Slice 21 (QA B1): a pending source request, as the edit API records it (a user's by default), and its id."""

        revision = (await self.variant()).revision
        body = {"actor": actor, "mode": "commit", "basis": {"variant_revision": revision},
                "ops": [{"op": "scene.source_request", "scene_id": scene_id, "intent": "test request"}]}
        if origin is not None:
            body["origin"] = origin
        done = await self.edits.edit(self.pid, self.vid, body)
        return done.source_requests[0]["request_id"]

    async def edit(self, files: dict, *, scene_id: str = SID, revision: int | None = None, auto_request: bool = True, **extra):
        """A source edit. A `brain` edit without a `request_id` gets a pending request recorded for it first (the Core rule of the Slice 21
        rework: the brain edits only for a pending request of the user); `auto_request=False` sends it as it is (the refusal tests)."""

        if extra.get("actor") == "brain" and auto_request and "request_id" not in extra and getattr(self, "edits", None) is not None:
            extra["request_id"] = await self.record_request(scene_id)
        if revision is None:
            revision = (await self.variant()).revision
        return await self.reload.apply_source_edit(self.pid, self.vid, self.request(revision, files, scene_id=scene_id, **extra))

    def stage_object_id(self) -> str | None:
        """La fenetre `studio-stage-<run_id>` de la lecture en cours, `None` si rien ne joue."""

        where = self.playback.position(self.pid) if self.playback is not None else None
        return None if where is None else where["stage_object_id"]

    async def stage_block(self):
        object_id = self.stage_object_id()
        found = None if object_id is None else (await self.scene.snapshot()).get_object(object_id)
        return None if found is None else found.payload.prefab

    async def add_window(self, object_id: str, prefab_id: str = "lab.counter", version: int = 1) -> None:
        """Une fenetre de la scene globale qui n'est pas le stage : un cadre voisin que le rechargement ne doit jamais toucher."""

        from jarvis.domain.scene import (
            Representation, SceneActor, SceneCommand, SceneGeometry, SceneObjectFields, SceneObjectKind, SceneOp, ScenePayload,
            ScenePrefabRef,
        )
        await self.scene.apply(SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.USER, object_id=object_id,
                                            fields=SceneObjectFields(
                                                kind=SceneObjectKind.WINDOW, category="note",
                                                representation=Representation.WINDOW, geometry=SceneGeometry(0, 0, 40, 24),
                                                payload=ScenePayload(title=object_id, prefab=ScenePrefabRef(
                                                    prefab_id, version, {"label": object_id}, {"count": 1})))))

    def manifest_of_pin(self, prefab_id: str = "lab.counter", version: int = 1) -> dict:
        return json.loads((self.data / LIBRARY_DIR / prefab_id / str(version) / "manifest.json").read_text(encoding="utf-8"))

    def shrunk_manifest(self) -> dict:
        """`count` devient optionnel avec un plafond bas : la valeur stockee (12) et les bornes du controle ne tiennent plus."""

        manifest = self.manifest_of_pin()
        manifest["inputs"]["props"]["properties"]["mode"].update(values=["compact"], default="compact")
        manifest["inputs"]["data"]["properties"]["count"].update(max=5, default=0)
        manifest["inputs"]["data"]["required"] = []
        return manifest

    def versions_of(self, prefab_id: str) -> list[int]:
        folder = self.data / LIBRARY_DIR / prefab_id
        return sorted(int(p.name) for p in folder.iterdir() if p.name.isdigit()) if folder.exists() else []

    def behavior(self, text: str) -> dict:
        return {"behavior": text}


def counter_behavior() -> str:
    return (FIXTURES / "test.counter" / "1" / "behavior.js").read_text(encoding="utf-8")
